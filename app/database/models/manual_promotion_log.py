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


class ManualPromotionLog(Base):
    """Лог изменения ставки ручного продвижения.

    На каждое изменение ставки серверный воркер
    ручного продвижения создает запись с новой ставкой
    (в копейках) и процентом опережения относительно
    ближайшего конкурента в выдаче.
    """

    manual_promotion_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("manual_promotion.id", ondelete="RESTRICT"),
        nullable=False,
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    bid: Mapped[int] = mapped_column(Integer, nullable=False)
    compare_percent: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "manual_promotion_id",
            "timestamp",
            name="uq_manual_promotion_log_mp_timestamp",
        ),
    )
