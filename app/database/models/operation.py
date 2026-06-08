from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Operation(Base):
    """Финансовая операция по объявлению.

    Данные о списаниях и начислениях: суммы в рублях
    и бонусах, тип операции, название и тип услуги.
    Импортируется из API Avito.
    """

    account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("account.id", ondelete="RESTRICT"),
        nullable=False,
    )
    ad_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    amount_bonus: Mapped[float] = mapped_column(Float, nullable=False)
    amount_rub: Mapped[float] = mapped_column(Float, nullable=False)
    operation_name: Mapped[str] = mapped_column(String(100), nullable=False)
    operation_type: Mapped[str] = mapped_column(String(100), nullable=False)
    service_id: Mapped[str | None] = mapped_column(Integer, nullable=True)
    service_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    service_type: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "ad_id",
            "updated_at",
            "operation_name",
            "amount_rub",
            name="op_account_ad_updated",
        ),
        Index(
            "ix_operation_acc_optype_servtype_updated",
            "account_id",
            "operation_type",
            "service_type",
            "updated_at",
        ),
    )
