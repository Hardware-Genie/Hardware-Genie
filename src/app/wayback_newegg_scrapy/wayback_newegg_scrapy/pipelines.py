"""
pipelines.py
============
Three pipelines that run for every scraped item:
    - CatalogDatabasePipeline → writes rows into the app's category tables
    - SQLitePipeline          → saves to newegg_price_history.db (queryable)
    - CSVPipeline             → saves to newegg_price_history.csv (for Excel/pandas)
"""

import csv
import os
import sqlite3

from sqlalchemy import create_engine, inspect, text


def _get_data_dir():
    """
    Determine the data directory path.
    From pipelines.py location:
      wayback_newegg_scrapy/wayback_newegg_scrapy/pipelines.py
      → go up 5 levels to project root
      → then static/data/
    """
    # Get the directory where this file is
    current_dir = os.path.dirname(os.path.abspath(__file__))
    # Go up to find the project root
    project_root = os.path.abspath(os.path.join(current_dir, "..", "..", "..", ".."))
    data_dir = os.path.join(project_root, "static", "data", "newegg_price_history_files")
    
    # Ensure the directory exists
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


def _get_project_root():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(current_dir, "..", "..", "..", ".."))


def _get_database_url():
    env_url = os.getenv("DATABASE_URL")
    if env_url:
        return env_url

    instance_db = os.path.join(_get_project_root(), "instance", "parts.db")
    return f"sqlite:///{instance_db.replace(os.sep, '/')}"


def _table_name_from_category(category):
    if not category:
        return None
    normalized = str(category).strip().lower().replace("-", "_")
    if normalized in {"power_supply", "internal_hard_drive", "video_card", "motherboard", "cpu", "memory"}:
        return normalized
    return None


class CatalogDatabasePipeline:
    """Upsert scraper rows into the main app database tables."""

    def open_spider(self, spider):
        self.engine = create_engine(_get_database_url(), future=True)
        self.table_name = getattr(spider, "table_name", None) or _table_name_from_category(getattr(spider, "category", None))
        self.inserted_rows = 0
        self.updated_rows = 0
        self.skipped_rows = 0

        if not self.table_name:
            spider.logger.warning("CatalogDatabasePipeline disabled: unknown table for category %s", getattr(spider, "category", None))
            self.columns = set()
            return

        inspector = inspect(self.engine)
        if not inspector.has_table(self.table_name):
            spider.logger.warning("CatalogDatabasePipeline disabled: table %s not found", self.table_name)
            self.columns = set()
            return

        self.columns = {column["name"] for column in inspector.get_columns(self.table_name)}

    def close_spider(self, spider):
        if self.table_name and self.columns:
            spider.logger.info(
                "Catalog DB sync complete for %s: %s inserted, %s updated, %s skipped",
                self.table_name,
                self.inserted_rows,
                self.updated_rows,
                self.skipped_rows,
            )

    def process_item(self, item, spider):
        if not self.table_name or not self.columns:
            return item

        name = item.get("name") or item.get("product_name")
        snapshot_date = item.get("snapshot_date")
        if not name or not snapshot_date:
            return item

        values = {}
        for column in self.columns:
            if column == "name":
                values[column] = name
            elif column == "snapshot_date":
                values[column] = snapshot_date
            elif column in item and item[column] is not None:
                values[column] = item[column]

        if not values:
            return item

        with self.engine.begin() as conn:
            existing = conn.execute(
                text(f"SELECT * FROM {self.table_name} WHERE name = :name AND snapshot_date = :snapshot_date LIMIT 1"),
                {"name": name, "snapshot_date": snapshot_date},
            ).mappings().first()

            if existing:
                updates = {
                    column: values[column]
                    for column in values
                    if column not in {"name", "snapshot_date"} and values[column] is not None and existing.get(column) in (None, "", "null")
                }
                if updates:
                    set_clause = ", ".join(f"{column} = :{column}" for column in updates)
                    conn.execute(
                        text(f"UPDATE {self.table_name} SET {set_clause} WHERE name = :name AND snapshot_date = :snapshot_date"),
                        {**updates, "name": name, "snapshot_date": snapshot_date},
                    )
                    self.updated_rows += 1
                else:
                    self.skipped_rows += 1
                return item

            columns_clause = ", ".join(values.keys())
            placeholders = ", ".join(f":{column}" for column in values)
            conn.execute(
                text(f"INSERT INTO {self.table_name} ({columns_clause}) VALUES ({placeholders})"),
                values,
            )
            self.inserted_rows += 1

        return item


class SQLitePipeline:
    """
    Saves every price record to a local SQLite database.
    The UNIQUE constraint on (product_url, timestamp) prevents
    duplicate entries if you run the spider multiple times.
    """

    def __init__(self):
        self.data_dir = _get_data_dir()
        # Will be set in open_spider

    def open_spider(self, spider):
        self.category = getattr(spider, 'category', 'other')
        self.db_file = os.path.join(self.data_dir, f"{self.category}_price_history.db")
        self.spider = spider  # Store spider reference for stats access
        self.stats = getattr(spider, 'stats', None)  # Store stats reference
        
        self.conn   = sqlite3.connect(self.db_file)
        self.cursor = self.conn.cursor()
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS price_history (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                product_name  TEXT,
                product_url   TEXT,
                snapshot_date TEXT,
                price         REAL,
                timestamp     TEXT,
                archive_url   TEXT,
                UNIQUE(product_url, timestamp)
            )
        """)
        self.conn.commit()
        self.items_processed_this_run = 0  # Track items processed in this run
        self.rate_limit_errors = 0  # Track rate limiting errors
        spider.logger.info(f"SQLite database ready: {self.db_file}")

    def close_spider(self, spider):
        self._print_summary()
        self.conn.close()
        spider.logger.info(f"SQLite database closed: {self.db_file}")

    def process_item(self, item, spider):
        try:
            self.cursor.execute("""
                INSERT OR IGNORE INTO price_history
                    (product_name, product_url, snapshot_date, price, timestamp, archive_url)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                item["product_name"],
                item["product_url"],
                item["snapshot_date"],
                item["price"],
                item["timestamp"],
                item["archive_url"],
            ))
            self.conn.commit()
            self.items_processed_this_run += 1
        except sqlite3.Error as e:
            spider.logger.error(f"DB insert error: {e}")
        return item

    def _print_summary(self):
        """Print a price summary table when the spider finishes."""
        # Check for errors from spider stats
        retry_count = 0
        exception_count = 0
        if self.stats:
            retry_count = self.stats.get_value('retry/count', 0)
            exception_count = self.stats.get_value('downloader/exception_count', 0)
        
        if self.items_processed_this_run == 0:
            print("\n" + "=" * 65)
            if retry_count > 0 or exception_count > 0:
                print("  SCRAPING FAILED - CONNECTION ISSUES")
                print("=" * 65)
                print(f"  Connection errors encountered: {exception_count}")
                print(f"  Retry attempts: {retry_count}")
                print(f"  Wayback Machine API is unreachable or rate limited.")
                print(f"  Try again in a few minutes or check your internet connection.")
            else:
                print("  NO NEW DATA SCRAPED")
                print("=" * 65)
                print(f"  No new items were processed in this run.")
                print(f"  All data already exists in the database.")
            print("\n" + "=" * 65)
            return

        print("\n" + "=" * 65)
        print("  PRICE HISTORY SUMMARY")
        print("=" * 65)
        print(f"  Items processed this run: {self.items_processed_this_run}")

        rows = self.cursor.execute("""
            SELECT
                product_name,
                COUNT(*)             AS snapshots,
                MIN(snapshot_date)   AS earliest,
                MAX(snapshot_date)   AS latest,
                ROUND(MIN(price), 2) AS low,
                ROUND(MAX(price), 2) AS high,
                ROUND(AVG(price), 2) AS avg
            FROM price_history
            WHERE price IS NOT NULL
            GROUP BY product_name
            ORDER BY product_name
        """).fetchall()

        for name, snaps, earliest, latest, low, high, avg in rows:
            print(f"\n  {name}")
            print(f"    Snapshots  : {snaps}  ({earliest} → {latest})")
            print(f"    All-time low   : ${low}")
            print(f"    All-time high  : ${high}")
            print(f"    Average price  : ${avg}")

        print("\n" + "=" * 65)


class CSVPipeline:
    """
    Writes every price record to a CSV file.
    Sorted by product name then date at close.
    """

    def __init__(self):
        self.data_dir = _get_data_dir()

    def open_spider(self, spider):
        self.category = getattr(spider, 'category', 'other')
        self.csv_file = os.path.join(self.data_dir, f"{self.category}.csv")
        self.rows = []

    def close_spider(self, spider):
        if not self.rows:
            spider.logger.warning("No rows to write to CSV")
            return

        # Load existing data if file exists
        existing_rows = []
        if os.path.exists(self.csv_file):
            try:
                with open(self.csv_file, "r", newline="", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    existing_rows = list(reader)
            except (FileNotFoundError, csv.Error):
                existing_rows = []

        # Combine existing and new rows
        all_rows = existing_rows + self.rows

        # Remove duplicates based on (product_name, snapshot_date)
        seen = set()
        unique_rows = []
        for row in all_rows:
            key = (row["product_name"], row["snapshot_date"])
            if key not in seen:
                seen.add(key)
                unique_rows.append(row)

        # Sort by product then date
        unique_rows.sort(key=lambda r: (r["product_name"], r["snapshot_date"]))

        # Write back the unique rows
        with open(self.csv_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "product_name",
                "snapshot_date",
                "price",
                "product_url",
                "archive_url",
            ])
            writer.writeheader()
            writer.writerows(unique_rows)

        print(f"\n  ✓ CSV saved: {self.csv_file}  ({len(unique_rows)} total records, {len(self.rows)} new)")

    def process_item(self, item, spider):
        self.rows.append({
            "product_name":  item["product_name"],
            "snapshot_date": item["snapshot_date"],
            "price":         item["price"],
            "product_url":   item["product_url"],
            "archive_url":   item["archive_url"],
        })
        return item


class PCPPFormatPipeline:
    """
    Writes scraped data in the same format as the old PCpartpicker CSV files.
    Each category has specific columns that match the combined_*.csv structure.
    """

    def __init__(self):
        self.data_dir = _get_data_dir()
        # Define column mappings for each category to match old PCpartpicker format
        self.category_columns = {
            "cpu": ["name", "price", "core_count", "core_clock", "boost_clock", "tdp", "graphics", "smt", "snapshot_date", "microarchitecture"],
            "memory": ["name", "price", "speed", "modules", "price_per_gb", "color", "first_word_latency", "cas_latency", "snapshot_date"],
            "video_card": ["name", "price", "chipset", "memory", "core_clock", "boost_clock", "color", "length", "snapshot_date"],
            "motherboard": ["name", "price", "socket", "form_factor", "max_memory", "memory_slots", "color", "snapshot_date"],
            "power_supply": ["name", "price", "type", "efficiency", "wattage", "modular", "color", "snapshot_date"],
            "internal_hard_drive": ["name", "price", "capacity", "price_per_gb", "type", "cache", "form_factor", "interface", "snapshot_date"]
        }

    def open_spider(self, spider):
        self.category = getattr(spider, 'category', 'other')
        self.csv_file = os.path.join(self.data_dir, f"combined_{self.category}.csv")
        self.rows = []

    def close_spider(self, spider):
        if not self.rows:
            spider.logger.warning("No rows to write to PCPP format CSV")
            return

        # Load existing data if file exists
        existing_rows = []
        if os.path.exists(self.csv_file):
            try:
                with open(self.csv_file, "r", newline="", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    existing_rows = list(reader)
            except (FileNotFoundError, csv.Error):
                existing_rows = []

        # Combine existing and new rows
        all_rows = existing_rows + self.rows

        # Remove duplicates based on (name, snapshot_date)
        seen = set()
        unique_rows = []
        for row in all_rows:
            key = (row["name"], row["snapshot_date"])
            if key not in seen:
                seen.add(key)
                unique_rows.append(row)

        # Sort by product then date
        unique_rows.sort(key=lambda r: (r["name"], r["snapshot_date"]))

        # Write back the unique rows in PCPP format
        columns = self.category_columns.get(self.category, ["name", "price", "snapshot_date"])
        with open(self.csv_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            writer.writerows(unique_rows)

        print(f"\n  ✓ PCPP format CSV saved: {self.csv_file}  ({len(unique_rows)} total records, {len(self.rows)} new)")

    def process_item(self, item, spider):
        # Get the column mapping for this category
        columns = self.category_columns.get(self.category, ["name", "price", "snapshot_date"])
        
        # Create row dict with only the columns that exist in the old format
        row = {}
        
        # Map fields to old PCpartpicker format
        for col in columns:
            if col == "name":
                row[col] = item.get("name") or item.get("product_name", "")
            elif col == "price":
                row[col] = item.get("price", "")
            elif col == "snapshot_date":
                row[col] = item.get("snapshot_date", "")
            elif col == "core_count":
                row[col] = item.get("core_count", "")
            elif col == "core_clock":
                row[col] = item.get("core_clock", "")
            elif col == "boost_clock":
                row[col] = item.get("boost_clock", "")
            elif col == "tdp":
                row[col] = item.get("tdp", "")
            elif col == "graphics":
                row[col] = item.get("graphics", "")
            elif col == "smt":
                # Convert boolean to string like old format
                smt_value = item.get("smt")
                if smt_value is True:
                    row[col] = "True"
                elif smt_value is False:
                    row[col] = "False"
                else:
                    row[col] = ""
            elif col == "microarchitecture":
                row[col] = item.get("microarchitecture", "")
            elif col == "speed":
                row[col] = item.get("speed", "")
            elif col == "modules":
                row[col] = item.get("modules", "")
            elif col == "price_per_gb":
                row[col] = item.get("price_per_gb", "")
            elif col == "color":
                row[col] = item.get("color", "")
            elif col == "first_word_latency":
                row[col] = item.get("first_word_latency", "")
            elif col == "cas_latency":
                row[col] = item.get("cas_latency", "")
            elif col == "chipset":
                row[col] = item.get("chipset", "")
            elif col == "memory":
                row[col] = item.get("memory", "")
            elif col == "gpu_clock":
                # Map core_clock to gpu_clock for video cards
                row[col] = item.get("core_clock", "")
            elif col == "length":
                row[col] = item.get("length", "")
            elif col == "socket":
                row[col] = item.get("socket", "")
            elif col == "form_factor":
                row[col] = item.get("form_factor", "")
            elif col == "max_memory":
                row[col] = item.get("max_memory", "")
            elif col == "memory_slots":
                row[col] = item.get("memory_slots", "")
            elif col == "type":
                row[col] = item.get("type", "")
            elif col == "efficiency":
                row[col] = item.get("efficiency", "")
            elif col == "wattage":
                row[col] = item.get("wattage", "")
            elif col == "modular":
                # Convert boolean/string to match old format
                modular_value = item.get("modular")
                if modular_value in [True, "full"]:
                    row[col] = "Full"
                elif modular_value in [False, "non"]:
                    row[col] = "False"
                elif modular_value == "semi":
                    row[col] = "Semi"
                else:
                    row[col] = ""
            elif col == "capacity":
                row[col] = item.get("capacity", "")
            elif col == "cache":
                row[col] = item.get("cache", "")
            elif col == "interface":
                row[col] = item.get("interface", "")
            else:
                row[col] = ""

        self.rows.append(row)
        return item
