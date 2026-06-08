from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ManualPromotionGroup(Base):
    """Группа объявлений ручного продвижения (веб-версия).

    Произвольный пользовательский набор объявлений, уже подключенных
    к ручному продвижению (M:M через manual_promotion_group_data).
    Сущность только веб-версии: на работу серверной части ручного
    продвижения не влияет.

    Имена не уникальны в рамках профиля - дубли разрешены.
    Дефолтное имя при создании: "Группа {N}", где N = count_profile + 1
    (нумерация не строго монотонна при concurrent создании - дубли
    допустимы по спецификации).

    Цвет назначается из общего BIDDER_GROUP_PALETTE (200 hex-кодов,
    golden-angle HSL, см. app/bidder/palette.py) случайным образом
    при создании; повторы цветов в рамках профиля разрешены и не
    отслеживаются. Палитра общая для разделов бид-менеджера и
    ручного продвижения.
    """

    profile_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("profile.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    color: Mapped[str] = mapped_column(String(7), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now
    )

    __table_args__ = (
        Index("ix_manual_promotion_group_profile_id", "profile_id"),
        Index(
            "ix_manual_promotion_group_profile_created",
            "profile_id",
            "created_at",
        ),
    )
