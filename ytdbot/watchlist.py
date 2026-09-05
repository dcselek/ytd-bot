"""Kullanici takip sepeti (/sepetim).

Botun temsilî risk-profili sepetlerinden bagimsizdir. Kullanici kendi
ticker listesini ekler; bot fiyat (TL) ve ilgili haberleri gosterir.

TEFAS fonlari Yahoo/PCX carpismasina dusmesin diye kisa kodlarda once
TEFAS denenir. Zorlamak icin: ``/sepetim ekle MAC tefas`` veya ``yahoo``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from . import market, news, storage, tefas
from .config import settings

log = logging.getLogger(__name__)

_VENUE_TOKENS = {
    "tefas": "tefas",
    "tefaş": "tefas",
    "fon": "tefas",
    "yahoo": "yahoo",
    "yf": "yahoo",
    "us": "yahoo",
    "bist": "bist",
}

ALERT_STATE_PREFIX = "watchlist_alert_pct:"


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


@dataclass
class CompareResult:
    watch_20d: float | None
    bot_20d: float | None
    bot_profile: str
    watch_items: int
    bot_name: str


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


def _parse_add_args(args: list[str]) -> tuple[str, str | None, float | None, str | None]:
    """ticker, venue, weight, error."""
    if not args:
        return "", None, None, "Kullanım: <code>/sepetim ekle TICKER [tefas|yahoo] [ağırlık]</code>"

    ticker = args[0]
    venue: str | None = None
    weight_raw: str | None = None

    for token in args[1:]:
        key = token.strip().lower()
        if key in _VENUE_TOKENS and venue is None:
            venue = _VENUE_TOKENS[key]
            continue
        if weight_raw is None and _parse_weight(token) is not None:
            weight_raw = token
            continue
        return "", None, None, f"Anlaşılamayan argüman: <code>{token}</code>"

    weight = _parse_weight(weight_raw)
    if weight is None:
        return "", None, None, "Ağırlık 0–100 arası bir sayı olmalı."
    return ticker, venue, weight, None


def add_item(
    chat_id: int,
    ticker_raw: str,
    weight_raw: str | None = None,
    venue: str | None = None,
) -> AddResult:
    # Geriye uyum: weight_raw icinde venue olabilir diye bot tarafinda parse edilir.
    weight = _parse_weight(weight_raw) if weight_raw is not None else 0.0
    if weight is None:
        return AddResult(
            False,
            "Ağırlık 0–100 arası bir sayı olmalı. Örnek: <code>/sepetim ekle AAPL 25</code>",
        )

    meta = market.resolve_ticker_meta(ticker_raw, venue=venue)
    if meta is None:
        hint = ""
        if venue == "tefas" or tefas.looks_like_fund_code(ticker_raw):
            hint = (
                "\nTEFAS için: <code>/sepetim ekle MAC tefas</code>\n"
                "ABD hissesi zorlamak için: <code>/sepetim ekle MAC yahoo</code>"
            )
        return AddResult(
            False,
            "Sembol bulunamadı."
            + hint
            + "\nÖrnekler: <code>AAPL</code>, <code>THYAO.IS</code>, "
            "<code>MAC tefas</code>, <code>VWCE.DE</code>",
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
    venue_txt = " · <b>TEFAS</b>" if meta.get("venue") == "tefas" else f" · {meta.get('exchange') or 'Yahoo'}"
    return AddResult(
        True,
        f"✅ <b>{ticker}</b> ({meta['name']}) sepete {verb}{weight_txt}{venue_txt}.",
        item,
    )


def add_item_from_args(chat_id: int, args: list[str]) -> AddResult:
    ticker, venue, weight, err = _parse_add_args(args)
    if err:
        return AddResult(False, err)
    return add_item(chat_id, ticker, None if weight is None else str(weight), venue=venue)


def remove_item(chat_id: int, ticker_raw: str) -> AddResult:
    base = market.normalize_ticker(ticker_raw)
    if not base:
        return AddResult(False, "Silinecek ticker'ı yazın. Örnek: <code>/sepetim sil AAPL</code>")

    candidates = [base, tefas.storage_ticker(base) if not tefas.is_tefas_ticker(base) else base]
    if "." not in base and not tefas.is_tefas_ticker(base):
        candidates.append(f"{base}.IS")

    for cand in candidates:
        if storage.remove_watchlist_item(chat_id, cand):
            return AddResult(True, f"🗑️ <b>{cand}</b> sepetinden çıkarıldı.")

    code = tefas.strip_prefix(base)
    for row in storage.list_watchlist(chat_id):
        t = row["ticker"]
        if t == base or t.endswith(":" + code) or t.startswith(code + ".") or tefas.strip_prefix(t) == code:
            storage.remove_watchlist_item(chat_id, t)
            return AddResult(True, f"🗑️ <b>{t}</b> sepetinden çıkarıldı.")

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
    tokens = {
        item.ticker.lower(),
        tefas.strip_prefix(item.ticker).lower(),
        item.ticker.split(".")[0].lower(),
    }
    for part in re.split(r"[^A-Za-z0-9ÇĞİÖŞÜçğıöşü]+", item.name):
        if len(part) >= 4:
            tokens.add(news.normalize(part))
    return [t for t in tokens if t]


def related_news(chat_id: int, limit: int = 12) -> list[tuple[news.NewsItem, list[str]]]:
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


# --- Uyarilar --------------------------------------------------------------


def get_alert_threshold(chat_id: int) -> float | None:
    value = storage.get_state(f"{ALERT_STATE_PREFIX}{chat_id}")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def set_alert_threshold(chat_id: int, pct: float | None) -> AddResult:
    key = f"{ALERT_STATE_PREFIX}{chat_id}"
    if pct is None or pct <= 0:
        storage.set_state(key, None)
        return AddResult(True, "🔕 Sepet fiyat uyarısı kapatıldı.")
    if pct > 50:
        return AddResult(False, "Eşik 0–50% arasında olmalı. Örnek: <code>/sepetim uyari 3</code>")
    storage.set_state(key, pct)
    return AddResult(
        True,
        f"🔔 Uyarı açıldı: sepetindeki bir sembol <b>1 günde ±%{pct:g}</b> "
        "hareket ederse günlük özette haber veririm.",
    )


def alert_hits(chat_id: int, snap: WatchSnapshot | None = None) -> list[WatchItem]:
    threshold = get_alert_threshold(chat_id)
    if threshold is None or threshold <= 0:
        return []
    snap = snap or snapshot(chat_id)
    hits: list[WatchItem] = []
    for item in snap.items:
        if item.quote and abs(item.quote.change_1d_pct) >= threshold:
            hits.append(item)
    return hits


# --- Bot sepeti vs kullanici sepeti ----------------------------------------


def compare_to_bot(chat_id: int, risk_profile: str = "mid") -> CompareResult:
    snap = snapshot(chat_id)
    quotes = market.cached_quotes()
    # Bot sepetinin enstrumanlarindan agirlikli 20g (universe key'leri)
    row = storage.active_basket(risk_profile)
    bot_20d: float | None = None
    bot_name = risk_profile
    if row is not None:
        import json

        weights = json.loads(row["weights_json"])
        total = 0.0
        acc = 0.0
        for key, w in weights.items():
            if key in ("CASH",) or w <= 0:
                continue
            q = quotes.get(key)
            if q is None:
                continue
            acc += float(w) * q.change_20d_pct
            total += float(w)
        if total > 0:
            bot_20d = acc / total

    return CompareResult(
        watch_20d=snap.weighted_20d_pct,
        bot_20d=bot_20d,
        bot_profile=risk_profile,
        watch_items=len(snap.items),
        bot_name=bot_name,
    )
