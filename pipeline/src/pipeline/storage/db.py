from __future__ import annotations

from sqlalchemy import Engine, create_engine

from pipeline.storage.tables import Base


def create_engine_from_url(url: str, *, echo: bool = False) -> Engine:
    return create_engine(url, echo=echo, future=True)


def create_schema(engine: Engine) -> None:
    Base.metadata.create_all(engine)
