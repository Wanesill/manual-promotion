"""Обёртка над AvitoService для одного аккаунта.

Делает 2 вещи:
1. ensure_token — приоритет источников токена:
   (a) `Account.access_token` из БД, если не истёк;
   (b) in-memory токен, который мы сами получили через `authenticate`
       в этом же воркере (живёт между итерациями `_account_loop`);
   (c) `authenticate(client_id, client_secret)` — только когда (a) и (b)
       не работают. Результат не пишем в БД — refresh устаревшего токена
       по-прежнему задача родительского API; здесь только первичная
       выдача для аккаунтов, у которых access_token ещё не положили.
2. Прозрачно кэширует bids (границы ставок) в AvitoCache. Snapshot текущих
   ставок с Avito не запрашиваем — drift считаем по `ManualPromotionLog.bid`.

Rate limiting не делаем проактивно: на 429/5xx AvitoService сам ждёт по
`x-ratelimit-retry-after` и повторяет запрос.
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
from app.infra.redis_cache import AvitoCache
from app.log_messages import (
    LOG_DISABLED_BY_AUTH_FAILED,
    LOG_DISABLED_BY_TOKEN_EXPIRED,
)

if TYPE_CHECKING:
    from app.database.database import Database

__all__ = ["AccountSession", "AccountTokenError"]


class AccountTokenError(Exception):
    """Не удалось получить рабочий токен — caller должен отключить ads."""

    def __init__(self, log_message: str) -> None:
        self.log_message = log_message
        super().__init__(log_message)


class AccountSession:
    """Stateful обёртка: один экземпляр живёт всю жизнь воркера аккаунта."""

    def __init__(
        self,
        account: Account,
        cache: AvitoCache,
    ) -> None:
        self.account = account
        self._cache = cache
        self._avito: AvitoService | None = None
        # In-memory токен от `authenticate`. Используется когда в БД
        # access_token отсутствует/истёк, а у аккаунта есть client_id/secret.
        self._fetched_token: str | None = None
        self._fetched_expires_at: datetime | None = None

    def update_account(self, account: Account) -> None:
        """Перезаписать модель Account новой версией из БД (новая итерация).

        Сам in-memory токен (`_fetched_token`) сохраняем — он привязан к
        client_id/secret, а не к снепшоту строки Account.
        """
        self.account = account

    # ---------- токен ----------

    async def ensure_token(self) -> None:
        """Готовит `self._avito` либо кидает AccountTokenError."""
        acc = self.account
        now = datetime.now()

        # (a) валидный access_token в БД — всегда выигрывает.
        if acc.access_token and acc.expires_in is not None and acc.expires_in > now:
            self._avito = AvitoService(user_id=acc.user_id, token=acc.access_token)
            return

        # (b) живой in-memory токен от прошлой authenticate в этом воркере.
        if (
            self._fetched_token
            and self._fetched_expires_at is not None
            and self._fetched_expires_at > now
        ):
            self._avito = AvitoService(user_id=acc.user_id, token=self._fetched_token)
            return

        # (c) пробуем authenticate, если есть чем.
        if not acc.client_id or not acc.client_secret:
            raise AccountTokenError(LOG_DISABLED_BY_TOKEN_EXPIRED)

        try:
            token_data = await AvitoService.authenticate(
                client_id=acc.client_id, client_secret=acc.client_secret
            )
        except Exception as err:
            logger.warning(
                "Авторизация аккаунта {} не удалась: {}",
                acc.user_id,
                err,
            )
            raise AccountTokenError(LOG_DISABLED_BY_AUTH_FAILED) from err

        if not isinstance(token_data, dict) or "access_token" not in token_data:
            logger.warning(
                "Авторизация аккаунта {} вернула пустой payload: {}",
                acc.user_id,
                token_data,
            )
            raise AccountTokenError(LOG_DISABLED_BY_AUTH_FAILED)

        token: str = token_data["access_token"]
        expires_in_s = int(token_data.get("expires_in", 0))
        self._fetched_token = token
        self._fetched_expires_at = now + timedelta(seconds=expires_in_s)
        self._avito = AvitoService(user_id=acc.user_id, token=token)

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
            try:
                result = await self.avito.get_bids(ad_id=ad_id)
            except AccountForbiddenError:
                raise
            return result or None

        return await self._cache.get_or_set_bids(ad_id, _fetch)

    async def set_manual_bid(
        self, ad_id: int, bid: int, limit_penny: int | None
    ) -> bool | None:
        return await self.avito.set_manual_bid(
            ad_id=ad_id, bid=bid, limit_penny=limit_penny
        )

    async def remove_cpxpromo(self, ad_id: int) -> None:
        await self.avito.remove_cpxpromo(ad_id=ad_id)

    async def invalidate_caches_for_ad(self, ad_id: int) -> None:
        await self._cache.invalidate_bids(ad_id)
