"""Motherboard value analysis using database rows as source of truth."""

from __future__ import annotations

from sqlalchemy import text

from db_analysis_common import app, db, ensure_columns, get_identifier_column, is_missing, parse_float, parse_price, table_exists


def run_motherboard_value_analysis() -> None:
    with app.app_context():
        table_name = "motherboard"
        if not table_exists(table_name):
            raise RuntimeError("motherboard table not found in the database")

        ensure_columns(table_name, {"value": "REAL", "deal_quality": "TEXT"})

        id_col = get_identifier_column(table_name)
        with db.engine.begin() as conn:
            rows = conn.execute(
                text(
                    f"""
                    SELECT {id_col} AS row_key, price, max_memory, socket, form_factor
                    FROM motherboard
                    """
                )
            ).mappings().all()
            if not rows:
                return

            values_by_group: dict[tuple[str, str, float], list[float]] = {}
            enriched_rows: list[dict[str, object | None]] = []

            for row in rows:
                max_memory_float = parse_float(row["max_memory"])
                price_float = parse_price(row["price"])

                socket = "" if is_missing(row["socket"]) else str(row["socket"]).strip()
                form_factor = "" if is_missing(row["form_factor"]) else str(row["form_factor"]).strip()

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
                        "row_key": row["row_key"],
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
                        f"""
                        UPDATE motherboard
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
    run_motherboard_value_analysis()
    print("Motherboard value analysis complete.")
