"""RSS kaynaklarindan haber toplama ve onem (tier) siniflandirmasi."""

from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import feedparser

from . import storage
from .config import settings

log = logging.getLogger(__name__)

FEEDS: tuple[tuple[str, str], ...] = (
    ("BloombergHT", "https://www.bloomberght.com/rss"),
    ("Investing TR", "https://tr.investing.com/rss/news.rss"),
    ("Investing TR Ekonomi", "https://tr.investing.com/rss/news_14.rss"),
    ("AA Ekonomi", "https://www.aa.com.tr/tr/rss/default?cat=ekonomi"),
    ("Dunya", "https://www.dunya.com/rss?dunya"),
    ("NTV Ekonomi", "https://www.ntv.com.tr/ekonomi.rss"),
    ("Yahoo Finance", "https://finance.yahoo.com/news/rssindex"),
    ("CNBC", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
)

# Tier-1: sepet degisimini tetiklemeye yetkili "temel" olaylar.
TIER1_PATTERNS = (
    "faiz karar",
    "politika faizi",
    "merkez bankasi",
    "tcmb",
    "fed ",
    "fomc",
    "federal reserve",
    "ecb",
    "avrupa merkez bankasi",
    "enflasyon",
    "tufe",
    "cpi ",
    "inflation",
    "interest rate",
    "rate cut",
    "rate hike",
    "secim",
    "election",
    "savas",
    "war ",
    "ambargo",
    "sanction",
    "yaptirim",
    "kredi notu",
    "credit rating",
    "moody",
    "fitch",
    "resesyon",
    "recession",
)

# Tier-2: yon icin anlamli ama tek basina degisim sebebi olmayan veriler.
TIER2_PATTERNS = (
    "buyume",
    "gsyh",
    "gdp",
    "issizlik",
    "unemployment",
    "istihdam",
    "payroll",
    "cari acik",
    "current account",
    "butce",
    "budget",
    "petrol",
    "oil ",
    "opec",
    "brent",
    "tarife",
    "tariff",
    "gumruk",
    "bilanco",
    "earnings",
    "kar",
    "borsa istanbul",
    "bist",
    "dolar",
    "euro",
    "altin",
    "gold",
    "rezerv",
    "reserve",
    "bitcoin",
    "kripto",
    "crypto",
)


@dataclass
class NewsItem:
    hash: str
    source: str
    title: str
    summary: str
    link: str
    published_at: datetime | None
    tier: int

    def as_dict(self) -> dict:
        return {
            "hash": self.hash,
            "source": self.source,
            "title": self.title,
            "summary": self.summary,
            "link": self.link,
            "published_at": storage.iso(self.published_at) if self.published_at else None,
            "tier": self.tier,
        }


def normalize(text: str) -> str:
    """Turkce karakterleri sadelestirip kucuk harfe cevirir."""
    text = text.replace("ı", "i").replace("İ", "i").replace("I", "i")
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_text = decomposed.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", ascii_text).lower()


def classify_tier(title: str, summary: str = "") -> int:
    haystack = normalize(f"{title} {summary}")
    if any(pattern in haystack for pattern in TIER1_PATTERNS):
        return 1
    if any(pattern in haystack for pattern in TIER2_PATTERNS):
        return 2
    return 3


def _parse_published(entry) -> datetime | None:
    for field in ("published_parsed", "updated_parsed"):
        value = getattr(entry, field, None)
        if value:
            try:
                return datetime(*value[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
    return None


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text or "").strip()


def _fetch_feed(source: str, url: str) -> list[NewsItem]:
    try:
        parsed = feedparser.parse(url)
    except Exception as exc:  # noqa: BLE001
        log.warning("RSS okunamadi (%s): %s", source, exc)
        return []

    items: list[NewsItem] = []
    for entry in parsed.entries:
        title = _strip_html(entry.get("title", ""))
        if not title:
            continue
        summary = _strip_html(entry.get("summary", ""))[:400]
        link = entry.get("link", "")
        digest = hashlib.sha256(normalize(title).encode("utf-8")).hexdigest()[:32]
        items.append(
            NewsItem(
                hash=digest,
                source=source,
                title=title,
                summary=summary,
                link=link,
                published_at=_parse_published(entry),
                tier=classify_tier(title, summary),
            )
        )
    return items


def collect(lookback_hours: int | None = None) -> list[NewsItem]:
    """Tum kaynaklari paralel okur; tekrarlari ve eski haberleri ayiklar."""
    lookback = lookback_hours if lookback_hours is not None else settings.news_lookback_hours
    cutoff = storage.utcnow() - timedelta(hours=lookback)

    with ThreadPoolExecutor(max_workers=len(FEEDS)) as pool:
        results = pool.map(lambda pair: _fetch_feed(*pair), FEEDS)

    seen: set[str] = set()
    items: list[NewsItem] = []
    for batch in results:
        for item in batch:
            if item.hash in seen:
                continue
            # Tarihi olmayan haberleri de aliyoruz; bazi kaynaklar tarih vermiyor.
            if item.published_at and item.published_at < cutoff:
                continue
            seen.add(item.hash)
            items.append(item)

    items.sort(key=lambda i: (i.tier, -(i.published_at or cutoff).timestamp()))
    trimmed = items[: settings.max_news_items]

    fresh_count = len(trimmed) - len(storage.news_seen([i.hash for i in trimmed]))
    storage.save_news([i.as_dict() for i in trimmed])
    log.info("%d haber toplandi (%d yeni)", len(trimmed), fresh_count)
    return trimmed


def tier1_items(items: list[NewsItem]) -> list[NewsItem]:
    return [item for item in items if item.tier == 1]


def to_prompt_block(items: list[NewsItem], limit: int = 30) -> str:
    lines = []
    for item in items[:limit]:
        stamp = item.published_at.strftime("%d.%m %H:%M") if item.published_at else "tarih yok"
        lines.append(f"[T{item.tier}] ({item.source}, {stamp}) {item.title}")
    return "\n".join(lines)
