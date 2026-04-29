"""Internal hard drive value analysis using database rows as source of truth."""

from __future__ import annotations

import re

from sqlalchemy import text

from db_analysis_common import app, db, ensure_columns, get_identifier_column, is_missing, parse_float, parse_price, table_exists


def _parse_capacity_gb(value: str | float | int | None) -> float | None:
    if is_missing(value):
        return None

    text_value = str(value).replace(",", "").strip().lower()
    match = re.search(r"-?\d+(?:\.\d+)?", text_value)
    if not match:
        return None

    try:
        capacity = float(match.group(0))
    except (TypeError, ValueError):
        return None

    if "tb" in text_value:
        capacity *= 1024

    return capacity


def _parse_cache(value: str | float | int | None) -> float | None:
    return parse_float(value)


def run_internal_hard_drive_value_analysis() -> None:
    with app.app_context():
        table_name = "internal_hard_drive"
        if not table_exists(table_name):
            raise RuntimeError("internal_hard_drive table not found in the database")

        ensure_columns(table_name, {"value": "REAL", "deal_quality": "TEXT"})

        id_col = get_identifier_column(table_name)
        with db.engine.begin() as conn:
            rows = conn.execute(
                text(
                    f"""
                    SELECT {id_col} AS row_key, price, capacity, cache, type, form_factor
                    FROM internal_hard_drive
                    """
                )
            ).mappings().all()
            if not rows:
                return

            parsed_rows: list[dict[str, object | None]] = []
            cache_values = []

            for row in rows:
                capacity_gb = _parse_capacity_gb(row["capacity"])
                cache_float = _parse_cache(row["cache"])
                price_float = parse_price(row["price"])
                type_value = "" if is_missing(row["type"]) else str(row["type"]).strip()
                form_factor_value = "" if is_missing(row["form_factor"]) else str(row["form_factor"]).strip()

                if cache_float is not None:
                    cache_values.append(cache_float)

                parsed_rows.append(
                    {
                        "row_key": row["row_key"],
                        "capacity_gb": capacity_gb,
                        "cache": cache_float,
                        "price": price_float,
                        "type": type_value,
                        "form_factor": form_factor_value,
                        "value": None,
                    }
                )

            cache_median = None
            if cache_values:
                sorted_cache_values = sorted(cache_values)
                mid = len(sorted_cache_values) // 2
                if len(sorted_cache_values) % 2 == 1:
                    cache_median = sorted_cache_values[mid]
                else:
                    cache_median = (sorted_cache_values[mid - 1] + sorted_cache_values[mid]) / 2

            values_by_group: dict[tuple[str, str], list[float]] = {}

            for row in parsed_rows:
                cache_float = row["cache"] if row["cache"] is not None else cache_median
                capacity_gb = row["capacity_gb"]
                price_float = row["price"]
                type_value = str(row["type"] or "")
                form_factor_value = str(row["form_factor"] or "")

                value = None
                if (
                    capacity_gb is not None
                    and cache_float is not None
                    and price_float not in (None, 0)
                    and type_value
                    and form_factor_value
                ):
                    quality = capacity_gb * (1 + cache_float / 256)
                    value = quality / price_float
                    values_by_group.setdefault((type_value, form_factor_value), []).append(value)

                row["cache"] = cache_float
                row["value"] = value

            conn.execute(text("UPDATE internal_hard_drive SET value = NULL, deal_quality = NULL"))

            for row in parsed_rows:
                deal_quality = None
                type_value = str(row["type"] or "")
                form_factor_value = str(row["form_factor"] or "")
                if row["value"] is not None and type_value and form_factor_value:
                    group_values = values_by_group.get((type_value, form_factor_value), [])
                    if group_values:
                        mean_value = sum(group_values) / len(group_values)
                        deal_quality = "Good Deal" if row["value"] >= mean_value else "Bad Deal"

                conn.execute(
                    text(
                        f"""
                        UPDATE internal_hard_drive
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
    run_internal_hard_drive_value_analysis()
    print("Internal hard drive value analysis complete.")