from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AnalyticsCollectionDates(Base):
    """Даты сбора аналитики по аккаунту.

    Отмечает временные метки последнего сбора данных
    для каждого типа (type: profile, ads). Используется
    для определения диапазона следующего сбора.
    """

    account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("account.id", ondelete="RESTRICT"),
        nullable=False,
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    type: Mapped[str] = mapped_column(
        String(100), nullable=False
    )  # profile, ads

    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "timestamp",
            "type",
            name="acd_account_timestamp_type",
        ),
    )
