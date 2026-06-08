"""Утилиты для работы с расписанием продвижения.

work_hours_mask — 24-битная маска: бит i установлен → час i активен.
work_days — строка через запятую из ["Пн","Вт","Ср","Чт","Пт","Сб","Вс"].

Сервер запущен в МСК, поэтому работаем напрямую с datetime.now()
без явных TZ-конверсий (см. план idempotent-launching-kahan.md).
"""

from __future__ import annotations

from datetime import datetime
from typing import Final

__all__ = [
    "WORK_DAY_NAMES",
    "hour_is_active",
    "is_in_work_schedule",
    "weekday_abbr",
]

WORK_DAY_NAMES: Final[tuple[str, ...]] = (
    "Пн",
    "Вт",
    "Ср",
    "Чт",
    "Пт",
    "Сб",
    "Вс",
)


def weekday_abbr(moment: datetime) -> str:
    """Возвращает русское двухсимвольное обозначение дня недели."""
    return WORK_DAY_NAMES[moment.weekday()]


def hour_is_active(work_hours_mask: int, hour: int) -> bool:
    """Возвращает True если для указанного часа установлен бит маски."""
    if not 0 <= hour <= 23:
        return False
    return bool((work_hours_mask >> hour) & 1)


def is_in_work_schedule(moment: datetime, work_days: str, work_hours_mask: int) -> bool:
    """Возвращает True если момент попадает в активное окно расписания."""
    day_abbr = weekday_abbr(moment)
    allowed_days = {part.strip() for part in work_days.split(",") if part}
    if day_abbr not in allowed_days:
        return False
    return hour_is_active(work_hours_mask, moment.hour)
