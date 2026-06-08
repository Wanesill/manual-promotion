from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class VerificationCode(Base):
    """Код подтверждения по email.

    Используется для регистрации, сброса и смены
    пароля (purpose: registration, password_reset,
    password_change). Ограничен по попыткам ввода
    и сроку действия. used = True после успешной
    верификации.
    """

    identifier: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(6), nullable=False)
    purpose: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # registration, password_reset, password_change
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=5
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
