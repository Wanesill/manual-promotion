"""Внешние интеграции с API третьих сторон."""

from .avito_service import AccountForbiddenError, AvitoService

__all__ = ["AccountForbiddenError", "AvitoService"]
