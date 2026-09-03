"""Veri kaynaklarinin canli calisip calismadigini dogrular (tek seferlik kontrol)."""

from __future__ import annotations

import sys

import feedparser
import yfinance as yf

TICKERS = [
    "XU030.IS",
    "XU100.IS",
    "GARAN.IS",
    "AKBNK.IS",
    "ISCTR.IS",
    "ASELS.IS",
    "THYAO.IS",
    "BIMAS.IS",
    "MGROS.IS",
    "TUPRS.IS",
    "EREGL.IS",
    "KCHOL.IS",
    "TCELL.IS",
    "FROTO.IS",
    "SASA.IS",
    "GC=F",
    "USDTRY=X",
    "EURTRY=X",
    "SPY",
    "QQQ",
    "BTC-USD",
    "ETH-USD",
]

FEEDS = [
    ("BloombergHT", "https://www.bloomberght.com/rss"),
    ("Investing TR", "https://tr.investing.com/rss/news.rss"),
    ("AA Ekonomi", "https://www.aa.com.tr/tr/rss/default?cat=ekonomi"),
    ("Dunya", "https://www.dunya.com/rss?dunya"),
    ("Yahoo Finance", "https://finance.yahoo.com/news/rssindex"),
    ("CNBC", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    ("Investing TR Ekonomi", "https://tr.investing.com/rss/news_14.rss"),
    ("NTV Ekonomi", "https://www.ntv.com.tr/ekonomi.rss"),
]


def check_tickers() -> None:
    print("=== TICKERS ===")
    data = yf.download(
        TICKERS,
        period="1mo",
        interval="1d",
        auto_adjust=True,
        progress=False,
        threads=True,
    )
    close = data["Close"]
    for ticker in TICKERS:
        try:
            series = close[ticker].dropna()
        except KeyError:
            print(f"  MISSING  {ticker}")
            continue
        if series.empty:
            print(f"  EMPTY    {ticker}")
        else:
            print(f"  OK       {ticker:12s} last={series.iloc[-1]:>14,.4f}  rows={len(series)}")


def check_feeds() -> None:
    print("\n=== RSS FEEDS ===")
    for name, url in FEEDS:
        try:
            parsed = feedparser.parse(url)
            count = len(parsed.entries)
            if count:
                sample = parsed.entries[0].get("title", "")[:70]
                print(f"  OK    {name:22s} entries={count:3d}  ornek: {sample}")
            else:
                print(f"  EMPTY {name:22s} url={url}")
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL  {name:22s} {exc}")


if __name__ == "__main__":
    check_tickers()
    check_feeds()
    sys.exit(0)
