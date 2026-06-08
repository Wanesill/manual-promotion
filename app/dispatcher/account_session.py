"""Обёртка над AvitoService для одного аккаунта.

Делает 3 вещи:
1. ensure_token — refresh access_token при истечении < 1ч до expires_in.
2. Прокидывает rate-limit acquire перед каждым вызовом Avito API.
3. Прозрачно кэширует rates / bids в AvitoCache (stats читаем из БД).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from loguru import logger

from app.database.models import Account
from app.external_services.avito_service import (
    AccountForbiddenError,
    AvitoService,
)
from app.infra.rate_limiter import AccountRateLimiter, Endpoint
from app.infra.redis_cache import AvitoCache
from app.log_messages import (
    LOG_DISABLED_BY_AUTH_FAILED,
    LOG_DISABLED_BY_TOKEN_EXPIRED,
)

if TYPE_CHECKING:
    from app.database.database import Database

__all__ = ["AccountSession", "AccountTokenError"]

TOKEN_REFRESH_THRESHOLD: timedelta = timedelta(hours=1)


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

    async def ensure_token(self, database: Database) -> None:
        """Проверяет и обновляет access_token при необходимости."""
        acc = self.account
        if acc.status == "deleted":
            raise AccountTokenError(LOG_DISABLED_BY_AUTH_FAILED)

        if (
            acc.access_token
            and acc.expires_in is not None
            and acc.expires_in - datetime.now() > TOKEN_REFRESH_THRESHOLD
        ):
            self._avito = AvitoService(user_id=acc.user_id, token=acc.access_token)
            return

        if not acc.client_id or not acc.client_secret:
            await database.mark_account_expired(acc.id)
            raise AccountTokenError(LOG_DISABLED_BY_TOKEN_EXPIRED)

        token_data = await AvitoService.authenticate(
            client_id=acc.client_id, client_secret=acc.client_secret
        )
        if "error" in token_data or "access_token" not in token_data:
            await database.mark_account_expired(acc.id)
            logger.warning(
                "Не удалось авторизовать аккаунт {}: {}",
                acc.user_id,
                token_data,
            )
            raise AccountTokenError(LOG_DISABLED_BY_AUTH_FAILED)

        access_token: str = token_data["access_token"]
        expires_in = datetime.now() + timedelta(
            seconds=int(token_data.get("expires_in", 0))
        )
        acc.access_token = access_token
        acc.expires_in = expires_in
        await database.update_account_token(
            account_id=acc.id,
            access_token=access_token,
            expires_in=expires_in,
        )
        await self._cache.set_token(acc.id, access_token, expires_in)
        self._avito = AvitoService(user_id=acc.user_id, token=access_token)

    # ---------- API ----------

    @property
    def avito(self) -> AvitoService:
        if self._avito is None:
            raise RuntimeError("ensure_token() must be called first")
        return self._avito

    async def fetch_actual_rates_batch(self, ad_ids: list[int]) -> dict[int, dict]:
        """Snapshot getPromotionsByItemIds: dict[ad_id, item-payload]."""

        async def _fetch() -> dict:
            await self._rate_limiter.acquire(self.account.id, Endpoint.BATCH_RATES)
            return await self.avito.get_actual_rates(ads_id=ad_ids)

        raw = await self._cache.get_or_set_rates(self.account.id, _fetch)
        # Структура ответа Avito: {"items": [{"itemId", "manual", ...}]}
        # На всякий случай поддерживаем уже-конвертированный dict из кэша.
        if not raw:
            return {}
        if isinstance(raw, dict) and "items" in raw:
            items = raw.get("items", [])
            return {int(it["itemId"]): it for it in items if "itemId" in it}
        return raw  # type: ignore[return-value]

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
        await self._cache.invalidate_rates(self.account.id)
        await self._cache.invalidate_bids(ad_id)
