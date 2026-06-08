from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Payment(Base):
    """Запись о платеже через T-Bank Acquiring.

    Фиксирует оплату тарифа: сумму, доход, способ
    оплаты, период и количество. ``acquiring_id`` -
    PaymentId из ответа T-Bank, ``order_id`` -
    UUID, генерируемый бэкендом при Init и
    отправляемый как OrderId в T-Bank. is_nalog
    отмечает платежи, учитываемые для
    налогообложения.
    """

    profile_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("profile.id", ondelete="RESTRICT"),
        nullable=False,
    )
    acquiring_id: Mapped[str] = mapped_column(String(100), nullable=False)
    order_id: Mapped[str] = mapped_column(String(36), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    income_amount: Mapped[float] = mapped_column(Float, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    payment_method: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(String(100), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    period: Mapped[str] = mapped_column(String(20), nullable=False)
    is_nalog: Mapped[bool] = mapped_column(Boolean, nullable=False)
