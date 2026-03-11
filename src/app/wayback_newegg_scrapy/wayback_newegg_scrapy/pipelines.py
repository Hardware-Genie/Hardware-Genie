"""
pipelines.py
============
Two pipelines that run for every scraped item:
  - SQLitePipeline  → saves to newegg_price_history.db (queryable)
  - CSVPipeline     → saves to newegg_price_history.csv (for Excel/pandas)
"""

import sqlite3
import csv
import os


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
        except sqlite3.Error as e:
            spider.logger.error(f"DB insert error: {e}")
        return item

    def _print_summary(self):
        """Print a price summary table when the spider finishes."""
        print("\n" + "=" * 65)
        print("  PRICE HISTORY SUMMARY")
        print("=" * 65)

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
