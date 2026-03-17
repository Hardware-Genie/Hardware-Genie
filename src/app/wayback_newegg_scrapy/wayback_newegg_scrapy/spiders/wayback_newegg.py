"""
Wayback Machine Newegg Price History Spider
============================================
A Scrapy spider that:
  1. Queries the Wayback CDX API for archived snapshots of Newegg product pages
  2. Follows each snapshot URL and parses the price from archived HTML
  3. Saves results to SQLite + CSV via pipelines

Run with:
    scrapy crawl wayback_newegg

Or target a specific product via CLI arg:
    scrapy crawl wayback_newegg -a product_name="RTX 4090" -a product_url="https://www.newegg.com/..."
"""

import scrapy
import json
import re
from datetime import datetime
from urllib.parse import urlencode


# ============================================================
# CONFIGURE YOUR PRODUCTS HERE
# ============================================================
PRODUCTS = [
    {
        "name": "RTX 3080 EVGA FTW3",
        "url": "https://www.newegg.com/evga-geforce-rtx-3080-10g-p5-3897-kr/p/N82E16814487518",
        
    },
    {
        "name": "ASRock Challenger RX 9070 XT CL 16G",
        "url": "https://www.newegg.com/asrock-challenger-rx9070xt-cl-16g-radeon-rx-9070-xt-16gb-graphics-card-triple-fans/p/N82E16814930145",

    }
    # {
    #     "name": "Intel Core i9-13900K",
    #     "url":  "https://www.newegg.com/intel-core-i9-13900k/p/N82E16819118412",
    # },
    # Add more here:
    # {"name": "Your Product", "url": "https://www.newegg.com/..."},
]

FROM_DATE            = "20200101"   # YYYYMMDD — how far back to look
TO_DATE              = None         # None = up to today
MAX_SNAPSHOTS        = 50           # per product; None = all available
CDX_API              = "http://web.archive.org/cdx/search/cdx"


class WaybackNeweggSpider(scrapy.Spider):
    name = "wayback_newegg"

    custom_settings = {
        # Be polite — Wayback Machine rate limits aggressive scrapers
        "DOWNLOAD_DELAY":              2,
        "RANDOMIZE_DOWNLOAD_DELAY":    True,
        "CONCURRENT_REQUESTS":         1,       # one at a time — Wayback doesn't like bursts
        "RETRY_TIMES":                 3,
        "RETRY_HTTP_CODES":            [429, 500, 502, 503, 504],
        "USER_AGENT":                  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",

        # Pipelines — both run for every item
        "ITEM_PIPELINES": {
            "wayback_newegg_scrapy.pipelines.SQLitePipeline": 300,
            "wayback_newegg_scrapy.pipelines.CSVPipeline":    400,
        },

        # Log only warnings and above to keep output readable
        "LOG_LEVEL": "WARNING",
    }

    def __init__(self, product_name=None, product_url=None, *args, **kwargs):
        """
        Can be used normally (iterates PRODUCTS list) or with CLI args:
        -a product_name="RTX 4090" -a product_url="https://..."
        """
        super().__init__(*args, **kwargs)

        if product_name and product_url:
            self.products = [{"name": product_name, "url": product_url}]
            self.category = self._determine_category(product_name)
        else:
            self.products = PRODUCTS
            # For multiple products, use a default or determine per product
            self.category = "other"

    def _determine_category(self, product_name):
        """Determine product category from name."""
        name = product_name.lower()
        
        if any(x in name for x in ['rtx', 'gtx', 'radeon', 'graphics card', 'gpu', 'video card']):
            return 'video-card'
        elif any(x in name for x in ['core i', 'ryzen', 'cpu', 'processor']):
            return 'cpu'
        elif any(x in name for x in ['ram', 'ddr', 'memory']):
            return 'memory'
        elif any(x in name for x in ['hdd', 'ssd', 'storage', 'drive', 'internal hard drive']):
            return 'internal-hard-drive'
        elif 'motherboard' in name:
            return 'motherboard'
        elif any(x in name for x in ['power supply', 'psu']):
            return 'power-supply'
        else:
            return 'other'

    def start_requests(self):
        """
        Entry point — fire off one CDX API request per product.
        """
        for product in self.products:
            params = {
                "url":      product["url"],
                "output":   "json",
                "fl":       "timestamp,statuscode",
                "filter":   "statuscode:200",
                "collapse": "timestamp:8",          # one snapshot per day
                "limit":    MAX_SNAPSHOTS or 500,
            }
            if FROM_DATE:
                params["from"] = FROM_DATE
            if TO_DATE:
                params["to"] = TO_DATE

            cdx_url = f"{CDX_API}?{urlencode(params)}"

            self.logger.info(f"Querying CDX for: {product['name']}")

            yield scrapy.Request(
                url=cdx_url,
                callback=self.parse_cdx,
                meta={
                    "product_name": product["name"],
                    "product_url":  product["url"],
                },
                # Don't cache CDX responses — always get fresh snapshot list
                dont_filter=True,
            )

    def parse_cdx(self, response):
        """
        Parse the CDX API JSON response and yield a request
        for each archived snapshot.
        """
        product_name = response.meta["product_name"]
        product_url  = response.meta["product_url"]

        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            self.logger.error(f"CDX parse failed for {product_name}")
            return

        if not data or len(data) <= 1:
            self.logger.warning(f"No snapshots found for {product_name}")
            return

        # data[0] is the header ["timestamp", "statuscode"]
        # data[1:] are the actual snapshot records
        snapshots = data[1:]
        self.logger.info(f"{product_name}: {len(snapshots)} snapshots found")
        print(f"\n[{product_name}] Found {len(snapshots)} snapshots — fetching prices...")

        for i, row in enumerate(snapshots):
            timestamp   = row[0]
            archive_url = f"https://web.archive.org/web/{timestamp}id_/{product_url}"

            try:
                snapshot_date = datetime.strptime(timestamp[:8], "%Y%m%d").strftime("%Y-%m-%d")
            except ValueError:
                snapshot_date = timestamp[:8]

            print(f"  [{i+1}/{len(snapshots)}] Queuing {snapshot_date}...")

            yield scrapy.Request(
                url=archive_url,
                callback=self.parse_snapshot,
                meta={
                    "product_name":  product_name,
                    "product_url":   product_url,
                    "snapshot_date": snapshot_date,
                    "timestamp":     timestamp,
                    "archive_url":   archive_url,
                    # Don't let Scrapy's dupe filter skip identical URLs
                    "dont_filter":   True,
                },
                errback=self.handle_error,
            )

    def parse_snapshot(self, response):
        """
        Parse price from an archived Newegg product page.
        Tries multiple strategies since Newegg's HTML has changed over the years.
        """
        product_name  = response.meta["product_name"]
        product_url   = response.meta["product_url"]
        snapshot_date = response.meta["snapshot_date"]
        timestamp     = response.meta["timestamp"]
        archive_url   = response.meta["archive_url"]

        price = (
            self._parse_price_modern(response)
            or self._parse_price_legacy(response)
            or self._parse_price_regex(response.text)
        )

        if price:
            print(f"  ✓ {snapshot_date}  →  ${price:.2f}")
            yield {
                "product_name":  product_name,
                "product_url":   product_url,
                "snapshot_date": snapshot_date,
                "price":         price,
                "timestamp":     timestamp,
                "archive_url":   archive_url,
            }
        else:
            print(f"  ✗ {snapshot_date}  →  price not found")

    # ----------------------------------------------------------
    # Price parsing strategies (modern → legacy → regex fallback)
    # ----------------------------------------------------------

    def _parse_price_modern(self, response):
        """
        Modern Newegg pages (2020+):
        Price is split across <strong>599</strong><sup>.99</sup>
        """
        dollars = response.css(
            "li.price-current strong::text, "
            ".price-current-label strong::text"
        ).get()
        cents = response.css(
            "li.price-current sup::text, "
            ".price-current-label sup::text"
        ).get()

        if dollars and dollars.strip():
            price_str = dollars.strip()
            if cents and cents.strip():
                price_str += cents.strip()
            return self._to_float(price_str)

        return None

    def _parse_price_legacy(self, response):
        """
        Older Newegg pages (pre-2020):
        Price in .product-price or #pricing containers.
        """
        selectors = [
            ".product-price .price-current::text",
            "#pricing .price-current::text",
            ".product-buy-box .price-current::text",
            "span.price-current::text",
        ]
        for sel in selectors:
            text = response.css(sel).get()
            if text and text.strip():
                price = self._to_float(text.strip())
                if price:
                    return price

        return None

    def _parse_price_regex(self, html):
        """
        Last resort: regex scan the raw HTML for price patterns.
        Looks for things like "$599.99" near price-related keywords.
        """
        match = re.search(
            r'(?:price["\s:]+|"\$)(\d{2,4}(?:\.\d{2})?)',
            html,
            re.IGNORECASE,
        )
        if match:
            price = self._to_float(match.group(1))
            # Sanity check — PC parts range
            if price and 10 <= price <= 5000:
                return price

        return None

    def _to_float(self, text):
        """Strip non-numeric chars and convert to float."""
        try:
            cleaned = re.sub(r"[^\d.]", "", text)
            if cleaned:
                return float(cleaned)
        except (ValueError, TypeError):
            pass
        return None

    def handle_error(self, failure):
        """Log failed snapshot requests without crashing the spider."""
        meta = failure.request.meta
        print(f"  ✗ {meta.get('snapshot_date', '?')}  →  request failed: {failure.value}")
