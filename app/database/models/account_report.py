from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AccountReport(Base):
    """Настройки автоматических отчетов по аккаунту.

    Конфигурация периодической отправки отчетов:
    report_period (weekly, monthly или оба), день
    недели/месяца и час отправки. report_datetime -
    время последней отправки.
    """

    account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("account.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
        index=True,
    )
    report_period: Mapped[str | None] = mapped_column(
        String(30), nullable=True, default="weekly,monthly"
    )
    report_day: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    hour: Mapped[int] = mapped_column(Integer, nullable=False, default=12)
    report_datetime: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
