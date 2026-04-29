"""CPU value analysis using database rows as source of truth."""

from __future__ import annotations

from sqlalchemy import text

from db_analysis_common import app, db, ensure_columns, get_identifier_column, is_missing, parse_float, table_exists


def _parse_core_count(value: str | float | int | None) -> int | None:
    parsed = parse_float(value)
    return int(parsed) if parsed is not None else None


def _status_from_field(value: object | None) -> str:
    return "No" if is_missing(value) else "Yes"


def run_cpu_value_analysis() -> None:
    with app.app_context():
        table_name = "cpu"
        if not table_exists(table_name):
            raise RuntimeError("cpu table not found in the database")

        ensure_columns(
            table_name,
            {
                "value": "REAL",
                "deal_quality": "TEXT",
                "boost_status": "TEXT",
                "graphics_status": "TEXT",
            },
        )

        id_col = get_identifier_column(table_name)
        with db.engine.begin() as conn:
            rows = conn.execute(
                text(
                    f"""
                    SELECT {id_col} AS row_key, price, core_count, core_clock, tdp, boost_clock, graphics
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
                core_clock = parse_float(row["core_clock"])
                tdp = parse_float(row["tdp"])
                price = parse_float(row["price"])

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
                        "row_key": row["row_key"],
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
                        f"""
                        UPDATE cpu
                        SET value = :value,
                            deal_quality = :deal_quality,
                            boost_status = :boost_status,
                            graphics_status = :graphics_status
                        WHERE {id_col} = :row_key
                        """
                    ),
                    {
                        "row_key": row["row_key"],
                        "value": row["value"],
                        "deal_quality": deal_quality,
                        "boost_status": row["boost_status"],
                        "graphics_status": row["graphics_status"],
                    },
                )


if __name__ == "__main__":
    run_cpu_value_analysis()
    print("CPU value analysis complete.")
