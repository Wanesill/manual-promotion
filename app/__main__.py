"""Точка входа сервиса manual-promotion dispatcher."""

from __future__ import annotations

import asyncio
import contextlib
import locale
import signal
import sys
from datetime import date
from typing import Final

import uvloop
from loguru import logger
from redis.asyncio import ConnectionPool, Redis
from redis.asyncio.retry import Retry
from redis.backoff import ExponentialBackoff
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

from app.database.database import Database
from app.dispatcher.process_dispatcher import run_dispatcher_loop
from app.external_services import AvitoService
from app.infra import AccountRateLimiter, AvitoCache, StateStore
from app.settings import (
    DatabaseConfig,
    LoggingConfig,
    RedisConfig,
    get_config,
)
from app.utils import sanitize_message

LOGS_DIR: Final[str] = "logs"
LOCALE_SETTING: Final[str] = "ru_RU.UTF-8"

LOG_FORMAT: Final[str] = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> "
    "<level>{level:<7}</level> "
    "<cyan>{name}:{line}</cyan> {message}"
)


def _sanitize_record(record) -> None:
    record["message"] = sanitize_message(record["message"])


def setup_logging() -> None:
    """loguru: stderr (опционально) + ротация файлов по дате."""
    cfg: LoggingConfig = get_config(model=LoggingConfig, root_key="logging")
    logger.remove()
    logger.configure(patcher=_sanitize_record)

    if cfg.console:
        logger.add(
            sys.stderr,
            level=cfg.level,
            format=LOG_FORMAT,
            colorize=True,
            backtrace=True,
            diagnose=False,
        )

    logger.add(
        f"{LOGS_DIR}/{date.today()}.log",
        level=cfg.level,
        format=LOG_FORMAT,
        encoding="utf-8",
        retention="30 days",
    )


async def main() -> None:
    setup_logging()
    try:
        locale.setlocale(category=locale.LC_TIME, locale=LOCALE_SETTING)
    except locale.Error:
        logger.warning(
            "Не удалось установить locale {} — продолжаем",
            LOCALE_SETTING,
        )

    redis_config: RedisConfig = get_config(model=RedisConfig, root_key="redis")
    database_config: DatabaseConfig = get_config(
        model=DatabaseConfig, root_key="database"
    )

    pool: ConnectionPool = ConnectionPool.from_url(url=str(redis_config.dsn))
    redis: Redis = Redis(
        connection_pool=pool,
        health_check_interval=30,
        retry=Retry(ExponentialBackoff(cap=10, base=1), retries=10),
        retry_on_error=[RedisConnectionError, RedisTimeoutError],
    )

    engine: AsyncEngine = create_async_engine(
        url=str(database_config.dsn),
        echo=database_config.echo,
        pool_size=database_config.pool_size,
        max_overflow=database_config.max_overflow,
        pool_timeout=database_config.pool_timeout,
        pool_recycle=database_config.pool_recycle,
        pool_pre_ping=True,
    )
    sessionmaker: async_sessionmaker = async_sessionmaker(
        bind=engine, expire_on_commit=False
    )

    database = Database(sessionmaker=sessionmaker)
    cache = AvitoCache(redis=redis)
    state = StateStore(redis=redis)
    rate_limiter = AccountRateLimiter()

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop_event.set)

    dispatcher_task = asyncio.create_task(
        run_dispatcher_loop(
            database=database,
            cache=cache,
            rate_limiter=rate_limiter,
            state=state,
            stop_event=stop_event,
        )
    )

    logger.info("Сервис manual-promotion запущен")
    try:
        done, pending = await asyncio.wait(
            {dispatcher_task, asyncio.create_task(stop_event.wait())},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if not dispatcher_task.done():
            stop_event.set()
            dispatcher_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await dispatcher_task
    finally:
        await AvitoService.close_session()
        await redis.aclose()
        await engine.dispose()
        logger.info("Сервис manual-promotion остановлен")


if __name__ == "__main__":
    uvloop.install()
    asyncio.run(main())
