"""Pipelines for writing scraped part history directly into the app database."""

import difflib
import json
import os
import re
from sqlalchemy import create_engine, text


CATEGORY_TO_TABLE = {
    "cpu": "cpu",
    "memory": "memory",
    "video-card": "video_card",
    "motherboard": "motherboard",
    "power-supply": "power_supply",
    "internal-hard-drive": "internal_hard_drive",
}

CATEGORY_COLUMNS = {
    "cpu": ["name", "price", "core_count", "core_clock", "boost_clock", "tdp", "graphics", "smt", "snapshot_date", "microarchitecture"],
    "memory": ["name", "price", "speed", "modules", "price_per_gb", "color", "first_word_latency", "cas_latency", "snapshot_date"],
    "video-card": ["name", "price", "chipset", "memory", "core_clock", "boost_clock", "color", "length", "snapshot_date"],
    "motherboard": ["name", "price", "socket", "form_factor", "max_memory", "memory_slots", "color", "snapshot_date"],
    "power-supply": ["name", "price", "type", "efficiency", "wattage", "modular", "color", "snapshot_date"],
    "internal-hard-drive": ["name", "price", "capacity", "price_per_gb", "type", "cache", "form_factor", "interface", "snapshot_date"],
}

CATEGORY_SIGNATURE_COLUMNS = {
    "cpu": ["core_count", "core_clock", "boost_clock", "tdp", "graphics", "smt"],
    "memory": ["modules", "speed", "cas_latency", "color"],
    "video-card": ["chipset", "memory", "core_clock", "boost_clock", "length"],
    "motherboard": ["socket", "form_factor", "max_memory", "memory_slots"],
    "power-supply": ["type", "efficiency", "wattage", "modular"],
    "internal-hard-drive": ["capacity", "type", "interface", "form_factor", "cache"],
}

CREATE_TABLE_SQL = {
    "cpu": """
        CREATE TABLE IF NOT EXISTS cpu (
            name TEXT,
            price REAL,
            core_count REAL,
            core_clock REAL,
            boost_clock REAL,
            tdp REAL,
            graphics TEXT,
            smt BOOLEAN,
            snapshot_date TEXT,
            microarchitecture TEXT
        )
    """,
    "memory": """
        CREATE TABLE IF NOT EXISTS memory (
            name TEXT,
            price REAL,
            speed TEXT,
            modules TEXT,
            price_per_gb REAL,
            color TEXT,
            first_word_latency REAL,
            cas_latency REAL,
            snapshot_date TEXT
        )
    """,
    "video-card": """
        CREATE TABLE IF NOT EXISTS video_card (
            name TEXT,
            price REAL,
            chipset TEXT,
            memory REAL,
            core_clock REAL,
            boost_clock REAL,
            color TEXT,
            length REAL,
            snapshot_date TEXT
        )
    """,
    "motherboard": """
        CREATE TABLE IF NOT EXISTS motherboard (
            name TEXT,
            price REAL,
            socket TEXT,
            form_factor TEXT,
            max_memory REAL,
            memory_slots REAL,
            color TEXT,
            snapshot_date TEXT
        )
    """,
    "power-supply": """
        CREATE TABLE IF NOT EXISTS power_supply (
            name TEXT,
            price REAL,
            type TEXT,
            efficiency TEXT,
            wattage REAL,
            modular TEXT,
            color TEXT,
            snapshot_date TEXT
        )
    """,
    "internal-hard-drive": """
        CREATE TABLE IF NOT EXISTS internal_hard_drive (
            name TEXT,
            price REAL,
            capacity REAL,
            price_per_gb REAL,
            type TEXT,
            cache REAL,
            form_factor TEXT,
            interface TEXT,
            snapshot_date TEXT
        )
    """,
}


def _resolve_database_uri():
    db_uri = os.getenv("DATABASE_URL", "").strip()
    if not db_uri:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.abspath(os.path.join(current_dir, "..", "..", "..", ".."))
        db_path = os.path.abspath(os.path.join(project_root, "instance", "parts.db")).replace("\\", "/")
        db_uri = f"sqlite:///{db_path}"
    elif db_uri.startswith("sqlite:///"):
        sqlite_path = db_uri[len("sqlite:///"):]
        if sqlite_path and sqlite_path != ':memory:' and not os.path.isabs(sqlite_path):
            current_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.abspath(os.path.join(current_dir, "..", "..", "..", ".."))
            if sqlite_path in ('parts.db', './parts.db'):
                sqlite_path = os.path.join(project_root, 'instance', 'parts.db')
            else:
                sqlite_path = os.path.join(project_root, sqlite_path)
            db_uri = f"sqlite:///{os.path.abspath(sqlite_path).replace('\\', '/')}"
    if db_uri.startswith("postgres://"):
        db_uri = db_uri.replace("postgres://", "postgresql://", 1)
    return db_uri


class AppDatabasePipeline:
    """Persist scraped rows directly into category tables in the main app DB."""

    def __init__(self):
        self.crawler = None
        self.category = ""
        self.table_name = None
        self.columns = []
        self.engine = None
        self.inserted_count = 0
        self.skipped_existing_count = 0
        self.skipped_invalid_count = 0
        self.summary_file = os.getenv("SCRAPE_SUMMARY_FILE", "").strip()
        self.canonical_name_counts = {}
        self._name_cache = {}

    @classmethod
    def from_crawler(cls, crawler):
        instance = cls()
        instance.crawler = crawler
        return instance

    def _resolve_spider(self, spider=None):
        if spider is not None:
            return spider
        if self.crawler is not None:
            return getattr(self.crawler, "spider", None)
        return None

    def _ensure_category_context(self, spider=None, item=None):
        effective_spider = self._resolve_spider(spider)

        if not self.category and effective_spider is not None:
            self.category = getattr(effective_spider, "category", "") or ""

        if not self.category and item is not None:
            self.category = str(item.get("category") or "").strip()

        self.table_name = CATEGORY_TO_TABLE.get(self.category)
        self.columns = CATEGORY_COLUMNS.get(self.category, [])
        return effective_spider

    def open_spider(self, spider=None):
        effective_spider = self._ensure_category_context(spider=spider)
        db_uri = _resolve_database_uri()
        self.engine = create_engine(db_uri)

        if not self.table_name:
            if effective_spider is not None:
                effective_spider.logger.warning("Unknown category '%s'; DB writes will be skipped.", self.category)
            return

        create_sql = CREATE_TABLE_SQL.get(self.category)
        if create_sql:
            with self.engine.begin() as conn:
                conn.execute(text(create_sql))

    def close_spider(self, spider=None):
        self._write_summary()
        if hasattr(self, "engine"):
            self.engine.dispose()

    def process_item(self, item, spider=None):
        effective_spider = self._ensure_category_context(spider=spider, item=item)

        if self.engine is None:
            self.open_spider(spider=effective_spider)

        if not self.table_name or not self.columns:
            self.skipped_invalid_count += 1
            return item

        row = self._build_row(item)
        if row is None:
            self.skipped_invalid_count += 1
            return item

        try:
            with self.engine.begin() as conn:
                canonical_name = self._canonicalize_name(conn, row)
                row["name"] = canonical_name
                self.canonical_name_counts[canonical_name] = self.canonical_name_counts.get(canonical_name, 0) + 1

                exists = conn.execute(
                    text(f"SELECT 1 FROM {self.table_name} WHERE name = :name AND snapshot_date = :snapshot_date LIMIT 1"),
                    {"name": row["name"], "snapshot_date": row["snapshot_date"]},
                ).first()
                if exists is not None:
                    self.skipped_existing_count += 1
                    return item

                placeholders = ", ".join([f":{column}" for column in self.columns])
                columns_sql = ", ".join(self.columns)
                conn.execute(
                    text(f"INSERT INTO {self.table_name} ({columns_sql}) VALUES ({placeholders})"),
                    row,
                )
                self.inserted_count += 1
        except Exception as exc:
            if effective_spider is not None:
                effective_spider.logger.error("DB insert error for %s on %s: %s", row.get("name"), row.get("snapshot_date"), exc)
            else:
                print(f"DB insert error for {row.get('name')} on {row.get('snapshot_date')}: {exc}")

        return item

    def _build_row(self, item):
        name = str(item.get("name") or item.get("product_name") or "").strip()
        snapshot_date = str(item.get("snapshot_date") or "").strip()
        price = item.get("price")

        if not name or not snapshot_date or price in (None, ""):
            return None

        row = {column: item.get(column) for column in self.columns}
        row["name"] = name
        row["snapshot_date"] = snapshot_date
        row["price"] = price
        return row

    def _write_summary(self):
        if not self.summary_file:
            return

        summary = {
            "category": self.category,
            "table": self.table_name,
            "canonical_name": self._most_common_canonical_name(),
            "inserted": self.inserted_count,
            "skipped_existing": self.skipped_existing_count,
            "skipped_invalid": self.skipped_invalid_count,
            "skipped_total": self.skipped_existing_count + self.skipped_invalid_count,
            "processed_total": self.inserted_count + self.skipped_existing_count + self.skipped_invalid_count,
        }

        try:
            with open(self.summary_file, "w", encoding="utf-8") as handle:
                json.dump(summary, handle)
        except OSError:
            pass

    def _most_common_canonical_name(self):
        if not self.canonical_name_counts:
            return None
        return max(self.canonical_name_counts.items(), key=lambda pair: pair[1])[0]

    def _canonicalize_name(self, conn, row):
        source_name = str(row.get("name") or "").strip()
        if not source_name:
            return source_name

        match_by_specs = self._canonical_name_by_specs(conn, row, source_name)
        if match_by_specs:
            return match_by_specs

        match_by_fuzzy = self._canonical_name_by_fuzzy(source_name)
        if match_by_fuzzy:
            return match_by_fuzzy

        return source_name

    def _canonical_name_by_specs(self, conn, row, source_name):
        signature_columns = CATEGORY_SIGNATURE_COLUMNS.get(self.category, [])
        if not signature_columns:
            return None

        where_clauses = []
        params = {}
        for column in signature_columns:
            value = row.get(column)
            if value in (None, ""):
                continue
            where_clauses.append(f"{column} = :{column}")
            params[column] = value

        if not where_clauses:
            return None

        sql = text(
            f"""
            SELECT name, COUNT(*) AS sample_count
            FROM {self.table_name}
            WHERE name IS NOT NULL AND TRIM(name) != ''
              AND {' AND '.join(where_clauses)}
            GROUP BY name
            ORDER BY sample_count DESC
            """
        )
        matches = conn.execute(sql, params).fetchall()
        if not matches:
            return None

        normalized_source = self._normalize_name(source_name)
        source_gb = self._extract_gb(source_name)

        best_name = None
        best_score = 0.0
        best_count = -1

        for match in matches:
            candidate_name = str(match[0]).strip()
            candidate_count = int(match[1] or 0)
            candidate_gb = self._extract_gb(candidate_name)
            if source_gb is not None and candidate_gb is not None and source_gb != candidate_gb:
                continue

            score = difflib.SequenceMatcher(None, normalized_source, self._normalize_name(candidate_name)).ratio()
            if score > best_score or (score == best_score and candidate_count > best_count):
                best_score = score
                best_count = candidate_count
                best_name = candidate_name

        if best_name and best_score >= 0.85:
            return best_name
        return None

    def _canonical_name_by_fuzzy(self, source_name):
        candidates = self._get_name_candidates()
        if not candidates:
            return None

        normalized_source = self._normalize_name(source_name)
        source_gb = self._extract_gb(source_name)

        best_name = None
        best_score = 0.0
        for candidate_name, _count in candidates:
            candidate_gb = self._extract_gb(candidate_name)
            if source_gb is not None and candidate_gb is not None and source_gb != candidate_gb:
                continue

            score = difflib.SequenceMatcher(None, normalized_source, self._normalize_name(candidate_name)).ratio()
            if score > best_score:
                best_score = score
                best_name = candidate_name

        if best_name and best_score >= 0.72:
            return best_name
        return None

    def _get_name_candidates(self):
        if self.table_name in self._name_cache:
            return self._name_cache[self.table_name]

        if self.engine is None or not self.table_name:
            return []

        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    f"""
                    SELECT name, COUNT(*) AS sample_count
                    FROM {self.table_name}
                    WHERE name IS NOT NULL AND TRIM(name) != ''
                    GROUP BY name
                    ORDER BY sample_count DESC
                    """
                )
            ).fetchall()

        candidates = [(str(row[0]).strip(), int(row[1] or 0)) for row in rows if row and row[0]]
        self._name_cache[self.table_name] = candidates
        return candidates

    def _normalize_name(self, value):
        text_value = str(value or "").lower()
        return re.sub(r"[^a-z0-9]", "", text_value)

    def _extract_gb(self, value):
        match = re.search(r"(\d+(?:\.\d+)?)\s*gb", str(value or ""), re.IGNORECASE)
        if not match:
            return None
        try:
            return float(match.group(1))
        except (TypeError, ValueError):
            return None
