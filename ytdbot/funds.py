"""Opsiyonel fon / ETF katalogu (TEFAS + yabanci).

Bot sepeti zorunlu fon degildir; hisse, endeks, altin vb. de secilebilir.
Fon onerildiginde TEFAS veya yabanci (Yahoo) araclar arasindan secilir.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import tefas

# Rol siniflari (hangi varlik sinifina alternatif oldugu)
MONEY_MARKET = "money_market"
GOLD = "gold"
DEBT = "debt"
EQUITY_INDEX = "equity_index"
EQUITY_GROWTH = "equity_growth"
EQUITY_DIVIDEND = "equity_dividend"
FOREIGN = "foreign"
FLEXIBLE = "flexible"
CASH = "cash"

VENUE_TEFAS = "tefas"
VENUE_YAHOO = "yahoo"

ROLE_LABELS_TR = {
    MONEY_MARKET: "Para piyasası fonu",
    GOLD: "Altın fonu",
    DEBT: "Borçlanma araçları fonu",
    EQUITY_INDEX: "Endeks hisse fonu",
    EQUITY_GROWTH: "Büyüme hisse fonu",
    EQUITY_DIVIDEND: "Temettü hisse / ETF",
    FOREIGN: "Yabancı hisse fonu / ETF",
    FLEXIBLE: "Değişken fon",
    CASH: "Nakit",
}

INCOME_GROWTH = "growth"
INCOME_PASSIVE = "passive"

INCOME_PREFS = (INCOME_GROWTH, INCOME_PASSIVE)

INCOME_PREF_TR = {
    INCOME_GROWTH: "Büyüme (temettü öncelikli değil)",
    INCOME_PASSIVE: "Pasif gelir (temettü / sabit getirili)",
}

INCOME_PREF_EMOJI = {INCOME_GROWTH: "🚀", INCOME_PASSIVE: "💰"}

INCOME_PREF_DESC = {
    INCOME_GROWTH: "Büyüme odaklı hisse, endeks ve yerli/yabancı fon karışımı.",
    INCOME_PASSIVE: "Temettü hisseleri, temettü ETF/fonları ve borçlanma ağırlıklı.",
}


@dataclass(frozen=True)
class Fund:
    code: str
    name: str
    role: str
    venue: str = VENUE_TEFAS  # tefas | yahoo
    yahoo_ticker: str | None = None  # venue=yahoo icin yfinance sembolu
    passive: bool = False
    note: str = ""

    @property
    def key(self) -> str:
        if self.venue == VENUE_YAHOO:
            return f"YF:{self.code.upper()}"
        return tefas.storage_ticker(self.code)

    @property
    def role_tr(self) -> str:
        return ROLE_LABELS_TR.get(self.role, self.role)

    @property
    def venue_tr(self) -> str:
        return "TEFAS" if self.venue == VENUE_TEFAS else "Yabancı ETF"


# El ile secilmis fon / ETF'ler — sepette hisseye alternatif olabilirler.
FUNDS: tuple[Fund, ...] = (
    # --- TEFAS ---
    Fund("AAL", "Ata Portföy Para Piyasası (TL) Fonu", MONEY_MARKET),
    Fund("AIS", "Ak Portföy Para Piyasası Katılım Fonu", MONEY_MARKET),
    Fund("HAI", "Ahlatcı Portföy Altın Fonu", GOLD),
    Fund("AFO", "Ak Portföy Altın Fonu", GOLD),
    Fund("NJR", "Nurol Portföy Birinci Borçlanma Araçları Fonu", DEBT, passive=True),
    Fund("AHU", "Atlas Portföy Özel Sektör Borçlanma Araçları Fonu", DEBT, passive=True),
    Fund("AKU", "Ak Portföy BIST 30 Endeksi Hisse Senedi Fonu", EQUITY_INDEX),
    Fund("TTE", "İş Portföy BIST Teknoloji Endeksi Hisse Fonu", EQUITY_GROWTH),
    Fund("MAC", "Marmara Capital Portföy Hisse Senedi Fonu", EQUITY_GROWTH),
    Fund("AAV", "Ata Portföy İkinci Hisse Senedi Fonu", EQUITY_GROWTH),
    Fund("DPT", "Deniz Portföy BIST Temettü 25 Endeksi Hisse Fonu", EQUITY_DIVIDEND, passive=True),
    Fund("DTM", "Deniz Portföy Temettü Ödeyen Şirketler Değişken Fon", EQUITY_DIVIDEND, passive=True),
    Fund("GTM", "Garanti Portföy Temettü Ödeyen Şirketler Hisse Fonu", EQUITY_DIVIDEND, passive=True),
    Fund("ITC", "Inveo Portföy Temettü Ödeyen Şirketler Hisse Fonu", EQUITY_DIVIDEND, passive=True),
    Fund("AFT", "Ak Portföy Yeni Teknolojiler Yabancı Hisse Fonu", FOREIGN),
    Fund("YAY", "Yapı Kredi Portföy Yabancı Teknoloji Hisse Fonu", FOREIGN),
    Fund("IPB", "İstanbul Portföy Birinci Değişken Fon", FLEXIBLE),
    # --- Yabanci ETF (Yahoo) ---
    Fund(
        "SCHD",
        "Schwab US Dividend Equity ETF",
        EQUITY_DIVIDEND,
        venue=VENUE_YAHOO,
        yahoo_ticker="SCHD",
        passive=True,
        note="ABD temettü ETF",
    ),
    Fund(
        "VIG",
        "Vanguard Dividend Appreciation ETF",
        EQUITY_DIVIDEND,
        venue=VENUE_YAHOO,
        yahoo_ticker="VIG",
        passive=True,
        note="ABD temettü büyüme ETF",
    ),
    Fund(
        "VXUS",
        "Vanguard Total International Stock ETF",
        FOREIGN,
        venue=VENUE_YAHOO,
        yahoo_ticker="VXUS",
        note="ABD dışı hisse ETF",
    ),
    Fund(
        "EEM",
        "iShares MSCI Emerging Markets ETF",
        FOREIGN,
        venue=VENUE_YAHOO,
        yahoo_ticker="EEM",
        note="Gelişmekte olan piyasalar",
    ),
)

BY_KEY: dict[str, Fund] = {f.key: f for f in FUNDS}
BY_CODE: dict[str, Fund] = {f.code.upper(): f for f in FUNDS}


def is_fund_key(key: str) -> bool:
    return key in BY_KEY or tefas.is_tefas_ticker(key) or key.startswith("YF:")


def get(key: str) -> Fund | None:
    if key in BY_KEY:
        return BY_KEY[key]
    if key.startswith("YF:"):
        return BY_CODE.get(key[3:].upper())
    code = tefas.strip_prefix(key)
    return BY_CODE.get(code.upper())


def display_name(key: str) -> str:
    if key == "CASH":
        return "Nakit (TL)"
    fund = get(key)
    if fund:
        tag = fund.venue_tr
        return f"{fund.code} — {fund.name} ({tag})"
    if tefas.is_tefas_ticker(key):
        return tefas.strip_prefix(key)
    return key


def display_code(key: str) -> str:
    if key == "CASH":
        return "CASH"
    fund = get(key)
    if fund:
        return fund.code
    if key.startswith("YF:"):
        return key[3:]
    return tefas.strip_prefix(key)


def by_role(role: str) -> list[Fund]:
    return [f for f in FUNDS if f.role == role]


def pool_for(role: str, income_pref: str) -> list[Fund]:
    """Rol + gelir tercihine gore fon/ETF havuzu (her iki venue)."""
    items = by_role(role)
    if not items:
        return []
    if income_pref == INCOME_PASSIVE:
        preferred = [f for f in items if f.passive]
        return preferred or items
    growth = [f for f in items if not f.passive]
    return growth or items


def tefas_codes() -> list[str]:
    return [f.code for f in FUNDS if f.venue == VENUE_TEFAS]


def yahoo_fund_tickers() -> list[str]:
    return [f.yahoo_ticker for f in FUNDS if f.venue == VENUE_YAHOO and f.yahoo_ticker]


def all_codes() -> list[str]:
    """Geriye uyum: TEFAS kodlari."""
    return tefas_codes()
