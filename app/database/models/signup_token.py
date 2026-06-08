from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SignupToken(Base):
    """Временный токен регистрации.

    Создается на этапе POST /register, хранит email,
    хеш пароля и опциональный referer_id. После
    верификации кода API создает Profile и WebAuth
    на основе данных токена. Имеет срок действия.
    """

    email: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    profile_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("profile.id", ondelete="RESTRICT"),
        nullable=True,
    )
    referer_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("profile.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
