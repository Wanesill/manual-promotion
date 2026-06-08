from datetime import date

from sqlalchemy import (
    BigInteger,
    Date,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class GoogleTable(Base):
    """Google-таблица аналитики.

    Назначается профилю из пула при регистрации.
    profile_id = NULL означает свободную таблицу в
    пуле. Хранит ссылку на таблицу и параметры
    последнего сбора данных (города, объявления).
    """

    profile_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("profile.id", ondelete="RESTRICT"),
        nullable=True,
    )
    table_ref: Mapped[str] = mapped_column(
        String(100), nullable=False, unique=True, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=True)
    cities_account_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    cities_date_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    cities_date_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    cities_count_line: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    ads_account_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    ads_date_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    ads_date_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    ads_count_line: Mapped[int | None] = mapped_column(Integer, nullable=True)
