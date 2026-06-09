"""Data Access Layer.

Не владеет схемой БД — схема ведётся родительским API-сервисом.
Здесь только запросы под нужды dispatcher'а: чтение активных
promotion'ов одним JOIN, чтение метрик за сегодня из
`ad_detail_statistic`, точечные UPDATE whitelisted-полей и
INSERT логов/заметок.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import TYPE_CHECKING

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.database.models import (
    Account,
    AccountStateHistory,
    Ad,
    AdDetailStatistic,
    ManualPromotion,
    ManualPromotionLog,
    ManualPromotionNote,
    Profile,
)
from app.log_messages import NOTE_KIND_SYSTEM

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["CriticalUpdate", "Database", "PromotionContext"]


@dataclass(frozen=True)
class CriticalUpdate:
    """Поля, которые dispatcher вправе писать в ManualPromotion."""

    critical_min_bid: int
    critical_max_bid: int
    critical_min_limit: int
    critical_max_limit: int
    disabled_bid: int


@dataclass
class PromotionContext:
    """Связка ManualPromotion + Account + Ad + Profile + last log."""

    promotion: ManualPromotion
    account: Account
    ad: Ad
    profile: Profile | None
    last_log: ManualPromotionLog | None


class Database:
    """Async DAL — открывает короткие сессии под каждый метод."""

    def __init__(self, sessionmaker: async_sessionmaker) -> None:
        self._sessionmaker = sessionmaker

    # ---------- чтение ----------

    async def load_active_account_ids(self) -> set[int]:
        """ID аккаунтов, у которых есть хоть один активный ManualPromotion.

        Возвращается supervisor'у каждые ~5 мин для синхронизации списка
        per-account воркеров (добавить новых, отменить отвалившихся).
        """
        stmt = (
            select(ManualPromotion.account_id)
            .where(ManualPromotion.status.is_(True))
            .where(ManualPromotion.deleted_at.is_(None))
            .distinct()
        )
        async with self._sessionmaker() as session:
            rows = (await session.execute(stmt)).scalars().all()
        return set(rows)

    async def load_account_promotions(
        self, account_id: int
    ) -> tuple[Account, list[PromotionContext], int] | None:
        """Снимок всех активных promotion'ов одного аккаунта.

        Возвращает (Account, list[PromotionContext], profile_active_count)
        либо None, если у аккаунта не осталось активных строк (тогда воркер
        выходит — supervisor не заведёт его, пока не появится активный
        promotion).

        `profile_active_count` — суммарное число активных promotion'ов по
        всем аккаунтам того же profile_id. Нужно decision_engine'у, чтобы
        дополнительно сверить с `profile.manual_promotion_limit` на случай
        гонки с родительским API (если в БД оказалось больше активных
        строк, чем разрешает тариф).
        """
        async with self._sessionmaker() as session:
            stmt = (
                select(ManualPromotion, Account, Ad, Profile)
                .join(Account, Account.id == ManualPromotion.account_id)
                .join(Ad, Ad.id == ManualPromotion.ad_id)
                .outerjoin(Profile, Profile.id == Account.profile_id)
                .where(ManualPromotion.account_id == account_id)
                .where(ManualPromotion.status.is_(True))
                .where(ManualPromotion.deleted_at.is_(None))
                .order_by(ManualPromotion.id)
            )
            rows = (await session.execute(stmt)).all()
            if not rows:
                return None

            account = rows[0][1]
            profile_id = account.profile_id

            count_stmt = (
                select(func.count(ManualPromotion.id))
                .join(Account, Account.id == ManualPromotion.account_id)
                .where(Account.profile_id == profile_id)
                .where(ManualPromotion.status.is_(True))
                .where(ManualPromotion.deleted_at.is_(None))
            )
            profile_active_count = int(
                (await session.execute(count_stmt)).scalar_one()
            )

            promotion_ids = [row[0].id for row in rows]
            last_logs = await self._load_last_logs(session, promotion_ids)

        contexts: list[PromotionContext] = []
        for promotion, account_row, ad, profile in rows:
            contexts.append(
                PromotionContext(
                    promotion=promotion,
                    account=account_row,
                    ad=ad,
                    profile=profile,
                    last_log=last_logs.get(promotion.id),
                )
            )
        return account, contexts, profile_active_count

    @staticmethod
    async def _load_last_logs(
        session: AsyncSession, promotion_ids: list[int]
    ) -> dict[int, ManualPromotionLog]:
        if not promotion_ids:
            return {}
        latest_ts = (
            select(
                ManualPromotionLog.manual_promotion_id,
                func.max(ManualPromotionLog.timestamp).label("max_ts"),
            )
            .where(ManualPromotionLog.manual_promotion_id.in_(promotion_ids))
            .group_by(ManualPromotionLog.manual_promotion_id)
        ).subquery()

        stmt = select(ManualPromotionLog).join(
            latest_ts,
            (
                ManualPromotionLog.manual_promotion_id
                == latest_ts.c.manual_promotion_id
            )
            & (ManualPromotionLog.timestamp == latest_ts.c.max_ts),
        )
        result = (await session.execute(stmt)).scalars().all()
        return {log.manual_promotion_id: log for log in result}

    async def load_today_stats(
        self, account_id: int, today: date | None = None
    ) -> dict[int, dict]:
        """Дневные метрики для всех объявлений аккаунта.

        Каждая запись в `ad_detail_statistic` — накопительный счётчик за
        текущий день (родительский сервис сбрасывает значения в 00:00),
        поэтому достаточно взять последнюю запись за сегодня на каждое
        объявление (`DISTINCT ON (ad_id) ... ORDER BY ad_id, timestamp DESC`,
        использует индекс `ix_ads_ad_id_ts_desc`).

        Возвращает `{avito_ad_id: {views, contacts, impressions,
        presenceSpending, promoSpending, restSpending}}` — camelCase
        ключей под формат, ожидаемый decision_engine.
        """
        target_day = today or date.today()
        day_start = datetime.combine(target_day, time.min)

        stmt = (
            select(
                Ad.ad_id,
                AdDetailStatistic.views,
                AdDetailStatistic.contacts,
                AdDetailStatistic.impressions,
                AdDetailStatistic.presence_spending,
                AdDetailStatistic.promo_spending,
                AdDetailStatistic.rest_spending,
            )
            .distinct(AdDetailStatistic.ad_id)
            .join(Ad, Ad.id == AdDetailStatistic.ad_id)
            .where(AdDetailStatistic.account_id == account_id)
            .where(AdDetailStatistic.timestamp >= day_start)
            .order_by(
                AdDetailStatistic.ad_id, AdDetailStatistic.timestamp.desc()
            )
        )

        async with self._sessionmaker() as session:
            rows = (await session.execute(stmt)).all()

        result: dict[int, dict] = {}
        for row in rows:
            result[int(row.ad_id)] = {
                "views": int(row.views or 0),
                "contacts": int(row.contacts or 0),
                "impressions": int(row.impressions or 0),
                "presenceSpending": int(row.presence_spending or 0),
                "promoSpending": int(row.promo_spending or 0),
                "restSpending": int(row.rest_spending or 0),
            }
        return result

    async def load_account_advance_balance(
        self, account_id: int
    ) -> float | None:
        """Последний `advance_balance` аккаунта из `account_state_history`.

        Снимки баланса заводит родительский сервис (отдельный синхронизатор),
        мы только читаем самую свежую запись по индексу
        `(account_id, timestamp DESC)`.

        Возвращает:
        - `float` — значение `advance_balance` из последней записи;
        - `None` — если записей нет ИЛИ `advance_balance is NULL` (источник
          не успел заполниться). Caller интерпретирует None как «неизвестно»
          и НЕ блокирует продвижение — поведение зеркалит bidder.
        """
        stmt = (
            select(AccountStateHistory.advance_balance)
            .where(AccountStateHistory.account_id == account_id)
            .order_by(AccountStateHistory.timestamp.desc())
            .limit(1)
        )
        async with self._sessionmaker() as session:
            value = (await session.execute(stmt)).scalar_one_or_none()
        return value

    # ---------- запись ----------

    async def insert_log(
        self,
        promotion_id: int,
        bid: int,
        compare_percent: int,
        timestamp: datetime,
    ) -> None:
        """INSERT с защитой от дубля по UNIQUE (promotion_id, timestamp)."""
        async with self._sessionmaker() as session:
            stmt = (
                pg_insert(ManualPromotionLog)
                .values(
                    manual_promotion_id=promotion_id,
                    bid=bid,
                    compare_percent=compare_percent,
                    timestamp=timestamp,
                )
                .on_conflict_do_nothing(
                    constraint="uq_manual_promotion_log_mp_timestamp"
                )
            )
            try:
                await session.execute(stmt)
                await session.commit()
            except IntegrityError:
                await session.rollback()

    async def insert_system_note(
        self, promotion_id: int, text: str, created_at: datetime
    ) -> None:
        async with self._sessionmaker() as session:
            session.add(
                ManualPromotionNote(
                    manual_promotion_id=promotion_id,
                    kind=NOTE_KIND_SYSTEM,
                    text=text,
                    created_at=created_at,
                )
            )
            await session.commit()

    async def upsert_critical(
        self, promotion_id: int, payload: CriticalUpdate
    ) -> None:
        async with self._sessionmaker() as session:
            await session.execute(
                update(ManualPromotion)
                .where(ManualPromotion.id == promotion_id)
                .values(
                    critical_min_bid=payload.critical_min_bid,
                    critical_max_bid=payload.critical_max_bid,
                    critical_min_limit=payload.critical_min_limit,
                    critical_max_limit=payload.critical_max_limit,
                    disabled_bid=payload.disabled_bid,
                )
            )
            await session.commit()

    async def reset_critical(self, promotion_id: int) -> None:
        """Сбрасывает все 5 critical-полей ManualPromotion в NULL.

        Вызывается из apply_decision когда Avito отверг set_manual_bid (400)
        — границы устарели. Следующая итерация воркера увидит NULL'ы,
        decision_engine вернёт FETCH_BIDS, upsert_critical перепишет
        свежие значения.
        """
        async with self._sessionmaker() as session:
            await session.execute(
                update(ManualPromotion)
                .where(ManualPromotion.id == promotion_id)
                .values(
                    critical_min_bid=None,
                    critical_max_bid=None,
                    critical_min_limit=None,
                    critical_max_limit=None,
                    disabled_bid=None,
                )
            )
            await session.commit()

    async def bulk_update_log_message(
        self, updates: list[tuple[int, str | None]]
    ) -> None:
        """[(promotion_id, log_message), …] — массовое обновление."""
        if not updates:
            return
        async with self._sessionmaker() as session:
            for promotion_id, message in updates:
                await session.execute(
                    update(ManualPromotion)
                    .where(ManualPromotion.id == promotion_id)
                    .values(log_message=message)
                )
            await session.commit()
