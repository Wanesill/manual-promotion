"""Decision engine — чистая функция compute_target_state.

Без I/O: принимает контекст, возвращает Decision (что делать дальше).
Caller (apply_decision) выполняет сетевые вызовы и записи в БД.

Stages (порядок ранних выходов, повторён в коде compute_target_state):
1. ad.status != active                    → NOOP   LOG_USER_DELETED
2. promotion.bid IS NULL                  → NOOP   LOG_NOT_CONFIGURED
3. profile / limit / end_date             → NOOP   LOG_DISABLED_BY_TARIFF
4. critical_* в БД отсутствуют            → FETCH_BIDS
5. parse_critical_bids -> None            → NOOP   LOG_PROMOTION_UNAVAILABLE
6. !in_work_schedule                      → REMOVE LOG_DISABLED_BY_TIME
7. spending >= daily_budget (если задан)  → REMOVE LOG_DISABLED_BY_BUDGET
8-12. метрики                             → REMOVE LOG_DISABLED_BY_*
13. bid < critical_min_bid                → NOOP   LOG_BID_BELOW_MIN
14. bid > critical_max_bid                → NOOP   LOG_BID_ABOVE_MAX(...)
15. drift && cooldown_ok                  → SET_BID LOG_SUCCESS
16. drift && !cooldown_ok                 → NOOP
17. !drift && hourly_log_due              → NOOP write_log=True

`bid` обязателен; ставку за пределами critical_min_bid / critical_max_bid
не зажимаем — возвращаем NOOP с ошибочным log_message.
`daily_budget` опционален: если None → limitPenny в Avito не отправляем,
бюджет не проверяем. Если задан и вышел за critical_min_limit /
critical_max_limit — зажимаем до критического, округляя до рубля.

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
    stats_snapshot: dict | None
    bids_info: dict | None


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
    """Лимит для set_manual_bid с округлением до рубля при clamp'е.

    - `daily_budget is None` → None: limitPenny в Avito не отправляем.
    - daily_budget < critical_min_limit → ceil(min/100)*100 (вверх до рубля,
      чтобы попасть >= min).
    - daily_budget > critical_max_limit → floor(max/100)*100 (вниз до рубля,
      чтобы попасть <= max).
    - daily_budget внутри границ → отдаём как есть.
    """
    if daily_budget is None:
        return None
    if daily_budget < bounds.critical_min_limit:
        return ((bounds.critical_min_limit + 99) // 100) * 100
    if daily_budget > bounds.critical_max_limit:
        return (bounds.critical_max_limit // 100) * 100
    return daily_budget


def _system_note_text(
    log_message: str, prev_log_message: str | None
) -> tuple[bool, str] | None:
    """Возвращает (need_write, text) для системной заметки.

    Дедупликация по последнему канонически записанному `log_message`
    (`ManualPromotion.log_message`): если состояние не сменилось — не пишем.
    """
    if prev_log_message == log_message:
        return None
    if log_message in SOFT_DISABLED_LOGS or log_message in (
        LOG_DISABLED_BY_TARIFF,
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
            write_system_note=_system_note_text(
                LOG_USER_DELETED, inp.ctx.promotion.log_message
            ),
        )
    # 2. not configured (bid обязателен; daily_budget — опционален)
    if p.bid is None:
        return Decision(
            action=Action.NOOP,
            log_message=LOG_NOT_CONFIGURED,
            write_system_note=_system_note_text(
                LOG_NOT_CONFIGURED, inp.ctx.promotion.log_message
            ),
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
                LOG_DISABLED_BY_TARIFF, inp.ctx.promotion.log_message
            ),
        )
    # 4. need critical_* — запрашиваем bids
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
    write_log = _hourly_log_due(last_ts, inp.now) or (
        inp.ctx.promotion.log_message != log_message
    )
    compare = _compare_percent_for(bounds.disabled_bid, inp.bids_info)
    return Decision(
        action=Action.REMOVE,
        log_message=log_message,
        compare_percent=compare,
        write_log=write_log,
        log_bid=bounds.disabled_bid,
        write_system_note=_system_note_text(log_message, inp.ctx.promotion.log_message),
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
                    LOG_PROMOTION_UNAVAILABLE, inp.ctx.promotion.log_message
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
            write_system_note=_system_note_text(
                LOG_BID_BELOW_MIN, inp.ctx.promotion.log_message
            ),
        )
    # 15. ставка выше максимума
    if bid > bounds.critical_max_bid:
        return Decision(
            action=Action.NOOP,
            log_message=LOG_BID_ABOVE_MAX_PREFIX,
        )

    limit_to_send = _clamp_limit(p.daily_budget, bounds)

    # 16-17. drift detection
    # Источник "что уже стоит на Avito" — наш собственный лог ставок
    # (`ManualPromotionLog.bid`). Лимит туда не пишем, поэтому при заданном
    # `limit_to_send` (== `daily_budget != None`, гарантировано stage 2)
    # считаем drift, чтобы дотолкнуть лимит на следующем cooldown'е.
    last_bid = inp.ctx.last_log.bid if inp.ctx.last_log else None
    drift = last_bid != bid or limit_to_send is not None
    last_log_ts = ctx.last_log.timestamp if ctx.last_log else None
    # Cooldown-якорь — последняя запись в manual_promotion_log (там лежат
    # и SET_BID, и почасовые snapshot'ы). Worst case: drift сразу после
    # hourly snapshot'а будет ждать ещё час до пуша. На стабильном
    # состоянии разницы нет.
    cooldown_ok = last_log_ts is None or (inp.now - last_log_ts) >= COOLDOWN
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
            write_system_note=_system_note_text(
                LOG_SUCCESS, inp.ctx.promotion.log_message
            ),
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
        write_system_note=_system_note_text(LOG_SUCCESS, inp.ctx.promotion.log_message),
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
                write_system_note=_system_note_text(msg, inp.ctx.promotion.log_message),
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
        stats_snapshot=inp.stats_snapshot,
        bids_info=bids_info,
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
