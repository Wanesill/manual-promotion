"""Per-account workers + supervisor.

`run_dispatcher` запускает один supervisor-таск:

- supervisor каждые `CYCLE_INTERVAL_S` (5 мин) перечитывает список активных
  аккаунтов из БД, спавнит воркеры для новых, сигналит остановку для
  отвалившихся (cancel'а нет — воркер выходит между объявлениями, не рвёт
  сетевой вызов), и подбирает упавшие задачи.
- account_loop(account_id) — независимый бесконечный цикл одного аккаунта.
  На каждой итерации:
    1. load_account_promotions → если уже пусто, выходим (supervisor поймёт);
    2. ensure_token; снимок stats; обрабатываем объявления последовательно;
    3. внутри прохода каждые `STATS_REFRESH_INTERVAL_S` (5 мин) дозагружаем
       свежие stats + `now`, потому что на 5000 объявлений с лимитом
       20/мин на get_bids цикл может длиться часами и бюджет успеет
       протечь;
    4. между объявлениями проверяем `stop_event` — это точка корректного
       выхода и для shutdown'а, и для cancel'а отвалившегося аккаунта.

Хард-таймаута на итерацию через `asyncio.wait_for` нет — цикл аккаунта
может занять часы (5000 ad × 20/мин get_bids ≈ 4 ч). Но есть soft-cap
`MAX_ITERATION_S` (6 ч), проверяется между ad'ами — если итерация затянулась
сверх него, корректно выходим, в следующей итерации стартуем заново.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
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
    )
    from app.infra.redis_cache import AvitoCache

__all__ = [
    "CYCLE_INTERVAL_S",
    "MAX_ITERATION_S",
    "STATS_REFRESH_INTERVAL_S",
    "run_dispatcher",
]

CYCLE_INTERVAL_S: Final[int] = 300
"""Целевой интервал между итерациями account_loop и supervisor refresh-тиками."""

STATS_REFRESH_INTERVAL_S: Final[int] = 300
"""Перечитывать stats + now внутри одной итерации account_loop не реже этого."""

MAX_ITERATION_S: Final[int] = 6 * 60 * 60
"""Soft-лимит одной итерации account_cycle. Проверяется на границе ad'а;
сетевой вызов не рвём. По истечении — выходим из прохода, в следующей
итерации начинаем заново (свежий load_account_promotions, заново
получаем токен если истёк, и т.д.)."""


@dataclass
class _Worker:
    task: asyncio.Task
    stop: asyncio.Event


async def run_dispatcher(
    database: Database,
    cache: AvitoCache,
    stop_event: asyncio.Event,
) -> None:
    """Точка входа: supervisor с воркерами на аккаунт."""
    workers: dict[int, _Worker] = {}
    try:
        while not stop_event.is_set():
            tick_start = time.monotonic()
            await _supervisor_tick(database, cache, stop_event, workers)
            elapsed = time.monotonic() - tick_start
            wait_for = max(0.0, CYCLE_INTERVAL_S - elapsed)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=wait_for)
                break
            except TimeoutError:
                continue
    finally:
        for worker in workers.values():
            worker.stop.set()
        if workers:
            await asyncio.gather(
                *(w.task for w in workers.values()),
                return_exceptions=True,
            )


async def _supervisor_tick(
    database: Database,
    cache: AvitoCache,
    stop_event: asyncio.Event,
    workers: dict[int, _Worker],
) -> None:
    """Один supervisor-тик: обновить список активных аккаунтов."""
    try:
        active_ids = await database.load_active_account_ids()
    except Exception:
        logger.exception("supervisor: load_active_account_ids упал")
        return

    # 1. подобрать завершённые/упавшие воркеры
    for acc_id, worker in list(workers.items()):
        if not worker.task.done():
            continue
        if exc := worker.task.exception():
            logger.error("account {} воркер упал: {}", acc_id, exc)
        workers.pop(acc_id, None)

    # 2. остановить воркеры неактивных аккаунтов (graceful, между ad'ами)
    for acc_id, worker in workers.items():
        if acc_id not in active_ids and not worker.stop.is_set():
            logger.info(
                "account {} больше не активен — останавливаем воркер", acc_id
            )
            worker.stop.set()

    # 3. поднять воркеры для новых активных аккаунтов
    for acc_id in active_ids - workers.keys():
        worker_stop = asyncio.Event()
        task = asyncio.create_task(
            _account_loop(acc_id, database, cache, stop_event, worker_stop),
            name=f"account-{acc_id}",
        )
        workers[acc_id] = _Worker(task=task, stop=worker_stop)
        logger.info("account {} запущен воркер", acc_id)

    logger.info(
        "supervisor: активных аккаунтов {}, живых воркеров {}",
        len(active_ids),
        sum(1 for w in workers.values() if not w.task.done()),
    )


async def _account_loop(
    account_id: int,
    database: Database,
    cache: AvitoCache,
    stop_event: asyncio.Event,
    worker_stop: asyncio.Event,
) -> None:
    """Бесконечный цикл одного аккаунта.

    `session` живёт на всю жизнь воркера — это нужно, чтобы in-memory токен
    от `authenticate` сохранялся между итерациями. Если воркер крашится и
    supervisor перезапускает его — у нового экземпляра `session=None`,
    и `authenticate` дёрнется заново (это и есть «refresh через restart»).
    """
    iteration = 0
    session: AccountSession | None = None
    while not stop_event.is_set() and not worker_stop.is_set():
        iteration += 1
        iter_start = time.monotonic()
        iter_deadline = iter_start + MAX_ITERATION_S
        try:
            done, session = await _account_cycle(
                account_id=account_id,
                database=database,
                cache=cache,
                stop_event=stop_event,
                worker_stop=worker_stop,
                session=session,
                iter_deadline=iter_deadline,
            )
        except Exception:
            logger.exception(
                "account {} итерация {} упала", account_id, iteration
            )
            done = False

        elapsed = time.monotonic() - iter_start
        logger.info(
            "account {} итерация {} завершена за {:.1f}с (active={})",
            account_id,
            iteration,
            elapsed,
            not done,
        )
        if done:
            return
        wait_for = max(0.0, CYCLE_INTERVAL_S - elapsed)
        if not await _sleep_or_stop(wait_for, stop_event, worker_stop):
            return


async def _account_cycle(
    account_id: int,
    database: Database,
    cache: AvitoCache,
    stop_event: asyncio.Event,
    worker_stop: asyncio.Event,
    session: AccountSession | None,
    iter_deadline: float,
) -> tuple[bool, AccountSession | None]:
    """Одна итерация цикла. Возвращает (done, session).

    `done=True` — у аккаунта не осталось активных promotion'ов
    (load_account_promotions вернул None), воркер завершается.
    `session` — пробрасывается дальше, чтобы in-memory токен пережил итерацию.
    `iter_deadline` — `time.monotonic()` после которого прерываем обход на
    границе ad'а (см. MAX_ITERATION_S).
    """
    snapshot = await database.load_account_promotions(account_id)
    if snapshot is None:
        return True, session
    account, contexts, profile_active_count = snapshot

    if session is None:
        session = AccountSession(account=account, cache=cache)
    else:
        session.update_account(account)

    if account.status == "deleted":
        await _bulk_set_log(
            database, contexts, LOG_DISABLED_BY_ACCOUNT_DELETED
        )
        return False, session

    try:
        await session.ensure_token()
    except AccountTokenError as err:
        await _bulk_set_log(database, contexts, err.log_message)
        return False, session

    stats = await session.fetch_stats_today(database)
    stats_at = time.monotonic()
    now = datetime.now()

    for ctx in contexts:
        if stop_event.is_set() or worker_stop.is_set():
            return False, session
        if time.monotonic() >= iter_deadline:
            logger.warning(
                "account {} итерация превысила {}с — прерываем на границе ad'а",
                account_id,
                MAX_ITERATION_S,
            )
            return False, session
        if time.monotonic() - stats_at >= STATS_REFRESH_INTERVAL_S:
            try:
                stats = await session.fetch_stats_today(database)
            except Exception:
                logger.exception("account {} refresh stats упал", account_id)
            else:
                stats_at = time.monotonic()
                now = datetime.now()
        try:
            log_message = await _decide_and_apply(
                ctx=ctx,
                now=now,
                session=session,
                database=database,
                stats_snapshot=stats.get(ctx.ad.ad_id),
                profile_active_count=profile_active_count,
            )
        except Exception:
            logger.exception("Сбой обработки promotion={}", ctx.promotion.id)
            continue
        if (
            log_message is not None
            and log_message != ctx.promotion.log_message
        ):
            await database.bulk_update_log_message(
                [(ctx.promotion.id, log_message)]
            )
            ctx.promotion.log_message = log_message
    return False, session


async def _decide_and_apply(
    ctx: PromotionContext,
    now: datetime,
    session: AccountSession,
    database: Database,
    stats_snapshot: dict | None,
    profile_active_count: int,
) -> str | None:
    """Один decide → (опц. fetch_bids → recompute) → apply."""
    base_input = DecisionInput(
        ctx=ctx,
        now=now,
        stats_snapshot=stats_snapshot,
        bids_info=None,
        profile_active_count=profile_active_count,
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
        now=now,
    )


async def _bulk_set_log(
    database: Database,
    contexts: list[PromotionContext],
    log_message: str,
) -> None:
    updates: list[tuple[int, str | None]] = []
    for ctx in contexts:
        if ctx.promotion.log_message != log_message:
            updates.append((ctx.promotion.id, log_message))
    await database.bulk_update_log_message(updates)


async def _sleep_or_stop(
    seconds: float,
    stop_event: asyncio.Event,
    worker_stop: asyncio.Event,
) -> bool:
    """Спит, возвращая False, если за это время взвели любой из stop-флагов."""
    if seconds <= 0:
        return not (stop_event.is_set() or worker_stop.is_set())
    waiter = asyncio.create_task(_wait_either(stop_event, worker_stop))
    try:
        await asyncio.wait_for(waiter, timeout=seconds)
        return False
    except TimeoutError:
        waiter.cancel()
        return True


async def _wait_either(a: asyncio.Event, b: asyncio.Event) -> None:
    """Ждёт, пока взведут любое из двух событий."""
    a_task = asyncio.create_task(a.wait())
    b_task = asyncio.create_task(b.wait())
    try:
        await asyncio.wait(
            {a_task, b_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
    finally:
        for t in (a_task, b_task):
            if not t.done():
                t.cancel()
