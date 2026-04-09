"""One-time script to populate power supply analysis columns in the database.

Run this from the project root whenever the power_supply table needs to be
recomputed with `value` and `deal_quality`.
"""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import inspect, text


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from app import app, db  # noqa: E402


EFFICIENCY_MAP = {
    "plus": 80,
    "bronze": 85,
    "silver": 88,
    "gold": 90,
    "platinum": 92,
    "titanium": 94,
}


def _parse_efficiency_tier(efficiency: str | None) -> str:
    if not efficiency:
        return "plus"

    value = str(efficiency).lower().strip()
    if "titanium" in value:
        return "titanium"
    if "platinum" in value:
        return "platinum"
    if "gold" in value:
        return "gold"
    if "silver" in value:
        return "silver"
    if "bronze" in value:
        return "bronze"
    return "plus"


def _parse_wattage(value: str | float | int | None) -> float | None:
    if value is None:
        return None
    try:
        cleaned = str(value).replace("W", "").replace("w", "").replace(",", "").strip()
        return float(cleaned)
    except (TypeError, ValueError):
        return None


def _parse_price(value: str | float | int | None) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def populate_power_supply_analysis_columns() -> None:
    with app.app_context():
        inspector = inspect(db.engine)
        if "power_supply" not in inspector.get_table_names():
            raise RuntimeError("power_supply table not found in the database")

        existing_columns = {column["name"] for column in inspector.get_columns("power_supply")}

        with db.engine.begin() as conn:
            if "value" not in existing_columns:
                conn.execute(text("ALTER TABLE power_supply ADD COLUMN value REAL"))
            if "deal_quality" not in existing_columns:
                conn.execute(text("ALTER TABLE power_supply ADD COLUMN deal_quality TEXT"))

            rows = conn.execute(
                text("SELECT rowid, efficiency, wattage, price FROM power_supply")
            ).mappings().all()
            if not rows:
                return

            values_by_efficiency: dict[str, list[float]] = {}
            enriched_rows: list[dict[str, object]] = []

            for row in rows:
                efficiency_tier = _parse_efficiency_tier(row["efficiency"])
                efficiency_numeric = EFFICIENCY_MAP.get(efficiency_tier)
                wattage_float = _parse_wattage(row["wattage"])
                price_float = _parse_price(row["price"])

                value = None
                if (
                    efficiency_numeric is not None
                    and wattage_float is not None
                    and price_float not in (None, 0)
                ):
                    quality = efficiency_numeric * wattage_float
                    value = quality / price_float
                    values_by_efficiency.setdefault(efficiency_tier, []).append(value)

                enriched_rows.append(
                    {
                        "rowid": row["rowid"],
                        "efficiency_tier": efficiency_tier,
                        "value": value,
                    }
                )

            conn.execute(text("UPDATE power_supply SET value = NULL, deal_quality = NULL"))

            for row in enriched_rows:
                if row["value"] is None:
                    continue

                tier_values = values_by_efficiency.get(row["efficiency_tier"], [])
                if not tier_values:
                    continue

                mean_value = sum(tier_values) / len(tier_values)
                deal_quality = "Good Deal" if row["value"] >= mean_value else "Bad Deal"

                conn.execute(
                    text(
                        """
                        UPDATE power_supply
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
    populate_power_supply_analysis_columns()
    print("Power supply analysis columns updated.")
