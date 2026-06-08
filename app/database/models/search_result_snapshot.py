from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    desc,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SearchResultSnapshot(Base):
    """Снимок поисковой выдачи Avito по биддеру.

    Per (bidder_data × timestamp × ad): позиция и
    метаданные объявления, найденного на странице
    выдачи. История нужна для аналитики (как менялся
    топ выдачи) и для логики «не конкурировать со
    своими объявлениями».
    """

    bidder_data_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("bidder_data.id", ondelete="RESTRICT"),
        nullable=False,
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    ad_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    title: Mapped[str | None] = mapped_column(String(250), nullable=True)
    seller_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    seller_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_srs_bd_ts", "bidder_data_id", desc("timestamp")),
        Index("ix_srs_ad_id_ts", "ad_id", desc("timestamp")),
    )
