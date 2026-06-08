from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class UserAvito(Base):
    """Профиль пользователя Avito.

    Кеш данных пользователя Avito (имя, URL).
    Используется как справочник для ChatAvito -
    хранит участников чатов (владелец и собеседник).
    """

    user_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, unique=True, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    url: Mapped[str] = mapped_column(String(250), nullable=False)
