"""Compatibility spider that routes `wayback_newegg` to the functional implementation.

This keeps legacy commands (e.g. `scrapy crawl wayback_newegg`) working while
using the category-aware extractor that writes schema-matching fields.
"""

from __future__ import annotations

from .wb_ne_functional import WaybackNeweggSpider as FunctionalWaybackNeweggSpider


class WaybackNeweggSpider(FunctionalWaybackNeweggSpider):
    """Alias the functional spider under the legacy name."""

    name = "wayback_newegg"
