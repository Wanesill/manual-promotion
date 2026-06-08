from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MailingMessage(Base):
    """Сообщение в рассылке.

    Одна рассылка может содержать несколько сообщений
    с задержкой между ними. Хранит текст, медиа
    (JSONB-список) и кнопки (JSONB). status = True
    означает отправленное сообщение.

    media - список dict со специфичными для платформы
    ключами (например для Telegram: media_type,
    file_id, file_unique_id). Платформа определяется
    родительским Mailing.platform, поэтому отдельной
    вложенности по платформам в media нет.
    """

    mailing_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("mailing.id", ondelete="RESTRICT"),
        nullable=False,
    )
    delay: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    text: Mapped[str | None] = mapped_column(String(5000), nullable=True)
    media: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    buttons_json: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list
    )
