from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MessageAvito(Base):
    """Сообщение в чате Avito.

    Хранит содержимое сообщения, тип, направление
    (direction: in/out), статус прочтения и время
    прочтения. message_id - строковый идентификатор
    сообщения в Avito.
    """

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_avito.id", ondelete="RESTRICT"),
        nullable=True,
    )
    chat_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("chat_avito.id", ondelete="RESTRICT"),
        nullable=False,
    )
    message_id: Mapped[str] = mapped_column(
        String(100), nullable=False, unique=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    type: Mapped[str] = mapped_column(String(9), nullable=False)
    content: Mapped[str] = mapped_column(String(5000), nullable=False)
    direction: Mapped[str] = mapped_column(String(3), nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False)
    read: Mapped[datetime] = mapped_column(DateTime, nullable=True)
