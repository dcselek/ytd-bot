"""Analiz dongusunun orkestrasyonu.

Sira: haber topla -> fiyat cek -> rejim analizi -> disiplin karari ->
gerekiyorsa sepetleri guncelle -> temsili portfoyu tasi -> anlik goruntu al.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from . import analysis as analysis_mod
from . import baskets, discipline, market, news, portfolio, storage
from .analysis import Analysis
from .baskets import RISK_PROFILES
from .config import settings
from .portfolio import Order

log = logging.getLogger(__name__)


@dataclass
class ProfileOutcome:
    risk_profile: str
    changed: bool
    old_weights: dict[str, float]
    new_weights: dict[str, float]
    orders: list[Order] = field(default_factory=list)
    skip_reason: str | None = None


@dataclass
class CycleResult:
    cycle_id: int
    analysis: Analysis
    decision: discipline.Decision
    quotes: dict[str, market.Quote]
    news_count: int
    outcomes: dict[str, ProfileOutcome] = field(default_factory=dict)

    @property
    def any_change(self) -> bool:
        return any(outcome.changed for outcome in self.outcomes.values())


def _active_weights(risk_profile: str) -> tuple[int | None, dict[str, float], str | None]:
    row = storage.active_basket(risk_profile)
    if row is None:
        return None, {}, None
    return int(row["id"]), json.loads(row["weights_json"]), row["regime"]


def run_cycle() -> CycleResult:
    log.info("Analiz dongusu basliyor")

    quotes = market.fetch_quotes()
    news_items = news.collect()
    current_regime = discipline.current_regime()

    result = analysis_mod.analyze(news_items, quotes, current_regime)
    decision = discipline.evaluate(result, news_items)

    log.info(
        "Analiz: %s (guven %d, kaynak %s) -> karar: %s",
        result.regime,
        result.confidence,
        result.source,
        decision.action,
    )

    cycle_id = storage.insert_cycle(
        regime=result.regime,
        confidence=result.confidence,
        horizon_weeks=result.horizon_weeks,
        decision=decision.action,
        analysis=result.to_dict(),
        decision_detail=decision.to_dict(),
        news_count=len(news_items),
    )

    portfolio.ensure_portfolios()
    portfolio.record_benchmark_start(quotes)

    cycle_result = CycleResult(
        cycle_id=cycle_id,
        analysis=result,
        decision=decision,
        quotes=quotes,
        news_count=len(news_items),
    )

    if decision.changes_basket:
        # Sepetler kararin hedef rejimine gore kurulur; analizin anlik gorusune degil.
        target_analysis = dataclasses.replace(result, regime=decision.target_regime)
        for profile in RISK_PROFILES:
            cycle_result.outcomes[profile] = _apply_profile(
                profile, target_analysis, decision, quotes, cycle_id
            )
    else:
        for profile in RISK_PROFILES:
            _, weights, _ = _active_weights(profile)
            cycle_result.outcomes[profile] = ProfileOutcome(
                risk_profile=profile,
                changed=False,
                old_weights=weights,
                new_weights=weights,
                skip_reason="Karar: beklemede",
            )

    discipline.commit(decision)

    for profile in RISK_PROFILES:
        portfolio.take_snapshot(profile, quotes, cycle_id)

    return cycle_result


def _apply_profile(
    risk_profile: str,
    target_analysis: Analysis,
    decision: discipline.Decision,
    quotes: dict[str, market.Quote],
    cycle_id: int,
) -> ProfileOutcome:
    old_basket_id, old_weights, old_regime = _active_weights(risk_profile)
    target = baskets.build(risk_profile, target_analysis, quotes)

    # Kademeli gecis: hedefe tek hamlede degil, adim adim yaklasiyoruz.
    if decision.transition_ratio < 1.0 and old_weights:
        applied = baskets.blend(old_weights, target.weights, decision.transition_ratio)
    else:
        applied = target.weights

    drift = baskets.weight_distance(old_weights, applied) if old_weights else 100.0

    # Ayni rejim icindeki periyodik kontrolde kucuk sapmalar icin islem yapmiyoruz.
    if decision.action == discipline.REBALANCE and drift < settings.min_weight_drift_pct:
        return ProfileOutcome(
            risk_profile=risk_profile,
            changed=False,
            old_weights=old_weights,
            new_weights=old_weights,
            skip_reason=(
                f"Sapma %{drift:.1f}, eşik %{settings.min_weight_drift_pct:.0f} "
                "altında olduğu için işlem yapılmadı."
            ),
        )

    new_basket_id = storage.insert_basket(
        risk_profile=risk_profile,
        regime=decision.target_regime,
        weights=applied,
        rationale=target.rationale,
        cycle_id=cycle_id,
    )
    orders = portfolio.rebalance(risk_profile, applied, quotes, cycle_id)

    storage.insert_basket_change(
        risk_profile=risk_profile,
        old_basket_id=old_basket_id,
        new_basket_id=new_basket_id,
        old_regime=old_regime,
        new_regime=decision.target_regime,
        kind={
            discipline.REBALANCE: "rebalance",
            discipline.SWITCH_STEP: "transition",
        }.get(decision.action, "switch"),
        reason={
            "reasons": decision.reasons,
            "action": decision.action,
            "confidence": target_analysis.confidence,
            "drift_pct": round(drift, 2),
            "transition_ratio": decision.transition_ratio,
        },
        held_days=decision.days_held if decision.days_held < 1e5 else 0.0,
    )

    return ProfileOutcome(
        risk_profile=risk_profile,
        changed=True,
        old_weights=old_weights,
        new_weights=applied,
        orders=orders,
    )


def current_state() -> dict[str, Any]:
    """Bot komutlarinin okudugu son durum (yeni dongu tetiklemeden)."""
    row = storage.latest_cycle()
    if row is None:
        return {
            "analysis": None,
            "decision": None,
            "last_run": None,
            "news_count": 0,
            "stability": discipline.stability_summary(),
        }

    analysis_data = json.loads(row["analysis_json"])
    decision_data = json.loads(row["decision_json"])
    return {
        "analysis": Analysis.from_dict(analysis_data),
        "decision": discipline.Decision(
            action=decision_data.get("action", discipline.HOLD),
            target_regime=decision_data.get("target_regime", analysis_data.get("regime")),
            current_regime=decision_data.get("current_regime", analysis_data.get("regime")),
            transition_ratio=decision_data.get("transition_ratio", 1.0),
            transition_step=decision_data.get("transition_step", 0),
            reasons=decision_data.get("reasons", []),
            blocked_reasons=decision_data.get("blocked_reasons", []),
            days_held=decision_data.get("days_held", 0.0),
            next_review_at=storage.parse_iso(decision_data.get("next_review_at")),
            change_probability=decision_data.get("change_probability", "dusuk"),
            pending_streak=decision_data.get("pending_streak", 0),
            required_streak=decision_data.get("required_streak", 0),
        ),
        "last_run": storage.parse_iso(row["ran_at"]),
        "news_count": int(row["news_count"]),
        "stability": discipline.stability_summary(),
    }
