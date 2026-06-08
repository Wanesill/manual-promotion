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


class WalletBalanceAlert(Base):
    """Настройки уведомления о балансе кошелька.

    Аналогично BalanceAlert, но отслеживает баланс
    кошелька (wallet) аккаунта Avito.
    """

    account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("account.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
        index=True,
    )
    status: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
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
