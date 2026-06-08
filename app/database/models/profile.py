from datetime import date, datetime, timedelta

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Profile(Base):
    """Профиль пользователя.

    Центральная сущность - к ней привязаны аккаунты,
    платежи, таблицы и интеграции с ботами. Содержит
    баланс, лимиты сервисов и даты окончания подписок.

    referral_code - уникальный 8-символьный код для
    реферальной системы. referral_percent растет
    с числом рефералов: <5 = 5%, >=5 = 15%, >=10 = 20%.
    """

    registration_date: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )
    balance: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    referer_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("profile.id", ondelete="RESTRICT"),
        nullable=True,
    )
    referral_percent: Mapped[int] = mapped_column(
        Integer, nullable=False, default=5
    )
    referral_code: Mapped[str] = mapped_column(
        String(8), nullable=False, unique=True
    )
    accounts_limit: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100
    )
    bidder_ads_limit: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10
    )
    manual_promotion_limit: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100
    )
    parser_reports_limit: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    analytics_end_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, default=lambda: date.today() + timedelta(days=7)
    )
    bidder_end_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, default=lambda: date.today() + timedelta(days=7)
    )
    manual_promotion_end_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, default=lambda: date.today() + timedelta(days=7)
    )
    parser_end_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, default=None
    )
