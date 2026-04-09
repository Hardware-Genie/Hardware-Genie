"""
PC Tech News Spider
===================
Scrapes the latest PC hardware and tech news articles from multiple sources:
  - Tom's Hardware
  - AnandTech
  - TechPowerUp
  - PC Gamer
  - Wccftech
  - VideoCardz

Extracts: title, summary, publish date, URL, source, tags/categories

Run with:
    scrapy crawl tech_news

Options:
    -a source="tomshardware"     # scrape only one source
    -a keywords="RTX,GPU,AMD"    # filter for specific keywords
    -a max_articles=50           # limit total articles
"""

import scrapy
import re
from datetime import datetime
from urllib.parse import urljoin


# ============================================================
# CONFIGURE SOURCES
# You can enable/disable sources by commenting them out
# ============================================================
NEWS_SOURCES = {
    "tomshardware": {
        "url": "https://www.tomshardware.com/news",
        "enabled": True,
    },
    "anandtech": {
        "url": "https://www.anandtech.com/",
        "enabled": True,
    },
    "techpowerup": {
        "url": "https://www.techpowerup.com/",
        "enabled": True,
    },
    "pcgamer": {
        "url": "https://www.pcgamer.com/hardware/",
        "enabled": True,
    },
    "wccftech": {
        "url": "https://wccftech.com/category/hardware/",
        "enabled": True,
    },
    "videocardz": {
        "url": "https://videocardz.com/",
        "enabled": True,
    },
}

# Keywords to filter for (case-insensitive)
# Leave empty [] to get all articles
KEYWORDS = [
    "RTX", "GPU", "graphics card", "AMD", "NVIDIA", "Intel",
    "CPU", "processor", "gaming", "benchmark", "review",
    "Ryzen", "Core i9", "GeForce", "Radeon",
]


class TechNewsSpider(scrapy.Spider):
    name = "tech_news"

    custom_settings = {
        "DOWNLOAD_DELAY": 1,
        "RANDOMIZE_DOWNLOAD_DELAY": True,
        "CONCURRENT_REQUESTS": 2,
        "ROBOTSTXT_OBEY": True,
        "USER_AGENT": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",

        "LOG_LEVEL": "WARNING",
    }

    def __init__(self, source=None, keywords=None, max_articles=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # CLI args override config
        self.filter_source = source
        self.filter_keywords = keywords.split(",") if keywords else KEYWORDS
        self.max_articles = int(max_articles) if max_articles else None
        self.articles_scraped = 0

    def start_requests(self):
        """Start scraping enabled news sources."""
        for source_name, config in NEWS_SOURCES.items():
            # Skip if user specified a single source via -a source=...
            if self.filter_source and source_name != self.filter_source:
                continue
            if not config["enabled"]:
                continue

            self.logger.info(f"Scraping: {source_name}")
            print(f"\n[{source_name.upper()}] Starting scrape...")

            yield scrapy.Request(
                url=config["url"],
                callback=self.parse,
                meta={"source": source_name},
                errback=self.handle_error,
            )

    def parse(self, response):
        """Route to the appropriate parser based on source."""
        source = response.meta["source"]
        
        parser_map = {
            "tomshardware":  self.parse_tomshardware,
            "anandtech":     self.parse_anandtech,
            "techpowerup":   self.parse_techpowerup,
            "pcgamer":       self.parse_pcgamer,
            "wccftech":      self.parse_wccftech,
            "videocardz":    self.parse_videocardz,
        }

        parser = parser_map.get(source)
        if parser:
            yield from parser(response)
        else:
            self.logger.warning(f"No parser for {source}")

    # ============================================================
    # PARSERS — one per news source
    # ============================================================

    def parse_tomshardware(self, response):
        """Tom's Hardware article parser."""
        articles = response.css("article.listingResult")

        for article in articles:
            title = article.css("a.article-link::text").get()
            url   = article.css("a.article-link::attr(href)").get()
            summary = article.css("p.synopsis::text").get()
            category = article.css("a.article-category::text").get()
            
            if title and url:
                url = urljoin(response.url, url)
                
                # Follow the article link to get full text
                yield scrapy.Request(
                    url=url,
                    callback=self.parse_article_full,
                    meta={
                        "source": "Tom's Hardware",
                        "title": title.strip(),
                        "url": url,
                        "summary": summary.strip() if summary else "",
                        "category": category.strip() if category else "",
                    },
                )

    def parse_anandtech(self, response):
        """AnandTech article parser."""
        articles = response.css("div.blog")

        for article in articles:
            title = article.css("h2 a::text").get()
            url   = article.css("h2 a::attr(href)").get()
            summary = article.css("p::text").get()
            
            if title and url:
                url = urljoin(response.url, url)
                yield scrapy.Request(
                    url=url,
                    callback=self.parse_article_full,
                    meta={
                        "source": "AnandTech",
                        "title": title.strip(),
                        "url": url,
                        "summary": summary.strip() if summary else "",
                        "category": "",
                    },
                )

    def parse_techpowerup(self, response):
        """TechPowerUp article parser."""
        articles = response.css("div.news-flex")

        for article in articles:
            title = article.css("a::text").get()
            url   = article.css("a::attr(href)").get()
            
            if title and url:
                url = urljoin(response.url, url)
                yield scrapy.Request(
                    url=url,
                    callback=self.parse_article_full,
                    meta={
                        "source": "TechPowerUp",
                        "title": title.strip(),
                        "url": url,
                        "summary": "",
                        "category": "",
                    },
                )

    def parse_pcgamer(self, response):
        """PC Gamer hardware section parser."""
        articles = response.css("article.listingResult")

        for article in articles:
            title = article.css("h3.article-name a::text").get()
            url   = article.css("h3.article-name a::attr(href)").get()
            summary = article.css("p.synopsis::text").get()
            
            if title and url:
                url = urljoin(response.url, url)
                yield scrapy.Request(
                    url=url,
                    callback=self.parse_article_full,
                    meta={
                        "source": "PC Gamer",
                        "title": title.strip(),
                        "url": url,
                        "summary": summary.strip() if summary else "",
                        "category": "Hardware",
                    },
                )

    def parse_wccftech(self, response):
        """Wccftech hardware news parser."""
        articles = response.css("article.post")

        for article in articles:
            title = article.css("h2.entry-title a::text").get()
            url   = article.css("h2.entry-title a::attr(href)").get()
            summary = article.css("div.entry-content p::text").get()
            
            if title and url:
                yield scrapy.Request(
                    url=url,
                    callback=self.parse_article_full,
                    meta={
                        "source": "Wccftech",
                        "title": title.strip(),
                        "url": url,
                        "summary": summary.strip() if summary else "",
                        "category": "Hardware",
                    },
                )

    def parse_videocardz(self, response):
        """VideoCardz GPU news parser."""
        articles = response.css("article.post")

        for article in articles:
            title = article.css("h2.entry-title a::text").get()
            url   = article.css("h2.entry-title a::attr(href)").get()
            summary = article.css("div.entry-summary p::text").get()
            category = article.css("a[rel='category tag']::text").get()
            
            if title and url:
                yield scrapy.Request(
                    url=url,
                    callback=self.parse_article_full,
                    meta={
                        "source": "VideoCardz",
                        "title": title.strip(),
                        "url": url,
                        "summary": summary.strip() if summary else "",
                        "category": category.strip() if category else "",
                    },
                )

    # ============================================================
    # HELPER METHODS
    # ============================================================

    def parse_article_full(self, response):
        """
        Extract full article text from article pages.
        Works across most news sites using common article selectors.
        """
        source   = response.meta["source"]
        title    = response.meta["title"]
        url      = response.meta["url"]
        summary  = response.meta["summary"]
        category = response.meta["category"]

        # Try multiple common article content selectors
        # Most news sites use one of these patterns
        full_text_selectors = [
            "article p::text",
            "div.article-content p::text",
            "div.entry-content p::text",
            "div.article-body p::text",
            "div.content p::text",
            "div[itemprop='articleBody'] p::text",
            "main article p::text",
        ]

        paragraphs = []
        for selector in full_text_selectors:
            paragraphs = response.css(selector).getall()
            if paragraphs and len(paragraphs) > 2:  # valid article has multiple paragraphs
                break

        # Join paragraphs, clean up whitespace
        full_text = " ".join([p.strip() for p in paragraphs if p.strip()])

        # Fallback to summary if full text extraction failed
        if not full_text or len(full_text) < 100:
            full_text = summary

        # Try to extract publish date
        publish_date = (
            response.css("time::attr(datetime)").get() or
            response.css("meta[property='article:published_time']::attr(content)").get() or
            response.css("span.date::text").get() or
            ""
        )

        yield self.build_item(
            source=source,
            title=title,
            url=url,
            summary=summary,
            full_text=full_text,
            category=category,
            publish_date=publish_date,
        )

    def build_item(self, source, title, url, summary, category, publish_date, full_text=""):
        """
        Build a standardized article item.
        Applies keyword filtering and max article limit.
        """
        # Keyword filter
        if self.filter_keywords:
            text_to_search = f"{title} {summary} {category}".lower()
            if not any(kw.lower() in text_to_search for kw in self.filter_keywords):
                return  # skip this article

        # Max articles limit
        if self.max_articles and self.articles_scraped >= self.max_articles:
            return

        self.articles_scraped += 1
        
        print(f"  ✓ [{source}] {title[:60]}...")

        return {
            "source":       source,
            "title":        title,
            "url":          url,
            "summary":      summary,
            "full_text":    full_text,
            "category":     category,
            "publish_date": publish_date or "",
            "scraped_at":   datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def handle_error(self, failure):
        """Log failed requests without crashing."""
        source = failure.request.meta.get("source", "unknown")
        print(f"  ✗ [{source}] Request failed: {failure.value}")


