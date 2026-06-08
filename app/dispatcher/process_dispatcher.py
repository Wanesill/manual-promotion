"""Главный цикл диспетчера: 5-минутный snapshot → per-account обработка."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import TYPE_CHECKING, Final

from loguru import logger

from app.dispatcher.account_session import (
    AccountSession,
    AccountTokenError,
)
from app.dispatcher.apply_decision import apply_decision
from app.dispatcher.decision_engine import (
    Action,
    Decision,
    DecisionInput,
    compute_target_state,
    recompute_with_bids,
)
from app.external_services.avito_service import AccountForbiddenError
from app.log_messages import (
    LOG_DISABLED_BY_ACCOUNT_DELETED,
    LOG_DISABLED_BY_AUTH_FAILED,
)

if TYPE_CHECKING:
    from app.database.database import (
        Database,
        PromotionContext,
        Snapshot,
    )
    from app.database.models import Account
    from app.infra.redis_cache import AvitoCache
    from app.infra.state_store import StateStore

__all__ = [
    "CYCLE_INTERVAL_S",
    "MAX_CYCLE_TIMEOUT_MULTIPLIER",
    "cycle",
    "run_dispatcher_loop",
]

CYCLE_INTERVAL_S: Final[int] = 300
"""Интервал между стартами циклов диспетчера, секунды."""

MAX_CYCLE_TIMEOUT_MULTIPLIER: Final[int] = 3
"""Принудительный cancel если цикл идёт дольше CYCLE_INTERVAL_S × этот множитель."""


async def cycle(
    database: Database,
    cache: AvitoCache,
    state: StateStore,
    cycle_number: int,
) -> None:
    """Один полный цикл: загружает snapshot и обрабатывает по аккаунтам."""
    now = datetime.now()
    snapshot: Snapshot = await database.load_active_promotions()
    if not snapshot.by_account:
        logger.info("Цикл {} — активных promotion'ов нет", cycle_number)
        return

    total_ads = sum(len(c) for _, c in snapshot.by_account.values())
    logger.info(
        "Цикл {} старт: аккаунтов {}, объявлений {}",
        cycle_number,
        len(snapshot.by_account),
        total_ads,
    )

    await asyncio.gather(
        *(
            _process_account(
                account=account,
                contexts=contexts,
                now=now,
                database=database,
                cache=cache,
                state=state,
            )
            for account, contexts in snapshot.by_account.values()
        ),
        return_exceptions=False,
    )


async def _process_account(
    account: Account,
    contexts: list[PromotionContext],
    now: datetime,
    database: Database,
    cache: AvitoCache,
    state: StateStore,
) -> None:
    """Обрабатывает все promotion'ы одного аккаунта последовательно."""
    if account.status == "deleted":
        await _bulk_set_log(
            database,
            contexts,
            LOG_DISABLED_BY_ACCOUNT_DELETED,
            state,
        )
        return

    session = AccountSession(account=account, cache=cache)
    try:
        await session.ensure_token()
    except AccountTokenError as err:
        await _bulk_set_log(database, contexts, err.log_message, state)
        return

    stats = await session.fetch_stats_today(database)

    updates: list[tuple[int, str | None]] = []
    for ctx in contexts:
        try:
            log_message = await _decide_and_apply(
                ctx=ctx,
                now=now,
                session=session,
                database=database,
                state=state,
                stats_snapshot=stats.get(ctx.ad.ad_id),
            )
        except Exception:
            logger.exception("Сбой обработки promotion={}", ctx.promotion.id)
            continue
        if log_message is not None and log_message != ctx.promotion.log_message:
            updates.append((ctx.promotion.id, log_message))

    await database.bulk_update_log_message(updates)


async def _decide_and_apply(
    ctx: PromotionContext,
    now: datetime,
    session: AccountSession,
    database: Database,
    state: StateStore,
    stats_snapshot: dict | None,
) -> str | None:
    """Один decide → (опц. fetch_bids → recompute) → apply."""
    last_set_at = await state.get_last_set_at(ctx.ad.ad_id)
    cached_event = await state.get_last_event(ctx.promotion.id)

    base_input = DecisionInput(
        ctx=ctx,
        now=now,
        stats_snapshot=stats_snapshot,
        bids_info=None,
        last_set_at=last_set_at,
        cached_event=cached_event,
    )
    decision: Decision = compute_target_state(base_input)

    if decision.action == Action.FETCH_BIDS:
        try:
            bids_info = await session.fetch_bids(ctx.ad.ad_id)
        except AccountForbiddenError:
            return LOG_DISABLED_BY_AUTH_FAILED
        if bids_info is None:
            from app.log_messages import LOG_PROMOTION_UNAVAILABLE

            return LOG_PROMOTION_UNAVAILABLE
        decision, _ = recompute_with_bids(base_input, bids_info)

    return await apply_decision(
        decision=decision,
        ctx=ctx,
        session=session,
        database=database,
        state=state,
        now=now,
    )


async def _bulk_set_log(
    database: Database,
    contexts: list[PromotionContext],
    log_message: str,
    state: StateStore,
) -> None:
    updates: list[tuple[int, str | None]] = []
    for ctx in contexts:
        if ctx.promotion.log_message != log_message:
            updates.append((ctx.promotion.id, log_message))
            await state.set_last_event(ctx.promotion.id, log_message)
    await database.bulk_update_log_message(updates)


async def run_dispatcher_loop(
    database: Database,
    cache: AvitoCache,
    state: StateStore,
    stop_event: asyncio.Event,
) -> None:
    """Бесконечный loop с фиксированными окнами CYCLE_INTERVAL_S секунд."""
    cycle_number = 0
    max_timeout = CYCLE_INTERVAL_S * MAX_CYCLE_TIMEOUT_MULTIPLIER
    while not stop_event.is_set():
        cycle_number += 1
        cycle_start = time.monotonic()
        try:
            await asyncio.wait_for(
                cycle(
                    database=database,
                    cache=cache,
                    state=state,
                    cycle_number=cycle_number,
                ),
                timeout=max_timeout,
            )
        except TimeoutError:
            logger.error(
                "Цикл {} превысил таймаут {}с — отменён",
                cycle_number,
                max_timeout,
            )
        except Exception:
            logger.exception("Цикл {} упал", cycle_number)
        elapsed = time.monotonic() - cycle_start
        logger.info("Цикл {} завершён за {:.1f}с", cycle_number, elapsed)
        wait_for = max(0.0, CYCLE_INTERVAL_S - elapsed)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=wait_for)
            return
        except TimeoutError:
            continue
