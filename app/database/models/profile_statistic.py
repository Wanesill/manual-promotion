from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    UniqueConstraint,
)
from sqlalchemy.orm import mapped_column

from app.database import Base


class ProfileStatistic(Base):
    """Сводная статистика профиля по аккаунту.

    Агрегированные метрики объявлений аккаунта:
    просмотры, контакты, избранное, показы, заказы
    с доставкой, расходы на продвижение и количество
    активных объявлений.
    """

    account_id = mapped_column(
        BigInteger,
        ForeignKey("account.id", ondelete="RESTRICT"),
        nullable=False,
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

    # Объявления
    active_items = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "account_id", "timestamp", name="ps_account_timestamp"
        ),
    )
