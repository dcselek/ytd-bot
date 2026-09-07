"""Advisor discipline kurallarinin simulasyonu.

Zamani ileri sararak ve analiz sonucunu sahte veriyle besleyerek botun
"sik gorus degistirmeme" davranisini dogrular. Ag baglantisi gerekmez.

Kullanim:
    python scripts/simulate_discipline.py
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# Windows konsolu varsayilan olarak cp1254; Turkce cikti icin UTF-8'e geciyoruz.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Gercek veritabanina dokunmamak icin ayri bir dosya kullaniyoruz.
DB_FILE = BASE_DIR / "data" / "simulation.sqlite3"
os.environ["DB_PATH"] = "data/simulation.sqlite3"
os.environ.setdefault("ANTHROPIC_API_KEY", "")

for suffix in ("", "-wal", "-shm"):
    stale = Path(str(DB_FILE) + suffix)
    if stale.exists():
        stale.unlink()

from ytdbot import analysis as analysis_mod  # noqa: E402
from ytdbot import baskets, discipline, engine, funds, market, news, portfolio, storage  # noqa: E402
from ytdbot.analysis import BALANCED, BEARISH, BULLISH, Analysis  # noqa: E402
from ytdbot.baskets import INCOME_PREFS, RISK_PROFILES, portfolio_key  # noqa: E402
from ytdbot.universe import INSTRUMENTS  # noqa: E402

START = datetime(2026, 1, 6, 9, 0, tzinfo=timezone.utc)
CLOCK = [START]


def fake_now() -> datetime:
    return CLOCK[0]


# Tum zaman okumalari storage.utcnow uzerinden gectigi icin tek nokta yeterli.
storage.utcnow = fake_now

BASE_PRICES = {
    "XU030": 16_000.0,
    "XU100": 13_800.0,
    "GARAN": 132.0,
    "AKBNK": 72.0,
    "ISCTR": 12.9,
    "ASELS": 373.0,
    "THYAO": 293.0,
    "BIMAS": 408.0,
    "MGROS": 517.0,
    "TUPRS": 394.0,
    "EREGL": 37.3,
    "KCHOL": 213.0,
    "TCELL": 96.8,
    "FROTO": 76.3,
    "SASA": 2.27,
    "GOLD_GRAM": 6_900.0,
    "USDTRY": 48.3,
    "EURTRY": 56.2,
    "SP500": 36_900.0,
    "NASDAQ": 34_200.0,
    "BTC": 3_747_000.0,
    "ETH": 115_000.0,
}

# Rejime gore basit momentum senaryosu (20 gunluk yuzde).
MOMENTUM = {
    BULLISH: 8.0,
    BALANCED: 1.0,
    BEARISH: -7.0,
}


def fake_quotes(regime: str = BALANCED, drift_pct: float = 0.0) -> dict[str, market.Quote]:
    quotes = {
        "MONEY_MARKET": market.money_market_quote(),
        "CASH": market.cash_quote(),
    }
    momentum = MOMENTUM[regime]
    for inst in INSTRUMENTS:
        if inst.is_synthetic:
            continue
        base = BASE_PRICES.get(inst.key, 100.0)
        quotes[inst.key] = market.Quote(
            instrument_key=inst.key,
            price_try=base * (1 + drift_pct / 100.0),
            change_1d_pct=momentum / 20.0,
            change_5d_pct=momentum / 4.0,
            change_20d_pct=momentum + (hash(inst.key) % 7 - 3),
            as_of=fake_now(),
        )
    # Bot sepeti TEFAS fonlari kullanir; simulasonda sahte fiyatlar.
    for fund in funds.FUNDS:
        base = 1.0 + (hash(fund.code) % 50) / 100.0
        # Yabanci ETF'ler USD bazinda daha yuksek fiyat gibi
        if fund.venue == funds.VENUE_YAHOO:
            base = 50.0 + (hash(fund.code) % 40)
        quotes[fund.key] = market.Quote(
            instrument_key=fund.key,
            price_try=base * (1 + drift_pct / 100.0),
            change_1d_pct=momentum / 20.0,
            change_5d_pct=momentum / 4.0,
            change_20d_pct=momentum + (hash(fund.code) % 7 - 3),
            as_of=fake_now(),
        )
    return quotes


def fake_news(tier1_titles: list[str] | None = None) -> list[news.NewsItem]:
    items = [
        news.NewsItem(
            hash=f"sim-{i}-{fake_now().timestamp()}",
            source="Simulasyon",
            title=title,
            summary="",
            link="",
            published_at=fake_now(),
            tier=1,
        )
        for i, title in enumerate(tier1_titles or [])
    ]
    items.append(
        news.NewsItem(
            hash=f"sim-generic-{fake_now().timestamp()}",
            source="Simulasyon",
            title="Piyasalarda yatay seyir suruyor",
            summary="",
            link="",
            published_at=fake_now(),
            tier=3,
        )
    )
    return items


def run_step(
    label: str,
    day_offset: float,
    regime: str,
    confidence: int,
    tier1_titles: list[str] | None = None,
    drift_pct: float = 0.0,
) -> None:
    CLOCK[0] = START + timedelta(days=day_offset)

    quotes = fake_quotes(regime, drift_pct)
    items = fake_news(tier1_titles)

    analysis = Analysis(
        regime=regime,
        confidence=confidence,
        horizon_weeks=4,
        summary_tr="Simulasyon girdisi",
        drivers=["Simulasyon"],
        source="rule",
    )

    market.fetch_quotes = lambda: quotes
    news.collect = lambda *a, **k: items
    analysis_mod.analyze = lambda *a, **k: analysis

    result = engine.run_cycle()
    decision = result.decision

    action_labels = {
        discipline.HOLD: "BEKLE",
        discipline.REBALANCE: "AGIRLIK AYARI",
        discipline.SWITCH: "SEPET DEGISIMI",
        discipline.SWITCH_STEP: "GECIS ADIMI",
    }

    mid_outcome = result.outcomes.get("mid")
    trades = len(mid_outcome.orders) if mid_outcome else 0

    print(f"\n{'-' * 92}")
    print(f"Gün {day_offset:>5.1f} | {label}")
    print(f"{'-' * 92}")
    print(
        f"  Sinyal      : {regime} (güven {confidence}/10)"
        + (f" + kritik haber: {tier1_titles[0]}" if tier1_titles else "")
    )
    print(f"  KARAR       : {action_labels.get(decision.action, decision.action)}")
    print(f"  Orta risk   : {trades} işlem")
    if decision.transition_ratio < 1.0 or decision.transition_step:
        print(
            f"  Geçiş       : adım {decision.transition_step}/{discipline.TRANSITION_STEPS} "
            f"(hedefe %{decision.transition_ratio * 100:.0f} yaklaşıldı)"
        )
    for reason in decision.reasons:
        print(f"    + {reason}")
    for reason in decision.blocked_reasons:
        print(f"    - {reason}")

    if mid_outcome and mid_outcome.changed:
        weights = ", ".join(
            f"{k} %{v:.0f}" for k, v in sorted(mid_outcome.new_weights.items(), key=lambda x: -x[1])
        )
        print(f"  Yeni sepet  : {weights}")


def main() -> None:
    storage.connect()
    portfolio.ensure_portfolios()

    print("=" * 92)
    print("ADVISOR DISCIPLINE SIMÜLASYONU")
    print("=" * 92)
    print(
        f"Kurallar: minimum sepet ömrü {discipline.settings.min_basket_lifetime_days} gün | "
        f"görüş onayı {discipline.settings.regime_confirmation_cycles} döngü | "
        f"güven eşiği {discipline.settings.min_switch_confidence}/10 | "
        f"kademeli geçiş {discipline.TRANSITION_STEPS} adım"
    )

    run_step("İlk kurulum", 0.0, BALANCED, 5)
    run_step("Yükseliş sinyali (1. görülme)", 0.2, BULLISH, 7)
    run_step("Yükseliş sinyali (2. görülme)", 0.5, BULLISH, 7)
    run_step("Yükseliş sinyali (3. görülme) — onay tamam ama süre dolmadı", 1.0, BULLISH, 7)
    run_step("Tek günlük panik sinyali (düşük güven)", 2.0, BEARISH, 4)
    run_step("Yükseliş sinyali sürüyor", 5.0, BULLISH, 7)
    run_step("Minimum süre doldu — geçiş başlıyor", 14.5, BULLISH, 7)
    run_step("Geçiş sürerken yeni sinyal", 15.0, BULLISH, 7)
    run_step("Kademeli geçişin 2. adımı", 17.6, BULLISH, 7)
    run_step("Rejim içinde fiyatlar kaydı (periyodik kontrol)", 25.0, BULLISH, 7, drift_pct=6.0)
    run_step(
        "Kritik gelişme + yüksek güven (1. görülme)",
        27.0,
        BEARISH,
        9,
        tier1_titles=["TCMB politika faizini 500 baz puan artırdı"],
    )
    run_step(
        "Kritik gelişme (2. görülme)",
        27.5,
        BEARISH,
        9,
        tier1_titles=["TCMB politika faizini 500 baz puan artırdı"],
    )
    run_step(
        "Kritik gelişme (3. görülme) — acil istisna devreye giriyor",
        28.0,
        BEARISH,
        9,
        tier1_titles=["TCMB politika faizini 500 baz puan artırdı"],
    )

    print(f"\n{'=' * 92}")
    print("ÖZET: DEĞİŞİM GEÇMİŞİ (orta risk)")
    print("=" * 92)
    changes = storage.basket_history("mid", limit=20)
    for row in reversed(changes):
        changed = storage.parse_iso(row["changed_at"])
        day = (changed - START).total_seconds() / 86400.0 if changed else 0
        print(
            f"  Gün {day:>5.1f} | {row['kind']:<9} | "
            f"{row['old_regime'] or '—':<9} -> {row['new_regime']:<9} | "
            f"önceki sepet {row['held_days']:.1f} gün kaldı"
        )

    total_cycles = len(storage.recent_cycles(limit=100))
    print(f"\n  {total_cycles} analiz döngüsünde {len(changes)} sepet müdahalesi yapıldı.")

    print("\n" + "=" * 92)
    print("PORTFÖY DURUMU")
    print("=" * 92)
    quotes = fake_quotes(BEARISH, drift_pct=6.0)
    for profile in RISK_PROFILES:
        for pref in INCOME_PREFS:
            key = portfolio_key(profile, pref)
            view = portfolio.valuation(key, quotes)
            label = f"{baskets.RISK_PROFILE_TR[profile]} · {baskets.INCOME_PREF_TR[pref]}"
            print(
                f"  {label:<42} "
                f"{view.total_value:>14,.2f} TL  ({view.pnl_pct:+.2f}%)  "
                f"{int(view.trade_count)} işlem, komisyon {view.total_fees:,.2f} TL"
            )


if __name__ == "__main__":
    main()
