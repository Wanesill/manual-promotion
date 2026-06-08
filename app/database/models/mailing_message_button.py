from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MailingMessageButton(Base):
    """Кнопка для сообщения рассылки.

    Определение inline-кнопки: текст, callback_data
    (для обработки бота) или url (для внешней ссылки).
    """

    text: Mapped[str] = mapped_column(String(100), nullable=False)
    callback_data: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    url: Mapped[str | None] = mapped_column(String(200), nullable=True)
