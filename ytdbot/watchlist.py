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
BUDGET_STATE_PREFIX = "watchlist_budget_try:"


@dataclass
class WatchItem:
    ticker: str
    weight: float
    name: str
    currency: str
    exchange: str
    quote: market.TickerQuote | None = None
    allocated_try: float | None = None  # butce * weight / 100
    approx_qty: float | None = None  # allocated / price_try


@dataclass
class WatchSnapshot:
    items: list[WatchItem] = field(default_factory=list)
    weight_sum: float = 0.0
    weighted_1d_pct: float | None = None
    weighted_5d_pct: float | None = None
    weighted_20d_pct: float | None = None
    budget_try: float | None = None
    allocated_sum_try: float | None = None
    approx_pnl_1d_try: float | None = None
    approx_pnl_20d_try: float | None = None


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


@dataclass
class WatchAnalysis:
    tone: str  # positive | mixed | negative
    confidence: int
    summary_tr: str
    drivers: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    highlights: list[str] = field(default_factory=list)
    news_count: int = 0
    source: str = "rule"
    weighted_1d_pct: float | None = None
    weighted_5d_pct: float | None = None
    weighted_20d_pct: float | None = None
    item_count: int = 0


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
    budget = get_budget(chat_id)
    if not rows:
        return WatchSnapshot(budget_try=budget)

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
        weight = float(row["weight"] or 0)
        allocated = (budget * weight / 100.0) if budget and weight > 0 else None
        qty = None
        if allocated is not None and q is not None and q.price_try > 0:
            qty = allocated / q.price_try
        items.append(
            WatchItem(
                ticker=row["ticker"],
                weight=weight,
                name=row["name"] or row["ticker"],
                currency=row["currency"] or "",
                exchange=row["exchange"] or "",
                quote=q,
                allocated_try=allocated,
                approx_qty=qty,
            )
        )

    weight_sum = sum(i.weight for i in items)
    snap = WatchSnapshot(items=items, weight_sum=weight_sum, budget_try=budget)

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

    allocated_items = [i for i in items if i.allocated_try is not None]
    if allocated_items:
        snap.allocated_sum_try = sum(i.allocated_try or 0 for i in allocated_items)
        if snap.weighted_1d_pct is not None and budget:
            snap.approx_pnl_1d_try = budget * snap.weighted_1d_pct / 100.0
        if snap.weighted_20d_pct is not None and budget:
            snap.approx_pnl_20d_try = budget * snap.weighted_20d_pct / 100.0

    return snap


def get_budget(chat_id: int) -> float | None:
    value = storage.get_state(f"{BUDGET_STATE_PREFIX}{chat_id}")
    if value is None:
        return None
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    return amount if amount > 0 else None


def set_budget(chat_id: int, amount: float | None) -> AddResult:
    key = f"{BUDGET_STATE_PREFIX}{chat_id}"
    if amount is None or amount <= 0:
        storage.set_state(key, None)
        return AddResult(True, "💵 Sepet bütçesi temizlendi.")
    if amount > 1_000_000_000:
        return AddResult(False, "Bütçe çok büyük. Makul bir TL tutarı girin.")
    storage.set_state(key, amount)
    pretty = f"{amount:,.0f}".replace(",", ".")
    return AddResult(
        True,
        f"💵 Sepet bütçesi <b>{pretty} TL</b> olarak ayarlandı.\n"
        "Ağırlıklı sembollerde tahmini tutar/adet gösterilir.\n"
        "<i>Kağıt üstü takip — gerçek işlem yapılmaz.</i>",
    )


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


WATCH_SYSTEM_PROMPT = """Sen temkinli bir portfoy gozlemcisisin. Kullanicinin kendi takip \
sepetini egitim amacli degerlendirirsin; yatirim tavsiyesi vermezsin, "al/sat" demezsin.

Kurallar:
- Sadece gecerli JSON dondur.
- Turkce yaz.
- Belirsizlikte "mixed" sec.
- Guven dusukse dusuk ver.

JSON semasi:
{
  "tone": "positive" | "mixed" | "negative",
  "confidence": 1-10,
  "summary_tr": "2-3 cumlelik sepet ozeti",
  "drivers": ["en fazla 4 somut gozlem"],
  "risks": ["en fazla 3 risk"],
  "highlights": ["tek sembole dair en fazla 4 dikkat ceken nokta"]
}"""


WATCH_USER_TEMPLATE = """## Kullanicinin takip sepeti
Butce: {budget}
{basket_block}

## Sepet ozeti (agirlikli, TL)
- 1g: {w1}
- 5g: {w5}
- 20g: {w20}

## Ilgili haber basliklari
{news_block}

Bu sepete ozel JSON degerlendirmesini uret."""


def _tone_from_pct(pct: float | None) -> str:
    if pct is None:
        return "mixed"
    if pct > 1.0:
        return "positive"
    if pct < -1.0:
        return "negative"
    return "mixed"


def _basket_prompt_block(snap: WatchSnapshot) -> str:
    lines: list[str] = []
    for item in snap.items:
        display = tefas.strip_prefix(item.ticker)
        venue = item.exchange or ("TEFAS" if tefas.is_tefas_ticker(item.ticker) else "")
        weight = f"%{item.weight:g}" if item.weight else "agirlik yok"
        if item.quote:
            q = item.quote
            lines.append(
                f"- {display} ({item.name}, {venue}): {weight} | "
                f"{q.price_try:,.2f} TL | 1g {q.change_1d_pct:+.2f}% | "
                f"5g {q.change_5d_pct:+.2f}% | 20g {q.change_20d_pct:+.2f}%"
            )
        else:
            lines.append(f"- {display} ({item.name}, {venue}): {weight} | fiyat yok")
    return "\n".join(lines) or "(bos sepet)"


def _analyze_watchlist_with_llm(
    snap: WatchSnapshot,
    matched_news: list[tuple[news.NewsItem, list[str]]],
) -> WatchAnalysis | None:
    if not settings.has_llm:
        return None
    try:
        import json as _json
        import re as _re

        import anthropic
    except ImportError:
        return None

    news_lines = []
    for article, tickers in matched_news[:20]:
        tag = ",".join(tefas.strip_prefix(t) for t in tickers[:3])
        news_lines.append(f"[T{article.tier}] ({tag}) {article.title}")

    def fmt(v: float | None) -> str:
        return "n/a" if v is None else f"{v:+.2f}%"

    prompt = WATCH_USER_TEMPLATE.format(
        budget=("yok" if snap.budget_try is None else f"{snap.budget_try:,.0f} TL"),
        basket_block=_basket_prompt_block(snap),
        w1=fmt(snap.weighted_1d_pct),
        w5=fmt(snap.weighted_5d_pct),
        w20=fmt(snap.weighted_20d_pct),
        news_block="\n".join(news_lines) or "(eslesen haber yok)",
    )

    try:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        response = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=1200,
            system=WATCH_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(block.text for block in response.content if block.type == "text")
    except Exception as exc:  # noqa: BLE001
        log.warning("Watchlist LLM analizi basarisiz: %s", exc)
        return None

    match = _re.search(r"\{.*\}", text, _re.DOTALL)
    if not match:
        return None
    try:
        data = _json.loads(match.group(0))
    except _json.JSONDecodeError:
        return None

    tone = str(data.get("tone", "mixed")).lower().strip()
    if tone not in ("positive", "mixed", "negative"):
        tone = "mixed"
    try:
        confidence = max(1, min(10, int(round(float(data.get("confidence", 5))))))
    except (TypeError, ValueError):
        confidence = 5

    return WatchAnalysis(
        tone=tone,
        confidence=confidence,
        summary_tr=str(data.get("summary_tr", "")).strip(),
        drivers=[str(d) for d in (data.get("drivers") or [])][:4],
        risks=[str(r) for r in (data.get("risks") or [])][:3],
        highlights=[str(h) for h in (data.get("highlights") or [])][:4],
        news_count=len(matched_news),
        source="llm",
        weighted_1d_pct=snap.weighted_1d_pct,
        weighted_5d_pct=snap.weighted_5d_pct,
        weighted_20d_pct=snap.weighted_20d_pct,
        item_count=len(snap.items),
    )


def _analyze_watchlist_with_rules(
    snap: WatchSnapshot,
    matched_news: list[tuple[news.NewsItem, list[str]]],
) -> WatchAnalysis:
    tone = _tone_from_pct(snap.weighted_20d_pct)
    pos = neg = 0
    for article, _ in matched_news:
        hay = news.normalize(article.title)
        if any(w in hay for w in ("yuksel", "artis", "rekor", "rally", "gain", "beat")):
            pos += 1
        if any(w in hay for w in ("dusus", "gerile", "zarar", "kriz", "fall", "drop", "loss")):
            neg += 1
    if pos > neg + 1 and tone == "mixed":
        tone = "positive"
    elif neg > pos + 1 and tone == "mixed":
        tone = "negative"

    movers = sorted(
        [i for i in snap.items if i.quote],
        key=lambda i: abs(i.quote.change_20d_pct),  # type: ignore[union-attr]
        reverse=True,
    )
    highlights: list[str] = []
    for item in movers[:4]:
        q = item.quote
        assert q is not None
        display = tefas.strip_prefix(item.ticker)
        highlights.append(
            f"{display}: 20g {q.change_20d_pct:+.1f}% · 1g {q.change_1d_pct:+.1f}%".replace(".", ",")
        )

    w20 = snap.weighted_20d_pct
    w20_txt = "bilinmiyor" if w20 is None else f"%{w20:+.1f}".replace(".", ",")
    tone_tr = {"positive": "olumlu", "mixed": "karışık", "negative": "temkinli"}[tone]
    drivers = [
        f"Ağırlıklı 20 günlük sepet getirisi {w20_txt}",
        f"Ağırlıklı 5 günlük getiri: "
        + (
            "n/a"
            if snap.weighted_5d_pct is None
            else f"%{snap.weighted_5d_pct:+.1f}".replace(".", ",")
        ),
        f"Eşleşen haber sayısı: {len(matched_news)}",
    ]
    if snap.weight_sum > 0 and abs(snap.weight_sum - 100) > 0.5:
        drivers.append(f"Ağırlık toplamı %{snap.weight_sum:.0f} (100 değil)")

    confidence = 5
    if snap.weighted_20d_pct is not None:
        confidence = max(3, min(7, 4 + int(abs(snap.weighted_20d_pct) / 2)))

    return WatchAnalysis(
        tone=tone,
        confidence=confidence,
        summary_tr=(
            f"Kural tabanlı sepet değerlendirmesi: görünüm {tone_tr}. "
            "LLM yoksa/başarısızsa yalnızca fiyat momentumu ve haber başlıkları kullanıldı; "
            "bu bir al/sat önerisi değildir."
        ),
        drivers=drivers,
        risks=[
            "Tek sembol veya sektör yoğunluğu riski kontrol edilmedi.",
            "Kural tabanlı model haber içeriğini derinlemesine yorumlamaz.",
        ],
        highlights=highlights,
        news_count=len(matched_news),
        source="rule",
        weighted_1d_pct=snap.weighted_1d_pct,
        weighted_5d_pct=snap.weighted_5d_pct,
        weighted_20d_pct=snap.weighted_20d_pct,
        item_count=len(snap.items),
    )


def analyze_watchlist(chat_id: int) -> WatchAnalysis | None:
    """Kullanici sepetine ozel analiz (LLM varsa onu, yoksa kural)."""
    snap = snapshot(chat_id)
    if not snap.items:
        return None
    matched = related_news(chat_id, limit=20)
    if settings.has_llm:
        llm = _analyze_watchlist_with_llm(snap, matched)
        if llm is not None:
            return llm
    return _analyze_watchlist_with_rules(snap, matched)


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
    """risk_profile: risk veya portfolio_key (ornek mid / mid_passive)."""
    from .baskets import parse_portfolio_key

    snap = snapshot(chat_id)
    quotes = market.cached_quotes()
    profile, pref = parse_portfolio_key(risk_profile)
    from .baskets import portfolio_key as _pkey

    storage_key = risk_profile if "_" in risk_profile else _pkey(profile, pref)
    row = storage.active_basket(storage_key)
    if row is None and storage_key != profile:
        row = storage.active_basket(profile)
    bot_20d: float | None = None
    bot_name = storage_key
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
        bot_profile=storage_key,
        watch_items=len(snap.items),
        bot_name=bot_name,
    )
