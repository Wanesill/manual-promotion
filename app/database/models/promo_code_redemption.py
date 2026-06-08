from sqlalchemy import BigInteger, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PromoCodeRedemption(Base):
    """Факт использования промокода.

    Фиксирует, какой профиль активировал промокод
    и когда. Используется для проверки per_user_once
    и подсчета общего числа использований.
    """

    promo_code_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("promo_code.id", ondelete="RESTRICT"),
        nullable=False,
    )
    profile_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("profile.id", ondelete="RESTRICT"),
        nullable=False,
    )
    redeemed_at: Mapped[DateTime] = mapped_column(DateTime, nullable=False)
