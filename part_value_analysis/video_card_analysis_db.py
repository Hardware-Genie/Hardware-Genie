"""Video card value analysis using database rows as source of truth."""

from __future__ import annotations

from sqlalchemy import text

from db_analysis_common import app, db, ensure_columns, get_identifier_column, is_missing, parse_float, parse_price, table_exists


def run_video_card_value_analysis() -> None:
    with app.app_context():
        table_name = "video_card"
        if not table_exists(table_name):
            raise RuntimeError("video_card table not found in the database")

        ensure_columns(table_name, {"value": "REAL", "deal_quality": "TEXT"})

        id_col = get_identifier_column(table_name)
        with db.engine.begin() as conn:
            rows = conn.execute(
                text(
                    f"""
                    SELECT {id_col} AS row_key, price, chipset, memory, core_clock, boost_clock
                    FROM video_card
                    """
                )
            ).mappings().all()
            if not rows:
                return

            values_by_chipset: dict[str, list[float]] = {}
            enriched_rows: list[dict[str, object | None]] = []

            for row in rows:
                chipset = "" if is_missing(row["chipset"]) else str(row["chipset"]).strip()
                memory_float = parse_float(row["memory"])
                core_clock_float = parse_float(row["core_clock"])
                boost_clock_float = parse_float(row["boost_clock"])
                price_float = parse_price(row["price"])

                value = None
                if (
                    chipset
                    and memory_float is not None
                    and core_clock_float is not None
                    and boost_clock_float is not None
                    and price_float not in (None, 0)
                ):
                    quality = memory_float * ((core_clock_float + boost_clock_float) / 2)
                    value = quality / price_float
                    values_by_chipset.setdefault(chipset, []).append(value)

                enriched_rows.append(
                    {
                        "row_key": row["row_key"],
                        "chipset": chipset,
                        "value": value,
                    }
                )

            conn.execute(text("UPDATE video_card SET value = NULL, deal_quality = NULL"))

            for row in enriched_rows:
                deal_quality = None
                if row["value"] is not None and row["chipset"]:
                    chipset_values = values_by_chipset.get(str(row["chipset"]), [])
                    if chipset_values:
                        mean_value = sum(chipset_values) / len(chipset_values)
                        deal_quality = "Good Deal" if row["value"] >= mean_value else "Bad Deal"

                conn.execute(
                    text(
                        f"""
                        UPDATE video_card
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
    run_video_card_value_analysis()
    print("Video card value analysis complete.")