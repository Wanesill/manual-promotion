"""Rate limiter per (account_id, endpoint) — sliding window 60 секунд.

Лимиты заданы Avito CPxPromo API:
- set_manual_bid: 20/мин/аккаунт
- get_bids: 20/мин/аккаунт
- remove_cpxpromo: 300/мин/аккаунт

Реализация: deque монотонных timestamps под per-key asyncio.Lock.
Один инстанс на процесс. Состояние теряется при рестарте — допустимо
(worst case: первая минута после рестарта может вызвать 429,
который сам Avito-клиент обработает через `x-ratelimit-retry-after`).
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from enum import StrEnum
from typing import Final

__all__ = ["AccountRateLimiter", "Endpoint", "LIMITS_PER_MIN", "WINDOW_S"]


class Endpoint(StrEnum):
    """Категории запросов с раздельными лимитами per account."""

    SET_BID = "set_bid"
    GET_BIDS = "get_bids"
    REMOVE = "remove"


LIMITS_PER_MIN: Final[dict[Endpoint, int]] = {
    Endpoint.SET_BID: 20,
    Endpoint.GET_BIDS: 20,
    Endpoint.REMOVE: 300,
}

WINDOW_S: Final[float] = 60.0


class AccountRateLimiter:
    """In-memory sliding-window rate limiter per (account_id, endpoint)."""

    def __init__(self) -> None:
        self._windows: dict[tuple[int, Endpoint], deque[float]] = defaultdict(deque)
        self._locks: dict[tuple[int, Endpoint], asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()

    async def _get_lock(self, key: tuple[int, Endpoint]) -> asyncio.Lock:
        async with self._locks_guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[key] = lock
            return lock

    async def acquire(self, account_id: int, endpoint: Endpoint) -> None:
        """Блокирует до момента, когда квота на (account, endpoint) свободна."""
        key = (account_id, endpoint)
        lock = await self._get_lock(key)
        limit = LIMITS_PER_MIN[endpoint]

        while True:
            async with lock:
                now = time.monotonic()
                window = self._windows[key]
                horizon = now - WINDOW_S
                while window and window[0] < horizon:
                    window.popleft()
                if len(window) < limit:
                    window.append(now)
                    return
                wait_for = window[0] + WINDOW_S - now
            if wait_for > 0:
                await asyncio.sleep(wait_for)

    def gc(self) -> None:
        """Удаляет пустые окна — вызывается в начале каждого цикла."""
        empty = [k for k, w in self._windows.items() if not w]
        for k in empty:
            self._windows.pop(k, None)
            self._locks.pop(k, None)
