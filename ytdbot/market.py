"""Piyasa verisi: yfinance'ten fiyat cekimi ve TL bazina cevirme."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

from . import storage, universe
from .config import settings

log = logging.getLogger(__name__)

OUNCE_IN_GRAM = 31.1034768

# Sentetik para piyasasi biriminin baslangic fiyati.
MONEY_MARKET_BASE_PRICE = 100.0
MM_EPOCH_STATE_KEY = "money_market_epoch"


@dataclass
class Quote:
    instrument_key: str
    price_try: float
    change_1d_pct: float
    change_5d_pct: float
    change_20d_pct: float
    as_of: datetime
    stale: bool = False

    @property
    def name(self) -> str:
        from . import funds

        if self.instrument_key in universe.BY_KEY:
            return universe.get(self.instrument_key).name
        return funds.display_name(self.instrument_key)


def _pct_change(series: pd.Series, periods: int) -> float:
    if len(series) <= periods:
        return 0.0
    previous = float(series.iloc[-1 - periods])
    if previous == 0:
        return 0.0
    return (float(series.iloc[-1]) / previous - 1.0) * 100.0


def _money_market_epoch() -> datetime:
    stored = storage.get_state(MM_EPOCH_STATE_KEY)
    if stored:
        parsed = storage.parse_iso(stored)
        if parsed:
            return parsed
    now = storage.utcnow()
    storage.set_state(MM_EPOCH_STATE_KEY, storage.iso(now))
    return now


def money_market_quote() -> Quote:
    """Likit fonu gunluk bilesik getiriyle modelleyen sentetik fiyat."""
    epoch = _money_market_epoch()
    now = storage.utcnow()
    days = max((now - epoch).total_seconds() / 86400.0, 0.0)
    daily = settings.money_market_daily_rate
    price = MONEY_MARKET_BASE_PRICE * (1.0 + daily) ** days
    return Quote(
        instrument_key="MONEY_MARKET",
        price_try=price,
        change_1d_pct=daily * 100.0,
        change_5d_pct=((1 + daily) ** 5 - 1) * 100.0,
        change_20d_pct=((1 + daily) ** 20 - 1) * 100.0,
        as_of=now,
    )


def cash_quote() -> Quote:
    return Quote(
        instrument_key="CASH",
        price_try=1.0,
        change_1d_pct=0.0,
        change_5d_pct=0.0,
        change_20d_pct=0.0,
        as_of=storage.utcnow(),
    )


def _download_close(tickers: list[str], period: str = "3mo") -> pd.DataFrame:
    data = yf.download(
        tickers,
        period=period,
        interval="1d",
        auto_adjust=True,
        progress=False,
        threads=True,
    )
    if data is None or data.empty:
        return pd.DataFrame()
    close = data["Close"]
    if isinstance(close, pd.Series):  # tek sembol istendiginde
        close = close.to_frame(name=tickers[0])
    return close.ffill()


def fetch_quotes() -> dict[str, Quote]:
    """Tum enstrumanlar icin TL bazli guncel fiyat ve momentum verisi.

    yfinance basarisiz olursa onbellekteki son fiyatlar `stale` isaretiyle kullanilir.
    """
    quotes: dict[str, Quote] = {
        "MONEY_MARKET": money_market_quote(),
        "CASH": cash_quote(),
    }

    tickers = list(universe.market_data_tickers())
    try:
        from . import funds

        for yt in funds.yahoo_fund_tickers():
            if yt not in tickers:
                tickers.append(yt)
    except Exception:  # noqa: BLE001
        pass

    close = pd.DataFrame()
    try:
        close = _download_close(tickers)
    except Exception as exc:  # noqa: BLE001 - ag hatalarinda onbellege dusuyoruz
        log.warning("Piyasa verisi cekilemedi: %s", exc)

    usdtry_series: pd.Series | None = None
    if "USDTRY=X" in close.columns:
        candidate = close["USDTRY=X"].dropna()
        if not candidate.empty:
            usdtry_series = candidate

    for inst in universe.INSTRUMENTS:
        if inst.is_synthetic:
            continue

        series: pd.Series | None = None
        if inst.ticker in close.columns:
            raw = close[inst.ticker].dropna()
            if not raw.empty:
                series = raw

        if series is None:
            continue

        try_series = _to_try_series(inst, series, usdtry_series)
        if try_series is None or try_series.empty:
            continue

        last_index = try_series.index[-1]
        as_of = (
            last_index.to_pydatetime().replace(tzinfo=timezone.utc)
            if hasattr(last_index, "to_pydatetime")
            else storage.utcnow()
        )
        quotes[inst.key] = Quote(
            instrument_key=inst.key,
            price_try=float(try_series.iloc[-1]),
            change_1d_pct=_pct_change(try_series, 1),
            change_5d_pct=_pct_change(try_series, 5),
            change_20d_pct=_pct_change(try_series, 20),
            as_of=as_of,
        )

    _merge_yahoo_funds(quotes, close, usdtry_series)
    _fill_from_cache(quotes)

    # Opsiyonel TEFAS fon katalogu
    try:
        from . import funds, tefas

        tefas_quotes = tefas.fetch_quotes(funds.tefas_codes())
        for key, tq in tefas_quotes.items():
            quotes[key] = Quote(
                instrument_key=key,
                price_try=tq.price_try,
                change_1d_pct=tq.change_1d_pct,
                change_5d_pct=tq.change_5d_pct,
                change_20d_pct=tq.change_20d_pct,
                as_of=tq.as_of,
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("TEFAS fon fiyatlari sepete eklenemedi: %s", exc)

    storage.save_prices(
        {
            key: {
                "price_try": q.price_try,
                "change_1d_pct": q.change_1d_pct,
                "change_5d_pct": q.change_5d_pct,
                "change_20d_pct": q.change_20d_pct,
                "as_of": storage.iso(q.as_of),
            }
            for key, q in quotes.items()
            if not q.stale
        }
    )
    return quotes


def _to_try_series(
    inst: universe.Instrument,
    series: pd.Series,
    usdtry_series: pd.Series | None,
) -> pd.Series | None:
    """Enstrumanin fiyat serisini TL bazina cevirir."""
    if inst.currency == "TRY":
        return series

    if usdtry_series is None:
        return None

    aligned = usdtry_series.reindex(series.index).ffill().bfill()

    if inst.currency == "USD":
        return series * aligned
    if inst.currency == "USD_OUNCE":  # ons altin -> gram altin TL
        return series * aligned / OUNCE_IN_GRAM
    return None


def _merge_yahoo_funds(
    quotes: dict[str, Quote],
    close: pd.DataFrame,
    usdtry_series: pd.Series | None,
) -> None:
    """Katalogdaki yabanci ETF'leri (YF:XXX) TL fiyata cevirip quotes'a ekler."""
    from . import funds

    if close is None or close.empty or usdtry_series is None:
        return

    for fund in funds.FUNDS:
        if fund.venue != funds.VENUE_YAHOO or not fund.yahoo_ticker:
            continue
        ticker = fund.yahoo_ticker
        if ticker not in close.columns:
            continue
        series = close[ticker].dropna()
        if series.empty:
            continue
        aligned = usdtry_series.reindex(series.index).ffill().bfill()
        try_series = series * aligned
        if try_series.empty:
            continue
        last_index = try_series.index[-1]
        as_of = (
            last_index.to_pydatetime().replace(tzinfo=timezone.utc)
            if hasattr(last_index, "to_pydatetime")
            else storage.utcnow()
        )
        quotes[fund.key] = Quote(
            instrument_key=fund.key,
            price_try=float(try_series.iloc[-1]),
            change_1d_pct=_pct_change(try_series, 1),
            change_5d_pct=_pct_change(try_series, 5),
            change_20d_pct=_pct_change(try_series, 20),
            as_of=as_of,
        )


def _fill_from_cache(quotes: dict[str, Quote]) -> None:
    """Canli veri gelmeyen enstrumanlar icin onbellegi kullanir."""
    missing = [
        inst.key
        for inst in universe.INSTRUMENTS
        if not inst.is_synthetic and inst.key not in quotes
    ]
    if not missing:
        return

    cached = storage.load_cached_prices()
    for key in missing:
        row = cached.get(key)
        if not row:
            log.warning("%s icin ne canli ne onbellek fiyati var, atlaniyor", key)
            continue
        quotes[key] = Quote(
            instrument_key=key,
            price_try=float(row["price_try"]),
            change_1d_pct=float(row["change_1d_pct"]),
            change_5d_pct=float(row["change_5d_pct"]),
            change_20d_pct=float(row["change_20d_pct"]),
            as_of=storage.parse_iso(row["as_of"]) or storage.utcnow(),
            stale=True,
        )
    log.info("Onbellekten doldurulan enstruman sayisi: %d", len(missing))


def cached_quotes() -> dict[str, Quote]:
    """Onbellekten hizli fiyat okuma; bot komutlari icin kullanilir.

    `fetch_quotes` ag cagrisi yaptigi icin yavastir ve sadece analiz dongusunde
    calistirilir. Komutlar son dongude kaydedilen fiyatlari okur.
    """
    quotes: dict[str, Quote] = {
        "MONEY_MARKET": money_market_quote(),
        "CASH": cash_quote(),
    }
    for key, row in storage.load_cached_prices().items():
        if key in quotes:
            continue
        # Universe veya TEFAS fon anahtarlari
        if (
            key not in universe.BY_KEY
            and not key.startswith("TEFAS:")
            and not key.startswith("YF:")
        ):
            continue
        quotes[key] = Quote(
            instrument_key=key,
            price_try=float(row["price_try"]),
            change_1d_pct=float(row["change_1d_pct"]),
            change_5d_pct=float(row["change_5d_pct"]),
            change_20d_pct=float(row["change_20d_pct"]),
            as_of=storage.parse_iso(row["as_of"]) or storage.utcnow(),
        )
    return quotes


def market_snapshot_text(quotes: dict[str, Quote]) -> str:
    """LLM'e verilecek kompakt piyasa ozeti."""
    lines = []
    for inst in universe.INSTRUMENTS:
        q = quotes.get(inst.key)
        if q is None or inst.key == "CASH":
            continue
        lines.append(
            f"{inst.name} ({inst.asset_class_tr}): {q.price_try:,.2f} TL | "
            f"1g {q.change_1d_pct:+.2f}% | 5g {q.change_5d_pct:+.2f}% | 20g {q.change_20d_pct:+.2f}%"
        )
    return "\n".join(lines)


def breadth_score(quotes: dict[str, Quote]) -> float:
    """BIST hisselerinin kacinin 20 gunluk momentumu pozitif (0-1)."""
    stocks = [
        quotes[inst.key]
        for inst in universe.by_asset_class(universe.BIST_STOCK)
        if inst.key in quotes
    ]
    if not stocks:
        return 0.5
    positive = sum(1 for q in stocks if q.change_20d_pct > 0)
    return positive / len(stocks)


# --- Harici ticker'lar (kullanici sepeti) -----------------------------------


@dataclass
class TickerQuote:
    ticker: str
    price_native: float
    price_try: float
    currency: str
    change_1d_pct: float
    change_5d_pct: float
    change_20d_pct: float
    as_of: datetime
    name: str = ""
    exchange: str = ""


_FX_PAIR_BY_CURRENCY = {
    "TRY": None,
    "USD": "USDTRY=X",
    "EUR": "EURTRY=X",
    "GBP": "GBPTRY=X",
    "JPY": "JPYTRY=X",
    "CHF": "CHFTRY=X",
    "CAD": "CADTRY=X",
    "AUD": "AUDTRY=X",
}


def normalize_ticker(raw: str) -> str:
    return re.sub(r"\s+", "", (raw or "").strip().upper())


def resolve_ticker_meta(raw: str, venue: str | None = None) -> dict[str, str] | None:
    """Ticker cozumler. venue: tefas | yahoo | None (otomatik).

    Kisa TR fon kodlari (MAC, TTE...) Yahoo'da ABD hissesiyle carpisir (NYSE/PCX).
    Otomatik modda noktasiz 2-5 harfli kodlarda once TEFAS denenir.
    """
    from . import tefas

    base = normalize_ticker(raw)
    if not base or len(base) > 40:
        return None

    forced = (venue or "").strip().lower()
    if base.startswith(tefas.TEFAS_PREFIX):
        forced = "tefas"

    if forced in ("tefas", "tefaş", "fon"):
        meta = tefas.resolve_fund(base)
        if meta is None:
            return None
        return {
            "ticker": tefas.storage_ticker(meta.code),
            "name": meta.name,
            "currency": "TRY",
            "exchange": "TEFAS",
            "venue": "tefas",
            "category": meta.category,
        }

    if forced in ("yahoo", "yf", "us", "bist"):
        return _resolve_yahoo(base, prefer_is=(forced == "bist"))

    # Otomatik: kisa kod -> once TEFAS
    if tefas.looks_like_fund_code(base) and "." not in base and not base.endswith("=X"):
        meta = tefas.resolve_fund(base)
        if meta is not None:
            return {
                "ticker": tefas.storage_ticker(meta.code),
                "name": meta.name,
                "currency": "TRY",
                "exchange": "TEFAS",
                "venue": "tefas",
                "category": meta.category,
            }

    return _resolve_yahoo(base, prefer_is=False)


def _resolve_yahoo(base: str, prefer_is: bool) -> dict[str, str] | None:
    candidates: list[str] = []
    clean = base
    if clean.startswith("TEFAS:"):
        return None
    if prefer_is and "." not in clean:
        candidates.append(f"{clean}.IS")
        candidates.append(clean)
    else:
        candidates.append(clean)
        if "." not in clean and not clean.endswith("=X"):
            candidates.append(f"{clean}.IS")

    for cand in candidates:
        try:
            ticker = yf.Ticker(cand)
            hist = ticker.history(period="5d", auto_adjust=True)
            if hist is None or hist.empty:
                continue
            info: dict = {}
            try:
                info = ticker.info or {}
            except Exception:  # noqa: BLE001
                info = {}
            currency = str(info.get("currency") or "").upper() or "USD"
            name = (
                str(info.get("shortName") or info.get("longName") or cand).strip() or cand
            )
            exchange = str(info.get("exchange") or info.get("fullExchangeName") or "").strip()
            return {
                "ticker": cand,
                "name": name[:120],
                "currency": currency,
                "exchange": exchange[:40],
                "venue": "yahoo",
                "category": "",
            }
        except Exception as exc:  # noqa: BLE001
            log.debug("Ticker cozumlenemedi (%s): %s", cand, exc)
            continue
    return None


def fetch_ticker_quotes(
    tickers: list[str],
    meta_by_ticker: dict[str, dict[str, str]] | None = None,
) -> dict[str, TickerQuote]:
    """Harici ticker listesi icin TL bazli fiyat/momentum (Yahoo + TEFAS)."""
    if not tickers:
        return {}

    from . import tefas

    meta_by_ticker = meta_by_ticker or {}
    unique = list(dict.fromkeys(tickers))
    tefas_tickers = [t for t in unique if tefas.is_tefas_ticker(t)]
    yahoo_tickers = [t for t in unique if not tefas.is_tefas_ticker(t)]

    result: dict[str, TickerQuote] = {}

    if tefas_tickers:
        for key, q in tefas.fetch_quotes(tefas_tickers).items():
            result[key] = TickerQuote(
                ticker=key,
                price_native=q.price_try,
                price_try=q.price_try,
                currency="TRY",
                change_1d_pct=q.change_1d_pct,
                change_5d_pct=q.change_5d_pct,
                change_20d_pct=q.change_20d_pct,
                as_of=q.as_of,
                name=q.name,
                exchange="TEFAS",
            )

    if not yahoo_tickers:
        return result

    currencies = {
        (meta_by_ticker.get(t) or {}).get("currency", "USD").upper() for t in yahoo_tickers
    }
    fx_pairs = [
        pair
        for cur in currencies
        if (pair := _FX_PAIR_BY_CURRENCY.get(cur)) is not None
    ]
    if any(cur not in _FX_PAIR_BY_CURRENCY for cur in currencies):
        if "USDTRY=X" not in fx_pairs:
            fx_pairs.append("USDTRY=X")

    download_list = yahoo_tickers + fx_pairs
    try:
        close = _download_close(download_list, period="3mo")
    except Exception as exc:  # noqa: BLE001
        log.warning("Harici ticker fiyatlari cekilemedi: %s", exc)
        return result

    if close.empty:
        return result

    fx_series: dict[str, pd.Series] = {}
    for pair in fx_pairs:
        if pair in close.columns:
            series = close[pair].dropna()
            if not series.empty:
                fx_series[pair] = series

    usdtry = fx_series.get("USDTRY=X")

    for ticker in yahoo_tickers:
        if ticker not in close.columns:
            continue
        series = close[ticker].dropna()
        if series.empty:
            continue

        meta = meta_by_ticker.get(ticker) or {}
        currency = str(meta.get("currency") or "USD").upper()
        try_series = _external_to_try(series, currency, fx_series, usdtry)
        if try_series is None or try_series.empty:
            continue

        last_index = try_series.index[-1]
        as_of = (
            last_index.to_pydatetime().replace(tzinfo=timezone.utc)
            if hasattr(last_index, "to_pydatetime")
            else storage.utcnow()
        )
        result[ticker] = TickerQuote(
            ticker=ticker,
            price_native=float(series.iloc[-1]),
            price_try=float(try_series.iloc[-1]),
            currency=currency,
            change_1d_pct=_pct_change(try_series, 1),
            change_5d_pct=_pct_change(try_series, 5),
            change_20d_pct=_pct_change(try_series, 20),
            as_of=as_of,
            name=str(meta.get("name") or ticker),
            exchange=str(meta.get("exchange") or ""),
        )
    return result


def _external_to_try(
    series: pd.Series,
    currency: str,
    fx_series: dict[str, pd.Series],
    usdtry: pd.Series | None,
) -> pd.Series | None:
    if currency == "TRY":
        return series

    pair = _FX_PAIR_BY_CURRENCY.get(currency)
    if pair and pair in fx_series:
        aligned = fx_series[pair].reindex(series.index).ffill().bfill()
        return series * aligned

    if usdtry is not None and currency == "USD":
        aligned = usdtry.reindex(series.index).ffill().bfill()
        return series * aligned

    if usdtry is not None and currency not in _FX_PAIR_BY_CURRENCY:
        aligned = usdtry.reindex(series.index).ffill().bfill()
        return series * aligned

    return None
