"""Power supply value analysis using database rows as source of truth."""

from __future__ import annotations

from sqlalchemy import text

from db_analysis_common import app, db, ensure_columns, get_identifier_column, parse_price, table_exists


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


def run_power_supply_value_analysis() -> None:
    with app.app_context():
        table_name = "power_supply"
        if not table_exists(table_name):
            raise RuntimeError("power_supply table not found in the database")

        ensure_columns(table_name, {"value": "REAL", "deal_quality": "TEXT"})

        id_col = get_identifier_column(table_name)
        with db.engine.begin() as conn:
            rows = conn.execute(
                text(
                    f"""
                    SELECT {id_col} AS row_key, efficiency, wattage, price
                    FROM power_supply
                    """
                )
            ).mappings().all()
            if not rows:
                return

            values_by_wattage: dict[float, list[float]] = {}
            enriched_rows: list[dict[str, object | None]] = []

            for row in rows:
                efficiency_tier = _parse_efficiency_tier(row["efficiency"])
                efficiency_numeric = EFFICIENCY_MAP.get(efficiency_tier)
                wattage_float = _parse_wattage(row["wattage"])
                price_float = parse_price(row["price"])

                value = None
                if (
                    efficiency_numeric is not None
                    and wattage_float is not None
                    and price_float not in (None, 0)
                ):
                    quality = efficiency_numeric * wattage_float
                    value = quality / price_float
                    values_by_wattage.setdefault(wattage_float, []).append(value)

                enriched_rows.append(
                    {
                        "row_key": row["row_key"],
                        "wattage_float": wattage_float,
                        "value": value,
                    }
                )

            conn.execute(text("UPDATE power_supply SET value = NULL, deal_quality = NULL"))

            for row in enriched_rows:
                deal_quality = None
                if row["value"] is not None and row["wattage_float"] is not None:
                    wattage_values = values_by_wattage.get(row["wattage_float"], [])
                    if wattage_values:
                        mean_value = sum(wattage_values) / len(wattage_values)
                        deal_quality = "Good Deal" if row["value"] >= mean_value else "Bad Deal"

                conn.execute(
                    text(
                        f"""
                        UPDATE power_supply
                        SET value = :value,
                            deal_quality = :deal_quality
                        WHERE {id_col} = :row_key
                        """
                    ),
                    {
                        "row_key": row["row_key"],
                        "value": row["value"],
                        "deal_quality": deal_quality,
                    },
                )


if __name__ == "__main__":
    run_power_supply_value_analysis()
    print("Power supply value analysis complete.")
