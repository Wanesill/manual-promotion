from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class BidderGroupData(Base):
    """Junction-таблица M:M между BidderGroup и BidderData.

    Одно объявление может состоять в нескольких группах одновременно.
    Уникальная пара (bidder_group_id, bidder_data_id) запрещает дубли
    подвязки. Все FK с ondelete='RESTRICT' (общая конвенция проекта)
    - удалить bidder_group или bidder_data без предварительного
    cleanup junction нельзя. Cleanup делается явно в сервисе:
    при DELETE группы (delete_bidder_group / bulk_delete_bidder_groups)
    и при soft-delete объявления (_soft_delete_bidder_rows), где
    DELETE FROM bidder_group_data вызывается до DELETE родителя.
    """

    bidder_group_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("bidder_group.id", ondelete="RESTRICT"),
        nullable=False,
    )
    bidder_data_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("bidder_data.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )

    __table_args__ = (
        UniqueConstraint(
            "bidder_group_id",
            "bidder_data_id",
            name="uq_bidder_group_data_group_data",
        ),
        Index(
            "ix_bidder_group_data_bidder_data_id",
            "bidder_data_id",
        ),
    )
