"""Shared helpers for part value analysis scripts.

Each script in this folder reads from the DB, computes value/deal quality,
and writes results back to the same table.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import inspect, text


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from app import app, db  # noqa: E402


_MISSING_STRINGS = {"", "nan", "none", "null", "n/a", "na", "-"}


def is_missing(value: object | None) -> bool:
    if value is None:
        return True
    return str(value).strip().lower() in _MISSING_STRINGS


def parse_float(value: str | float | int | None) -> float | None:
    if is_missing(value):
        return None

    text_value = str(value).replace(",", "").strip()
    match = re.search(r"-?\d+(?:\.\d+)?", text_value)
    if not match:
        return None

    try:
        return float(match.group(0))
    except (TypeError, ValueError):
        return None


def parse_price(value: str | float | int | None) -> float | None:
    return parse_float(value)


def get_identifier_column(table_name: str) -> str:
    """Prefer explicit id; fall back to sqlite rowid for legacy tables."""
    inspector = inspect(db.engine)
    column_names = {column["name"] for column in inspector.get_columns(table_name)}
    return "id" if "id" in column_names else "rowid"


def ensure_columns(table_name: str, columns_with_sql_type: dict[str, str]) -> None:
    inspector = inspect(db.engine)
    existing_columns = {column["name"] for column in inspector.get_columns(table_name)}

    with db.engine.begin() as conn:
        for column_name, sql_type in columns_with_sql_type.items():
            if column_name not in existing_columns:
                conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {sql_type}"))


def table_exists(table_name: str) -> bool:
    inspector = inspect(db.engine)
    return table_name in inspector.get_table_names()


def execute_select(query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    with db.engine.begin() as conn:
        rows = conn.execute(text(query), params or {}).mappings().all()
    return [dict(row) for row in rows]
