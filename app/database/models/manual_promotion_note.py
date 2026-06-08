from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ManualPromotionNote(Base):
    """Текстовая заметка, привязанная к ManualPromotion.

    Отображается как маркер на графике детальной страницы
    ручного продвижения. Дата создания фиксируется при
    создании и не меняется при PATCH - это позиция маркера
    на временной оси графика.

    kind:
    - "user" - создана пользователем через API (CRUD доступен);
    - "system" - создана автоматически другими процессами
      (например, серверной частью ручного продвижения при
      событиях вроде "тариф истек" или "настройки изменены");
      через API недоступна для PATCH/DELETE (403).
    """

    manual_promotion_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("manual_promotion.id", ondelete="RESTRICT"),
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
            "ix_manual_promotion_note_manual_promotion_id",
            "manual_promotion_id",
        ),
    )
