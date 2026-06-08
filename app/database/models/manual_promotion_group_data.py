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


class ManualPromotionGroupData(Base):
    """Junction-таблица M:M между ManualPromotionGroup и ManualPromotion.

    Одно объявление может состоять в нескольких группах одновременно.
    Уникальная пара (manual_promotion_group_id, manual_promotion_id)
    запрещает дубли подвязки. Все FK с ondelete='RESTRICT' (общая
    конвенция проекта) - удалить manual_promotion_group или
    manual_promotion без предварительного cleanup junction нельзя.
    Cleanup делается явно в сервисе:
    при DELETE группы DELETE FROM manual_promotion_group_data
    WHERE manual_promotion_group_id=... вызывается до DELETE родителя;
    при soft-delete объявления DELETE FROM manual_promotion_group_data
    WHERE manual_promotion_id IN (...) выполняется в той же транзакции,
    что и установка deleted_at.
    """

    manual_promotion_group_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("manual_promotion_group.id", ondelete="RESTRICT"),
        nullable=False,
    )
    manual_promotion_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("manual_promotion.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )

    __table_args__ = (
        UniqueConstraint(
            "manual_promotion_group_id",
            "manual_promotion_id",
            name="uq_manual_promotion_group_data_group_data",
        ),
        Index(
            "ix_manual_promotion_group_data_manual_promotion_id",
            "manual_promotion_id",
        ),
    )
