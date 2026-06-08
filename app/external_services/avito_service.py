"""Клиент Avito CPxPromo API.

Singleton aiohttp.ClientSession + TCPConnector(30 per host, DNS 5 мин).
Сетевые ошибки повторяются через @retry_with_backoff; 429/500/503/504
повторяются внутри метода с уважением заголовка `x-ratelimit-retry-after`;
HTTP 403 пробрасывается как AccountForbiddenError для caller-side handling.

Rate limits (per account) контролируются НЕ здесь, а в `AccountRateLimiter`
(infra/rate_limiter.py) — вызывается caller'ом перед методом.

Аутентификация (получение access_token по client_id/secret) НЕ выполняется
этим сервисом — токен пишет родительский API. Здесь токен только читается
из БД и используется как есть.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from functools import wraps
from typing import Any

import aiohttp
from aiohttp import ClientTimeout, TCPConnector
from aiohttp.client_exceptions import (
    ClientConnectorError,
    ClientError,
    ClientPayloadError,
    ServerDisconnectedError,
)
from loguru import logger

__all__ = ["AccountForbiddenError", "AvitoService"]

MANUAL_PROMOTION_ACTION_TYPE_ID: int = 5


class AccountForbiddenError(Exception):
    """403 от Avito API — токен/доступ невалиден, требует caller-side handling."""

    def __init__(self, user_id: int) -> None:
        self.user_id = user_id
        super().__init__(f"403 Forbidden for user {user_id}")


def retry_with_backoff(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    max_delay: float = 60.0,
) -> Callable:
    """Декоратор с экспоненциальным backoff для сетевых ошибок."""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            delay = initial_delay
            last_exception: BaseException | None = None
            self_instance = args[0] if args else None
            user_id = getattr(self_instance, "user_id", "unknown")

            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except (
                    TimeoutError,
                    ServerDisconnectedError,
                    ClientConnectorError,
                    ClientPayloadError,
                ) as err:
                    last_exception = err
                    logger.warning(
                        "Avito {} попытка {}/{} аккаунт {} {}: {}",
                        func.__name__,
                        attempt + 1,
                        max_retries,
                        user_id,
                        type(err).__name__,
                        err,
                    )
                    if attempt < max_retries - 1:
                        await asyncio.sleep(delay)
                        delay = min(delay * backoff_factor, max_delay)

            logger.error(
                "Avito {} — все {} попыток исчерпаны для аккаунта {}",
                func.__name__,
                max_retries,
                user_id,
            )
            annotation = func.__annotations__.get("return", "")
            annotation_str = str(annotation)
            if "dict" in annotation_str:
                return {}
            if "list" in annotation_str:
                return []
            if "None" in annotation_str:
                return None
            if "bool" in annotation_str:
                return False
            if last_exception is not None:
                raise last_exception
            return None

        return wrapper

    return decorator


class AvitoService:
    """Singleton aiohttp ClientSession + типизированная обёртка над API."""

    _session: aiohttp.ClientSession | None = None
    _connector: TCPConnector | None = None
    _session_lock: asyncio.Lock = asyncio.Lock()

    ten_minutes_timeout: ClientTimeout = ClientTimeout(total=600)

    def __init__(self, user_id: int, token: str) -> None:
        self.user_id = user_id
        self.token = token

    # ---------- сессия ----------

    @classmethod
    async def get_session(cls) -> aiohttp.ClientSession:
        """Возвращает singleton ClientSession (double-check lock)."""
        if cls._session is None or cls._session.closed:
            async with cls._session_lock:
                if cls._session is None or cls._session.closed:
                    cls._connector = TCPConnector(
                        limit=100,
                        limit_per_host=30,
                        ttl_dns_cache=300,
                        enable_cleanup_closed=True,
                        ssl=False,
                    )
                    cls._session = aiohttp.ClientSession(
                        connector=cls._connector,
                        timeout=cls.ten_minutes_timeout,
                    )
                    logger.info("Avito ClientSession создана")
        return cls._session

    @classmethod
    async def close_session(cls) -> None:
        """Graceful shutdown: закрывает singleton session."""
        async with cls._session_lock:
            if cls._session and not cls._session.closed:
                await cls._session.close()
                logger.info("Avito ClientSession закрыта")
            cls._session = None
            cls._connector = None

    def get_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    # ---------- per-ad: границы ставок ----------

    @retry_with_backoff()
    async def get_bids(self, ad_id: int) -> dict:
        """GET /cpxpromo/1/getBids/{ad_id} — границы ставок и таблица compare.

        Сырая структура из плана:
        {"actionTypeID": int, "auto": {...}, "manual": {
            "bidPenny", "limitPenny", "minBidPenny", "maxBidPenny",
            "minLimitPenny", "maxLimitPenny", "recBidPenny",
            "bids": [{"compare", "valuePenny", "maxForecast", "minForecast"}]
        }, "selectedType": str}
        """
        session = await self.get_session()
        while True:
            try:
                async with session.get(
                    url=(f"https://api.avito.ru/cpxpromo/1/getBids/{ad_id}"),
                    headers=self.get_headers(),
                    timeout=self.ten_minutes_timeout,
                ) as response:
                    if response.status in (429, 500, 503, 504):
                        retry_after = (
                            int(response.headers.get("x-ratelimit-retry-after", "5"))
                            + 1
                        )
                        await asyncio.sleep(retry_after)
                        continue
                    if response.status == 403:
                        raise AccountForbiddenError(user_id=self.user_id)
                    response.raise_for_status()
                    return await response.json()
            except ClientError as err:
                if not isinstance(
                    err,
                    (
                        ServerDisconnectedError,
                        ClientConnectorError,
                        ClientPayloadError,
                    ),
                ):
                    logger.warning(
                        "get_bids({}) сбой, аккаунт {}: {}",
                        ad_id,
                        self.user_id,
                        err,
                    )
                    return {}
                raise

    # ---------- per-ad: установка ставки + лимита ----------

    @retry_with_backoff()
    async def set_manual_bid(
        self,
        ad_id: int,
        bid: int,
        limit_penny: int | None = None,
    ) -> bool | None:
        """POST /cpxpromo/1/setManual.

        Возвращает:
        - True  — успешно (HTTP 2xx)
        - None  — HTTP 400 (Avito отверг ставку — пересчитать границы)
        - False — нерекаверабельная ошибка (caller пишет LOG_BID_CHANGE_FAILED)
        """
        session = await self.get_session()
        payload: dict[str, Any] = {
            "actionTypeID": MANUAL_PROMOTION_ACTION_TYPE_ID,
            "itemID": ad_id,
            "bidPenny": bid,
        }
        if limit_penny is not None:
            payload["limitPenny"] = limit_penny

        while True:
            try:
                async with session.post(
                    url="https://api.avito.ru/cpxpromo/1/setManual",
                    timeout=self.ten_minutes_timeout,
                    headers=self.get_headers(),
                    json=payload,
                ) as response:
                    if response.status in (429, 500, 503, 504):
                        retry_after = int(
                            response.headers.get("x-ratelimit-retry-after", "2")
                        )
                        await asyncio.sleep(retry_after)
                        continue
                    if response.status == 403:
                        raise AccountForbiddenError(user_id=self.user_id)
                    if response.status == 400:
                        text = await response.text()
                        logger.warning(
                            "set_manual_bid 400 ad={} bid={} acc={} body={}",
                            ad_id,
                            bid,
                            self.user_id,
                            text,
                        )
                        return None
                    response.raise_for_status()
                    await response.text()
                    return True
            except ClientError as err:
                if not isinstance(
                    err,
                    (
                        ServerDisconnectedError,
                        ClientConnectorError,
                        ClientPayloadError,
                    ),
                ):
                    logger.exception(
                        "set_manual_bid сбой ad={} bid={} acc={}",
                        ad_id,
                        bid,
                        self.user_id,
                    )
                    return False
                raise

    # ---------- per-ad: отключение ----------

    @retry_with_backoff()
    async def remove_cpxpromo(self, ad_id: int) -> None:
        """POST /cpxpromo/1/remove — снимает объявление с продвижения."""
        session = await self.get_session()
        while True:
            try:
                async with session.post(
                    url="https://api.avito.ru/cpxpromo/1/remove",
                    timeout=self.ten_minutes_timeout,
                    json={"itemID": ad_id},
                    headers=self.get_headers(),
                ) as response:
                    if response.status in (429, 500, 503, 504):
                        retry_after = (
                            int(response.headers.get("x-ratelimit-retry-after", "5"))
                            + 1
                        )
                        await asyncio.sleep(retry_after)
                        continue
                    if response.status == 403:
                        raise AccountForbiddenError(user_id=self.user_id)
                    response.raise_for_status()
                    await response.text()
                    return
            except ClientError as err:
                if not isinstance(
                    err,
                    (
                        ServerDisconnectedError,
                        ClientConnectorError,
                        ClientPayloadError,
                    ),
                ):
                    logger.exception(
                        "remove_cpxpromo сбой ad={} acc={}",
                        ad_id,
                        self.user_id,
                    )
                    return
                raise
