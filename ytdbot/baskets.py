"""Risk profili + gelir tercihine gore karisik sepet uretimi.

Hisse, endeks, altin, döviz, kripto ve (isteğe bağlı) TEFAS / yabancı fon-ETF
birlikte seçilebilir. Fon zorunlu değildir; skor yüksekse fon veya doğrudan
enstrüman seçilir.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import funds, market, universe
from .analysis import BALANCED, BEARISH, BULLISH, Analysis
from .funds import (
    DEBT,
    EQUITY_DIVIDEND,
    EQUITY_GROWTH,
    EQUITY_INDEX,
    FOREIGN,
    INCOME_GROWTH,
    INCOME_PASSIVE,
    INCOME_PREF_DESC,
    INCOME_PREF_EMOJI,
    INCOME_PREF_TR,
    INCOME_PREFS,
    MONEY_MARKET,
)

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
    LOW: "Sermayeyi korumaya odaklı; likit, altın, endeks ve isteğe bağlı fonlar.",
    MID: "Dengeli; hisse/endeks + likit + altın; uygunsa yerli/yabancı fon.",
    HIGH: "Büyüme odaklı; hisse, global ve isteğe bağlı fon/ETF ağırlığı yüksek.",
}

# risk x income x regime -> varlik sinifi agirliklari (%)
ALLOCATIONS: dict[str, dict[str, dict[str, dict[str, float]]]] = {
    LOW: {
        INCOME_GROWTH: {
            BULLISH: {
                universe.MONEY_MARKET: 35,
                universe.BIST_INDEX: 25,
                universe.GOLD: 15,
                universe.GLOBAL_EQUITY: 10,
                universe.FX: 5,
                universe.CASH: 10,
            },
            BALANCED: {
                universe.MONEY_MARKET: 45,
                universe.GOLD: 20,
                universe.BIST_INDEX: 15,
                universe.FX: 10,
                universe.CASH: 10,
            },
            BEARISH: {
                universe.MONEY_MARKET: 50,
                universe.GOLD: 20,
                universe.FX: 12,
                universe.BIST_INDEX: 8,
                universe.CASH: 10,
            },
        },
        INCOME_PASSIVE: {
            BULLISH: {
                universe.MONEY_MARKET: 30,
                DEBT: 20,
                universe.BIST_INDEX: 15,
                universe.GOLD: 15,
                EQUITY_DIVIDEND: 10,
                universe.CASH: 10,
            },
            BALANCED: {
                universe.MONEY_MARKET: 40,
                DEBT: 20,
                universe.GOLD: 15,
                EQUITY_DIVIDEND: 10,
                universe.FX: 5,
                universe.CASH: 10,
            },
            BEARISH: {
                universe.MONEY_MARKET: 45,
                DEBT: 25,
                universe.GOLD: 15,
                universe.CASH: 15,
            },
        },
    },
    MID: {
        INCOME_GROWTH: {
            BULLISH: {
                universe.BIST_STOCK: 25,
                universe.BIST_INDEX: 20,
                universe.MONEY_MARKET: 18,
                universe.GLOBAL_EQUITY: 15,
                universe.GOLD: 12,
                universe.CASH: 10,
            },
            BALANCED: {
                universe.MONEY_MARKET: 30,
                universe.BIST_INDEX: 18,
                universe.GOLD: 15,
                universe.BIST_STOCK: 12,
                universe.GLOBAL_EQUITY: 12,
                universe.CASH: 13,
            },
            BEARISH: {
                universe.MONEY_MARKET: 40,
                universe.GOLD: 20,
                universe.FX: 12,
                universe.BIST_INDEX: 10,
                universe.GLOBAL_EQUITY: 8,
                universe.CASH: 10,
            },
        },
        INCOME_PASSIVE: {
            BULLISH: {
                EQUITY_DIVIDEND: 22,
                universe.BIST_STOCK: 18,
                universe.MONEY_MARKET: 20,
                DEBT: 12,
                universe.GOLD: 13,
                universe.CASH: 15,
            },
            BALANCED: {
                universe.MONEY_MARKET: 28,
                EQUITY_DIVIDEND: 18,
                DEBT: 15,
                universe.GOLD: 15,
                universe.BIST_STOCK: 10,
                universe.CASH: 14,
            },
            BEARISH: {
                universe.MONEY_MARKET: 38,
                DEBT: 20,
                universe.GOLD: 18,
                EQUITY_DIVIDEND: 10,
                universe.CASH: 14,
            },
        },
    },
    HIGH: {
        INCOME_GROWTH: {
            BULLISH: {
                universe.BIST_STOCK: 32,
                universe.GLOBAL_EQUITY: 18,
                universe.BIST_INDEX: 14,
                universe.CRYPTO: 10,
                universe.MONEY_MARKET: 12,
                universe.CASH: 14,
            },
            BALANCED: {
                universe.BIST_STOCK: 24,
                universe.MONEY_MARKET: 22,
                universe.GLOBAL_EQUITY: 15,
                universe.BIST_INDEX: 12,
                universe.GOLD: 12,
                universe.CASH: 15,
            },
            BEARISH: {
                universe.MONEY_MARKET: 35,
                universe.GOLD: 20,
                universe.FX: 12,
                universe.BIST_STOCK: 12,
                universe.GLOBAL_EQUITY: 8,
                universe.CASH: 13,
            },
        },
        INCOME_PASSIVE: {
            BULLISH: {
                EQUITY_DIVIDEND: 28,
                universe.BIST_STOCK: 18,
                universe.GLOBAL_EQUITY: 12,
                DEBT: 12,
                universe.MONEY_MARKET: 15,
                universe.CASH: 15,
            },
            BALANCED: {
                EQUITY_DIVIDEND: 22,
                universe.MONEY_MARKET: 22,
                DEBT: 15,
                universe.GOLD: 12,
                universe.BIST_STOCK: 12,
                universe.CASH: 17,
            },
            BEARISH: {
                universe.MONEY_MARKET: 32,
                DEBT: 22,
                universe.GOLD: 18,
                EQUITY_DIVIDEND: 12,
                universe.CASH: 16,
            },
        },
    },
}

STOCK_COUNT: dict[str, dict[str, int]] = {
    LOW: {BULLISH: 0, BALANCED: 0, BEARISH: 0},
    MID: {BULLISH: 2, BALANCED: 1, BEARISH: 1},
    HIGH: {BULLISH: 3, BALANCED: 2, BEARISH: 1},
}

# Buyume / pasif hisse havuzlari
STOCK_POOL: dict[str, tuple[str, ...]] = {
    BULLISH: ("ASELS", "THYAO", "GARAN", "AKBNK", "ISCTR", "FROTO", "KCHOL", "SASA"),
    BALANCED: ("KCHOL", "GARAN", "TCELL", "BIMAS", "FROTO", "TUPRS", "AKBNK"),
    BEARISH: ("BIMAS", "MGROS", "TCELL", "TUPRS", "KCHOL"),
}

STOCK_POOL_PASSIVE: dict[str, tuple[str, ...]] = {
    BULLISH: ("GARAN", "AKBNK", "TCELL", "BIMAS", "TUPRS", "KCHOL", "ISCTR"),
    BALANCED: ("BIMAS", "TCELL", "GARAN", "TUPRS", "KCHOL", "AKBNK"),
    BEARISH: ("BIMAS", "TCELL", "TUPRS", "GARAN"),
}

# Dogrudan enstruman tercihi (fonlarla yarisa girer)
DIRECT_PICK: dict[str, dict[str, str]] = {
    universe.BIST_INDEX: {BULLISH: "XU100", BALANCED: "XU030", BEARISH: "XU030"},
    universe.GLOBAL_EQUITY: {BULLISH: "NASDAQ", BALANCED: "SP500", BEARISH: "SP500"},
    universe.GOLD: {BULLISH: "GOLD_GRAM", BALANCED: "GOLD_GRAM", BEARISH: "GOLD_GRAM"},
    universe.FX: {BULLISH: "USDTRY", BALANCED: "USDTRY", BEARISH: "USDTRY"},
    universe.CRYPTO: {BULLISH: "BTC", BALANCED: "BTC", BEARISH: "BTC"},
    universe.MONEY_MARKET: {
        BULLISH: "MONEY_MARKET",
        BALANCED: "MONEY_MARKET",
        BEARISH: "MONEY_MARKET",
    },
    universe.CASH: {BULLISH: "CASH", BALANCED: "CASH", BEARISH: "CASH"},
}

# Varlik sinifi -> fon rol eslemesi (alternatif adaylar)
FUND_ROLES_FOR_CLASS: dict[str, tuple[str, ...]] = {
    universe.MONEY_MARKET: (MONEY_MARKET,),
    universe.GOLD: (funds.GOLD,),
    universe.BIST_INDEX: (EQUITY_INDEX,),
    universe.GLOBAL_EQUITY: (FOREIGN,),
    EQUITY_DIVIDEND: (EQUITY_DIVIDEND,),
    DEBT: (DEBT,),
}

SECTOR_VIEW_BONUS = {"positive": 6.0, "neutral": 0.0, "negative": -6.0}
# Fonlari hisseyle ayni skor bandinda tutmak icin kucuk cezalandirma yok;
# momentum yeter. Cok sik fon flip'ini azaltmak icin hafif preferans:
DIRECT_BIAS = 0.4  # dogrudan enstruman +0.4 skor (esitlikte hisse/endeks kazanir)

MIN_POSITION_WEIGHT = 3.0
MAX_POSITIONS = 8


@dataclass
class Basket:
    risk_profile: str
    income_pref: str
    regime: str
    weights: dict[str, float]
    rationale: str

    @property
    def instrument_count(self) -> int:
        return sum(1 for key in self.weights if key != "CASH")

    def sorted_items(self) -> list[tuple[str, float]]:
        return sorted(self.weights.items(), key=lambda kv: -kv[1])


def portfolio_key(risk_profile: str, income_pref: str = INCOME_GROWTH) -> str:
    if income_pref == INCOME_GROWTH:
        return risk_profile
    return f"{risk_profile}_{income_pref}"


def parse_portfolio_key(key: str) -> tuple[str, str]:
    if key.endswith("_passive"):
        return key[: -len("_passive")], INCOME_PASSIVE
    return key, INCOME_GROWTH


def _score(key: str, quotes: dict[str, market.Quote], analysis: Analysis) -> float:
    quote = quotes.get(key)
    if quote is None:
        return -1e9
    score = 0.7 * quote.change_20d_pct + 0.3 * quote.change_5d_pct
    if key in universe.BY_KEY:
        score += DIRECT_BIAS
        for sector in universe.get(key).sectors:
            view = analysis.sector_views.get(sector)
            if view:
                score += SECTOR_VIEW_BONUS.get(view, 0.0)
    return score


def _fund_keys_for(asset_class: str, income_pref: str) -> list[str]:
    roles = list(FUND_ROLES_FOR_CLASS.get(asset_class, ()))
    if asset_class == universe.BIST_STOCK:
        roles = (
            [EQUITY_DIVIDEND]
            if income_pref == INCOME_PASSIVE
            else [EQUITY_GROWTH]
        )
    keys: list[str] = []
    for role in roles:
        for fund in funds.pool_for(role, income_pref):
            if fund.key not in keys:
                keys.append(fund.key)
    return keys


def _pick_best(
    candidates: list[str],
    quotes: dict[str, market.Quote],
    analysis: Analysis,
    count: int = 1,
) -> list[str]:
    if count <= 0 or not candidates:
        return []
    ranked = sorted(
        candidates,
        key=lambda key: (-_score(key, quotes, analysis), key),
    )
    return [key for key in ranked if quotes.get(key) is not None][:count]


def _candidates_for_class(
    asset_class: str,
    regime: str,
    income_pref: str,
    risk_profile: str,
) -> tuple[list[str], int]:
    """Aday anahtarlar + kac tane secilecek."""
    if asset_class == universe.CASH:
        return ["CASH"], 1

    if asset_class == universe.BIST_STOCK:
        pool = (
            STOCK_POOL_PASSIVE[regime]
            if income_pref == INCOME_PASSIVE
            else STOCK_POOL[regime]
        )
        count = STOCK_COUNT[risk_profile][regime]
        # Hisse + uygun fon/ETF; skor kazananlar secilir
        candidates = list(pool) + _fund_keys_for(asset_class, income_pref)
        return candidates, max(count, 1) if count > 0 else 0

    if asset_class == EQUITY_DIVIDEND:
        # Dogrudan temettu hisseleri + temettu fon/ETF (TEFAS veya yabanci)
        pool = STOCK_POOL_PASSIVE[regime]
        fund_keys = _fund_keys_for(EQUITY_DIVIDEND, income_pref)
        count = 2 if risk_profile == HIGH else 1
        return list(pool) + fund_keys, count

    if asset_class == DEBT:
        return _fund_keys_for(DEBT, income_pref), 1

    direct = DIRECT_PICK.get(asset_class, {}).get(regime)
    candidates: list[str] = [direct] if direct else []
    candidates.extend(_fund_keys_for(asset_class, income_pref))
    # Tekil siniflar: 1 kazanan (hisse/endeks VEYA fon)
    return candidates, 1


def build(
    risk_profile: str,
    analysis: Analysis,
    quotes: dict[str, market.Quote],
    income_pref: str = INCOME_GROWTH,
) -> Basket:
    if income_pref not in INCOME_PREFS:
        income_pref = INCOME_GROWTH
    regime = analysis.regime
    allocation = ALLOCATIONS[risk_profile][income_pref][regime]
    weights: dict[str, float] = {}

    for asset_class, weight in allocation.items():
        if asset_class == universe.CASH:
            weights["CASH"] = weights.get("CASH", 0.0) + weight
            continue

        candidates, count = _candidates_for_class(
            asset_class, regime, income_pref, risk_profile
        )
        if count <= 0:
            # Hisse yoksa agirligi endekse kaydir
            fallback = DIRECT_PICK[universe.BIST_INDEX][regime]
            weights[fallback] = weights.get(fallback, 0.0) + weight
            continue

        picks = _pick_best(candidates, quotes, analysis, count)
        if not picks:
            mm = _pick_best(
                ["MONEY_MARKET"] + _fund_keys_for(universe.MONEY_MARKET, income_pref),
                quotes,
                analysis,
                1,
            )
            fallback = mm[0] if mm else "CASH"
            weights[fallback] = weights.get(fallback, 0.0) + weight
            continue

        share = weight / len(picks)
        for key in picks:
            weights[key] = weights.get(key, 0.0) + share

    weights = _round_weights(weights)
    return Basket(
        risk_profile=risk_profile,
        income_pref=income_pref,
        regime=regime,
        weights=weights,
        rationale=_rationale(risk_profile, income_pref, analysis),
    )


def _round_weights(weights: dict[str, float], prune: bool = True) -> dict[str, float]:
    cleaned = {key: value for key, value in weights.items() if value > 0.05}
    if not cleaned:
        return {"MONEY_MARKET": 100.0}

    if prune:
        cash = cleaned.pop("CASH", 0.0)
        keepers = {k: v for k, v in cleaned.items() if v >= MIN_POSITION_WEIGHT}
        if not keepers:
            keepers = {max(cleaned, key=lambda k: cleaned[k]): sum(cleaned.values())}
        if len(keepers) > MAX_POSITIONS:
            ranked = sorted(keepers.items(), key=lambda kv: -kv[1])[:MAX_POSITIONS]
            keepers = dict(ranked)

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


def _rationale(risk_profile: str, income_pref: str, analysis: Analysis) -> str:
    return (
        f"{RISK_PROFILE_TR[risk_profile]} · {INCOME_PREF_TR[income_pref]} · "
        f"{analysis.regime} görüşü (güven {analysis.confidence}/10, "
        f"ufuk ~{analysis.horizon_weeks} hafta). "
        "Hisse, endeks veya yerli/yabancı fon-ETF karışık seçilebilir."
    )


def build_all(
    analysis: Analysis,
    quotes: dict[str, market.Quote],
) -> dict[str, Basket]:
    out: dict[str, Basket] = {}
    for profile in RISK_PROFILES:
        for pref in INCOME_PREFS:
            out[portfolio_key(profile, pref)] = build(profile, analysis, quotes, pref)
    return out


def weight_distance(old: dict[str, float], new: dict[str, float]) -> float:
    keys = set(old) | set(new)
    return sum(abs(new.get(k, 0.0) - old.get(k, 0.0)) for k in keys) / 2.0


def blend(old: dict[str, float], new: dict[str, float], ratio: float) -> dict[str, float]:
    ratio = max(0.0, min(1.0, ratio))
    keys = set(old) | set(new)
    blended = {
        key: old.get(key, 0.0) * (1 - ratio) + new.get(key, 0.0) * ratio for key in keys
    }
    return _round_weights(blended)


__all__ = [
    "LOW",
    "MID",
    "HIGH",
    "RISK_PROFILES",
    "RISK_PROFILE_TR",
    "RISK_PROFILE_EMOJI",
    "RISK_PROFILE_DESC",
    "INCOME_GROWTH",
    "INCOME_PASSIVE",
    "INCOME_PREFS",
    "INCOME_PREF_TR",
    "INCOME_PREF_EMOJI",
    "INCOME_PREF_DESC",
    "Basket",
    "build",
    "build_all",
    "blend",
    "weight_distance",
    "portfolio_key",
    "parse_portfolio_key",
]
