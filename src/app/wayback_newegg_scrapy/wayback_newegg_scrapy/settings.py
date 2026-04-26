"""
settings.py
===========
Scrapy project settings for the Wayback Machine Newegg scraper.
Most important settings are also set in custom_settings inside the spider
itself, so you can run the spider standalone without needing this file.
This file acts as the project-level defaults.
"""

BOT_NAME    = "wayback_newegg_scrapy"
SPIDER_MODULES   = ["wayback_newegg_scrapy.spiders"]
NEWSPIDER_MODULE = "wayback_newegg_scrapy.spiders"

# ---- Politeness ----
DOWNLOAD_DELAY           = 2        # seconds between requests
RANDOMIZE_DOWNLOAD_DELAY = True     # adds up to 50% variance
CONCURRENT_REQUESTS      = 1        # one at a time — Wayback rate limits bursts
ROBOTSTXT_OBEY           = False    # Wayback Machine doesn't have a useful robots.txt

# ---- Retries ----
RETRY_TIMES      = 3
RETRY_HTTP_CODES = [429, 500, 502, 503, 504]

# ---- Timeouts ----
DOWNLOAD_TIMEOUT = 30

# ---- Identity ----
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# ---- Pipelines ----
# Order matters: SQLite → CSV → Alerts (alerts run last, after data is saved)
ITEM_PIPELINES = {
    "wayback_newegg_scrapy.pipelines.CatalogDatabasePipeline": 200,
    "wayback_newegg_scrapy.pipelines.SQLitePipeline": 300,
    "wayback_newegg_scrapy.pipelines.CSVPipeline":    400,
    "wayback_newegg_scrapy.alerts.AlertPipeline":     500,
}

# ---- Logging ----
LOG_LEVEL = "WARNING"   # Change to "INFO" or "DEBUG" to see more detail

# ---- Disable unused middlewares for speed ----
COOKIES_ENABLED    = False
TELNETCONSOLE_ENABLED = False

# ---- Feed exports (optional — pipelines handle output by default) ----
# Uncomment below to ALSO get a raw JSON export:
# FEEDS = {
#     "newegg_raw.json": {"format": "json", "overwrite": True},
# }
