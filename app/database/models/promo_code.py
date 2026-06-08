from datetime import datetime

from sqlalchemy import ARRAY, BigInteger, Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PromoCode(Base):
    """Промокод на скидку.

    type определяет область действия: all (для всех)
    или profile (для конкретных profile_ids).
    service_type - тип сервиса: analytics, bidder,
    manual_promotion, parser. Ограничен по количеству
    использований и сроку действия.
    """

    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    type: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # all, profile
    profile_ids: Mapped[list[int]] = mapped_column(
        ARRAY(BigInteger),
        nullable=True,
    )
    service_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # analytics, bidder, manual_promotion, parser
    max_uses: Mapped[int] = mapped_column(Integer, nullable=True)
    per_user_once: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    discount: Mapped[int] = mapped_column(Integer, nullable=False)
