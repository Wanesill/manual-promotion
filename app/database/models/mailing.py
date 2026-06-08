from datetime import datetime, time

from sqlalchemy import Boolean, DateTime, Integer, String, Text, Time
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Mailing(Base):
    """Рассылка сообщений пользователям.

    Конфигурация рассылки: платформа
    (telegram/max), аудитория (user_type:
    all, new, custom), время отправки, задержка
    между сообщениями. status = True означает
    активную рассылку. Под каждую платформу
    создается отдельная запись Mailing со
    своими сообщениями и медиа.
    """

    title: Mapped[str] = mapped_column(String(100), nullable=False)
    platform: Mapped[str] = mapped_column(
        String(10), nullable=False, default="telegram"
    )
    status: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )
    user_type: Mapped[str | None] = mapped_column(
        String(6), nullable=True
    )  # all, new, custom
    users_list: Mapped[str | None] = mapped_column(Text, nullable=True)
    time_to_send: Mapped[time | None] = mapped_column(Time, nullable=True)
    delay: Mapped[int | None] = mapped_column(Integer, nullable=True)
