from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class BidderDataNote(Base):
    """Текстовая заметка, привязанная к BidderData.

    Отображается как маркер на графике детальной страницы
    бид-менеджера. Дата создания фиксируется при создании
    и не меняется при PATCH - это позиция маркера на временной
    оси графика.

    kind:
    - "user" - создана пользователем через API (CRUD доступен);
    - "system" - создана автоматически другими процессами
      (например, серверной частью биддера при событиях вроде
      "тариф истек" или "настройки изменены"); через API недоступна
      для PATCH/DELETE (403).
    """

    bidder_data_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("bidder_data.id", ondelete="RESTRICT"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="user",
    )
    text: Mapped[str] = mapped_column(String(1000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.now,
    )

    __table_args__ = (
        Index(
            "ix_bidder_data_note_bidder_data_id",
            "bidder_data_id",
        ),
    )
