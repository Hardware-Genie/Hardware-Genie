"""Wayback Machine spider for Newegg part history plus category-specific specs."""

import json
import os
import re
from datetime import datetime
from urllib.parse import urlencode, urlparse

import scrapy
from sqlalchemy import create_engine, text


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

CATEGORY_FIELDS = {
    "cpu": ["name", "price", "core_count", "core_clock", "boost_clock", "tdp", "graphics", "smt", "snapshot_date", "microarchitecture"],
    "memory": ["name", "price", "speed", "modules", "price_per_gb", "color", "first_word_latency", "cas_latency", "snapshot_date"],
    "video-card": ["name", "price", "chipset", "memory", "core_clock", "boost_clock", "color", "length", "snapshot_date"],
    "motherboard": ["name", "price", "socket", "form_factor", "max_memory", "memory_slots", "color", "snapshot_date"],
    "power-supply": ["name", "price", "type", "efficiency", "wattage", "modular", "color", "snapshot_date"],
    "internal-hard-drive": ["name", "price", "capacity", "price_per_gb", "type", "cache", "form_factor", "interface", "snapshot_date"],
}

CATEGORY_TABLES = {
    "cpu": "cpu",
    "memory": "memory",
    "video-card": "video_card",
    "motherboard": "motherboard",
    "power-supply": "power_supply",
    "internal-hard-drive": "internal_hard_drive",
}


def _clean_text(value):
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", str(value)).strip()
    return cleaned or None


def _slug_to_name(product_url):
    parsed = urlparse(product_url or "")
    path_parts = [p for p in parsed.path.split("/") if p]
    if "p" in path_parts:
        p_index = path_parts.index("p")
        if p_index > 0:
            slug = path_parts[p_index - 1]
        elif len(path_parts) >= 2:
            slug = path_parts[-2]
        else:
            slug = path_parts[-1] if path_parts else ""
    elif len(path_parts) >= 2:
        slug = path_parts[-2]
    elif path_parts:
        slug = path_parts[-1]
    else:
        return "Unknown Product"

    slug = re.sub(r"-p$", "", slug, flags=re.IGNORECASE)
    slug = re.sub(r"[-_]+", " ", slug).strip()
    return _shorten_name_from_slug(slug)


def _shorten_name_from_slug(slug_text):
    if not slug_text:
        return "Unknown Product"

    tokens = [t for t in re.split(r"\s+", str(slug_text).strip()) if t]
    if not tokens:
        return "Unknown Product"

    stop_exact = {
        'desktop', 'laptop', 'notebook', 'memory', 'ram', 'black', 'white',
        'silver', 'red', 'blue', 'gray', 'grey', 'gold', 'kit', 'module', 'gaming'
    }

    shortened = []
    for token in tokens:
        lower = token.lower()
        if re.match(r'^ddr\d+$', lower):
            break
        if re.match(r'^cl\d+$', lower):
            break
        if lower in {'cas', 'latency'}:
            break
        if lower in stop_exact and len(shortened) >= 3:
            break
        shortened.append(token)

    if not shortened:
        shortened = tokens[:7]

    return ' '.join(shortened).title()


def _resolve_database_uri():
    db_uri = os.getenv("DATABASE_URL", "").strip()
    if not db_uri:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.abspath(os.path.join(current_dir, "..", "..", "..", "..", ".."))
        db_path = os.path.abspath(os.path.join(project_root, "instance", "parts.db")).replace("\\", "/")
        db_uri = f"sqlite:///{db_path}"
    elif db_uri.startswith("sqlite:///"):
        sqlite_path = db_uri[len("sqlite:///"):]
        if sqlite_path and sqlite_path != ':memory:' and not os.path.isabs(sqlite_path):
            current_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.abspath(os.path.join(current_dir, "..", "..", "..", "..", ".."))
            if sqlite_path in ('parts.db', './parts.db'):
                sqlite_path = os.path.join(project_root, 'instance', 'parts.db')
            else:
                sqlite_path = os.path.join(project_root, sqlite_path)
            normalized_sqlite_path = os.path.abspath(sqlite_path).replace('\\', '/')
            db_uri = f"sqlite:///{normalized_sqlite_path}"
    if db_uri.startswith("postgres://"):
        db_uri = db_uri.replace("postgres://", "postgresql://", 1)
    return db_uri


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
            "wayback_newegg_scrapy.pipelines.AppDatabasePipeline": 300,
        },

        # Log only warnings and above to keep output readable
        "LOG_LEVEL": "WARNING",
    }

    def __init__(self, product_name=None, product_url=None, category=None, *args, **kwargs):
        """
        Can be used normally (iterates PRODUCTS list) or with CLI args:
        -a product_name="RTX 4090" -a product_url="https://..."
        """
        super().__init__(*args, **kwargs)

        normalized_category = self._normalize_category(category)

        if product_url:
            derived_name = _slug_to_name(product_url)
            effective_name = _clean_text(product_name) or derived_name
            effective_category = normalized_category or self._determine_category(effective_name)
            self.products = [{"name": effective_name, "url": product_url, "category": effective_category}]
            self.category = effective_category
        else:
            self.products = []
            for product in PRODUCTS:
                url = product.get("url")
                default_name = _slug_to_name(url)
                name = _clean_text(product.get("name")) or default_name
                prod_category = normalized_category or self._determine_category(name)
                self.products.append({"name": name, "url": url, "category": prod_category})
            self.category = normalized_category or "other"

        self.db_engine = create_engine(_resolve_database_uri())

    def closed(self, reason):
        if getattr(self, "db_engine", None):
            self.db_engine.dispose()

    def _normalize_category(self, category):
        if not category:
            return None
        normalized = str(category).strip().lower().replace("_", "-")
        valid = set(CATEGORY_FIELDS.keys())
        return normalized if normalized in valid else None

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
            if not product.get("url"):
                continue

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
                    "category": product.get("category") or self.category,
                },
                # Don't cache CDX responses — always get fresh snapshot list
                dont_filter=True,
            )

    async def start(self):
        for request in self.start_requests():
            yield request

    def parse_cdx(self, response):
        """
        Parse the CDX API JSON response and yield a request
        for each archived snapshot.
        """
        product_name = response.meta["product_name"]
        product_url  = response.meta["product_url"]
        category = response.meta.get("category") or self.category

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
        existing_dates = self._get_existing_snapshot_dates(category, product_name)
        self.logger.info(f"{product_name}: {len(snapshots)} snapshots found")
        print(f"\n[{product_name}] Found {len(snapshots)} snapshots — fetching prices...")

        for i, row in enumerate(snapshots):
            timestamp   = row[0]
            archive_url = f"https://web.archive.org/web/{timestamp}id_/{product_url}"

            try:
                snapshot_date = datetime.strptime(timestamp[:8], "%Y%m%d").strftime("%Y-%m-%d")
            except ValueError:
                snapshot_date = timestamp[:8]

            if snapshot_date in existing_dates:
                print(f"  [{i+1}/{len(snapshots)}] Skipping {snapshot_date} (already in DB)")
                continue

            print(f"  [{i+1}/{len(snapshots)}] Queuing {snapshot_date}...")

            yield scrapy.Request(
                url=archive_url,
                callback=self.parse_snapshot,
                meta={
                    "product_name":  product_name,
                    "product_url":   product_url,
                    "category":      category,
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
        category      = response.meta.get("category") or self.category
        snapshot_date = response.meta["snapshot_date"]
        timestamp     = response.meta["timestamp"]
        archive_url   = response.meta["archive_url"]

        resolved_name = product_name

        price = (
            self._parse_price_modern(response)
            or self._parse_price_legacy(response)
            or self._parse_price_regex(response.text)
        )

        if price:
            print(f"  [OK] {snapshot_date} -> ${price:.2f}")
            spec_values = self._extract_category_values(response, category, price)
            item = {
                "name":          resolved_name,
                "product_name":  resolved_name,
                "product_url":   product_url,
                "category":      category,
                "snapshot_date": snapshot_date,
                "price":         price,
                "timestamp":     timestamp,
                "archive_url":   archive_url,
            }
            item.update(spec_values)
            yield item
        else:
            print(f"  [MISS] {snapshot_date} -> price not found")

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

    def _get_existing_snapshot_dates(self, category, product_name):
        table_name = CATEGORY_TABLES.get(category)
        if not table_name or not getattr(self, "db_engine", None):
            return set()

        try:
            with self.db_engine.connect() as conn:
                rows = conn.execute(
                    text(f"SELECT snapshot_date FROM {table_name} WHERE name = :name"),
                    {"name": product_name},
                ).fetchall()
            return {str(row[0]) for row in rows if row and row[0] is not None}
        except Exception as exc:
            self.logger.warning("Could not read existing snapshots for %s/%s: %s", table_name, product_name, exc)
            return set()

    def _extract_product_name(self, response):
        selectors = [
            "meta[property='og:title']::attr(content)",
            "meta[name='twitter:title']::attr(content)",
            "h1.product-title::text",
            "h1::text",
            "title::text",
        ]
        for selector in selectors:
            candidate = _clean_text(response.css(selector).get())
            if not candidate:
                continue
            candidate = re.sub(r"\s*[\-|]\s*Newegg.*$", "", candidate, flags=re.IGNORECASE).strip()
            candidate = re.sub(r"\s*\|\s*Buy.*$", "", candidate, flags=re.IGNORECASE).strip()
            if candidate:
                return candidate
        return None

    def _extract_spec_map(self, response):
        specs = {}

        for row in response.css("table tr"):
            key_parts = row.css("th::text, th *::text").getall()
            value_parts = row.css("td::text, td *::text").getall()
            key = _clean_text(" ".join(key_parts))
            value = _clean_text(" ".join(value_parts))
            if key and value:
                specs[self._normalize_spec_key(key)] = value

        for container in response.css("dl"):
            keys = container.css("dt")
            for dt in keys:
                key = _clean_text(" ".join(dt.css("::text").getall()))
                dd = dt.xpath("following-sibling::dd[1]")
                value = _clean_text(" ".join(dd.css("::text").getall()))
                if key and value:
                    specs[self._normalize_spec_key(key)] = value

        for node in response.css("li, p, span"):
            text = _clean_text(" ".join(node.css("::text").getall()))
            if not text or ":" not in text or len(text) > 160:
                continue
            key, value = text.split(":", 1)
            key = _clean_text(key)
            value = _clean_text(value)
            if key and value and len(key) < 50:
                specs[self._normalize_spec_key(key)] = value

        return specs

    def _normalize_spec_key(self, key):
        normalized = re.sub(r"[^a-z0-9]+", " ", str(key).lower()).strip()
        return re.sub(r"\s+", " ", normalized)

    def _get_spec(self, specs, candidates):
        for candidate in candidates:
            normalized = self._normalize_spec_key(candidate)
            if normalized in specs:
                return specs[normalized]

        for key, value in specs.items():
            for candidate in candidates:
                normalized = self._normalize_spec_key(candidate)
                if normalized in key:
                    return value
        return None

    def _extract_category_values(self, response, category, price):
        specs = self._extract_spec_map(response)
        if category == "cpu":
            return self._extract_cpu_specs(specs)
        if category == "memory":
            return self._extract_memory_specs(specs, price)
        if category == "video-card":
            return self._extract_gpu_specs(specs)
        if category == "motherboard":
            return self._extract_motherboard_specs(specs)
        if category == "power-supply":
            return self._extract_psu_specs(specs)
        if category == "internal-hard-drive":
            return self._extract_storage_specs(specs, price)
        return {}

    def _extract_cpu_specs(self, specs):
        core_count = self._to_float(self._get_spec(specs, ["core count", "cores"]))
        core_clock = self._parse_clock(self._get_spec(specs, ["core clock", "base clock", "processor base frequency"]))
        boost_clock = self._parse_clock(self._get_spec(specs, ["boost clock", "max boost clock", "max turbo frequency", "turbo boost"]))
        tdp = self._to_float(self._get_spec(specs, ["tdp", "thermal design power", "default tdp"]))
        graphics = self._compact_token(self._get_spec(specs, ["integrated graphics", "graphics", "graphics model"]))
        smt = self._parse_bool(self._get_spec(specs, ["smt", "hyper threading", "multithreading"]))
        microarchitecture = _clean_text(self._get_spec(specs, ["microarchitecture", "architecture", "codename"]))

        return {
            "core_count": core_count,
            "core_clock": core_clock,
            "boost_clock": boost_clock,
            "tdp": tdp,
            "graphics": graphics,
            "smt": smt,
            "microarchitecture": microarchitecture,
        }

    def _extract_memory_specs(self, specs, price):
        speed_raw = self._get_spec(specs, ["speed", "memory speed", "data rate"])
        modules_raw = self._get_spec(specs, ["modules", "kit", "capacity", "total capacity"])
        color = _clean_text(self._get_spec(specs, ["color", "colour"]))
        cas_latency = self._to_float(self._get_spec(specs, ["cas latency", "cl"]))
        first_word_latency = self._to_float(self._get_spec(specs, ["first word latency"]))

        speed = self._format_memory_speed(speed_raw)
        modules, total_gb = self._format_memory_modules(modules_raw)
        price_per_gb = round(price / total_gb, 3) if price and total_gb else None

        if first_word_latency is None and cas_latency and speed:
            ddr_mhz = self._to_float(speed.split(",", 1)[1]) if "," in speed else None
            if ddr_mhz:
                first_word_latency = round((cas_latency * 2000.0) / ddr_mhz, 3)

        return {
            "speed": speed,
            "modules": modules,
            "price_per_gb": price_per_gb,
            "color": color,
            "first_word_latency": first_word_latency,
            "cas_latency": cas_latency,
        }

    def _extract_gpu_specs(self, specs):
        chipset = self._compact_token(self._get_spec(specs, ["chipset", "gpu", "graphics processor"]))
        memory = self._parse_capacity_value(self._get_spec(specs, ["memory", "video memory", "vram"]))
        core_clock = self._parse_clock(self._get_spec(specs, ["core clock", "base clock", "gpu clock"]))
        boost_clock = self._parse_clock(self._get_spec(specs, ["boost clock", "boost", "max boost"]))
        color = _clean_text(self._get_spec(specs, ["color", "colour"]))
        length = self._parse_length_mm(self._get_spec(specs, ["length", "card length"]))

        return {
            "chipset": chipset,
            "memory": memory,
            "core_clock": core_clock,
            "boost_clock": boost_clock,
            "color": color,
            "length": length,
        }

    def _extract_motherboard_specs(self, specs):
        socket = _clean_text(self._get_spec(specs, ["socket", "cpu socket"]))
        form_factor = _clean_text(self._get_spec(specs, ["form factor", "board form factor"]))
        max_memory = self._parse_capacity_value(self._get_spec(specs, ["max memory", "maximum memory"]))
        memory_slots = self._to_float(self._get_spec(specs, ["memory slots", "dimm slots", "slots"]))
        color = _clean_text(self._get_spec(specs, ["color", "colour"]))

        return {
            "socket": socket,
            "form_factor": form_factor,
            "max_memory": max_memory,
            "memory_slots": memory_slots,
            "color": color,
        }

    def _extract_psu_specs(self, specs):
        psu_type = _clean_text(self._get_spec(specs, ["type", "form factor"]))
        efficiency = self._parse_efficiency(self._get_spec(specs, ["efficiency", "80 plus"]))
        wattage = self._to_float(self._get_spec(specs, ["wattage", "max power", "continuous power"]))
        modular = self._parse_modular(self._get_spec(specs, ["modular", "modularity", "cable type"]))
        color = _clean_text(self._get_spec(specs, ["color", "colour"]))

        return {
            "type": psu_type,
            "efficiency": efficiency,
            "wattage": wattage,
            "modular": modular,
            "color": color,
        }

    def _extract_storage_specs(self, specs, price):
        capacity = self._parse_capacity_value(self._get_spec(specs, ["capacity", "storage capacity"]))
        drive_type = self._parse_storage_type(self._get_spec(specs, ["type", "rpm", "drive type"]))
        cache = self._parse_cache(self._get_spec(specs, ["cache", "cache memory"]))
        form_factor = _clean_text(self._get_spec(specs, ["form factor"]))
        interface = self._compact_interface(self._get_spec(specs, ["interface", "bus interface"]))
        price_per_gb = round(price / capacity, 3) if price and capacity else None

        return {
            "capacity": capacity,
            "price_per_gb": price_per_gb,
            "type": drive_type,
            "cache": cache,
            "form_factor": form_factor,
            "interface": interface,
        }

    def _parse_clock(self, value):
        text = _clean_text(value)
        if not text:
            return None
        number = self._to_float(text)
        if number is None:
            return None
        return number

    def _parse_length_mm(self, value):
        text = _clean_text(value)
        if not text:
            return None
        number = self._to_float(text)
        if number is None:
            return None
        if "cm" in text.lower():
            return round(number * 10.0, 3)
        if "in" in text.lower() and "mm" not in text.lower():
            return round(number * 25.4, 3)
        return number

    def _parse_capacity_value(self, value):
        text = _clean_text(value)
        if not text:
            return None
        number = self._to_float(text)
        if number is None:
            return None
        lowered = text.lower()
        if "tb" in lowered:
            return round(number * 1000.0, 3)
        if "mb" in lowered:
            return round(number / 1000.0, 3)
        return number

    def _format_memory_speed(self, value):
        text = _clean_text(value)
        if not text:
            return None
        ddr_match = re.search(r"ddr\s*([0-9]+)", text, re.IGNORECASE)
        mhz_match = re.search(r"([0-9]{3,5})\s*(?:mhz|mt/s)?", text, re.IGNORECASE)
        if not ddr_match or not mhz_match:
            return None
        return f"{int(ddr_match.group(1))},{int(mhz_match.group(1))}"

    def _format_memory_modules(self, value):
        text = _clean_text(value)
        if not text:
            return None, None

        pair = re.search(r"([0-9]+)\s*[xX]\s*([0-9]+(?:\.[0-9]+)?)\s*(TB|GB)?", text, re.IGNORECASE)
        if pair:
            count = float(pair.group(1))
            size = float(pair.group(2))
            unit = (pair.group(3) or "GB").upper()
        else:
            numbers = [float(x) for x in re.findall(r"[0-9]+(?:\.[0-9]+)?", text)]
            if len(numbers) >= 2:
                count = numbers[0]
                size = numbers[1]
                unit = "TB" if "tb" in text.lower() else "GB"
            elif len(numbers) == 1:
                count = 1.0
                size = numbers[0]
                unit = "TB" if "tb" in text.lower() else "GB"
            else:
                return None, None

        size_gb = size * 1024.0 if unit == "TB" else size
        total_gb = count * size_gb
        return f"{int(count)},{int(size_gb) if size_gb.is_integer() else round(size_gb, 3)}", total_gb

    def _parse_bool(self, value):
        text = _clean_text(value)
        if not text:
            return None
        lowered = text.lower()
        if any(token in lowered for token in ["yes", "true", "supported", "enabled"]):
            return True
        if any(token in lowered for token in ["no", "false", "not supported", "disabled"]):
            return False
        return None

    def _parse_efficiency(self, value):
        text = _clean_text(value)
        if not text:
            return None
        match = re.search(r"(titanium|platinum|gold|silver|bronze)", text, re.IGNORECASE)
        if match:
            return match.group(1).lower()
        return text.lower()

    def _parse_modular(self, value):
        text = _clean_text(value)
        if not text:
            return None
        lowered = text.lower()
        if "full" in lowered:
            return "Full"
        if "semi" in lowered:
            return "Semi"
        if any(token in lowered for token in ["non", "fixed", "no", "false"]):
            return "False"
        return None

    def _parse_storage_type(self, value):
        text = _clean_text(value)
        if not text:
            return None
        lowered = text.lower()
        if "ssd" in lowered:
            return "SSD"
        rpm_match = re.search(r"([0-9]{4,5})", lowered)
        if rpm_match:
            return rpm_match.group(1)
        if "hdd" in lowered:
            return "HDD"
        return text

    def _parse_cache(self, value):
        text = _clean_text(value)
        if not text:
            return None
        number = self._to_float(text)
        if number is None:
            return None
        lowered = text.lower()
        if "gb" in lowered:
            return round(number * 1024.0, 3)
        return number

    def _compact_interface(self, value):
        text = _clean_text(value)
        if not text:
            return None
        return re.sub(r"\s+", "", text)

    def _compact_token(self, value):
        text = _clean_text(value)
        if not text:
            return None
        return re.sub(r"[^A-Za-z0-9.+]", "", text)

    def _to_float(self, text):
        """Strip non-numeric chars and convert to float."""
        try:
            cleaned = re.sub(r"[^\d.]", "", str(text))
            if cleaned:
                return float(cleaned)
        except (ValueError, TypeError):
            pass
        return None

    def handle_error(self, failure):
        """Log failed snapshot requests without crashing the spider."""
        meta = failure.request.meta
        print(f"  [ERR] {meta.get('snapshot_date', '?')} -> request failed: {failure.value}")
