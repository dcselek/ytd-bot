"""Haber + piyasa verisini piyasa rejimi gorusune donusturen katman.

LLM varsa onu kullanir; yoksa deterministik kural tabanli bir yedek calisir.
Boylece bot API anahtari olmadan da test edilebilir.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field, asdict
from typing import Any

from . import market, news
from .config import settings

log = logging.getLogger(__name__)

BULLISH = "bullish"
BALANCED = "balanced"
BEARISH = "bearish"

REGIME_TR = {
    BULLISH: "Yükseliş eğilimi",
    BALANCED: "Dengeli / temkinli",
    BEARISH: "Düşüş eğilimi",
}

REGIME_EMOJI = {BULLISH: "📈", BALANCED: "⚖️", BEARISH: "📉"}


@dataclass
class Analysis:
    regime: str
    confidence: int
    horizon_weeks: int
    summary_tr: str
    drivers: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    sector_views: dict[str, str] = field(default_factory=dict)
    tier1_events: list[str] = field(default_factory=list)
    source: str = "rule"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Analysis":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


SYSTEM_PROMPT = """Sen orta-uzun vadeli yatirimcilara hitap eden, disiplinli ve temkinli bir \
piyasa stratejistisin. Turkiye (BIST, TL, TCMB) ve global piyasalari birlikte degerlendirirsin.

Gorevin: verilen haber basliklari ve fiyat verisinden onumuzdeki HAFTALAR icin bir piyasa rejimi \
gorusu uretmek. Gunluk gurultuye gore gorus degistirmezsin; sadece temel (fundamental) gelismeler \
gorusunu degistirir.

Kurallar:
- Sadece gecerli JSON dondur, baska hicbir metin yazma.
- Guven skoru dusukse cekinmeden dusuk ver; sahte kesinlik uretme.
- Belirsizlikte "balanced" rejimini sec.
- Turkce yaz, yatirim tavsiyesi dili degil egitim/analiz dili kullan.

JSON semasi:
{
  "regime": "bullish" | "balanced" | "bearish",
  "confidence": 1-10 arasi tam sayi,
  "horizon_weeks": 2-8 arasi tam sayi,
  "summary_tr": "2-3 cumlelik genel degerlendirme",
  "drivers": ["gorusu destekleyen en fazla 4 somut sebep"],
  "risks": ["bu gorusu bozabilecek en fazla 3 risk"],
  "sector_views": {"bankacilik": "positive|neutral|negative", "...": "..."},
  "tier1_events": ["varsa temel/kritik olaylar, yoksa bos liste"]
}"""

USER_PROMPT_TEMPLATE = """## Haber basliklari (T1 = kritik/temel, T2 = onemli veri, T3 = genel)
{news_block}

## Piyasa verisi (TL bazli)
{market_block}

## Ek gostergeler
- BIST hisselerinde 20 gunluk pozitif momentum orani: {breadth:.0%}
- Son {lookback} saatte toplanan haber sayisi: {news_count}
- Mevcut yururlukteki rejim: {current_regime}

Yukaridakilere gore JSON gorusunu uret."""


def _extract_json(text: str) -> dict[str, Any] | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _clamp(value: Any, low: int, high: int, default: int) -> int:
    try:
        return max(low, min(high, int(round(float(value)))))
    except (TypeError, ValueError):
        return default


def _analyze_with_llm(
    items: list[news.NewsItem],
    quotes: dict[str, market.Quote],
    current_regime: str,
) -> Analysis | None:
    try:
        import anthropic
    except ImportError:
        log.warning("anthropic paketi yok, kural tabanli analize dusuluyor")
        return None

    prompt = USER_PROMPT_TEMPLATE.format(
        news_block=news.to_prompt_block(items) or "(haber alinamadi)",
        market_block=market.market_snapshot_text(quotes),
        breadth=market.breadth_score(quotes),
        lookback=settings.news_lookback_hours,
        news_count=len(items),
        current_regime=REGIME_TR.get(current_regime, current_regime),
    )

    try:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        response = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=1500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(block.text for block in response.content if block.type == "text")
    except Exception as exc:  # noqa: BLE001 - LLM hatasinda yedege dusuyoruz
        log.warning("LLM analizi basarisiz: %s", exc)
        return None

    data = _extract_json(text)
    if not data:
        log.warning("LLM yanitindan JSON cikarilamadi")
        return None

    regime = str(data.get("regime", "")).lower().strip()
    if regime not in (BULLISH, BALANCED, BEARISH):
        regime = BALANCED

    sector_views = data.get("sector_views") or {}
    if not isinstance(sector_views, dict):
        sector_views = {}

    return Analysis(
        regime=regime,
        confidence=_clamp(data.get("confidence"), 1, 10, 5),
        horizon_weeks=_clamp(data.get("horizon_weeks"), 2, 8, 4),
        summary_tr=str(data.get("summary_tr", "")).strip(),
        drivers=[str(d) for d in (data.get("drivers") or [])][:4],
        risks=[str(r) for r in (data.get("risks") or [])][:3],
        # Sektor adlarini ASCII'ye indiriyoruz; universe.sectors ile eslesmesi gerekiyor.
        sector_views={news.normalize(str(k)): str(v).lower().strip() for k, v in sector_views.items()},
        tier1_events=[str(e) for e in (data.get("tier1_events") or [])][:5],
        source="llm",
    )


NEGATIVE_WORDS = (
    "dusus",
    "geriledi",
    "kayip",
    "satis baskisi",
    "resesyon",
    "kriz",
    "iflas",
    "zarar",
    "daralma",
    "risk",
    "endise",
    "savas",
    "gerilim",
    "yaptirim",
    "not indirim",
    "fall",
    "drop",
    "slump",
    "loss",
    "fear",
    "selloff",
    "warn",
)

POSITIVE_WORDS = (
    "yukseldi",
    "artis",
    "rekor",
    "kazanc",
    "buyume",
    "iyilesme",
    "destek",
    "faiz indirim",
    "not artis",
    "anlasma",
    "rally",
    "surge",
    "gain",
    "beat",
    "optimism",
    "record",
)


def _news_tone(items: list[news.NewsItem]) -> float:
    """-1 ile +1 arasi kaba haber tonu skoru."""
    if not items:
        return 0.0
    score = 0.0
    total_weight = 0.0
    for item in items:
        text = news.normalize(f"{item.title} {item.summary}")
        weight = {1: 3.0, 2: 1.5}.get(item.tier, 1.0)
        negatives = sum(1 for word in NEGATIVE_WORDS if word in text)
        positives = sum(1 for word in POSITIVE_WORDS if word in text)
        if negatives or positives:
            score += weight * (positives - negatives)
        total_weight += weight
    if total_weight == 0:
        return 0.0
    return max(-1.0, min(1.0, score / total_weight))


def _analyze_with_rules(
    items: list[news.NewsItem],
    quotes: dict[str, market.Quote],
) -> Analysis:
    """LLM yoksa calisan momentum + haber tonu tabanli yedek."""
    def momentum(key: str) -> float:
        quote = quotes.get(key)
        return quote.change_20d_pct if quote else 0.0

    bist = momentum("XU100")
    breadth = market.breadth_score(quotes)
    usdtry = momentum("USDTRY")
    gold = momentum("GOLD_GRAM")
    tone = _news_tone(items)

    # BIST momentumu enflasyonist ortamda nominal, doviz artisina gore duzeltiyoruz.
    real_bist = bist - usdtry
    signal = (
        0.45 * max(-1.0, min(1.0, real_bist / 10.0))
        + 0.20 * (breadth - 0.5) * 2.0
        + 0.20 * tone
        - 0.15 * max(-1.0, min(1.0, (gold - usdtry) / 10.0))
    )

    if signal > 0.18:
        regime = BULLISH
    elif signal < -0.18:
        regime = BEARISH
    else:
        regime = BALANCED

    confidence = _clamp(4 + abs(signal) * 6, 1, 8, 4)
    tier1 = news.tier1_items(items)

    def pct(value: float) -> str:  # Turk sayi bicimi: virgul ondalik ayirici
        return f"%{value:+.1f}".replace(".", ",")

    drivers = [
        f"BIST 100'ün 20 günlük getirisi {pct(bist)}, USD/TRY {pct(usdtry)} "
        f"(döviz düzeltmeli fark {pct(real_bist)})",
        f"BIST hisselerinde pozitif momentum oranı %{breadth * 100:.0f}",
        f"Gram altının 20 günlük getirisi {pct(gold)}",
        f"Haber tonu skoru {tone:+.2f}".replace(".", ",")
        + f" ({len(items)} başlık, {len(tier1)} kritik gelişme)",
    ]

    return Analysis(
        regime=regime,
        confidence=confidence,
        horizon_weeks=4,
        summary_tr=(
            f"Kural tabanlı değerlendirme: {REGIME_TR[regime].lower()}. "
            "LLM anahtarı tanımlı olmadığı için görüş yalnızca fiyat momentumundan ve "
            "haber başlıklarındaki anahtar kelimelerden üretildi."
        ),
        drivers=drivers,
        risks=["Kural tabanlı model haberlerin içeriğini yorumlamaz, yalnızca yüzeysel tarar."],
        sector_views={},
        tier1_events=[item.title for item in tier1[:5]],
        source="rule",
    )


def analyze(
    items: list[news.NewsItem],
    quotes: dict[str, market.Quote],
    current_regime: str = BALANCED,
) -> Analysis:
    if settings.has_llm:
        result = _analyze_with_llm(items, quotes, current_regime)
        if result is not None:
            return result
    return _analyze_with_rules(items, quotes)
