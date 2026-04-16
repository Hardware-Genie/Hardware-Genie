"""One-time script to populate CPU analysis columns in the database.

Run this from the project root whenever the cpu table needs to be
recomputed with `value`, `deal_quality`, `boost_status`, and `graphics_status`.
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


def _parse_core_count(value: str | float | int | None) -> int | None:
    parsed = _parse_float(value)
    return int(parsed) if parsed is not None else None


def _status_from_field(value: object | None) -> str:
    return "No" if _is_missing(value) else "Yes"


def populate_cpu_analysis_columns() -> None:
    with app.app_context():
        inspector = inspect(db.engine)
        if "cpu" not in inspector.get_table_names():
            raise RuntimeError("cpu table not found in the database")

        existing_columns = {column["name"] for column in inspector.get_columns("cpu")}

        with db.engine.begin() as conn:
            if "value" not in existing_columns:
                conn.execute(text("ALTER TABLE cpu ADD COLUMN value REAL"))
            if "deal_quality" not in existing_columns:
                conn.execute(text("ALTER TABLE cpu ADD COLUMN deal_quality TEXT"))
            if "boost_status" not in existing_columns:
                conn.execute(text("ALTER TABLE cpu ADD COLUMN boost_status TEXT"))
            if "graphics_status" not in existing_columns:
                conn.execute(text("ALTER TABLE cpu ADD COLUMN graphics_status TEXT"))

            rows = conn.execute(
                text(
                    """
                    SELECT rowid, price, core_count, core_clock, tdp, boost_clock, graphics
                    FROM cpu
                    """
                )
            ).mappings().all()
            if not rows:
                return

            values_by_core_count: dict[int, list[float]] = {}
            enriched_rows: list[dict[str, object | None]] = []

            for row in rows:
                core_count = _parse_core_count(row["core_count"])
                core_clock = _parse_float(row["core_clock"])
                tdp = _parse_float(row["tdp"])
                price = _parse_float(row["price"])

                boost_status = _status_from_field(row["boost_clock"])
                graphics_status = _status_from_field(row["graphics"])

                value = None
                if (
                    core_count is not None
                    and core_clock is not None
                    and tdp is not None
                    and price not in (None, 0)
                ):
                    quality = core_count * core_clock * tdp
                    value = quality / price
                    values_by_core_count.setdefault(core_count, []).append(value)

                enriched_rows.append(
                    {
                        "rowid": row["rowid"],
                        "core_count": core_count,
                        "value": value,
                        "boost_status": boost_status,
                        "graphics_status": graphics_status,
                    }
                )

            conn.execute(
                text(
                    """
                    UPDATE cpu
                    SET value = NULL,
                        deal_quality = NULL,
                        boost_status = NULL,
                        graphics_status = NULL
                    """
                )
            )

            for row in enriched_rows:
                deal_quality = None
                if row["value"] is not None and row["core_count"] is not None:
                    tier_values = values_by_core_count.get(row["core_count"], [])
                    if tier_values:
                        mean_value = sum(tier_values) / len(tier_values)
                        deal_quality = "Good Deal" if row["value"] >= mean_value else "Bad Deal"

                conn.execute(
                    text(
                        """
                        UPDATE cpu
                        SET value = :value,
                            deal_quality = :deal_quality,
                            boost_status = :boost_status,
                            graphics_status = :graphics_status
                        WHERE rowid = :rowid
                        """
                    ),
                    {
                        "rowid": row["rowid"],
                        "value": row["value"],
                        "deal_quality": deal_quality,
                        "boost_status": row["boost_status"],
                        "graphics_status": row["graphics_status"],
                    },
                )


if __name__ == "__main__":
    populate_cpu_analysis_columns()
    print("CPU analysis columns updated.")
