from __future__ import annotations

import os
from collections.abc import Iterator

from sqlalchemy import inspect, text
from sqlmodel import Session, SQLModel, create_engine

DB_URL = os.environ.get("RELAY_DB_URL", "sqlite:///./relay.db")

engine = create_engine(
    DB_URL,
    echo=bool(os.environ.get("RELAY_SQL_ECHO")),
    connect_args={"check_same_thread": False} if DB_URL.startswith("sqlite") else {},
)


def add_missing_columns() -> None:
    """Add columns a model has gained since the database was created.

    ``create_all`` only creates tables it cannot see; a table that already
    exists keeps its old shape, so a new field on ``Technician`` would read as
    "no such column" against a database from last week. Additive only: it never
    drops, renames or retypes anything, which is what makes it safe to run on
    every start. A database carrying 146,606 imported history rows should not
    have to be thrown away to give people a skills field.
    """
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            if table.name not in existing:
                continue
            have = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in have or column.primary_key:
                    continue
                kind = column.type.compile(engine.dialect)
                default = column.default.arg if column.default is not None and not callable(column.default.arg) else None
                clause = f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {kind}'
                if default is not None:
                    clause += f" DEFAULT {default!r}" if isinstance(default, str) else f" DEFAULT {default}"
                conn.execute(text(clause))


def create_all() -> None:
    SQLModel.metadata.create_all(engine)
    add_missing_columns()


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
