from sqlalchemy import BigInteger, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ProfileContacts(Base):
    """Контактные данные профиля.

    Связь 1-к-1 с Profile. Имя и фамилия
    заполняются пользователем опционально.
    """

    profile_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("profile.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
