"""Functional Wayback Newegg spider.

This version accepts a single Newegg product URL, pulls the latest daily
Wayback snapshots for that URL, and writes category-specific rows that match
the existing application tables.
"""

from __future__ import annotations

import html
import json
import os
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode, urlparse

import scrapy

from sqlalchemy import create_engine, inspect, text


CDX_API = "https://web.archive.org/cdx/search/cdx"
FROM_DATE = "20200101"
TO_DATE = None
MAX_SNAPSHOTS = 50
RELAXED_MAX_SNAPSHOTS = 500


CATEGORY_CONFIG = {
	"cpu": {
		"table": "cpu",
		"keywords": ["cpu", "processor", "ryzen", "core i", "intel-core"],
	},
	"memory": {
		"table": "memory",
		"keywords": ["memory", "ram", "ddr", "desktop-memory"],
	},
	"video_card": {
		"table": "video_card",
		"keywords": ["graphics-card", "video-card", "gpu", "rtx", "gtx", "radeon"],
	},
	"motherboard": {
		"table": "motherboard",
		"keywords": ["motherboard"],
	},
	"power_supply": {
		"table": "power_supply",
		"keywords": ["power-supply", "psu", "power supply"],
	},
	"internal_hard_drive": {
		"table": "internal_hard_drive",
		"keywords": ["internal-hard-drive", "ssd", "hdd", "storage", "hard-drive"],
	},
}


def _project_root() -> Path:
	return Path(__file__).resolve().parents[5]


def _default_database_url() -> str:
	env_url = os.getenv("DATABASE_URL")
	if env_url:
		return env_url

	sqlite_path = _project_root() / "instance" / "parts.db"
	return f"sqlite:///{sqlite_path.as_posix()}"


def _normalize_whitespace(value: str | None) -> str | None:
	if value is None:
		return None
	cleaned = html.unescape(re.sub(r"\s+", " ", str(value))).strip()
	return cleaned or None


def _normalize_key(value: str | None) -> str:
	cleaned = _normalize_whitespace(value)
	if not cleaned:
		return ""
	return re.sub(r"[^a-z0-9]+", " ", cleaned.lower()).strip()


def _is_missing(value: object | None) -> bool:
	if value is None:
		return True
	text_value = str(value).strip().lower()
	return text_value in {"", "na", "n/a", "none", "null", "-", "unknown"}


def _parse_float(value: object | None) -> float | None:
	if _is_missing(value):
		return None
	match = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
	if not match:
		return None
	try:
		return float(match.group(0))
	except (TypeError, ValueError):
		return None


def _parse_int(value: object | None) -> int | None:
	parsed = _parse_float(value)
	if parsed is None:
		return None
	return int(round(parsed))


def _compact_token(value: str | None) -> str | None:
	cleaned = _normalize_whitespace(value)
	if not cleaned:
		return None
	return re.sub(r"[^A-Za-z0-9]+", "", cleaned)


def _compact_spaces(value: str | None) -> str | None:
	cleaned = _normalize_whitespace(value)
	if not cleaned:
		return None
	return re.sub(r"\s+", "", cleaned)


def _first_match(text_value: str | None, patterns: list[str]) -> str | None:
	if not text_value:
		return None

	for pattern in patterns:
		match = re.search(pattern, text_value, re.IGNORECASE | re.DOTALL)
		if match:
			return _normalize_whitespace(match.group(1))
	return None


class WaybackNeweggSpider(scrapy.Spider):
	name = "wayback_newegg_functional"

	custom_settings = {
		"DOWNLOAD_DELAY": 5,
		"RANDOMIZE_DOWNLOAD_DELAY": True,
		"CONCURRENT_REQUESTS": 1,
		"RETRY_TIMES": 5,
		"RETRY_HTTP_CODES": [429, 500, 502, 503, 504],
		"USER_AGENT": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
		"ITEM_PIPELINES": {
			"wayback_newegg_scrapy.pipelines.CatalogDatabasePipeline": 200,
			"wayback_newegg_scrapy.pipelines.SQLitePipeline": 300,
			"wayback_newegg_scrapy.pipelines.CSVPipeline": 400,
			"wayback_newegg_scrapy.pipelines.PCPPFormatPipeline": 450,
			"wayback_newegg_scrapy.alerts.AlertPipeline": 500,
		},
		"LOG_LEVEL": "WARNING",
	}

	def __init__(self, product_url=None, product_name=None, category=None, *args, **kwargs):
		super().__init__(*args, **kwargs)

		if not product_url:
			raise ValueError("product_url is required")

		self.product_url = product_url.strip()
		self.product_name_hint = product_name.strip() if product_name else None
		self.category = self._normalize_category(category) if category else self._detect_category_from_url(self.product_url)
		self.debug_extract = str(kwargs.get("debug_extract", "")).strip().lower() in {"1", "true", "yes", "on"}
		self.table_name = CATEGORY_CONFIG.get(self.category, {}).get("table")
		self.database_url = _default_database_url()
		self.engine = create_engine(self.database_url, future=True)
		self._existing_dates_cache: dict[str, set[str]] = {}
		self.max_snapshots = MAX_SNAPSHOTS
		self.relaxed_max_snapshots = RELAXED_MAX_SNAPSHOTS

	def _normalize_category(self, category: str | None) -> str:
		if not category:
			return "other"
		normalized = str(category).strip().lower().replace("-", "_")
		return normalized if normalized in CATEGORY_CONFIG else "other"

	def _detect_category_from_url(self, product_url: str) -> str:
		normalized_url = product_url.lower()
		for category, config in CATEGORY_CONFIG.items():
			if any(keyword in normalized_url for keyword in config["keywords"]):
				return category

		return "other"

	def _build_relaxed_lookup_url(self, product_url: str) -> str:
		parsed = urlparse(product_url)
		if not parsed.netloc:
			return product_url

		path = parsed.path or ""
		if parsed.query:
			path = f"{path}?{parsed.query}"
		return f"{parsed.netloc}{path}"

	def _build_cdx_url(self, product_url: str, relaxed: bool = False) -> str:
		params = {
			"url": self._build_relaxed_lookup_url(product_url) if relaxed else product_url,
			"output": "json",
			"fl": "timestamp,statuscode",
			"filter": "statuscode:200",
			"limit": self.relaxed_max_snapshots if relaxed else self.max_snapshots,
		}

		if relaxed:
			params["matchType"] = "prefix"
		else:
			params["collapse"] = "timestamp:8"
			if FROM_DATE:
				params["from"] = FROM_DATE
			if TO_DATE:
				params["to"] = TO_DATE
		return f"{CDX_API}?{urlencode(params)}"

	def start_requests(self):
		yield scrapy.Request(
			url=self._build_cdx_url(self.product_url, relaxed=False),
			callback=self.parse_cdx,
			meta={
				"product_url": self.product_url,
				"product_name": self.product_name_hint,
				"cdx_mode": "strict",
			},
			dont_filter=True,
		)

	def parse_cdx(self, response):
		product_url = response.meta["product_url"]
		product_name = response.meta.get("product_name")
		cdx_mode = response.meta.get("cdx_mode", "strict")

		if not product_url:
			self.logger.warning("Missing product_url in CDX response metadata")
			return

		try:
			data = json.loads(response.text)
		except json.JSONDecodeError:
			self.logger.error("CDX parse failed for %s", product_url)
			return

		if not data or len(data) <= 1:
			if cdx_mode == "strict":
				self.logger.warning("No strict CDX snapshots found for %s; retrying relaxed query", product_url)
				yield scrapy.Request(
					url=self._build_cdx_url(product_url, relaxed=True),
					callback=self.parse_cdx,
					meta={
						"product_url": product_url,
						"product_name": product_name,
						"cdx_mode": "relaxed",
					},
					dont_filter=True,
				)
				return

			self.logger.warning("No snapshots found for %s (mode=%s)", product_url, cdx_mode)
			return

		snapshots = [row for row in data[1:] if row]
		snapshots.sort(key=lambda row: row[0], reverse=True)
		latest_snapshot = snapshots[0]
		remaining_snapshots = snapshots[1:]

		yield self._build_snapshot_request(
			snapshot_row=latest_snapshot,
			product_url=product_url,
			product_name=product_name,
			remaining_snapshots=remaining_snapshots,
		)

	def _build_snapshot_request(self, snapshot_row, product_url, product_name, remaining_snapshots):
		timestamp = snapshot_row[0]
		archive_url = f"https://web.archive.org/web/{timestamp}id_/{product_url}"
		try:
			snapshot_date = datetime.strptime(timestamp[:8], "%Y%m%d").strftime("%Y-%m-%d")
		except ValueError:
			snapshot_date = timestamp[:8]

		return scrapy.Request(
			url=archive_url,
			callback=self.parse_snapshot,
			meta={
				"product_url": product_url,
				"product_name": product_name,
				"snapshot_date": snapshot_date,
				"timestamp": timestamp,
				"archive_url": archive_url,
				"remaining_snapshots": remaining_snapshots,
			},
			errback=self.handle_error,
			dont_filter=True,
		)

	def parse_snapshot(self, response):
		product_url = response.meta["product_url"]
		product_name = self._extract_product_name(response, response.meta.get("product_name"))
		snapshot_date = response.meta["snapshot_date"]
		timestamp = response.meta["timestamp"]
		archive_url = response.meta["archive_url"]
		raw_text = response.text
		spec_index = self._collect_spec_index(response)
		price = self._parse_price(response)
		category_fields = self._extract_category_fields(response, spec_index, raw_text, price)
		
		self._log_extracted_fields(product_name, snapshot_date, category_fields)

		existing_dates = self._get_existing_dates(product_name)

		if snapshot_date not in existing_dates:
			item = {
				"name": product_name,
				"product_name": product_name,
				"product_url": product_url,
				"snapshot_date": snapshot_date,
				"timestamp": timestamp,
				"archive_url": archive_url,
				"category": self.category,
				"price": price,
			}
			item.update(category_fields)
			yield item

		remaining_snapshots = response.meta.get("remaining_snapshots") or []
		seen_dates = set(existing_dates)
		seen_dates.add(snapshot_date)

		for snapshot_row in remaining_snapshots:
			timestamp = snapshot_row[0]
			try:
				current_snapshot_date = datetime.strptime(timestamp[:8], "%Y%m%d").strftime("%Y-%m-%d")
			except ValueError:
				current_snapshot_date = timestamp[:8]

			if current_snapshot_date in seen_dates:
				continue

			seen_dates.add(current_snapshot_date)
			yield self._build_snapshot_request(
				snapshot_row=snapshot_row,
				product_url=product_url,
				product_name=product_name,
				remaining_snapshots=[],
			)

	def _collect_spec_index(self, response) -> dict[str, list[str]]:
		pairs: list[tuple[str, str]] = []

		for row in response.xpath("//tr[th and td or td[2]]"):
			cells = [
				_normalize_whitespace(cell.xpath("string(.)").get())
				for cell in row.xpath("./th|./td")
			]
			cells = [cell for cell in cells if cell]
			if len(cells) >= 2:
				label = cells[0]
				value = " ".join(cells[1:])
				if label and value:
					pairs.append((label, value))

		for row in response.xpath("//dl[dt and dd]"):
			labels = [
				_normalize_whitespace(label.xpath("string(.)").get())
				for label in row.xpath("./dt")
			]
			values = [
				_normalize_whitespace(value.xpath("string(.)").get())
				for value in row.xpath("./dd")
			]
			labels = [label for label in labels if label]
			values = [value for value in values if value]
			for label, value in zip(labels, values, strict=False):
				pairs.append((label, value))

		index: dict[str, list[str]] = defaultdict(list)
		for label, value in pairs:
			normalized_label = _normalize_key(label)
			if normalized_label and value:
				index[normalized_label].append(value)

		return index

	def _lookup_spec(self, spec_index: dict[str, list[str]], aliases: list[str], raw_text: str | None = None, patterns: list[str] | None = None) -> str | None:
		for alias in aliases:
			normalized_alias = _normalize_key(alias)
			if not normalized_alias:
				continue

			for label, values in spec_index.items():
				if label == normalized_alias or normalized_alias in label or label in normalized_alias:
					for value in values:
						if not _is_missing(value):
							return _normalize_whitespace(value)

		if raw_text and patterns:
			return _first_match(raw_text, patterns)

		return None

	def _extract_product_name(self, response, product_name_hint: str | None = None) -> str:
		candidates = [
			product_name_hint,
			response.css("meta[property='og:title']::attr(content)").get(),
			response.css("meta[name='title']::attr(content)").get(),
			response.css("meta[property='twitter:title']::attr(content)").get(),
			response.css("h1::text").get(),
			response.css("title::text").get(),
		]

		for candidate in candidates:
			cleaned = self._clean_product_name(candidate)
			if cleaned:
				return cleaned

		return self._fallback_name_from_url(self.product_url)

	def _clean_product_name(self, value: str | None) -> str | None:
		cleaned = _normalize_whitespace(value)
		if not cleaned:
			return None

		# Remove Newegg suffixes
		cleaned = re.sub(r"\s*[|]\s*Newegg(?:\.com)?(?:\s*.*)?$", "", cleaned, flags=re.IGNORECASE)
		cleaned = re.sub(r"\s*-\s*Newegg(?:\.com)?(?:\s*.*)?$", "", cleaned, flags=re.IGNORECASE)
		
		# For memory products, extract core information: Brand Series Capacity
		# Pattern: "G.SKILL Ripjaws V Series 32GB (2 x 16GB) 288-Pin PC RAM DDR4 3200..."
		# To: "G.SKILL Ripjaws V 32 GB"
		if any(keyword in cleaned.lower() for keyword in ['ddr', 'memory', 'ram', 'pin']):
			# Extract brand, series, and capacity
			brand_match = re.match(r"^([A-Z][A-Z0-9\.\-_]+)", cleaned)
			if brand_match:
				brand = brand_match.group(1)
				
				# Look for series (usually after brand, before capacity)
				series_match = re.search(rf"{re.escape(brand)}\s+([A-Za-z0-9]+(?:\s+[A-Za-z0-9]+)*)\s+(?=\d+(?:\.\d+)?\s*(TB|GB|MB))", cleaned)
				series = series_match.group(1) if series_match else ""
				
				# Look for capacity (first occurrence)
				capacity_match = re.search(r"(\d+(?:\.\d+)?)\s*(TB|GB|MB)", cleaned, re.IGNORECASE)
				if capacity_match:
					capacity = f"{capacity_match.group(1)} {capacity_match.group(2).upper()}"
					
					# Build clean name
					parts = [brand]
					if series and series.lower() not in ['series', 'desktop', 'laptop']:
						parts.append(series)
					parts.append(capacity)
					
					cleaned = " ".join(parts)
		
		# Remove model numbers, technical specs, and parenthetical information
		cleaned = re.sub(r"\([^)]*\)", "", cleaned)  # Remove content in parentheses
		cleaned = re.sub(r"\b\d{3,}-\d{3,}\b", "", cleaned)  # Remove model numbers
		cleaned = re.sub(r"\bF\d+-[A-Z0-9]+\b", "", cleaned)  # Remove model codes
		cleaned = re.sub(r"\bPC\d+-\d+\b", "", cleaned)  # Remove PC spec codes
		cleaned = re.sub(r"\b288-Pin\b", "", cleaned)  # Remove pin count
		cleaned = re.sub(r"\bDesktop Memory\b", "Memory", cleaned, flags=re.IGNORECASE)
		cleaned = re.sub(r"\bModel\b.*$", "", cleaned)  # Remove "Model" and everything after
		
		cleaned = cleaned.strip(" -|")
		cleaned = re.sub(r"\s+", " ", cleaned)  # Normalize whitespace
		
		return cleaned or None

	def _fallback_name_from_url(self, product_url: str) -> str:
		parsed = urlparse(product_url)
		path_segments = [segment for segment in parsed.path.split("/") if segment]
		slug = path_segments[0] if path_segments else ""
		slug = slug.replace("-p-", " ")
		slug = re.sub(r"-+", " ", slug)
		slug = re.sub(r"\bN\d+E\d+\b", "", slug, flags=re.IGNORECASE)
		slug = _normalize_whitespace(slug)
		return slug or product_url

	def _parse_price(self, response) -> float | None:
		# Target the specific product price within product-pane div
		product_price_dollars = response.css(
			".product-pane .price-current strong::text"
		).get()
		product_price_cents = response.css(
			".product-pane .price-current sup::text"
		).get()

		if product_price_dollars and product_price_dollars.strip():
			price_text = product_price_dollars.strip()
			if product_price_cents and product_price_cents.strip():
				price_text += "." + product_price_cents.strip()
			price = _parse_float(price_text)
			if price is not None:
				return price

		# Try alternative specific selectors within product context
		alt_price_dollars = response.css(
			".product-pane .price-current-label strong::text, "
			".product-pane .product-price .price-current strong::text, "
			".product-pane .product-buy .price-current strong::text"
		).get()
		alt_price_cents = response.css(
			".product-pane .price-current-label sup::text, "
			".product-pane .product-price .price-current sup::text, "
			".product-pane .product-buy .price-current sup::text"
		).get()

		if alt_price_dollars and alt_price_dollars.strip():
			price_text = alt_price_dollars.strip()
			if alt_price_cents and alt_price_cents.strip():
				price_text += "." + alt_price_cents.strip()
			price = _parse_float(price_text)
			if price is not None:
				return price

		# Fallback to broader product-area selectors (avoid page-wide selectors)
		dollars = response.css(
			".product-info .price-current strong::text, "
			".product-details .price-current strong::text, "
			".product-main .price-current strong::text"
		).get()
		cents = response.css(
			".product-info .price-current sup::text, "
			".product-details .price-current sup::text, "
			".product-main .price-current sup::text"
		).get()

		if dollars and dollars.strip():
			price_text = dollars.strip()
			if cents and cents.strip():
				price_text += "." + cents.strip()
			price = _parse_float(price_text)
			if price is not None:
				return price  # Let the final validation handle this

		# Try to find price in product details area
		product_area_price = response.css(
			".product-info .price::text, "
			".product-details .price::text, "
			".product-main .price::text"
		).get()
		
		if product_area_price:
			price = _parse_float(product_area_price)
			if price is not None and 10 <= price <= 10000:
				return price

		# Last resort: look for price patterns but be more restrictive
		price_text = self._lookup_spec(
			{},
			[],
			raw_text=response.text,
			patterns=[r"\$(\d{1,4}(?:,\d{3})*(?:\.\d{2})?)"],
		)
		price = _parse_float(price_text)
		if price is not None:
			return price

		return None

	def _extract_category_fields(self, response, spec_index: dict[str, list[str]], raw_text: str, price: float | None) -> dict[str, object | None]:
		if self.category == "cpu":
			return self._extract_cpu_fields(spec_index, raw_text, price)
		if self.category == "memory":
			return self._extract_memory_fields(response, spec_index, raw_text, price)
		if self.category == "video_card":
			return self._extract_video_card_fields(spec_index, raw_text)
		if self.category == "motherboard":
			return self._extract_motherboard_fields(spec_index, raw_text, price)
		if self.category == "power_supply":
			return self._extract_power_supply_fields(spec_index, raw_text, price)
		if self.category == "internal_hard_drive":
			return self._extract_internal_drive_fields(spec_index, raw_text)
		return {}

	def _extract_cpu_fields(self, spec_index, raw_text, price):
		core_count = self._parse_cpu_core_count(spec_index, raw_text)
		core_clock = _parse_float(self._lookup_spec(
			spec_index,
			["core clock", "cpu base clock", "base clock", "processor base frequency", "speed"],
			raw_text,
			[r"(?:core|base|processor base|cpu base)[^\d]{0,40}(\d+(?:\.\d+)?)\s*ghz", r"(\d+(?:\.\d+)?)\s*ghz"],
		))
		boost_clock = _parse_float(self._lookup_spec(
			spec_index,
			["boost clock", "max turbo frequency", "turbo frequency", "max boost clock"],
			raw_text,
			[r"(?:boost|turbo|max turbo)[^\d]{0,40}(\d+(?:\.\d+)?)\s*ghz"],
		))
		tdp = _parse_int(self._lookup_spec(
			spec_index,
			["tdp", "thermal design power", "wattage", "power consumption"],
			raw_text,
			[r"(?:tdp|thermal design power|wattage)[^\d]{0,30}(\d+(?:\.\d+)?)\s*w"],
		))
		graphics = self._lookup_spec(
			spec_index,
			["integrated graphics", "graphics", "gpu"],
			raw_text,
			[r"integrated graphics[^:]*:\s*([^<\n\r]+)", r"graphics[^:]*:\s*([^<\n\r]+)"],
		)
		graphics = _compact_token(graphics) or graphics
		smt = self._parse_cpu_smt(spec_index, raw_text, core_count)
		microarchitecture = self._lookup_spec(
			spec_index,
			["microarchitecture", "architecture", "cpu series", "processor series"],
			raw_text,
			[r"(?:microarchitecture|architecture|series)[^:]*:\s*([^<\n\r]+)"],
		)
		microarchitecture = _normalize_whitespace(microarchitecture)

		value = None
		if core_count is not None and core_clock is not None and tdp is not None and price not in (None, 0):
			value = (core_count * core_clock * tdp) / price

		return {
			"core_count": core_count,
			"core_clock": core_clock,
			"boost_clock": boost_clock,
			"tdp": tdp,
			"graphics": graphics,
			"smt": smt,
			"microarchitecture": microarchitecture,
			"boost_status": "Yes" if boost_clock is not None else "No",
			"graphics_status": "Yes" if graphics else "No",
			"value": value,
		}

	def _parse_cpu_core_count(self, spec_index, raw_text):
		core_count = _parse_int(self._lookup_spec(
			spec_index,
			["core count", "number of cores", "cores"],
			raw_text,
			[r"(\d+)\s*[- ]?core", r"(\d+)\s*cores"],
		))
		if core_count is not None:
			return core_count

		title_guess = _first_match(raw_text, [r"(\d+)\s*[- ]?core"])
		return _parse_int(title_guess)

	def _parse_cpu_smt(self, spec_index, raw_text, core_count):
		threads = _parse_int(self._lookup_spec(
			spec_index,
			["threads", "thread count"],
			raw_text,
			[r"threads[^\d]{0,20}(\d+)"],
		))
		if core_count is not None and threads is not None:
			return 1 if threads > core_count else 0

		smt_text = self._lookup_spec(
			spec_index,
			["smt", "hyper-threading", "multithreading", "simultaneous multithreading"],
			raw_text,
			[r"(?:smt|hyper[- ]?threading|multithreading)[^:]*:\s*([^<\n\r]+)"],
		)
		if smt_text is None:
			return None

		lowered = smt_text.lower()
		if any(token in lowered for token in ["yes", "true", "enabled", "supported", "with"]):
			return 1
		if any(token in lowered for token in ["no", "false", "disabled", "without"]):
			return 0
		return None

	def _extract_memory_fields(self, response, spec_index, raw_text, price):
		modules_text = self._lookup_spec(
			spec_index,
			["modules", "number of modules", "module count", "memory per module"],
			raw_text,
			[r"(\d+)\s*[x×]\s*(\d+(?:\.\d+)?)\s*(tb|gb|mb)?", r"(\d+(?:\.\d+)?)\s*(tb|gb|mb)\s*(?:x|\*)\s*(\d+)"],
		)
		total_capacity = self._parse_memory_capacity(response, spec_index, raw_text)
		modules = self._parse_memory_modules(modules_text, total_capacity, raw_text)

		speed_text = self._lookup_spec(
			spec_index,
			["speed", "memory speed", "effective speed", "rated speed"],
			raw_text,
			[r"ddr\s*([2345])[^\d]{0,20}(\d{4,5})", r"(\d{4,5})\s*mt/s", r"(\d{4,5})\s*mhz"],
		)
		speed = self._parse_memory_speed(speed_text, raw_text)

		cas_latency = _parse_float(self._lookup_spec(
			spec_index,
			["cas latency", "cl"],
			raw_text,
			[r"cas latency[^\d]{0,20}(\d+(?:\.\d+)?)", r"\bcl\s*([0-9]+)"],
		))
		color = _normalize_whitespace(self._lookup_spec(
			spec_index,
			["color"],
			raw_text,
			[r"color[^:]*:\s*([^<\n\r]+)"],
		))

		price_per_gb = None
		if total_capacity not in (None, 0) and price not in (None, 0):
			price_per_gb = price / total_capacity

		value = None
		if modules and speed and price not in (None, 0):
			speed_float = self._speed_string_to_float(speed)
			if speed_float is not None:
				value = (speed_float * (modules[0] * modules[1])) / price

		first_word_latency = None
		if cas_latency is not None and speed:
			speed_numbers = re.findall(r"\d+(?:\.\d+)?", speed)
			if len(speed_numbers) >= 2:
				mhz = _parse_float(speed_numbers[1])
				if mhz not in (None, 0):
					first_word_latency = (cas_latency / mhz) * 2000

		return {
			"modules": f"{modules[0]},{modules[1]}" if modules else None,
			"speed": speed,
			"price_per_gb": price_per_gb,
			"color": color,
			"cas_latency": cas_latency,
			"first_word_latency": first_word_latency,
			"value": value,
		}

	def _parse_memory_capacity(self, response, spec_index, raw_text):
		capacity_text = self._lookup_spec(
			spec_index,
			["capacity", "total capacity", "memory capacity"],
			raw_text,
			[r"(\d+(?:\.\d+)?)\s*(tb|gb)", r"(\d+)\s*gb"],
		)
		if capacity_text:
			match = re.search(r"(\d+(?:\.\d+)?)\s*(tb|gb)", capacity_text, re.IGNORECASE)
			if match:
				amount = float(match.group(1))
				unit = match.group(2).lower()
				if unit == "tb":
					return amount * 1000.0
				return amount

		name_guess = self._lookup_spec({}, [], raw_text, [r"(\d+)\s*GB"])
		if name_guess:
			parsed = _parse_float(name_guess)
			return parsed
		return None

	def _parse_memory_modules(self, modules_text: str | None, total_capacity: float | None, raw_text: str = ""):
		if modules_text:
			match = re.search(r"(\d+)\s*[x×]\s*(\d+(?:\.\d+)?)\s*(tb|gb|mb)?", modules_text, re.IGNORECASE)
			if match:
				count = int(match.group(1))
				size = float(match.group(2))
				unit = (match.group(3) or "gb").lower()
				if unit == "tb":
					size *= 1000.0
				elif unit == "mb":
					size /= 1024.0
				# Ensure size is an integer for GB values
				if unit == "gb" and size == int(size):
					size = int(size)
				return count, size

			match = re.search(r"(\d+(?:\.\d+)?)\s*(tb|gb|mb)\s*(?:x|\*)\s*(\d+)", modules_text, re.IGNORECASE)
			if match:
				size = float(match.group(1))
				unit = match.group(2).lower()
				count = int(match.group(3))
				if unit == "tb":
					size *= 1000.0
				elif unit == "mb":
					size /= 1024.0
				# Ensure size is an integer for GB values
				if unit == "gb" and size == int(size):
					size = int(size)
				return count, size

		# Try to extract modules from product title as fallback
		if raw_text:
			# Look for patterns like "(2 x 16GB)" or "2x16GB" in the title/description
			title_match = re.search(r"\(\s*(\d+)\s*[x×]\s*(\d+(?:\.\d+)?)\s*(gb|mb|tb)?\s*\)", raw_text, re.IGNORECASE)
			if not title_match:
				title_match = re.search(r"(\d+)\s*[x×]\s*(\d+(?:\.\d+)?)\s*(gb|mb|tb)?", raw_text, re.IGNORECASE)
			
			if title_match:
				count = int(title_match.group(1))
				size = float(title_match.group(2))
				unit = (title_match.group(3) or "gb").lower()
				if unit == "tb":
					size *= 1000.0
				elif unit == "mb":
					size /= 1024.0
				# Ensure size is an integer for GB values
				if unit == "gb" and size == int(size):
					size = int(size)
				return count, size

		if total_capacity not in (None, 0):
			return 1, int(float(total_capacity)) if float(total_capacity) == int(float(total_capacity)) else float(total_capacity)
		return None

	def _parse_memory_speed(self, speed_text: str | None, raw_text: str):
		if speed_text:
			match = re.search(r"ddr\s*([2345])[^\d]{0,20}(\d{4,5})", speed_text, re.IGNORECASE)
			if match:
				return f"{match.group(1)},{match.group(2)}"

			numbers = re.findall(r"\d+(?:\.\d+)?", speed_text)
			if len(numbers) >= 2:
				return f"{int(float(numbers[0]))},{int(float(numbers[1]))}"
			if len(numbers) == 1:
				ddr = _first_match(raw_text, [r"DDR\s*([2345])"])
				if ddr:
					return f"{ddr},{int(float(numbers[0]))}"

		ddr = _first_match(raw_text, [r"DDR\s*([2345])"])
		mhz = _first_match(raw_text, [r"(\d{4,5})\s*(?:MT/s|MHz)"])
		if ddr and mhz:
			return f"{ddr},{mhz}"
		return None

	def _speed_string_to_float(self, speed_text: str) -> float | None:
		parts = re.findall(r"\d+(?:\.\d+)?", speed_text)
		if len(parts) < 2:
			return None
		try:
			return float(f"{int(float(parts[0]))}.{int(float(parts[1]))}")
		except (TypeError, ValueError):
			return None

	def _extract_video_card_fields(self, spec_index, raw_text):
		chipset = self._lookup_spec(
			spec_index,
			["chipset", "gpu chipset", "graphics chipset", "graphics processor"],
			raw_text,
			[r"(?:chipset|graphics processor)[^:]*:\s*([^<\n\r]+)"],
		)
		chipset = _compact_token(chipset) or chipset

		memory = _parse_float(self._lookup_spec(
			spec_index,
			["memory", "memory size", "video memory", "graphics memory"],
			raw_text,
			[r"(?:memory|video memory|graphics memory)[^\d]{0,20}(\d+(?:\.\d+)?)\s*gb"],
		))
		core_clock = _parse_float(self._lookup_spec(
			spec_index,
			["core clock", "graphics clock", "gpu clock"],
			raw_text,
			[r"(?:core clock|graphics clock|gpu clock)[^\d]{0,20}(\d+(?:\.\d+)?)\s*mhz"],
		))
		boost_clock = _parse_float(self._lookup_spec(
			spec_index,
			["boost clock", "gpu boost clock"],
			raw_text,
			[r"(?:boost clock|gpu boost clock)[^\d]{0,20}(\d+(?:\.\d+)?)\s*mhz"],
		))
		color = _normalize_whitespace(self._lookup_spec(
			spec_index,
			["color"],
			raw_text,
			[r"color[^:]*:\s*([^<\n\r]+)"],
		))
		length = _parse_float(self._lookup_spec(
			spec_index,
			["length", "card length", "dimensions"],
			raw_text,
			[r"(?:length|dimensions)[^\d]{0,20}(\d+(?:\.\d+)?)\s*mm"],
		))

		return {
			"chipset": chipset,
			"memory": memory,
			"core_clock": core_clock,
			"boost_clock": boost_clock,
			"color": color,
			"length": length,
		}

	def _extract_motherboard_fields(self, spec_index, raw_text, price):
		socket = _normalize_whitespace(self._lookup_spec(
			spec_index,
			["socket", "cpu socket", "socket type"],
			raw_text,
			[r"socket[^:]*:\s*([^<\n\r]+)"],
		))
		form_factor = _normalize_whitespace(self._lookup_spec(
			spec_index,
			["form factor"],
			raw_text,
			[r"form factor[^:]*:\s*([^<\n\r]+)"],
		))
		max_memory = _parse_int(self._lookup_spec(
			spec_index,
			["max memory", "maximum memory", "memory support"],
			raw_text,
			[r"(?:max memory|maximum memory|memory support)[^\d]{0,20}(\d+)\s*gb"],
		))
		memory_slots = _parse_int(self._lookup_spec(
			spec_index,
			["memory slots", "memory slot"],
			raw_text,
			[r"memory slots[^\d]{0,20}(\d+)"],
		))
		color = _normalize_whitespace(self._lookup_spec(
			spec_index,
			["color"],
			raw_text,
			[r"color[^:]*:\s*([^<\n\r]+)"],
		))

		value = None
		if max_memory is not None and price not in (None, 0):
			value = max_memory / price

		return {
			"socket": socket,
			"form_factor": form_factor,
			"max_memory": max_memory,
			"memory_slots": memory_slots,
			"color": color,
			"value": value,
		}

	def _extract_power_supply_fields(self, spec_index, raw_text, price):
		psu_type = _normalize_whitespace(self._lookup_spec(
			spec_index,
			["type", "form factor"],
			raw_text,
			[r"type[^:]*:\s*([^<\n\r]+)"],
		))
		efficiency = self._normalize_efficiency(self._lookup_spec(
			spec_index,
			["efficiency", "80 plus", "80+ certification"],
			raw_text,
			[r"(?:efficiency|80\+ certification)[^:]*:\s*([^<\n\r]+)"],
		))
		wattage = _parse_int(self._lookup_spec(
			spec_index,
			["wattage", "power", "output wattage"],
			raw_text,
			[r"(?:wattage|power|output wattage)[^\d]{0,20}(\d+)\s*w"],
		))
		modular = self._normalize_modular(self._lookup_spec(
			spec_index,
			["modular"],
			raw_text,
			[r"modular[^:]*:\s*([^<\n\r]+)"],
		))
		color = _normalize_whitespace(self._lookup_spec(
			spec_index,
			["color"],
			raw_text,
			[r"color[^:]*:\s*([^<\n\r]+)"],
		))

		value = None
		if efficiency and wattage is not None and price not in (None, 0):
			efficiency_score = {"plus": 80, "bronze": 85, "silver": 88, "gold": 90, "platinum": 92, "titanium": 94}.get(efficiency, 80)
			value = (efficiency_score * wattage) / price

		return {
			"type": psu_type,
			"efficiency": efficiency,
			"wattage": wattage,
			"modular": modular,
			"color": color,
			"value": value,
		}

	def _normalize_efficiency(self, efficiency: str | None) -> str | None:
		if not efficiency:
			return None
		lowered = efficiency.lower()
		for tier in ["titanium", "platinum", "gold", "silver", "bronze"]:
			if tier in lowered:
				return tier
		return "plus" if "80" in lowered else _normalize_whitespace(efficiency)

	def _normalize_modular(self, modular: str | None) -> str | None:
		if not modular:
			return None
		lowered = modular.lower()
		if "full" in lowered:
			return "full"
		if "semi" in lowered:
			return "semi"
		if "non" in lowered or "no" in lowered:
			return "non"
		return _normalize_whitespace(modular)

	def _extract_internal_drive_fields(self, spec_index, raw_text):
		capacity = self._parse_drive_capacity(self._lookup_spec(
			spec_index,
			["capacity", "storage capacity", "drive capacity"],
			raw_text,
			[r"(?:capacity|storage capacity|drive capacity)[^\d]{0,20}(\d+(?:\.\d+)?)\s*(tb|gb)"],
		))
		drive_type = _normalize_whitespace(self._lookup_spec(
			spec_index,
			["type", "drive type", "form factor"],
			raw_text,
			[r"type[^:]*:\s*([^<\n\r]+)"],
		))
		cache = self._parse_cache(self._lookup_spec(
			spec_index,
			["cache", "buffer"],
			raw_text,
			[r"cache[^\d]{0,20}(\d+(?:\.\d+)?)\s*(tb|gb|mb)?", r"buffer[^\d]{0,20}(\d+(?:\.\d+)?)\s*(tb|gb|mb)?"],
		))
		form_factor = _compact_spaces(self._lookup_spec(
			spec_index,
			["form factor"],
			raw_text,
			[r"form factor[^:]*:\s*([^<\n\r]+)"],
		))
		interface = _compact_spaces(self._lookup_spec(
			spec_index,
			["interface", "nvme", "sata", "pcie interface"],
			raw_text,
			[r"interface[^:]*:\s*([^<\n\r]+)"],
		))

		return {
			"capacity": capacity,
			"type": drive_type,
			"cache": cache,
			"form_factor": form_factor,
			"interface": interface,
		}

	def _parse_drive_capacity(self, capacity_text: str | None):
		if not capacity_text:
			return None
		match = re.search(r"(\d+(?:\.\d+)?)\s*(tb|gb)", capacity_text, re.IGNORECASE)
		if not match:
			return _parse_float(capacity_text)

		amount = float(match.group(1))
		unit = match.group(2).lower()
		if unit == "tb":
			return amount * 1000.0
		return amount

	def _parse_cache(self, cache_text: str | None):
		if not cache_text:
			return None
		match = re.search(r"(\d+(?:\.\d+)?)\s*(tb|gb|mb)?", cache_text, re.IGNORECASE)
		if not match:
			return _parse_float(cache_text)

		amount = float(match.group(1))
		unit = (match.group(2) or "mb").lower()
		if unit == "tb":
			return amount * 1024.0 * 1024.0
		if unit == "gb":
			return amount * 1024.0
		return amount

	def _get_existing_dates(self, product_name: str) -> set[str]:
		if not self.table_name:
			return set()

		cache_key = product_name.lower().strip()
		if cache_key in self._existing_dates_cache:
			return set(self._existing_dates_cache[cache_key])

		inspector = inspect(self.engine)
		if self.table_name not in inspector.get_table_names():
			self.logger.warning("Catalog table %s not found in database", self.table_name)
			self._existing_dates_cache[cache_key] = set()
			return set()

		with self.engine.connect() as conn:
			rows = conn.execute(
				text(f"SELECT snapshot_date FROM {self.table_name} WHERE name = :name"),
				{"name": product_name},
			).fetchall()

		dates = {str(row[0]) for row in rows if row and row[0]}
		self._existing_dates_cache[cache_key] = set(dates)
		return dates

	def handle_error(self, failure):
		meta = failure.request.meta
		self.logger.warning(
			"Snapshot request failed for %s on %s: %s",
			meta.get("product_url", "?"),
			meta.get("snapshot_date", "?"),
			failure.value,
		)

	def _log_extracted_fields(self, product_name: str, snapshot_date: str, category_fields: dict[str, object | None]) -> None:
		if not self.debug_extract:
			return

		non_empty_fields = {
			key: value
			for key, value in category_fields.items()
			if value not in (None, "", [], {}, ())
		}
		empty_fields = sorted(
			key for key, value in category_fields.items() if value in (None, "", [], {}, ())
		)

		self.logger.warning(
			"Extracted fields before pipeline insert | category=%s | snapshot=%s | product=%s | extracted=%s | missing=%s",
			self.category,
			snapshot_date,
			product_name,
			json.dumps(non_empty_fields, sort_keys=True, default=str),
			empty_fields,
		)
