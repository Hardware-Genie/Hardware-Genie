"""Lambda handler for part value analysis.

Triggered by the wayback scraper Lambda after new data is inserted.

Event payload:
  {"table": "cpu"}  # one of: cpu, memory, motherboard, power_supply
"""

from __future__ import annotations

import os
import re
from typing import Any

from sqlalchemy import create_engine, inspect, text


SUPPORTED_TABLES = {"cpu", "memory", "motherboard", "power_supply"}

EFFICIENCY_MAP = {
    "plus": 80, "bronze": 85, "silver": 88,
    "gold": 90, "platinum": 92, "titanium": 94,
}


# ── helpers ───────────────────────────────────────────────────────────────────

def _engine():
    url = os.environ["DATABASE_URL"]
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return create_engine(url)


def _is_missing(value: object) -> bool:
    if value is None:
        return True
    return str(value).strip().lower() in {"", "nan", "none", "null", "n/a", "na", "-"}


def _parse_float(value: object) -> float | None:
    if _is_missing(value):
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", "").strip())
    try:
        return float(m.group(0)) if m else None
    except (TypeError, ValueError):
        return None


def _id_col(engine, table_name: str) -> str:
    cols = {c["name"] for c in inspect(engine).get_columns(table_name)}
    return "id" if "id" in cols else "rowid"


def _ensure_columns(conn, table_name: str, cols: dict[str, str]) -> None:
    existing = {c["name"] for c in inspect(conn).get_columns(table_name)}
    for col, sql_type in cols.items():
        if col not in existing:
            conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col} {sql_type}"))


# ── per-table analysis ────────────────────────────────────────────────────────

def _analyse_cpu(conn, id_col: str) -> None:
    _ensure_columns(conn, "cpu", {"value": "REAL", "deal_quality": "TEXT",
                                   "boost_status": "TEXT", "graphics_status": "TEXT"})
    rows = conn.execute(text(
        f"SELECT {id_col} AS k, price, core_count, core_clock, tdp, boost_clock, graphics FROM cpu"
    )).mappings().all()
    if not rows:
        return

    buckets: dict[int, list[float]] = {}
    enriched: list[dict[str, Any]] = []
    for r in rows:
        cc = int(v) if (v := _parse_float(r["core_count"])) is not None else None
        clk = _parse_float(r["core_clock"])
        tdp = _parse_float(r["tdp"])
        price = _parse_float(r["price"])
        value = None
        if cc and clk and tdp and price:
            value = (cc * clk * tdp) / price
            buckets.setdefault(cc, []).append(value)
        enriched.append({"k": r["k"], "cc": cc, "value": value,
                         "boost": "No" if _is_missing(r["boost_clock"]) else "Yes",
                         "gfx": "No" if _is_missing(r["graphics"]) else "Yes"})

    conn.execute(text("UPDATE cpu SET value=NULL, deal_quality=NULL, boost_status=NULL, graphics_status=NULL"))
    for r in enriched:
        dq = None
        if r["value"] is not None and r["cc"] is not None:
            tier = buckets.get(r["cc"], [])
            if tier:
                dq = "Good Deal" if r["value"] >= sum(tier) / len(tier) else "Bad Deal"
        conn.execute(text(
            f"UPDATE cpu SET value=:v, deal_quality=:dq, boost_status=:bs, graphics_status=:gs WHERE {id_col}=:k"
        ), {"k": r["k"], "v": r["value"], "dq": dq, "bs": r["boost"], "gs": r["gfx"]})


def _analyse_memory(conn, id_col: str) -> None:
    _ensure_columns(conn, "memory", {"value": "REAL", "deal_quality": "TEXT"})
    rows = conn.execute(text(
        f"SELECT {id_col} AS k, name, speed, price FROM memory"
    )).mappings().all()
    if not rows:
        return

    buckets: dict[int, list[float]] = {}
    enriched: list[dict[str, Any]] = []
    for r in rows:
        m = re.search(r"\b(\d+)\s*GB\b", str(r["name"] or ""), re.IGNORECASE)
        cap = int(m.group(1)) if m else None
        spd = _parse_float(r["speed"])
        price = _parse_float(r["price"])
        value = None
        if cap and spd and price:
            value = (spd * cap) / price
            buckets.setdefault(cap, []).append(value)
        enriched.append({"k": r["k"], "cap": cap, "value": value})

    conn.execute(text("UPDATE memory SET value=NULL, deal_quality=NULL"))
    for r in enriched:
        dq = None
        if r["value"] is not None and r["cap"] is not None:
            tier = buckets.get(r["cap"], [])
            if tier:
                dq = "Good Deal" if r["value"] >= sum(tier) / len(tier) else "Bad Deal"
        conn.execute(text(
            f"UPDATE memory SET value=:v, deal_quality=:dq WHERE {id_col}=:k"
        ), {"k": r["k"], "v": r["value"], "dq": dq})


def _analyse_motherboard(conn, id_col: str) -> None:
    _ensure_columns(conn, "motherboard", {"value": "REAL", "deal_quality": "TEXT"})
    rows = conn.execute(text(
        f"SELECT {id_col} AS k, price, max_memory, socket, form_factor FROM motherboard"
    )).mappings().all()
    if not rows:
        return

    buckets: dict[tuple, list[float]] = {}
    enriched: list[dict[str, Any]] = []
    for r in rows:
        mm = _parse_float(r["max_memory"])
        price = _parse_float(r["price"])
        sock = "" if _is_missing(r["socket"]) else str(r["socket"]).strip()
        ff = "" if _is_missing(r["form_factor"]) else str(r["form_factor"]).strip()
        value, gk = None, None
        if mm and price and sock and ff:
            value = mm / price
            gk = (sock, ff, mm)
            buckets.setdefault(gk, []).append(value)
        enriched.append({"k": r["k"], "gk": gk, "value": value})

    conn.execute(text("UPDATE motherboard SET value=NULL, deal_quality=NULL"))
    for r in enriched:
        dq = None
        if r["value"] is not None and r["gk"] is not None:
            tier = buckets.get(r["gk"], [])
            if tier:
                dq = "Good Deal" if r["value"] >= sum(tier) / len(tier) else "Bad Deal"
        conn.execute(text(
            f"UPDATE motherboard SET value=:v, deal_quality=:dq WHERE {id_col}=:k"
        ), {"k": r["k"], "v": r["value"], "dq": dq})


def _analyse_power_supply(conn, id_col: str) -> None:
    _ensure_columns(conn, "power_supply", {"value": "REAL", "deal_quality": "TEXT"})
    rows = conn.execute(text(
        f"SELECT {id_col} AS k, efficiency, wattage, price FROM power_supply"
    )).mappings().all()
    if not rows:
        return

    def _eff_tier(e):
        v = str(e or "").lower()
        for tier in ("titanium", "platinum", "gold", "silver", "bronze"):
            if tier in v:
                return tier
        return "plus"

    def _wattage(v):
        try:
            return float(str(v or "").replace("W", "").replace("w", "").replace(",", "").strip())
        except (TypeError, ValueError):
            return None

    buckets: dict[float, list[float]] = {}
    enriched: list[dict[str, Any]] = []
    for r in rows:
        eff = EFFICIENCY_MAP.get(_eff_tier(r["efficiency"]))
        w = _wattage(r["wattage"])
        price = _parse_float(r["price"])
        value = None
        if eff and w and price:
            value = (eff * w) / price
            buckets.setdefault(w, []).append(value)
        enriched.append({"k": r["k"], "w": w, "value": value})

    conn.execute(text("UPDATE power_supply SET value=NULL, deal_quality=NULL"))
    for r in enriched:
        dq = None
        if r["value"] is not None and r["w"] is not None:
            tier = buckets.get(r["w"], [])
            if tier:
                dq = "Good Deal" if r["value"] >= sum(tier) / len(tier) else "Bad Deal"
        conn.execute(text(
            f"UPDATE power_supply SET value=:v, deal_quality=:dq WHERE {id_col}=:k"
        ), {"k": r["k"], "v": r["value"], "dq": dq})


_ANALYSERS = {
    "cpu": _analyse_cpu,
    "memory": _analyse_memory,
    "motherboard": _analyse_motherboard,
    "power_supply": _analyse_power_supply,
}


# ── handler ───────────────────────────────────────────────────────────────────

def handler(event: dict, context: object) -> dict:
    table = (event or {}).get("table", "").strip()
    if table not in SUPPORTED_TABLES:
        return {"status": "error", "message": f"Unsupported table '{table}'. Must be one of: {sorted(SUPPORTED_TABLES)}"}

    engine = _engine()
    id_col = _id_col(engine, table)
    with engine.begin() as conn:
        _ANALYSERS[table](conn, id_col)

    return {"status": "success", "table": table}
