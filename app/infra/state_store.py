"""Redis state store: 1-часовой cooldown и дедупликация системных заметок.

Ключи:
- mp:last_set:{ad_id}            TTL ~25ч  — timestamp последнего set_manual_bid
- mp:last_event:{promotion_id}   без TTL   — канонический log_message события

Read-after-write на own writes гарантируется отсутствием конкуренции
(один инстанс dispatcher). При потере Redis worst case — лишний
set_manual_bid в следующем цикле и одна дублированная заметка
при рестарте (приемлемо, см. план).
"""

from __future__ import annotations

from datetime import datetime
from typing import Final

from loguru import logger
from redis.asyncio import Redis
from redis.exceptions import RedisError

__all__ = ["StateStore"]

LAST_SET_TTL_S: Final[int] = 90_000  # ~25 часов
NAMESPACE: Final[str] = "mp"


class StateStore:
    """Тонкая обёртка над Redis для cooldown и event-дедупликации."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    # ---------- last_set_at (для 1-часового cooldown) ----------

    @staticmethod
    def _last_set_key(ad_id: int) -> str:
        return f"{NAMESPACE}:last_set:{ad_id}"

    async def get_last_set_at(self, ad_id: int) -> datetime | None:
        key = self._last_set_key(ad_id)
        try:
            raw = await self._redis.get(key)
        except RedisError as err:
            logger.warning("StateStore get last_set {} ошибка: {}", key, err)
            return None
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None

    async def mark_set(self, ad_id: int, when: datetime) -> None:
        key = self._last_set_key(ad_id)
        try:
            await self._redis.set(key, when.isoformat(), ex=LAST_SET_TTL_S)
        except RedisError as err:
            logger.warning("StateStore mark_set {} ошибка: {}", key, err)

    # ---------- last_event (для дедупликации system-заметок) ----------

    @staticmethod
    def _last_event_key(promotion_id: int) -> str:
        return f"{NAMESPACE}:last_event:{promotion_id}"

    async def get_last_event(self, promotion_id: int) -> str | None:
        key = self._last_event_key(promotion_id)
        try:
            raw = await self._redis.get(key)
        except RedisError as err:
            logger.warning("StateStore get last_event {} ошибка: {}", key, err)
            return None
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return raw

    async def set_last_event(self, promotion_id: int, event: str) -> None:
        key = self._last_event_key(promotion_id)
        try:
            await self._redis.set(key, event)
        except RedisError as err:
            logger.warning("StateStore set_last_event {} ошибка: {}", key, err)
