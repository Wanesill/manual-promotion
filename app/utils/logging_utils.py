"""Утилиты для логирования через loguru."""

from __future__ import annotations

import re
from typing import Final

__all__ = ["sanitize_message"]

BAD_CHARS_PATTERN: Final[re.Pattern[str]] = re.compile(r"[\x00-\x1F\x7F-\x9F ⁦⁧⁨⁩]+")
MULTIPLE_SPACES_PATTERN: Final[re.Pattern[str]] = re.compile(r"\s{2,}")
DIGIT_SPACE_PATTERN: Final[re.Pattern[str]] = re.compile(r"(?<=\d) (?=\d)")


def sanitize_message(text: str) -> str:
    """Очищает строку от управляющих символов и схлопывает пробелы."""
    text = BAD_CHARS_PATTERN.sub(" ", text)
    text = MULTIPLE_SPACES_PATTERN.sub(" ", text)
    text = DIGIT_SPACE_PATTERN.sub("", text)
    return text.strip()
