from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class BalanceAlert(Base):
    """Настройки уведомления о балансе аккаунта.

    Отслеживает основной баланс Avito. При снижении
    ниже threshold отправляет алерт. decrease_step -
    шаг снижения для повторного уведомления.
    alert_repeat_interval - интервал между повторами
    (в секундах, по умолчанию 6 часов).
    """

    account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("account.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
        index=True,
    )
    status: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    balance: Mapped[float | None] = mapped_column(Float, nullable=True)
    threshold: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1000
    )
    decrease_step: Mapped[int] = mapped_column(
        Integer, nullable=False, default=300
    )
    alert_datetime: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    alert_repeat_interval: Mapped[int] = mapped_column(
        Integer, nullable=False, default=21600
    )
