"""Risk profiline ve piyasa rejimine gore sepet uretimi."""

from __future__ import annotations

from dataclasses import dataclass

from . import market, universe
from .analysis import BALANCED, BEARISH, BULLISH, Analysis

LOW = "low"
MID = "mid"
HIGH = "high"

RISK_PROFILES = (LOW, MID, HIGH)

RISK_PROFILE_TR = {
    LOW: "Düşük risk",
    MID: "Orta risk",
    HIGH: "Yüksek risk",
}

RISK_PROFILE_EMOJI = {LOW: "🛡️", MID: "⚖️", HIGH: "🚀"}

RISK_PROFILE_DESC = {
    LOW: "Sermayeyi korumaya odaklı; ağırlık likit fon, altın ve endekste.",
    MID: "Dengeli büyüme; endeks, seçili hisse ve likit fon karışımı.",
    HIGH: "Büyüme odaklı; hisse ve global/kripto ağırlığı yüksek, dalgalanma fazla.",
}

# Varlik sinifi bazli hedef agirliklar (yuzde). Toplam her zaman 100.
# Pozisyon sayisi 4-6 enstruman + nakit tamponu olacak sekilde ayarlandi.
ALLOCATIONS: dict[str, dict[str, dict[str, float]]] = {
    LOW: {
        BULLISH: {
            universe.MONEY_MARKET: 40,
            universe.BIST_INDEX: 25,
            universe.GOLD: 15,
            universe.GLOBAL_EQUITY: 10,
            universe.FX: 5,
            universe.CASH: 5,
        },
        BALANCED: {
            universe.MONEY_MARKET: 50,
            universe.GOLD: 20,
            universe.BIST_INDEX: 15,
            universe.FX: 10,
            universe.CASH: 5,
        },
        BEARISH: {
            universe.MONEY_MARKET: 55,
            universe.GOLD: 20,
            universe.FX: 12,
            universe.BIST_INDEX: 8,
            universe.CASH: 5,
        },
    },
    MID: {
        BULLISH: {
            universe.BIST_STOCK: 25,
            universe.BIST_INDEX: 22,
            universe.MONEY_MARKET: 20,
            universe.GLOBAL_EQUITY: 15,
            universe.GOLD: 13,
            universe.CASH: 5,
        },
        BALANCED: {
            universe.MONEY_MARKET: 35,
            universe.BIST_INDEX: 18,
            universe.GOLD: 18,
            universe.BIST_STOCK: 12,
            universe.GLOBAL_EQUITY: 12,
            universe.CASH: 5,
        },
        BEARISH: {
            universe.MONEY_MARKET: 45,
            universe.GOLD: 22,
            universe.FX: 13,
            universe.BIST_INDEX: 10,
            universe.GLOBAL_EQUITY: 5,
            universe.CASH: 5,
        },
    },
    HIGH: {
        BULLISH: {
            universe.BIST_STOCK: 36,
            universe.GLOBAL_EQUITY: 20,
            universe.BIST_INDEX: 15,
            universe.CRYPTO: 12,
            universe.MONEY_MARKET: 12,
            universe.CASH: 5,
        },
        BALANCED: {
            universe.BIST_STOCK: 26,
            universe.MONEY_MARKET: 25,
            universe.GLOBAL_EQUITY: 15,
            universe.BIST_INDEX: 14,
            universe.GOLD: 12,
            universe.CASH: 8,
        },
        BEARISH: {
            universe.MONEY_MARKET: 38,
            universe.GOLD: 22,
            universe.FX: 15,
            universe.BIST_STOCK: 12,
            universe.GLOBAL_EQUITY: 8,
            universe.CASH: 5,
        },
    },
}

# BIST_STOCK agirliginin kac hisseye bolunecegi.
STOCK_COUNT: dict[str, dict[str, int]] = {
    LOW: {BULLISH: 0, BALANCED: 0, BEARISH: 0},
    MID: {BULLISH: 2, BALANCED: 1, BEARISH: 1},
    HIGH: {BULLISH: 3, BALANCED: 2, BEARISH: 1},
}

# Rejime gore hisse havuzu: yukseliste buyume, dususte defansif.
STOCK_POOL: dict[str, tuple[str, ...]] = {
    BULLISH: ("ASELS", "THYAO", "GARAN", "AKBNK", "ISCTR", "FROTO", "KCHOL", "SASA"),
    BALANCED: ("KCHOL", "GARAN", "TCELL", "BIMAS", "FROTO", "TUPRS", "AKBNK"),
    BEARISH: ("BIMAS", "MGROS", "TCELL", "TUPRS", "KCHOL"),
}

# Tek enstruman secilen varlik siniflarinda rejime gore tercih.
SINGLE_PICK: dict[str, dict[str, str]] = {
    universe.BIST_INDEX: {BULLISH: "XU100", BALANCED: "XU030", BEARISH: "XU030"},
    universe.GLOBAL_EQUITY: {BULLISH: "NASDAQ", BALANCED: "SP500", BEARISH: "SP500"},
    universe.GOLD: {BULLISH: "GOLD_GRAM", BALANCED: "GOLD_GRAM", BEARISH: "GOLD_GRAM"},
    universe.FX: {BULLISH: "USDTRY", BALANCED: "USDTRY", BEARISH: "USDTRY"},
    universe.CRYPTO: {BULLISH: "BTC", BALANCED: "BTC", BEARISH: "BTC"},
    universe.MONEY_MARKET: {BULLISH: "MONEY_MARKET", BALANCED: "MONEY_MARKET", BEARISH: "MONEY_MARKET"},
    universe.CASH: {BULLISH: "CASH", BALANCED: "CASH", BEARISH: "CASH"},
}

SECTOR_VIEW_BONUS = {"positive": 6.0, "neutral": 0.0, "negative": -6.0}


@dataclass
class Basket:
    risk_profile: str
    regime: str
    weights: dict[str, float]  # instrument_key -> yuzde
    rationale: str

    @property
    def instrument_count(self) -> int:
        return sum(1 for key in self.weights if key != "CASH")

    def sorted_items(self) -> list[tuple[str, float]]:
        return sorted(self.weights.items(), key=lambda kv: -kv[1])


def _stock_score(key: str, quotes: dict[str, market.Quote], analysis: Analysis) -> float:
    quote = quotes.get(key)
    if quote is None:
        return -1e9  # fiyati olmayan hisse secilemez

    # Momentum: 20 gunluk agirlikli, 5 gunluk destekleyici.
    score = 0.7 * quote.change_20d_pct + 0.3 * quote.change_5d_pct

    inst = universe.get(key)
    for sector in inst.sectors:
        view = analysis.sector_views.get(sector)
        if view:
            score += SECTOR_VIEW_BONUS.get(view, 0.0)
    return score


def _pick_stocks(
    regime: str,
    count: int,
    quotes: dict[str, market.Quote],
    analysis: Analysis,
) -> list[str]:
    if count <= 0:
        return []
    pool = STOCK_POOL[regime]
    # Deterministik siralama: skor sonra alfabetik (esitlikte sepet titremesini onler).
    ranked = sorted(pool, key=lambda key: (-_stock_score(key, quotes, analysis), key))
    return [key for key in ranked if quotes.get(key) is not None][:count]


def build(
    risk_profile: str,
    analysis: Analysis,
    quotes: dict[str, market.Quote],
) -> Basket:
    """Rejim + risk profili icin enstruman bazli sepet uretir."""
    regime = analysis.regime
    allocation = ALLOCATIONS[risk_profile][regime]
    weights: dict[str, float] = {}

    for asset_class, weight in allocation.items():
        if asset_class == universe.BIST_STOCK:
            count = STOCK_COUNT[risk_profile][regime]
            picks = _pick_stocks(regime, count, quotes, analysis)
            if not picks:
                # Hisse secilemezse agirligi endekse aktar (bosta birakmiyoruz).
                index_key = SINGLE_PICK[universe.BIST_INDEX][regime]
                weights[index_key] = weights.get(index_key, 0.0) + weight
                continue
            share = weight / len(picks)
            for key in picks:
                weights[key] = weights.get(key, 0.0) + share
            continue

        key = SINGLE_PICK[asset_class][regime]
        if key not in ("MONEY_MARKET", "CASH") and quotes.get(key) is None:
            # Fiyati alinamayan enstrumani likit fona kaydiriyoruz.
            weights["MONEY_MARKET"] = weights.get("MONEY_MARKET", 0.0) + weight
            continue
        weights[key] = weights.get(key, 0.0) + weight

    weights = _round_weights(weights)
    return Basket(
        risk_profile=risk_profile,
        regime=regime,
        weights=weights,
        rationale=_rationale(risk_profile, analysis),
    )


# Anlamsiz kalinti pozisyonlari (ornegin %2) tasimiyoruz; komisyon yer, takibi zorlastirir.
MIN_POSITION_WEIGHT = 3.0
MAX_POSITIONS = 8


def _round_weights(
    weights: dict[str, float], prune: bool = True
) -> dict[str, float]:
    """Agirliklari temizler, 0.1 hassasiyetine yuvarlar ve toplami 100'e sabitler."""
    cleaned = {key: value for key, value in weights.items() if value > 0.05}
    if not cleaned:
        return {"MONEY_MARKET": 100.0}

    if prune:
        # Nakit tamponu kucuk olabilir; esik disi tutuyoruz.
        cash = cleaned.pop("CASH", 0.0)
        keepers = {k: v for k, v in cleaned.items() if v >= MIN_POSITION_WEIGHT}
        if not keepers:
            keepers = {max(cleaned, key=lambda k: cleaned[k]): sum(cleaned.values())}
        if len(keepers) > MAX_POSITIONS:
            ranked = sorted(keepers.items(), key=lambda kv: -kv[1])[:MAX_POSITIONS]
            keepers = dict(ranked)

        # Elenen agirliklari kalanlara oransal dagitiyoruz ki toplam 100 kalsin.
        kept_total = sum(keepers.values())
        dropped = sum(cleaned.values()) - kept_total
        if kept_total > 0 and dropped > 0:
            keepers = {k: v + dropped * (v / kept_total) for k, v in keepers.items()}
        cleaned = keepers
        if cash > 0.05:
            cleaned["CASH"] = cash

    rounded = {key: round(value, 1) for key, value in cleaned.items()}
    difference = round(100.0 - sum(rounded.values()), 1)
    if abs(difference) >= 0.1:
        largest = max(rounded, key=lambda k: rounded[k])
        rounded[largest] = round(rounded[largest] + difference, 1)
    return rounded


def _rationale(risk_profile: str, analysis: Analysis) -> str:
    return (
        f"{RISK_PROFILE_TR[risk_profile]} profili, {analysis.regime} görüşü "
        f"(güven {analysis.confidence}/10, ufuk ~{analysis.horizon_weeks} hafta)."
    )


def build_all(
    analysis: Analysis, quotes: dict[str, market.Quote]
) -> dict[str, Basket]:
    return {profile: build(profile, analysis, quotes) for profile in RISK_PROFILES}


def weight_distance(old: dict[str, float], new: dict[str, float]) -> float:
    """Iki sepet arasindaki toplam mutlak agirlik farkinin yarisi (turnover %)."""
    keys = set(old) | set(new)
    return sum(abs(new.get(k, 0.0) - old.get(k, 0.0)) for k in keys) / 2.0


def blend(old: dict[str, float], new: dict[str, float], ratio: float) -> dict[str, float]:
    """Kademeli gecis: eski sepetten yeni sepete `ratio` oraninda yaklasir."""
    ratio = max(0.0, min(1.0, ratio))
    keys = set(old) | set(new)
    blended = {
        key: old.get(key, 0.0) * (1 - ratio) + new.get(key, 0.0) * ratio for key in keys
    }
    return _round_weights(blended)
