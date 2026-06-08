from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ManualPromotion(Base):
    """Настройки ручного продвижения объявления.

    Конфигурация ставки, задаваемой пользователем
    вручную: текущая ставка, дневной бюджет, расписание
    (битмаска часов + дни недели), лимиты остановки по
    метрикам. В отличие от BidderData позиции в выдаче
    не парсятся и не отслеживаются - пользователь сам
    решает, какую ставку поставить. status = True
    означает активное продвижение. log_message хранит
    последний результат работы серверного воркера
    ручного продвижения. deleted_at - момент soft-delete
    из веб-UI: запись со значением IS NOT NULL скрыта
    во всех листинговых и детальных эндпоинтах будущего
    модуля manual_promotion; настройки, заметки и логи
    ставки при этом физически сохраняются.

    Поля critical_min_limit / critical_max_limit задают
    допустимый диапазон значения лимита по объявлению,
    а disabled_bid (в копейках) - ставку, применяемую
    при выключенном продвижении. Все три заполняются
    исключительно внешним серверным воркером ручного
    продвижения: API их не принимает, не валидирует
    и не отдает наружу.

    История изменений ставки (время, новая ставка,
    процент опережения относительно конкурента)
    хранится в отдельной таблице manual_promotion_log.
    """

    account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("account.id", ondelete="RESTRICT"),
        nullable=False,
    )
    ad_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("ad.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
        index=True,
    )
    bid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    daily_budget: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    critical_min_bid: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    critical_max_bid: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    critical_min_limit: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    critical_max_limit: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    disabled_bid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    work_days: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="Пн,Вт,Ср,Чт,Пт,Сб,Вс",
    )
    work_hours_mask: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0xFFFFFF,
    )
    disable_impressions_limit: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    disable_views_limit: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    disable_contacts_limit: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    disable_cost_per_view_limit: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    disable_cost_per_contact_limit: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    status: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    log_message: Mapped[str | None] = mapped_column(String(200), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, default=None
    )

    __table_args__ = (
        Index("idx_manual_promotion_acc_status", "account_id", "status"),
        Index("idx_manual_promotion_account_id", "account_id"),
        Index("ix_manual_promotion_ad_id_id", "ad_id", "id"),
        Index(
            "ix_manual_promotion_status",
            "status",
            postgresql_where=text("status IS TRUE"),
        ),
        Index(
            "ix_manual_promotion_deleted_at",
            "deleted_at",
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )
