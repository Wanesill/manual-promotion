"""Обёртка над AvitoService для одного аккаунта.

Делает 3 вещи:
1. ensure_token — читает access_token из БД (refresh выполняет родительский
   сервис; здесь токен только проверяется на валидность).
2. Прокидывает rate-limit acquire перед каждым вызовом Avito API.
3. Прозрачно кэширует bids (границы ставок) в AvitoCache. Snapshot текущих
   ставок с Avito не запрашиваем — drift считаем по `ManualPromotionLog.bid`.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from app.database.models import Account
from app.external_services.avito_service import (
    AccountForbiddenError,
    AvitoService,
)
from app.infra.rate_limiter import AccountRateLimiter, Endpoint
from app.infra.redis_cache import AvitoCache
from app.log_messages import LOG_DISABLED_BY_TOKEN_EXPIRED

if TYPE_CHECKING:
    from app.database.database import Database

__all__ = ["AccountSession", "AccountTokenError"]


class AccountTokenError(Exception):
    """Не удалось получить рабочий токен — caller должен отключить ads."""

    def __init__(self, log_message: str) -> None:
        self.log_message = log_message
        super().__init__(log_message)


class AccountSession:
    """Stateful обёртка: один аккаунт = один экземпляр на цикл."""

    def __init__(
        self,
        account: Account,
        rate_limiter: AccountRateLimiter,
        cache: AvitoCache,
    ) -> None:
        self.account = account
        self._rate_limiter = rate_limiter
        self._cache = cache
        self._avito: AvitoService | None = None

    # ---------- токен ----------

    async def ensure_token(self) -> None:
        """Проверяет access_token из БД. Refresh не делаем — owner родительский."""
        acc = self.account
        if (
            not acc.access_token
            or acc.expires_in is None
            or acc.expires_in <= datetime.now()
        ):
            raise AccountTokenError(LOG_DISABLED_BY_TOKEN_EXPIRED)
        self._avito = AvitoService(user_id=acc.user_id, token=acc.access_token)

    # ---------- API ----------

    @property
    def avito(self) -> AvitoService:
        if self._avito is None:
            raise RuntimeError("ensure_token() must be called first")
        return self._avito

    async def fetch_stats_today(self, database: Database) -> dict[int, dict]:
        """Дневная дельта метрик из `ad_detail_statistic` (не Avito API)."""
        return await database.load_today_stats(account_id=self.account.id)

    async def fetch_bids(self, ad_id: int) -> dict | None:
        """get_bids(ad_id) — границы и таблица compare. Кэш 1ч."""

        async def _fetch() -> dict | None:
            await self._rate_limiter.acquire(self.account.id, Endpoint.GET_BIDS)
            try:
                result = await self.avito.get_bids(ad_id=ad_id)
            except AccountForbiddenError:
                raise
            return result or None

        return await self._cache.get_or_set_bids(ad_id, _fetch)

    async def set_manual_bid(
        self, ad_id: int, bid: int, limit_penny: int | None
    ) -> bool | None:
        await self._rate_limiter.acquire(self.account.id, Endpoint.SET_BID)
        return await self.avito.set_manual_bid(
            ad_id=ad_id, bid=bid, limit_penny=limit_penny
        )

    async def remove_cpxpromo(self, ad_id: int) -> None:
        await self._rate_limiter.acquire(self.account.id, Endpoint.REMOVE)
        await self.avito.remove_cpxpromo(ad_id=ad_id)

    async def invalidate_caches_for_ad(self, ad_id: int) -> None:
        await self._cache.invalidate_bids(ad_id)
