"""Memory (RAM) value analysis using database rows as source of truth."""

from __future__ import annotations

import re

from sqlalchemy import text

from db_analysis_common import app, db, ensure_columns, get_identifier_column, parse_float, parse_price, table_exists


def _parse_memory_capacity(name: str | None) -> int | None:
    if not name:
        return None
    match = re.search(r"\b(\d+)\s*GB\b", str(name), flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def _parse_memory_speed(speed: str | float | int | None) -> float | None:
    return parse_float(speed)


def run_ram_value_analysis() -> None:
    with app.app_context():
        table_name = "memory"
        if not table_exists(table_name):
            raise RuntimeError("memory table not found in the database")

        ensure_columns(table_name, {"value": "REAL", "deal_quality": "TEXT"})

        id_col = get_identifier_column(table_name)
        with db.engine.begin() as conn:
            rows = conn.execute(
                text(
                    f"""
                    SELECT {id_col} AS row_key, name, speed, price
                    FROM memory
                    """
                )
            ).mappings().all()
            if not rows:
                return

            values_by_capacity: dict[int, list[float]] = {}
            enriched_rows: list[dict[str, object | None]] = []

            for row in rows:
                capacity = _parse_memory_capacity(row["name"])
                speed_float = _parse_memory_speed(row["speed"])
                price_float = parse_price(row["price"])

                value = None
                if capacity is not None and speed_float is not None and price_float not in (None, 0):
                    quality = speed_float * capacity
                    value = quality / price_float
                    values_by_capacity.setdefault(capacity, []).append(value)

                enriched_rows.append(
                    {
                        "row_key": row["row_key"],
                        "capacity": capacity,
                        "value": value,
                    }
                )

            conn.execute(text("UPDATE memory SET value = NULL, deal_quality = NULL"))

            for row in enriched_rows:
                deal_quality = None
                if row["value"] is not None and row["capacity"] is not None:
                    capacity_values = values_by_capacity.get(row["capacity"], [])
                    if capacity_values:
                        mean_value = sum(capacity_values) / len(capacity_values)
                        deal_quality = "Good Deal" if row["value"] >= mean_value else "Bad Deal"

                conn.execute(
                    text(
                        f"""
                        UPDATE memory
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
    run_ram_value_analysis()
    print("RAM value analysis complete.")
