from sqlalchemy import BigInteger, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AccountGoogleTable(Base):
    """Связь аккаунта с Google-таблицей по типу сервиса.

    Junction-таблица. service_type определяет назначение
    связи: analytics, bidder или manual_promotion.
    Один аккаунт может быть привязан к одной таблице
    по каждому типу сервиса.
    """

    account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("account.id", ondelete="RESTRICT"),
        nullable=False,
    )
    google_table_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("google_table.id", ondelete="RESTRICT"),
        nullable=False,
    )
    service_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # analytics, bidder, manual_promotion

    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "google_table_id",
            "service_type",
            name="uq_agt_account_table_service",
        ),
    )
