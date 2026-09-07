"""Analiz dongusunu bir kez calistirip sonucu konsola yazar.

Telegram olmadan sistemin ucdan uca calistigini gormek ve test etmek icin kullanilir:
    python run_cycle.py
"""

from __future__ import annotations

import argparse
import json
import re

from ytdbot import discipline, engine, formatting, logging_setup, market, portfolio, storage
from ytdbot.baskets import (
    INCOME_PREF_TR,
    INCOME_PREFS,
    RISK_PROFILES,
    RISK_PROFILE_TR,
    portfolio_key,
)


def strip_html(text: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", text)
    return re.sub(r"<[^>]+>", "", text)


def main() -> None:
    parser = argparse.ArgumentParser(description="Tek seferlik analiz dongusu")
    parser.add_argument(
        "--messages",
        action="store_true",
        help="Telegram'a gidecek mesajlarin metin halini de yazdir",
    )
    args = parser.parse_args()

    logging_setup.configure()
    result = engine.run_cycle()

    print("\n" + "=" * 78)
    print(f"DÖNGÜ #{result.cycle_id}")
    print("=" * 78)
    print(f"Görüş        : {result.analysis.regime} (güven {result.analysis.confidence}/10)")
    print(f"Analiz kaynağı: {result.analysis.source}")
    print(f"Haber sayısı : {result.news_count}")
    print(f"Karar        : {result.decision.action}")
    for reason in result.decision.reasons:
        print(f"  + {reason}")
    for reason in result.decision.blocked_reasons:
        print(f"  - {reason}")

    quotes = market.cached_quotes()
    bench = portfolio.benchmarks(quotes)

    for profile in RISK_PROFILES:
        for pref in INCOME_PREFS:
            key = portfolio_key(profile, pref)
            outcome = result.outcomes.get(key)
            view = portfolio.valuation(key, quotes)
            print("\n" + "-" * 78)
            print(f"{RISK_PROFILE_TR[profile]} · {INCOME_PREF_TR[pref]}")
            print("-" * 78)
            if outcome and outcome.changed:
                print(f"Sepet güncellendi ({len(outcome.orders)} emir):")
                for order in outcome.orders:
                    print(
                        f"  {order.side:4s} {order.key:16s} "
                        f"{order.quantity:>14,.4f} adet @ {order.price:>12,.2f} TL "
                        f"= {order.amount:>12,.2f} TL"
                    )
            elif outcome and outcome.skip_reason:
                print(f"Değişiklik yok — {outcome.skip_reason}")

            print(f"Toplam değer : {view.total_value:>14,.2f} TL")
            print(f"Nakit        : {view.cash:>14,.2f} TL")
            print(f"Kâr/Zarar    : {view.pnl_abs:>14,.2f} TL  ({view.pnl_pct:+.2f}%)")
            print(f"Komisyon     : {view.total_fees:>14,.2f} TL  ({int(view.trade_count)} işlem)")
            if view.positions:
                print("Pozisyonlar:")
                for pos in view.positions:
                    print(
                        f"  {pos.name[:40]:40s} %{pos.weight_pct:5.1f}  "
                        f"{pos.value:>12,.2f} TL  ({pos.pnl_pct:+.2f}%)"
                    )

    if bench:
        print("\n" + "-" * 78)
        print("Referanslar (başlangıçtan bu yana)")
        print("-" * 78)
        for key, pct in bench.items():
            print(f"  {formatting.BENCHMARK_LABELS.get(key, key):14s} {pct:+.2f}%")

    if args.messages:
        state = engine.current_state()
        stability = discipline.stability_summary()
        for profile in RISK_PROFILES:
            for pref in INCOME_PREFS:
                key = portfolio_key(profile, pref)
                row = storage.active_basket(key)
                if row is None:
                    continue
                weights = json.loads(row["weights_json"])
                print("\n" + "=" * 78)
                print(f"TELEGRAM MESAJI — {RISK_PROFILE_TR[profile]} · {INCOME_PREF_TR[pref]}")
                print("=" * 78)
                print(
                    strip_html(
                        formatting.basket_message(
                            key,
                            weights,
                            state["analysis"],
                            quotes,
                            stability,
                            income_pref=pref,
                        )
                    )
                )
                print("\n--- /portfoy ---")
                print(
                    strip_html(
                        formatting.portfolio_message(
                            portfolio.valuation(key, quotes), bench
                        )
                    )
                )


if __name__ == "__main__":
    main()
