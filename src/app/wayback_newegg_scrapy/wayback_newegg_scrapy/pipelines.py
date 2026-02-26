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


class SQLitePipeline:
    """
    Saves every price record to a local SQLite database.
    The UNIQUE constraint on (product_url, timestamp) prevents
    duplicate entries if you run the spider multiple times.
    """

    DB_FILE = "newegg_price_history.db"

    def open_spider(self, spider):
        self.conn   = sqlite3.connect(self.DB_FILE)
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
        spider.logger.info(f"SQLite database ready: {self.DB_FILE}")

    def close_spider(self, spider):
        self._print_summary()
        self.conn.close()
        spider.logger.info(f"SQLite database closed: {self.DB_FILE}")

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

    CSV_FILE = "newegg_price_history.csv"

    def open_spider(self, spider):
        self.rows = []

    def close_spider(self, spider):
        if not self.rows:
            spider.logger.warning("No rows to write to CSV")
            return

        # Sort by product then date for clean output
        self.rows.sort(key=lambda r: (r["product_name"], r["snapshot_date"]))

        with open(self.CSV_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "product_name",
                "snapshot_date",
                "price",
                "product_url",
                "archive_url",
            ])
            writer.writeheader()
            writer.writerows(self.rows)

        print(f"\n  ✓ CSV saved: {self.CSV_FILE}  ({len(self.rows)} records)")

    def process_item(self, item, spider):
        self.rows.append({
            "product_name":  item["product_name"],
            "snapshot_date": item["snapshot_date"],
            "price":         item["price"],
            "product_url":   item["product_url"],
            "archive_url":   item["archive_url"],
        })
        return item
