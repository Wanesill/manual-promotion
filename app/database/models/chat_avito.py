from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ChatAvito(Base):
    """Чат в мессенджере Avito.

    Метаданные переписки на Avito: объявление, цена,
    локация, участники (item_user_id - владелец,
    companion_user_id - собеседник). chat_id - строковый
    идентификатор чата в Avito.
    """

    chat_id: Mapped[str] = mapped_column(
        String(100), nullable=False, unique=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    item_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    item_title: Mapped[str] = mapped_column(String(200), nullable=False)
    item_url: Mapped[str] = mapped_column(String(250), nullable=False)
    item_status_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    item_price: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    item_location: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    item_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("user_avito.id", ondelete="RESTRICT"),
        nullable=True,
    )
    companion_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("user_avito.id", ondelete="RESTRICT"),
        nullable=True,
    )
