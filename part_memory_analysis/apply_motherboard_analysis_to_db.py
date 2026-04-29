"""One-time script to populate motherboard analysis columns in the database.

Run this from the project root whenever the motherboard table needs to be
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

_MISSING_STRINGS = {"", "nan", "none", "null", "n/a", "na", "-"}


def _is_missing(value: object | None) -> bool:
    if value is None:
        return True
    string_value = str(value).strip().lower()
    return string_value in _MISSING_STRINGS


def _parse_float(value: str | float | int | None) -> float | None:
    if _is_missing(value):
        return None

    text_value = str(value).replace(",", "").strip()
    match = re.search(r"-?\d+(?:\.\d+)?", text_value)
    if not match:
        return None

    try:
        return float(match.group(0))
    except (TypeError, ValueError):
        return None


def _parse_price(value: str | float | int | None) -> float | None:
    return _parse_float(value)


def populate_motherboard_analysis_columns() -> None:
    with app.app_context():
        inspector = inspect(db.engine)
        if "motherboard" not in inspector.get_table_names():
            raise RuntimeError("motherboard table not found in the database")

        existing_columns = {column["name"] for column in inspector.get_columns("motherboard")}

        with db.engine.begin() as conn:
            if "value" not in existing_columns:
                conn.execute(text("ALTER TABLE motherboard ADD COLUMN value REAL"))
            if "deal_quality" not in existing_columns:
                conn.execute(text("ALTER TABLE motherboard ADD COLUMN deal_quality TEXT"))

            rows = conn.execute(
                text(
                    """
                    SELECT rowid, price, max_memory, socket, form_factor
                    FROM motherboard
                    """
                )
            ).mappings().all()
            if not rows:
                return

            values_by_group: dict[tuple[str, str, float], list[float]] = {}
            enriched_rows: list[dict[str, object | None]] = []

            for row in rows:
                max_memory_float = _parse_float(row["max_memory"])
                price_float = _parse_price(row["price"])

                socket = "" if _is_missing(row["socket"]) else str(row["socket"]).strip()
                form_factor = "" if _is_missing(row["form_factor"]) else str(row["form_factor"]).strip()

                value = None
                group_key: tuple[str, str, float] | None = None
                if (
                    max_memory_float is not None
                    and price_float not in (None, 0)
                    and socket
                    and form_factor
                ):
                    quality = max_memory_float
                    value = quality / price_float
                    group_key = (socket, form_factor, max_memory_float)
                    values_by_group.setdefault(group_key, []).append(value)

                enriched_rows.append(
                    {
                        "rowid": row["rowid"],
                        "group_key": group_key,
                        "value": value,
                    }
                )

            conn.execute(text("UPDATE motherboard SET value = NULL, deal_quality = NULL"))

            for row in enriched_rows:
                deal_quality = None
                if row["value"] is not None and row["group_key"] is not None:
                    group_values = values_by_group.get(row["group_key"], [])
                    if group_values:
                        mean_value = sum(group_values) / len(group_values)
                        deal_quality = "Good Deal" if row["value"] >= mean_value else "Bad Deal"

                conn.execute(
                    text(
                        """
                        UPDATE motherboard
                        SET value = :value, deal_quality = :deal_quality
                        WHERE rowid = :rowid
                        """
                    ),
                    {
                        "rowid": row["rowid"],
                        "value": row["value"],
                        "deal_quality": deal_quality,
                    },
                )


if __name__ == "__main__":
    populate_motherboard_analysis_columns()
    print("Motherboard analysis columns updated.")
