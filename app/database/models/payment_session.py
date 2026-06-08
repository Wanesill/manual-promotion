from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PaymentSession(Base):
    """Сессия инициированного платежа T-Bank.

    Хранит metadata запроса (профиль, лимиты,
    промокод, период, базовая сумма, метод оплаты).
    Создается при ``/payments/create``, читается
    при обработке вебхука и удаляется после
    успешной фиксации платежа.

    Зачем: T-Bank в нотификациях не возвращает
    DATA, переданный в Init - значит metadata
    нужно хранить на нашей стороне и доставать по
    ``OrderId`` (его банк возвращает гарантированно).
    """

    order_id: Mapped[str] = mapped_column(
        String(36), unique=True, index=True, nullable=False
    )
    profile_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("profile.id", ondelete="CASCADE"),
        nullable=False,
    )
    accounts_limit: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    bidder_ads_limit: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    manual_promotion_limit: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    parser_reports_limit: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    period: Mapped[str] = mapped_column(String(50), nullable=False)
    base_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    payment_method: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
