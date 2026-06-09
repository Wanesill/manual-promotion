"""Per-account workers + supervisor.

`run_dispatcher` запускает один supervisor-таск:

- supervisor каждые `CYCLE_INTERVAL_S` (5 мин) перечитывает список активных
  аккаунтов из БД, спавнит воркеры для новых, сигналит остановку для
  отвалившихся (cancel'а нет — воркер выходит между объявлениями, не рвёт
  сетевой вызов), и подбирает упавшие задачи.
- account_loop(account_id) — независимый бесконечный цикл одного аккаунта.
  На каждой итерации:
    1. load_account_promotions → если уже пусто, выходим (supervisor поймёт);
    2. inline token resolution: либо валидный access_token из БД
       (с запасом >= 1 ч), либо `AvitoService.authenticate` по
       client_id/secret; иначе пишем LOG_DISABLED_BY_TOKEN_EXPIRED /
       LOG_DISABLED_BY_AUTH_FAILED и заканчиваем итерацию;
    3. снимок stats; обрабатываем объявления последовательно;
    4. внутри прохода каждые `STATS_REFRESH_INTERVAL_S` (5 мин) дозагружаем
       свежие stats + `now`, потому что на 5000 объявлений с лимитом
       20/мин на get_bids цикл может длиться часами и бюджет успеет
       протечь;
    5. между объявлениями проверяем `stop_event` — это точка корректного
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

from app.database.models import Account
from app.dispatcher.apply_decision import apply_decision
from app.dispatcher.decision_engine import (
    Action,
    Decision,
    DecisionInput,
    compute_target_state,
    recompute_with_bids,
)
from app.external_services.avito_service import (
    AccountForbiddenError,
    AvitoService,
)
from app.log_messages import (
    LOG_DISABLED_BY_ACCOUNT_DELETED,
    LOG_DISABLED_BY_AUTH_FAILED,
    LOG_DISABLED_BY_TOKEN_EXPIRED,
    LOG_SUCCESS,
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
    "TOKEN_REFRESH_THRESHOLD_S",
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

TOKEN_REFRESH_THRESHOLD_S: Final[int] = 60 * 60
"""DB-токен считается невалидным, если до expires_in осталось < этого
значения. На каждой итерации проверяем — если порог нарушен, дёргаем
AvitoService.authenticate (in-memory only, в БД не пишем)."""


@dataclass
class _Worker:
    task: asyncio.Task
    stop: asyncio.Event


@dataclass
class _IterStats:
    """Счётчики одного прохода `_account_cycle`. Логируется в конце итерации."""

    processed: int = 0
    set_bid_ok: int = 0
    set_bid_rejected: int = 0  # 400/прочие неуспехи set_manual_bid
    removed: int = 0
    noop: int = 0
    fetch_bids: int = 0
    auth_403: int = 0
    errors: int = 0


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

    Никакого долгоживущего state между итерациями нет: каждая итерация
    заново загружает Account + promotions, перепроверяет токен из БД
    или дёргает authenticate, строит AvitoService локально и работает с
    ним до конца прохода.
    """
    iteration = 0
    while not stop_event.is_set() and not worker_stop.is_set():
        iteration += 1
        iter_start = time.monotonic()
        iter_deadline = iter_start + MAX_ITERATION_S
        stats: _IterStats | None = None
        try:
            done, stats = await _account_cycle(
                account_id=account_id,
                database=database,
                cache=cache,
                stop_event=stop_event,
                worker_stop=worker_stop,
                iter_deadline=iter_deadline,
            )
        except Exception:
            logger.exception(
                "account {} итерация {} упала", account_id, iteration
            )
            done = False

        elapsed = time.monotonic() - iter_start
        if stats is not None:
            logger.info(
                "account {} итерация {} {:.1f}с | processed={} set_bid_ok={} "
                "set_bid_rejected={} removed={} noop={} fetch_bids={} auth_403={} "
                "errors={}",
                account_id,
                iteration,
                elapsed,
                stats.processed,
                stats.set_bid_ok,
                stats.set_bid_rejected,
                stats.removed,
                stats.noop,
                stats.fetch_bids,
                stats.auth_403,
                stats.errors,
            )
        else:
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
    iter_deadline: float,
) -> tuple[bool, _IterStats | None]:
    """Одна итерация цикла. Возвращает (done, stats).

    `done=True` — у аккаунта не осталось активных promotion'ов
    (load_account_promotions вернул None), supervisor подберёт.
    `stats` — счётчики прохода для итогового лога. None если до прохода
    не дошли (deleted/auth_failed).
    `iter_deadline` — `time.monotonic()` после которого прерываем обход на
    границе ad'а (см. MAX_ITERATION_S).
    """
    snapshot = await database.load_account_promotions(account_id)
    if snapshot is None:
        return True, None
    account, contexts, profile_active_count = snapshot

    logger.info(
        "account {} (user_id={} profile_id={}): {} активных promotion'ов",
        account_id,
        account.user_id,
        account.profile_id,
        len(contexts),
    )

    # 1. Состояние аккаунта.
    if account.status == "deleted":
        logger.info(
            "account {}: status=deleted — выставляем LOG_DISABLED_BY_ACCOUNT_DELETED",
            account_id,
        )
        await _bulk_set_log(
            database, contexts, LOG_DISABLED_BY_ACCOUNT_DELETED
        )
        return False, None

    # 2. Авторизация — inline, без долгоживущего state.
    avito = await _resolve_avito(account)
    if avito is None:
        # _resolve_avito уже залогировал причину; решаем какой log_message
        # выставить ads, по наличию credentials.
        auth_fail_msg = (
            LOG_DISABLED_BY_TOKEN_EXPIRED
            if not account.client_id or not account.client_secret
            else LOG_DISABLED_BY_AUTH_FAILED
        )
        await _bulk_set_log(database, contexts, auth_fail_msg)
        return False, None

    iter_stats = _IterStats()
    today_stats = await database.load_today_stats(account_id=account.id)
    stats_at = time.monotonic()
    now = datetime.now()

    for ctx in contexts:
        if stop_event.is_set() or worker_stop.is_set():
            return False, iter_stats
        if time.monotonic() >= iter_deadline:
            logger.warning(
                "account {} итерация превысила {}с — прерываем на границе ad'а",
                account_id,
                MAX_ITERATION_S,
            )
            return False, iter_stats
        if time.monotonic() - stats_at >= STATS_REFRESH_INTERVAL_S:
            try:
                today_stats = await database.load_today_stats(
                    account_id=account.id
                )
            except Exception:
                logger.exception("account {} refresh stats упал", account_id)
            else:
                stats_at = time.monotonic()
                now = datetime.now()
        iter_stats.processed += 1
        try:
            log_message = await _decide_and_apply(
                ctx=ctx,
                now=now,
                avito=avito,
                cache=cache,
                database=database,
                stats_snapshot=today_stats.get(ctx.ad.ad_id),
                profile_active_count=profile_active_count,
                iter_stats=iter_stats,
            )
        except Exception:
            iter_stats.errors += 1
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
    return False, iter_stats


async def _resolve_avito(account: Account) -> AvitoService | None:
    """Строит AvitoService на текущий цикл; None — нет рабочего токена.

    Приоритет:
    - `Account.access_token` из БД, если `expires_in - now >=
      TOKEN_REFRESH_THRESHOLD_S` (с запасом, чтобы не оказаться с
      «протухшим» токеном к концу 4-часовой итерации);
    - иначе `AvitoService.authenticate(client_id, client_secret)`. Результат
      **в БД не сохраняем** — refresh устаревшего токена в Account это
      задача родительского сервиса.
    """
    has_db_token = (
        account.access_token
        and account.expires_in is not None
        and (account.expires_in - datetime.now()).total_seconds()
        >= TOKEN_REFRESH_THRESHOLD_S
    )
    if has_db_token:
        logger.info(
            "account {}: используем access_token из БД (expires={})",
            account.user_id,
            account.expires_in.isoformat() if account.expires_in else "?",
        )
        return AvitoService(
            user_id=account.user_id,
            token=account.access_token,  # type: ignore[arg-type]
        )

    if not account.client_id or not account.client_secret:
        logger.warning(
            "account {}: токен истёк, нет client creds для переавторизации",
            account.user_id,
        )
        return None

    if account.expires_in is None:
        logger.info(
            "account {}: access_token отсутствует в БД — дёргаем authenticate",
            account.user_id,
        )
    else:
        left_s = int((account.expires_in - datetime.now()).total_seconds())
        logger.info(
            "account {}: DB-токен истекает через {}с (порог {}с) — дёргаем authenticate",
            account.user_id,
            left_s,
            TOKEN_REFRESH_THRESHOLD_S,
        )

    try:
        token_data = await AvitoService.authenticate(
            client_id=account.client_id,
            client_secret=account.client_secret,
        )
    except Exception:
        logger.exception("account {}: authenticate упал", account.user_id)
        return None

    if (
        not isinstance(token_data, dict)
        or "error" in token_data
        or not token_data.get("access_token")
    ):
        logger.error(
            "account {}: authenticate вернул мусор: {}",
            account.user_id,
            token_data,
        )
        return None

    logger.info(
        "account {}: authenticate OK, expires_in={}с",
        account.user_id,
        int(token_data.get("expires_in", 0)),
    )
    return AvitoService(
        user_id=account.user_id, token=token_data["access_token"]
    )


async def _decide_and_apply(
    ctx: PromotionContext,
    now: datetime,
    avito: AvitoService,
    cache: AvitoCache,
    database: Database,
    stats_snapshot: dict | None,
    profile_active_count: int,
    iter_stats: _IterStats,
) -> str | None:
    """Один decide → (опц. fetch_bids → recompute) → apply.

    Попутно обновляет `iter_stats` (счётчики прохода) для итогового лога.
    """
    base_input = DecisionInput(
        ctx=ctx,
        now=now,
        stats_snapshot=stats_snapshot,
        bids_info=None,
        profile_active_count=profile_active_count,
    )
    decision: Decision = compute_target_state(base_input)

    if decision.action == Action.FETCH_BIDS:
        iter_stats.fetch_bids += 1
        try:
            bids_info = await _fetch_bids_cached(avito, cache, ctx.ad.ad_id)
        except AccountForbiddenError:
            iter_stats.auth_403 += 1
            return LOG_DISABLED_BY_AUTH_FAILED
        if bids_info is None:
            from app.log_messages import LOG_PROMOTION_UNAVAILABLE

            logger.debug(
                "ad={} parse_critical_bids → None (raw={})",
                ctx.ad.ad_id,
                str(bids_info)[:200],
            )
            iter_stats.noop += 1
            return LOG_PROMOTION_UNAVAILABLE
        decision, _ = recompute_with_bids(base_input, bids_info)

    log_message = await apply_decision(
        decision=decision,
        ctx=ctx,
        avito=avito,
        cache=cache,
        database=database,
        now=now,
    )

    # Счётчики по фактическому исходу:
    if decision.action == Action.SET_BID:
        if log_message == LOG_DISABLED_BY_AUTH_FAILED:
            iter_stats.auth_403 += 1
        elif log_message == LOG_SUCCESS:
            iter_stats.set_bid_ok += 1
        else:  # LOG_BID_CHANGE_FAILED и пр.
            iter_stats.set_bid_rejected += 1
    elif decision.action == Action.REMOVE:
        if log_message == LOG_DISABLED_BY_AUTH_FAILED:
            iter_stats.auth_403 += 1
        else:
            iter_stats.removed += 1
    else:
        iter_stats.noop += 1

    return log_message


async def _fetch_bids_cached(
    avito: AvitoService, cache: AvitoCache, ad_id: int
) -> dict | None:
    """get_bids(ad_id) через `AvitoCache.get_or_set_bids` (Redis TTL 1ч)."""

    async def _fetch() -> dict | None:
        result = await avito.get_bids(ad_id=ad_id)
        return result or None

    return await cache.get_or_set_bids(ad_id, _fetch)


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
