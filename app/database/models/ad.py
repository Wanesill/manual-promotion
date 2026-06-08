from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Ad(Base):
    """Объявление Avito.

    Хранит метаданные объявления: название, цену,
    статус, адрес, категорию и период размещения.
    ad_id - идентификатор объявления в Avito.
    """

    account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("account.id", ondelete="RESTRICT"),
        nullable=False,
    )
    ad_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, unique=True, index=True
    )
    address: Mapped[str | None] = mapped_column(String(200), nullable=True)
    category_name: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )
    price: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(8), nullable=False)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    url: Mapped[str | None] = mapped_column(String(250), nullable=True)
    start_time: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    finish_time: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)

    __table_args__ = (
        UniqueConstraint("account_id", "ad_id", name="ad_account_ad"),
        Index(
            "idx_ad_pk_include",
            "id",
            postgresql_include=["ad_id", "status", "price"],
        ),
        Index("ix_ad_account_id", "account_id"),
        Index("ix_ad_account_status", "account_id", "status"),
        Index("ix_ad_ad_id_id", "ad_id", "id"),
    )
