"""Bot'un secim yapabildigi enstruman evreni."""

from __future__ import annotations

from dataclasses import dataclass

# Varlik siniflari
MONEY_MARKET = "money_market"
BIST_INDEX = "bist_index"
BIST_STOCK = "bist_stock"
GOLD = "gold"
FX = "fx"
GLOBAL_EQUITY = "global_equity"
CRYPTO = "crypto"
CASH = "cash"

ASSET_CLASS_LABELS_TR = {
    MONEY_MARKET: "Likit fon",
    BIST_INDEX: "BIST endeks",
    BIST_STOCK: "BIST hisse",
    GOLD: "Altın",
    FX: "Döviz",
    GLOBAL_EQUITY: "Global hisse",
    CRYPTO: "Kripto",
    CASH: "Nakit",
}


@dataclass(frozen=True)
class Instrument:
    key: str
    name: str
    asset_class: str
    ticker: str | None  # yfinance sembolu; None ise sentetik
    currency: str  # fiyatin kote edildigi para birimi
    sectors: tuple[str, ...] = ()
    note: str = ""

    @property
    def is_synthetic(self) -> bool:
        return self.ticker is None

    @property
    def asset_class_tr(self) -> str:
        return ASSET_CLASS_LABELS_TR.get(self.asset_class, self.asset_class)


# NOT: Sentetik enstrumanlar (nakit, para piyasasi) piyasa verisi cekmez;
# fiyatlari config'teki yillik orandan turetilir.
INSTRUMENTS: tuple[Instrument, ...] = (
    Instrument(
        key="MONEY_MARKET",
        name="Likit / para piyasası fonu",
        asset_class=MONEY_MARKET,
        ticker=None,
        currency="TRY",
        note="TCMB politika faizine yakin getiri varsayimiyla modellenir",
    ),
    Instrument(
        key="CASH",
        name="Nakit (TL)",
        asset_class=CASH,
        ticker=None,
        currency="TRY",
        note="Getiri uretmez, tampon olarak tutulur",
    ),
    Instrument(
        key="XU030",
        name="BIST 30 endeksi",
        asset_class=BIST_INDEX,
        ticker="XU030.IS",
        currency="TRY",
        note="BIST30 endeks fonu / ETF karsiligi olarak kullanilir",
    ),
    Instrument(
        key="XU100",
        name="BIST 100 endeksi",
        asset_class=BIST_INDEX,
        ticker="XU100.IS",
        currency="TRY",
        note="BIST100 endeks fonu / ETF karsiligi olarak kullanilir",
    ),
    Instrument(
        key="GARAN",
        name="Garanti Bankası",
        asset_class=BIST_STOCK,
        ticker="GARAN.IS",
        currency="TRY",
        sectors=("bankacilik", "finans"),
    ),
    Instrument(
        key="AKBNK",
        name="Akbank",
        asset_class=BIST_STOCK,
        ticker="AKBNK.IS",
        currency="TRY",
        sectors=("bankacilik", "finans"),
    ),
    Instrument(
        key="ISCTR",
        name="İş Bankası",
        asset_class=BIST_STOCK,
        ticker="ISCTR.IS",
        currency="TRY",
        sectors=("bankacilik", "finans"),
    ),
    Instrument(
        key="ASELS",
        name="Aselsan",
        asset_class=BIST_STOCK,
        ticker="ASELS.IS",
        currency="TRY",
        sectors=("savunma", "teknoloji"),
    ),
    Instrument(
        key="THYAO",
        name="Türk Hava Yolları",
        asset_class=BIST_STOCK,
        ticker="THYAO.IS",
        currency="TRY",
        sectors=("ulastirma", "turizm"),
    ),
    Instrument(
        key="BIMAS",
        name="BIM",
        asset_class=BIST_STOCK,
        ticker="BIMAS.IS",
        currency="TRY",
        sectors=("perakende", "defansif"),
    ),
    Instrument(
        key="MGROS",
        name="Migros",
        asset_class=BIST_STOCK,
        ticker="MGROS.IS",
        currency="TRY",
        sectors=("perakende", "defansif"),
    ),
    Instrument(
        key="TUPRS",
        name="Tüpraş",
        asset_class=BIST_STOCK,
        ticker="TUPRS.IS",
        currency="TRY",
        sectors=("enerji", "emtia"),
    ),
    Instrument(
        key="EREGL",
        name="Erdemir",
        asset_class=BIST_STOCK,
        ticker="EREGL.IS",
        currency="TRY",
        sectors=("sanayi", "emtia"),
    ),
    Instrument(
        key="KCHOL",
        name="Koç Holding",
        asset_class=BIST_STOCK,
        ticker="KCHOL.IS",
        currency="TRY",
        sectors=("holding",),
    ),
    Instrument(
        key="TCELL",
        name="Turkcell",
        asset_class=BIST_STOCK,
        ticker="TCELL.IS",
        currency="TRY",
        sectors=("telekom", "defansif"),
    ),
    Instrument(
        key="FROTO",
        name="Ford Otosan",
        asset_class=BIST_STOCK,
        ticker="FROTO.IS",
        currency="TRY",
        sectors=("otomotiv", "sanayi"),
    ),
    Instrument(
        key="SASA",
        name="Sasa Polyester",
        asset_class=BIST_STOCK,
        ticker="SASA.IS",
        currency="TRY",
        sectors=("kimya", "sanayi"),
    ),
    Instrument(
        key="GOLD_GRAM",
        name="Gram altın",
        asset_class=GOLD,
        ticker="GC=F",
        currency="USD_OUNCE",
        note="Ons altin ve USD/TRY uzerinden gram TL fiyatina cevrilir",
    ),
    Instrument(
        key="USDTRY",
        name="ABD Doları",
        asset_class=FX,
        ticker="USDTRY=X",
        currency="TRY",
    ),
    Instrument(
        key="EURTRY",
        name="Euro",
        asset_class=FX,
        ticker="EURTRY=X",
        currency="TRY",
    ),
    Instrument(
        key="SP500",
        name="S&P 500 (SPY)",
        asset_class=GLOBAL_EQUITY,
        ticker="SPY",
        currency="USD",
        sectors=("global", "genis endeks"),
    ),
    Instrument(
        key="NASDAQ",
        name="Nasdaq 100 (QQQ)",
        asset_class=GLOBAL_EQUITY,
        ticker="QQQ",
        currency="USD",
        sectors=("global", "teknoloji"),
    ),
    Instrument(
        key="BTC",
        name="Bitcoin",
        asset_class=CRYPTO,
        ticker="BTC-USD",
        currency="USD",
    ),
    Instrument(
        key="ETH",
        name="Ethereum",
        asset_class=CRYPTO,
        ticker="ETH-USD",
        currency="USD",
    ),
)

BY_KEY: dict[str, Instrument] = {inst.key: inst for inst in INSTRUMENTS}


def get(key: str) -> Instrument:
    return BY_KEY[key]


def by_asset_class(asset_class: str) -> list[Instrument]:
    return [inst for inst in INSTRUMENTS if inst.asset_class == asset_class]


def market_data_tickers() -> list[str]:
    """Piyasa verisi cekilecek semboller (sentetikler haric)."""
    return [inst.ticker for inst in INSTRUMENTS if inst.ticker]
