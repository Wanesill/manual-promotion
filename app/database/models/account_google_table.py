from sqlalchemy import BigInteger, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AccountGoogleTable(Base):
    """Связь аккаунта с Google-таблицей для аналитики.

    Junction-таблица. Один аккаунт может быть привязан
    к нескольким Google-таблицам, но не более одной строки
    на пару (account_id, google_table_id).
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

    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "google_table_id",
            name="uq_agt_account_table",
        ),
    )
