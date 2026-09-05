"""Kullanici takip sepeti (/sepetim).

Botun temsilî risk-profili sepetlerinden bagimsizdir. Kullanici kendi
ticker listesini ekler; bot fiyat (TL) ve ilgili haberleri gosterir.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from . import market, news, storage
from .config import settings

log = logging.getLogger(__name__)


@dataclass
class WatchItem:
    ticker: str
    weight: float
    name: str
    currency: str
    exchange: str
    quote: market.TickerQuote | None = None


@dataclass
class WatchSnapshot:
    items: list[WatchItem] = field(default_factory=list)
    weight_sum: float = 0.0
    weighted_1d_pct: float | None = None
    weighted_5d_pct: float | None = None
    weighted_20d_pct: float | None = None


@dataclass
class AddResult:
    ok: bool
    message: str
    item: WatchItem | None = None


def _parse_weight(raw: str | None) -> float | None:
    if raw is None or raw == "":
        return 0.0
    text = raw.strip().replace(",", ".").replace("%", "")
    try:
        value = float(text)
    except ValueError:
        return None
    if value < 0 or value > 100:
        return None
    return value


def add_item(chat_id: int, ticker_raw: str, weight_raw: str | None = None) -> AddResult:
    weight = _parse_weight(weight_raw)
    if weight is None:
        return AddResult(False, "Ağırlık 0–100 arası bir sayı olmalı. Örnek: <code>/sepetim ekle AAPL 25</code>")

    meta = market.resolve_ticker_meta(ticker_raw)
    if meta is None:
        return AddResult(
            False,
            "Ticker bulunamadı. Yahoo Finance sembolünü kullanın.\n"
            "Örnekler: <code>AAPL</code>, <code>THYAO.IS</code>, <code>VWCE.DE</code>, "
            "<code>7203.T</code>, <code>QQQ</code>",
        )

    ticker = meta["ticker"]
    already = storage.get_watchlist_item(chat_id, ticker) is not None
    if not already and storage.watchlist_count(chat_id) >= settings.max_watchlist_items:
        return AddResult(
            False,
            f"Sepet dolu (en fazla {settings.max_watchlist_items} sembol). "
            "Önce <code>/sepetim sil TICKER</code> ile yer açın.",
        )

    storage.upsert_watchlist_item(
        chat_id=chat_id,
        ticker=ticker,
        weight=weight,
        name=meta["name"],
        currency=meta["currency"],
        exchange=meta["exchange"],
    )
    item = WatchItem(
        ticker=ticker,
        weight=weight,
        name=meta["name"],
        currency=meta["currency"],
        exchange=meta["exchange"],
    )
    verb = "güncellendi" if already else "eklendi"
    weight_txt = f" · ağırlık %{weight:g}" if weight else ""
    return AddResult(
        True,
        f"✅ <b>{ticker}</b> ({meta['name']}) sepete {verb}{weight_txt}.",
        item,
    )


def remove_item(chat_id: int, ticker_raw: str) -> AddResult:
    base = market.normalize_ticker(ticker_raw)
    if not base:
        return AddResult(False, "Silinecek ticker'ı yazın. Örnek: <code>/sepetim sil AAPL</code>")

    candidates = [base]
    if "." not in base:
        candidates.append(f"{base}.IS")

    for cand in candidates:
        if storage.remove_watchlist_item(chat_id, cand):
            return AddResult(True, f"🗑️ <b>{cand}</b> sepetinden çıkarıldı.")

    # Case-insensitive / partial: listedeki ticker'larla eslestir
    for row in storage.list_watchlist(chat_id):
        if row["ticker"] == base or row["ticker"].startswith(base + "."):
            storage.remove_watchlist_item(chat_id, row["ticker"])
            return AddResult(True, f"🗑️ <b>{row['ticker']}</b> sepetinden çıkarıldı.")

    return AddResult(False, f"<b>{base}</b> sepetinde yok. Liste için /sepetim yazın.")


def clear_items(chat_id: int) -> AddResult:
    n = storage.clear_watchlist(chat_id)
    if n == 0:
        return AddResult(False, "Sepetin zaten boş.")
    return AddResult(True, f"🧹 Sepet temizlendi ({n} sembol silindi).")


def snapshot(chat_id: int) -> WatchSnapshot:
    rows = storage.list_watchlist(chat_id)
    if not rows:
        return WatchSnapshot()

    meta = {
        row["ticker"]: {
            "name": row["name"],
            "currency": row["currency"],
            "exchange": row["exchange"],
        }
        for row in rows
    }
    tickers = [row["ticker"] for row in rows]
    quotes = market.fetch_ticker_quotes(tickers, meta)

    items: list[WatchItem] = []
    for row in rows:
        q = quotes.get(row["ticker"])
        items.append(
            WatchItem(
                ticker=row["ticker"],
                weight=float(row["weight"] or 0),
                name=row["name"] or row["ticker"],
                currency=row["currency"] or "",
                exchange=row["exchange"] or "",
                quote=q,
            )
        )

    weight_sum = sum(i.weight for i in items)
    snap = WatchSnapshot(items=items, weight_sum=weight_sum)

    priced = [i for i in items if i.quote is not None and i.weight > 0]
    if priced and weight_sum > 0:
        w = sum(i.weight for i in priced)
        if w > 0:
            snap.weighted_1d_pct = sum(i.weight * i.quote.change_1d_pct for i in priced) / w  # type: ignore[union-attr]
            snap.weighted_5d_pct = sum(i.weight * i.quote.change_5d_pct for i in priced) / w  # type: ignore[union-attr]
            snap.weighted_20d_pct = sum(i.weight * i.quote.change_20d_pct for i in priced) / w  # type: ignore[union-attr]
    elif items and all(i.quote is not None for i in items):
        n = len(items)
        snap.weighted_1d_pct = sum(i.quote.change_1d_pct for i in items) / n  # type: ignore[union-attr]
        snap.weighted_5d_pct = sum(i.quote.change_5d_pct for i in items) / n  # type: ignore[union-attr]
        snap.weighted_20d_pct = sum(i.quote.change_20d_pct for i in items) / n  # type: ignore[union-attr]

    return snap


def _match_tokens(item: WatchItem) -> list[str]:
    tokens = {item.ticker.lower(), item.ticker.split(".")[0].lower()}
    # Isımden anlamli kelimeler (kisa kelimeleri at)
    for part in re.split(r"[^A-Za-z0-9ÇĞİÖŞÜçğıöşü]+", item.name):
        if len(part) >= 4:
            tokens.add(news.normalize(part))
    return [t for t in tokens if t]


def related_news(chat_id: int, limit: int = 12) -> list[tuple[news.NewsItem, list[str]]]:
    """Sepetteki sembollerle eslesen haberleri dondurur (eslesen ticker listesiyle)."""
    rows = storage.list_watchlist(chat_id)
    if not rows:
        return []

    items = [
        WatchItem(
            ticker=row["ticker"],
            weight=float(row["weight"] or 0),
            name=row["name"] or row["ticker"],
            currency=row["currency"] or "",
            exchange=row["exchange"] or "",
        )
        for row in rows
    ]
    token_map = {it.ticker: _match_tokens(it) for it in items}

    collected = news.collect()
    matched: list[tuple[news.NewsItem, list[str]]] = []
    for article in collected:
        hay = news.normalize(f"{article.title} {article.summary}")
        hits: list[str] = []
        for ticker, tokens in token_map.items():
            if any(tok in hay for tok in tokens):
                hits.append(ticker)
        if hits:
            matched.append((article, hits))
        if len(matched) >= limit:
            break
    return matched
