from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    desc,
)
from sqlalchemy.orm import mapped_column

from app.database import Base


class AdDetailStatistic(Base):
    """Детальная статистика объявления.

    Метрики эффективности по временным меткам:
    просмотры, контакты, избранное, показы,
    целевые действия, заказы с Авито Доставкой
    и расходы на продвижение.
    """

    account_id = mapped_column(
        BigInteger,
        ForeignKey("account.id", ondelete="RESTRICT"),
        nullable=False,
    )
    ad_id = mapped_column(
        BigInteger, ForeignKey("ad.id", ondelete="RESTRICT"), nullable=False
    )
    timestamp = mapped_column(DateTime, nullable=False)

    # Основные метрики
    views = mapped_column(Integer, nullable=False)
    contacts = mapped_column(Integer, nullable=False)
    contacts_messenger = mapped_column(Integer, nullable=False)
    favorites = mapped_column(Integer, nullable=False)
    impressions = mapped_column(Integer, nullable=False)

    # Целевые действия
    job_contacts = mapped_column(Integer, nullable=False)

    # Заказы с Авито Доставкой
    ordered_items = mapped_column(Integer, nullable=False)
    ordered_items_price = mapped_column(Float, nullable=False)
    delivered_items = mapped_column(Integer, nullable=False)
    delivered_items_price = mapped_column(Float, nullable=False)

    # Расходы
    presence_spending = mapped_column(Float, nullable=False)
    promo_spending = mapped_column(Float, nullable=False)
    rest_spending = mapped_column(Float, nullable=False)
    commission = mapped_column(Float, nullable=False)
    spending_bonus = mapped_column(Float, nullable=False)

    __table_args__ = (
        Index(
            "adds_account_ad_timestamp",
            "account_id",
            "ad_id",
            desc("timestamp"),
            unique=True,
        ),
        Index(
            "ix_ad_detail_stat_account_ts",
            "account_id",
            "timestamp",
        ),
        Index("ix_ads_ad_id_ts_desc", "ad_id", desc("timestamp")),
    )
