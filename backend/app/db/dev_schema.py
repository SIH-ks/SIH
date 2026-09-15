"""Development-only schema reconciliation for the bundled SQLite database.

``Base.metadata.create_all()`` creates *missing tables* but never alters an existing
one, so a developer whose ``adhikar.db`` predates a new column gets a table that is
silently missing it and a ``no such column`` error on the first query. That is a
perfectly reasonable limitation of ``create_all`` -- and a bad first five minutes for
anyone pulling this repo.

This module closes exactly that gap and nothing more:

1. add columns the models declare and the table lacks, and
2. fill ``NULL``\\ s in a not-null column that has a declared default -- because
   ``ALTER TABLE ADD COLUMN`` cannot retroactively populate existing rows unless the
   statement itself carries a literal default, and a column the ORM believes is
   non-nullable but which reads back ``None`` fails Pydantic validation on the very
   first response.

It will not drop a column, change a type, or modify a value that is already set,
because those are the operations that need a reviewed migration and a backup.

**Production schema changes go through Alembic** (``backend/alembic/``). This runs
only when ``environment == "development"``, only against SQLite, and logs every
statement it issues.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import MetaData, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.schema import Column

from ..core.logging import get_logger

logger = get_logger("adhikar.dev_schema")

__all__ = ["reconcile_sqlite_schema"]


def _literal(value: object) -> str | None:
    """Render a Python default as a SQLite literal, or ``None`` if it cannot be.

    Callables (``uuid.uuid4``, ``func.now()``) deliberately return ``None``: a single
    literal is exactly the wrong thing for a per-row generated default, and adding
    the column nullable is the honest outcome.
    """
    if isinstance(value, Enum):
        value = value.value
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float, Decimal)):
        return str(value)
    if isinstance(value, str):
        escaped = value.replace("'", "''")
        return f"'{escaped}'"
    if isinstance(value, datetime):
        return f"'{value.isoformat()}'"
    return None


def _default_literal(column: Column) -> str | None:
    """The literal to use for ``column``, from a server default or a scalar ORM default."""
    if column.server_default is not None:
        arg = column.server_default.arg
        return arg if isinstance(arg, str) and arg.strip() else _literal(arg)
    if column.default is not None and not column.default.is_callable:
        return _literal(column.default.arg)
    return None


def reconcile_sqlite_schema(engine: Engine, metadata: MetaData) -> list[str]:
    """Bring a live SQLite database up to what the models declare.

    Returns the DDL/DML statements applied, for the caller to log or assert on.
    """
    if engine.dialect.name != "sqlite":
        return []

    inspector = inspect(engine)
    live_tables = set(inspector.get_table_names())
    applied: list[str] = []

    with engine.begin() as conn:
        for table in metadata.sorted_tables:
            if table.name not in live_tables:
                continue  # create_all handles wholly new tables
            # Case-insensitively: SQLite treats identifiers as case-insensitive in
            # SQL but reports them back exactly as they were declared, so an exact
            # comparison would try to re-add a column that is already there under a
            # different casing -- and fail with "duplicate column name".
            existing = {col["name"].lower() for col in inspector.get_columns(table.name)}

            for column in table.columns:
                literal = _default_literal(column)

                if column.name.lower() not in existing:
                    type_sql = column.type.compile(dialect=engine.dialect)
                    clause = f"{column.name} {type_sql}"
                    if literal is not None:
                        # With a literal default the column can keep NOT NULL: SQLite
                        # backfills every existing row with it as part of the ALTER.
                        clause += f" NOT NULL DEFAULT {literal}" if not column.nullable else f" DEFAULT {literal}"
                    statement = f"ALTER TABLE {table.name} ADD COLUMN {clause}"
                    conn.execute(text(statement))
                    applied.append(statement)
                    logger.warning("dev_schema_column_added", table=table.name, column=column.name)
                    continue

                # The column exists. If the model says it cannot be null and there is
                # a default to use, repair rows left NULL by an earlier, defaultless
                # ALTER. Touches only NULLs, so it can never overwrite real data.
                if not column.nullable and literal is not None:
                    statement = (
                        f"UPDATE {table.name} SET {column.name} = {literal} WHERE {column.name} IS NULL"
                    )
                    result = conn.execute(text(statement))
                    if result.rowcount:
                        applied.append(statement)
                        logger.warning(
                            "dev_schema_nulls_backfilled",
                            table=table.name,
                            column=column.name,
                            rows=result.rowcount,
                        )

    if applied:
        logger.warning(
            "dev_schema_reconciled",
            count=len(applied),
            note="Development convenience only. Production schema changes go through Alembic.",
        )
    return applied
