import re

from sqlalchemy import BigInteger
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    declared_attr,
    mapped_column,
)


class Base(DeclarativeBase):
    id: Mapped[int] = mapped_column(BigInteger, autoincrement=True, primary_key=True)

    @classmethod
    @declared_attr  # type: ignore[arg-type]
    def __tablename__(cls) -> str:
        name: str = cls.__name__
        s: str = re.sub(pattern="(.)([A-Z][a-z]+)", repl=r"\1_\2", string=name)
        table_name: str = re.sub(
            pattern="([a-z0-9])([A-Z])", repl=r"\1_\2", string=s
        ).lower()
        return table_name
