"""Модуль конфигурации приложения."""

from functools import lru_cache
from os import getenv
from typing import Final, TypeVar

from pydantic import BaseModel, PostgresDsn, RedisDsn
from yaml import load

try:
    from yaml import CSafeLoader as SafeLoader
except ImportError:
    from yaml import SafeLoader

__all__ = [
    "ConfigType",
    "DatabaseConfig",
    "LoggingConfig",
    "RedisConfig",
    "get_config",
]

CONFIG_ENV_VAR: Final[str] = "APP_CONFIG"

ConfigType = TypeVar("ConfigType", bound=BaseModel)


class DatabaseConfig(BaseModel):
    """Конфигурация подключения к PostgreSQL."""

    dsn: PostgresDsn
    echo: bool = False
    pool_size: int = 5
    max_overflow: int = 3
    pool_timeout: int = 30
    pool_recycle: int = 600


class RedisConfig(BaseModel):
    """Конфигурация подключения к Redis."""

    dsn: RedisDsn


class LoggingConfig(BaseModel):
    """Конфигурация логирования (loguru): stderr + ротация файлов."""

    level: int = 20
    console: bool = True


@lru_cache(maxsize=1)
def _parse_config_file() -> dict:
    """Загружает и парсит YAML конфигурационный файл."""
    file_path: str | None = getenv(key=CONFIG_ENV_VAR)
    if file_path is None:
        raise ValueError(f"Environment variable {CONFIG_ENV_VAR} is not set")
    with open(file_path, "rb") as file:
        return load(stream=file, Loader=SafeLoader)


@lru_cache
def get_config[ConfigType: BaseModel](
    model: type[ConfigType], root_key: str | None = None
) -> ConfigType:
    """Возвращает конфигурацию указанного типа из YAML."""
    config_dict: dict = _parse_config_file()
    if root_key is None:
        return model.model_validate(obj=config_dict)
    if root_key not in config_dict:
        raise ValueError(f"Configuration key '{root_key}' not found")
    return model.model_validate(obj=config_dict[root_key])
