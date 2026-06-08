from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class BidderGroup(Base):
    """Группа объявлений бид-менеджера (веб-версия).

    Произвольный пользовательский набор объявлений, уже подключенных
    к бид-менеджеру (M:M через bidder_group_data). Сущность только
    веб-версии: в Google-таблицах не отражается, на работу серверной
    части биддера не влияет.

    Имена не уникальны в рамках профиля - дубли разрешены.
    Дефолтное имя при создании: "Группа {N}", где N = count_profile + 1
    (нумерация не строго монотонна при concurrent создании - дубли
    допустимы по спецификации).

    Цвет назначается из BIDDER_GROUP_PALETTE (200 hex-кодов, golden-angle
    HSL из Приложения А спецификации) случайным образом при создании;
    повторы цветов в рамках профиля разрешены и не отслеживаются.
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
        Index("ix_bidder_group_profile_id", "profile_id"),
        Index(
            "ix_bidder_group_profile_created",
            "profile_id",
            "created_at",
        ),
    )
