from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class BidderDataLog(Base):
    """Лог работы биддера.

    Фиксирует позицию объявления и установленную
    ставку на каждый момент срабатывания биддера.
    """

    bidder_data_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("bidder_data.id", ondelete="RESTRICT"),
        nullable=False,
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    bid: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "bidder_data_id", "timestamp", name="bd_bidder_data_timestamp"
        ),
    )
