"""Decision engine — чистая функция compute_target_state.

Без I/O: принимает контекст, возвращает Decision (что делать дальше).
Caller (apply_decision) выполняет сетевые вызовы и записи в БД.

Stages (по плану idempotent-launching-kahan.md):
1. ad.status != active                    → NOOP   LOG_USER_DELETED
2. promotion.bid/daily_budget IS NULL     → NOOP   LOG_NOT_CONFIGURED
3. profile / limit / end_date             → NOOP   LOG_DISABLED_BY_TARIFF
4. profile_rank > manual_promotion_limit  → NOOP   LOG_LIMIT_EXCEEDED
5. critical_* в БД отсутствуют            → FETCH_BIDS
6. parse_critical_bids -> None            → NOOP   LOG_PROMOTION_UNAVAILABLE
7. !in_work_schedule                      → REMOVE LOG_DISABLED_BY_TIME
8. spending >= daily_budget               → REMOVE LOG_DISABLED_BY_BUDGET
9-13. метрики                             → REMOVE LOG_DISABLED_BY_*
14. bid < critical_min_bid                → NOOP   LOG_BID_BELOW_MIN
15. bid > critical_max_bid                → NOOP   LOG_BID_ABOVE_MAX(...)
16. drift && cooldown_ok                  → SET_BID LOG_SUCCESS
17. drift && !cooldown_ok                 → NOOP
18. !drift && hourly_log_due              → NOOP write_log=True

При write_log=True И bids_info is None → FETCH_BIDS (нужны bids
для compare_percent). После recompute_with_bids решение финализируется.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from app.database.database import CriticalUpdate, PromotionContext
from app.dispatcher.critical_bids import (
    CriticalBidsData,
    parse_critical_bids,
    pick_compare_percent,
)
from app.log_messages import (
    LOG_BID_ABOVE_MAX_PREFIX,
    LOG_BID_BELOW_MIN,
    LOG_BID_CHANGE_FAILED,
    LOG_DISABLED_BY_ACCOUNT_DELETED,
    LOG_DISABLED_BY_BUDGET,
    LOG_DISABLED_BY_CONTACTS,
    LOG_DISABLED_BY_CPC,
    LOG_DISABLED_BY_CPV,
    LOG_DISABLED_BY_IMPRESSIONS,
    LOG_DISABLED_BY_TARIFF,
    LOG_DISABLED_BY_TIME,
    LOG_DISABLED_BY_VIEWS,
    LOG_LIMIT_EXCEEDED,
    LOG_NOT_CONFIGURED,
    LOG_PROMOTION_UNAVAILABLE,
    LOG_SUCCESS,
    LOG_USER_DELETED,
    SOFT_DISABLED_LOGS,
)
from app.utils.time_utils import is_in_work_schedule

__all__ = [
    "Action",
    "Decision",
    "DecisionInput",
    "compute_target_state",
    "recompute_with_bids",
]

COOLDOWN: timedelta = timedelta(hours=1)
HOURLY_LOG_INTERVAL: timedelta = timedelta(hours=1)


class Action(StrEnum):
    SET_BID = "set_bid"
    REMOVE = "remove"
    FETCH_BIDS = "fetch_bids"
    NOOP = "noop"


@dataclass(frozen=True)
class Decision:
    action: Action
    bid_penny: int | None = None
    limit_penny: int | None = None
    log_message: str = ""
    compare_percent: int = 0
    write_log: bool = False
    log_bid: int | None = None  # реальный bid для записи (могут отличаться)
    write_system_note: tuple[bool, str] | None = None
    update_critical: CriticalUpdate | None = None


@dataclass(frozen=True)
class DecisionInput:
    ctx: PromotionContext
    now: datetime
    rates_snapshot: dict | None
    stats_snapshot: dict | None
    bids_info: dict | None
    last_set_at: datetime | None
    cached_event: str | None


# ---------- helpers ----------


def _hourly_log_due(last_log_ts: datetime | None, now: datetime) -> bool:
    if last_log_ts is None:
        return True
    return now - last_log_ts >= HOURLY_LOG_INTERVAL


def _spending_penny(stats: dict | None) -> int:
    if not stats:
        return 0
    return (
        int(stats.get("presenceSpending", 0) or 0)
        + int(stats.get("promoSpending", 0) or 0)
        + int(stats.get("restSpending", 0) or 0)
    )


def _bounds_from_promotion(
    ctx: PromotionContext,
) -> CriticalBidsData | None:
    p = ctx.promotion
    fields = (
        p.critical_min_bid,
        p.critical_max_bid,
        p.critical_min_limit,
        p.critical_max_limit,
        p.disabled_bid,
    )
    if any(f is None for f in fields):
        return None
    return CriticalBidsData(
        critical_min_bid=p.critical_min_bid,  # type: ignore[arg-type]
        critical_max_bid=p.critical_max_bid,  # type: ignore[arg-type]
        critical_min_limit=p.critical_min_limit,  # type: ignore[arg-type]
        critical_max_limit=p.critical_max_limit,  # type: ignore[arg-type]
        disabled_bid=p.disabled_bid,  # type: ignore[arg-type]
    )


def _clamp_limit(daily_budget: int | None, bounds: CriticalBidsData) -> int | None:
    if daily_budget is None:
        return None
    return max(
        bounds.critical_min_limit,
        min(bounds.critical_max_limit, daily_budget),
    )


def _system_note_text(
    log_message: str, cached_event: str | None
) -> tuple[bool, str] | None:
    """Возвращает (need_write, text) для системной заметки."""
    if cached_event == log_message:
        return None
    if log_message in SOFT_DISABLED_LOGS or log_message in (
        LOG_DISABLED_BY_TARIFF,
        LOG_LIMIT_EXCEEDED,
        LOG_PROMOTION_UNAVAILABLE,
        LOG_DISABLED_BY_ACCOUNT_DELETED,
        LOG_BID_CHANGE_FAILED,
        LOG_BID_BELOW_MIN,
    ):
        return True, log_message
    return None


# ---------- stages ----------


def _early_validation(
    inp: DecisionInput, bounds: CriticalBidsData | None
) -> Decision | None:
    ctx = inp.ctx
    p = ctx.promotion

    # 1. ad inactive
    if ctx.ad.status != "active":
        return Decision(
            action=Action.NOOP,
            log_message=LOG_USER_DELETED,
            write_system_note=_system_note_text(LOG_USER_DELETED, inp.cached_event),
        )
    # 2. not configured
    if p.bid is None or p.daily_budget is None:
        return Decision(
            action=Action.NOOP,
            log_message=LOG_NOT_CONFIGURED,
            write_system_note=_system_note_text(LOG_NOT_CONFIGURED, inp.cached_event),
        )
    # 3. tariff
    today = inp.now.date()
    if (
        ctx.profile is None
        or ctx.profile.manual_promotion_limit <= 0
        or ctx.profile.manual_promotion_end_date is None
        or ctx.profile.manual_promotion_end_date < today
    ):
        return Decision(
            action=Action.NOOP,
            log_message=LOG_DISABLED_BY_TARIFF,
            write_system_note=_system_note_text(
                LOG_DISABLED_BY_TARIFF, inp.cached_event
            ),
        )
    # 4. limit
    if ctx.profile_rank > ctx.profile.manual_promotion_limit:
        return Decision(
            action=Action.NOOP,
            log_message=LOG_LIMIT_EXCEEDED,
            write_system_note=_system_note_text(LOG_LIMIT_EXCEEDED, inp.cached_event),
        )
    # 5. need critical_* — запрашиваем bids
    if bounds is None:
        return Decision(action=Action.FETCH_BIDS)
    return None


def _disable_by_schedule_or_metrics(
    inp: DecisionInput, bounds: CriticalBidsData
) -> Decision | None:
    p = inp.ctx.promotion
    # 7. schedule
    if not is_in_work_schedule(inp.now, p.work_days, p.work_hours_mask):
        return _build_disable(inp, bounds, LOG_DISABLED_BY_TIME)
    stats = inp.stats_snapshot or {}
    spending = _spending_penny(stats)
    views = int(stats.get("views", 0) or 0)
    contacts = int(stats.get("contacts", 0) or 0)
    impressions = int(stats.get("impressions", 0) or 0)

    # 8. budget
    if p.daily_budget is not None and spending >= p.daily_budget:
        return _build_disable(inp, bounds, LOG_DISABLED_BY_BUDGET)
    # 9. impressions
    if p.disable_impressions_limit and impressions >= p.disable_impressions_limit:
        return _build_disable(inp, bounds, LOG_DISABLED_BY_IMPRESSIONS)
    # 10. views
    if p.disable_views_limit and views >= p.disable_views_limit:
        return _build_disable(inp, bounds, LOG_DISABLED_BY_VIEWS)
    # 11. contacts
    if p.disable_contacts_limit and contacts >= p.disable_contacts_limit:
        return _build_disable(inp, bounds, LOG_DISABLED_BY_CONTACTS)
    # 12. CPV
    if (
        p.disable_cost_per_view_limit
        and views > 0
        and (spending // views) >= p.disable_cost_per_view_limit
    ):
        return _build_disable(inp, bounds, LOG_DISABLED_BY_CPV)
    # 13. CPC
    if (
        p.disable_cost_per_contact_limit
        and contacts > 0
        and (spending // contacts) >= p.disable_cost_per_contact_limit
    ):
        return _build_disable(inp, bounds, LOG_DISABLED_BY_CPC)
    return None


def _build_disable(
    inp: DecisionInput,
    bounds: CriticalBidsData,
    log_message: str,
) -> Decision:
    last_ts = inp.ctx.last_log.timestamp if inp.ctx.last_log else None
    write_log = _hourly_log_due(last_ts, inp.now) or (inp.cached_event != log_message)
    compare = _compare_percent_for(bounds.disabled_bid, inp.bids_info)
    return Decision(
        action=Action.REMOVE,
        log_message=log_message,
        compare_percent=compare,
        write_log=write_log,
        log_bid=bounds.disabled_bid,
        write_system_note=_system_note_text(log_message, inp.cached_event),
    )


def _compare_percent_for(bid: int, bids_info: dict | None) -> int:
    if not isinstance(bids_info, dict):
        return 0
    manual = bids_info.get("manual")
    if not isinstance(manual, dict):
        return 0
    return pick_compare_percent(bid, manual.get("bids"))


# ---------- main ----------


def compute_target_state(inp: DecisionInput) -> Decision:
    """Чистая функция. См. docstring модуля для последовательности stages."""
    ctx = inp.ctx
    bounds = _bounds_from_promotion(ctx)
    early = _early_validation(inp, bounds)
    if early is not None:
        return early
    # bounds здесь точно not None (stage 5 уже прошёл)
    assert bounds is not None  # noqa: S101

    # 6. CPxPromo доступен?  Имеет смысл проверить только если есть bids_info
    if inp.bids_info is not None:
        parsed = parse_critical_bids(inp.bids_info)
        if parsed is None:
            return Decision(
                action=Action.NOOP,
                log_message=LOG_PROMOTION_UNAVAILABLE,
                write_system_note=_system_note_text(
                    LOG_PROMOTION_UNAVAILABLE, inp.cached_event
                ),
            )

    # 7-13. отключения по расписанию/метрикам
    disable = _disable_by_schedule_or_metrics(inp, bounds)
    if disable is not None:
        return disable

    p = ctx.promotion
    bid = p.bid
    assert bid is not None  # stage 2 уже отсеял None

    # 14. ставка ниже минимума
    if bid < bounds.critical_min_bid:
        return Decision(
            action=Action.NOOP,
            log_message=LOG_BID_BELOW_MIN,
            write_system_note=_system_note_text(LOG_BID_BELOW_MIN, inp.cached_event),
        )
    # 15. ставка выше максимума
    if bid > bounds.critical_max_bid:
        return Decision(
            action=Action.NOOP,
            log_message=LOG_BID_ABOVE_MAX_PREFIX,
        )

    limit_to_send = _clamp_limit(p.daily_budget, bounds)

    # 16-17. drift detection
    rates = inp.rates_snapshot or {}
    current_bid = rates.get("bidPenny")
    current_limit = rates.get("limitPenny")
    drift = current_bid != bid or (
        limit_to_send is not None and current_limit != limit_to_send
    )
    cooldown_ok = inp.last_set_at is None or (inp.now - inp.last_set_at) >= COOLDOWN
    last_log_ts = ctx.last_log.timestamp if ctx.last_log else None
    hourly_due = _hourly_log_due(last_log_ts, inp.now)

    # Если будем писать лог, а bids_info ещё нет — нужен FETCH_BIDS
    # чтобы получить точный compare_percent.
    will_write_log = (drift and cooldown_ok) or hourly_due
    if will_write_log and inp.bids_info is None:
        return Decision(action=Action.FETCH_BIDS)

    compare = _compare_percent_for(bid, inp.bids_info)

    if drift and cooldown_ok:
        # 16. фактическое перевыставление
        return Decision(
            action=Action.SET_BID,
            bid_penny=bid,
            limit_penny=limit_to_send,
            log_message=LOG_SUCCESS,
            compare_percent=compare,
            write_log=True,
            log_bid=bid,
            write_system_note=_system_note_text(LOG_SUCCESS, inp.cached_event),
        )
    if drift and not cooldown_ok:
        # 17. ждём окончания cooldown
        return Decision(action=Action.NOOP)
    # 18. нет drift — пишем регулярный snapshot если час прошёл
    return Decision(
        action=Action.NOOP,
        log_message=LOG_SUCCESS,
        compare_percent=compare,
        write_log=hourly_due,
        log_bid=bid,
        write_system_note=_system_note_text(LOG_SUCCESS, inp.cached_event),
    )


def recompute_with_bids(
    inp: DecisionInput, bids_info: dict
) -> tuple[Decision, CriticalUpdate | None]:
    """Повторный прогон после FETCH_BIDS — заполняет update_critical.

    Возвращает (Decision, CriticalUpdate | None). caller должен:
    - применить CriticalUpdate (если он не None) к ManualPromotion в БД
      и обновить promotion в текущей памяти,
    - применить Decision как обычно.

    Если parse_critical_bids вернёт None — возвращается Decision
    NOOP/LOG_PROMOTION_UNAVAILABLE.
    """
    parsed = parse_critical_bids(bids_info)
    if parsed is None:
        msg = LOG_PROMOTION_UNAVAILABLE
        return (
            Decision(
                action=Action.NOOP,
                log_message=msg,
                write_system_note=_system_note_text(msg, inp.cached_event),
            ),
            None,
        )

    p = inp.ctx.promotion
    update_payload: CriticalUpdate | None = None
    needs_update = (
        p.critical_min_bid != parsed.critical_min_bid
        or p.critical_max_bid != parsed.critical_max_bid
        or p.critical_min_limit != parsed.critical_min_limit
        or p.critical_max_limit != parsed.critical_max_limit
        or p.disabled_bid != parsed.disabled_bid
    )
    if needs_update:
        update_payload = CriticalUpdate(
            critical_min_bid=parsed.critical_min_bid,
            critical_max_bid=parsed.critical_max_bid,
            critical_min_limit=parsed.critical_min_limit,
            critical_max_limit=parsed.critical_max_limit,
            disabled_bid=parsed.disabled_bid,
        )
        p.critical_min_bid = parsed.critical_min_bid
        p.critical_max_bid = parsed.critical_max_bid
        p.critical_min_limit = parsed.critical_min_limit
        p.critical_max_limit = parsed.critical_max_limit
        p.disabled_bid = parsed.disabled_bid

    new_inp = DecisionInput(
        ctx=inp.ctx,
        now=inp.now,
        rates_snapshot=inp.rates_snapshot,
        stats_snapshot=inp.stats_snapshot,
        bids_info=bids_info,
        last_set_at=inp.last_set_at,
        cached_event=inp.cached_event,
    )
    decision = compute_target_state(new_inp)
    if update_payload is not None:
        decision = Decision(
            action=decision.action,
            bid_penny=decision.bid_penny,
            limit_penny=decision.limit_penny,
            log_message=decision.log_message,
            compare_percent=decision.compare_percent,
            write_log=decision.write_log,
            log_bid=decision.log_bid,
            write_system_note=decision.write_system_note,
            update_critical=update_payload,
        )
    return decision, update_payload
