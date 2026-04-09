"""One-time script to populate memory analysis columns in the database.

Run this from the project root whenever the memory table needs to be
recomputed with `value` and `deal_quality`.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from sqlalchemy import inspect, text


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from app import app, db  # noqa: E402


def _parse_memory_capacity(name: str | None) -> int | None:
    if not name:
        return None
    match = re.search(r"(\d+)\s+GB", str(name))
    return int(match.group(1)) if match else None


def _parse_memory_speed(speed: str | float | int | None) -> float | None:
    if speed is None:
        return None
    try:
        return float(str(speed).replace(", ", ",").replace(",", "."))
    except (TypeError, ValueError):
        return None


def _parse_price(value: str | float | int | None) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace("$", "").replace(",", ""))
    except (TypeError, ValueError):
        return None


def populate_memory_analysis_columns() -> None:
    with app.app_context():
        inspector = inspect(db.engine)
        if "memory" not in inspector.get_table_names():
            raise RuntimeError("memory table not found in the database")

        existing_columns = {column["name"] for column in inspector.get_columns("memory")}

        with db.engine.begin() as conn:
            if "value" not in existing_columns:
                conn.execute(text("ALTER TABLE memory ADD COLUMN value REAL"))
            if "deal_quality" not in existing_columns:
                conn.execute(text("ALTER TABLE memory ADD COLUMN deal_quality TEXT"))

            rows = conn.execute(text("SELECT rowid, name, price, speed FROM memory")).mappings().all()
            if not rows:
                return

            values_by_capacity: dict[int, list[float]] = {}
            enriched_rows: list[dict[str, object]] = []

            for row in rows:
                capacity = _parse_memory_capacity(row["name"])
                speed_float = _parse_memory_speed(row["speed"])
                price_float = _parse_price(row["price"])

                value = None
                if capacity is not None and speed_float is not None and price_float not in (None, 0):
                    quality = speed_float * capacity
                    value = quality / price_float
                    values_by_capacity.setdefault(capacity, []).append(value)

                enriched_rows.append({
                    "rowid": row["rowid"],
                    "capacity": capacity,
                    "value": value,
                })

            conn.execute(text("UPDATE memory SET value = NULL, deal_quality = NULL"))

            for row in enriched_rows:
                if row["value"] is None or row["capacity"] is None:
                    continue

                capacity_values = values_by_capacity.get(row["capacity"], [])
                if not capacity_values:
                    continue

                mean_value = sum(capacity_values) / len(capacity_values)
                deal_quality = "Good Deal" if row["value"] >= mean_value else "Bad Deal"

                conn.execute(
                    text("UPDATE memory SET value = :value, deal_quality = :deal_quality WHERE rowid = :rowid"),
                    {
                        "rowid": row["rowid"],
                        "value": row["value"],
                        "deal_quality": deal_quality,
                    },
                )


if __name__ == "__main__":
    populate_memory_analysis_columns()
    print("Memory analysis columns updated.")