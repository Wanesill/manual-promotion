"""Redis-кэш Avito-снапшотов с in-process fallback.

Ключи:
- mp:rates:{account_id}   TTL 300
- mp:bids:{ad_id}         TTL 3600

Токены аккаунтов НЕ кэшируем — читаем их напрямую из БД (Account.access_token),
refresh выполняет родительский сервис.

Статистика (`ad_detail_statistic`) НЕ кэшируется здесь — читаем напрямую
из БД каждый цикл (5 мин), родительский сервис её ведёт.

При недоступности Redis (RedisError) — fallback на cachetools.TTLCache
с per-key asyncio.Lock против thundering herd.

Сериализация через orjson.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Final

import orjson
from cachetools import TTLCache
from loguru import logger
from redis.asyncio import Redis
from redis.exceptions import RedisError

__all__ = ["AvitoCache"]

RATES_TTL_S: Final[int] = 300
BIDS_TTL_S: Final[int] = 3600
NAMESPACE: Final[str] = "mp"


class AvitoCache:
    """Двухуровневый кэш: Redis -> in-process TTLCache."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._rates_local: TTLCache = TTLCache(maxsize=10_000, ttl=RATES_TTL_S)
        self._bids_local: TTLCache = TTLCache(maxsize=100_000, ttl=BIDS_TTL_S)
        self._key_locks: dict[str, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()

    # ---------- helpers ----------

    async def _lock(self, key: str) -> asyncio.Lock:
        async with self._locks_guard:
            lock = self._key_locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._key_locks[key] = lock
            return lock

    @staticmethod
    def _dump(value: object) -> bytes:
        return orjson.dumps(value)

    @staticmethod
    def _load(data: bytes | str) -> object:
        return orjson.loads(data)

    async def _redis_get(self, key: str) -> object | None:
        try:
            raw = await self._redis.get(key)
        except RedisError as err:
            logger.warning("Redis get {} ошибка: {}", key, err)
            return None
        if raw is None:
            return None
        try:
            return self._load(raw)
        except orjson.JSONDecodeError:
            return None

    async def _redis_setex(self, key: str, ttl: int, value: object) -> None:
        if ttl <= 0:
            return
        try:
            await self._redis.set(key, self._dump(value), ex=ttl)
        except RedisError as err:
            logger.warning("Redis set {} ошибка: {}", key, err)

    async def _redis_del(self, key: str) -> None:
        try:
            await self._redis.delete(key)
        except RedisError as err:
            logger.warning("Redis del {} ошибка: {}", key, err)

    # ---------- rates (текущие установленные ставки аккаунта) ----------

    @staticmethod
    def _rates_key(account_id: int) -> str:
        return f"{NAMESPACE}:rates:{account_id}"

    async def get_or_set_rates(
        self,
        account_id: int,
        fetch: Callable[[], Awaitable[dict]],
    ) -> dict:
        """Возвращает snapshot get_actual_rates: dict[ad_id, dict]."""
        key = self._rates_key(account_id)
        cached = await self._redis_get(key)
        if isinstance(cached, dict):
            return {int(k): v for k, v in cached.items()}
        if cached is None and key in self._rates_local:
            return self._rates_local[key]

        lock = await self._lock(key)
        async with lock:
            cached = await self._redis_get(key)
            if isinstance(cached, dict):
                return {int(k): v for k, v in cached.items()}
            if cached is None and key in self._rates_local:
                return self._rates_local[key]
            fresh = await fetch()
            await self._redis_setex(key, RATES_TTL_S, fresh)
            self._rates_local[key] = fresh
            return fresh

    async def invalidate_rates(self, account_id: int) -> None:
        key = self._rates_key(account_id)
        await self._redis_del(key)
        self._rates_local.pop(key, None)

    # ---------- bids (границы ставок) ----------

    @staticmethod
    def _bids_key(ad_id: int) -> str:
        return f"{NAMESPACE}:bids:{ad_id}"

    async def get_or_set_bids(
        self,
        ad_id: int,
        fetch: Callable[[], Awaitable[dict | None]],
    ) -> dict | None:
        key = self._bids_key(ad_id)
        cached = await self._redis_get(key)
        if isinstance(cached, dict):
            return cached
        if cached is None and key in self._bids_local:
            return self._bids_local[key]

        lock = await self._lock(key)
        async with lock:
            cached = await self._redis_get(key)
            if isinstance(cached, dict):
                return cached
            if cached is None and key in self._bids_local:
                return self._bids_local[key]
            fresh = await fetch()
            if fresh is not None:
                await self._redis_setex(key, BIDS_TTL_S, fresh)
                self._bids_local[key] = fresh
            return fresh

    async def invalidate_bids(self, ad_id: int) -> None:
        key = self._bids_key(ad_id)
        await self._redis_del(key)
        self._bids_local.pop(key, None)
