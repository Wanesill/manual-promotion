"""Инфраструктурный слой: кэш Avito-ответов."""

from .redis_cache import AvitoCache

__all__ = [
    "AvitoCache",
]
