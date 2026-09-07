"""Temsili portfoy: baslangic sermayesi ile sepetleri gercek fiyatlardan takip eder.

Gercek para kullanilmaz. Amac sepet onerilerinin zaman icinde ne yaptigini
seffaf ve olculebilir sekilde gostermek.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from . import funds, market, storage, universe
from .baskets import INCOME_PREFS, RISK_PROFILES, portfolio_key
from .config import settings

log = logging.getLogger(__name__)

# Toplam degerin bu oraninin altindaki farklar icin islem yapilmaz (komisyon israfi).
MIN_TRADE_RATIO = 0.005

BENCHMARK_STATE_KEY = "benchmark_start_prices"
BENCHMARK_KEYS = ("XU100", "MONEY_MARKET", "GOLD_GRAM", "USDTRY")


@dataclass
class PositionView:
    key: str
    name: str
    asset_class_tr: str
    quantity: float
    price: float
    value: float
    weight_pct: float
    cost_basis: float
    pnl_abs: float
    pnl_pct: float
    stale: bool


@dataclass
class PortfolioView:
    risk_profile: str
    start_capital: float
    started_at: datetime | None
    total_value: float
    cash: float
    positions_value: float
    pnl_abs: float
    pnl_pct: float
    total_fees: float
    trade_count: float
    positions: list[PositionView] = field(default_factory=list)

    @property
    def days_running(self) -> float:
        if not self.started_at:
            return 0.0
        return (storage.utcnow() - self.started_at).total_seconds() / 86400.0


@dataclass
class Order:
    key: str
    side: str  # "BUY" | "SELL"
    quantity: float
    price: float
    amount: float
    fee: float


def ensure_portfolios() -> None:
    for profile in RISK_PROFILES:
        for pref in INCOME_PREFS:
            storage.create_portfolio(portfolio_key(profile, pref), settings.start_capital_try)


def _position_meta(key: str) -> tuple[str, str]:
    """name, asset_class_tr"""
    if key == "CASH":
        return "Nakit (TL)", "Nakit"
    if key in universe.BY_KEY:
        inst = universe.get(key)
        return inst.name, inst.asset_class_tr
    fund = funds.get(key)
    if fund:
        return funds.display_name(key), fund.role_tr
    return funds.display_name(key), "Fon / ETF"


def _fee(amount: float) -> float:
    return abs(amount) * settings.broker_fee_bps / 10_000.0


def positions_value(
    positions: dict[str, dict[str, float]], quotes: dict[str, market.Quote]
) -> float:
    total = 0.0
    for key, pos in positions.items():
        quote = quotes.get(key)
        if quote is None:
            continue
        total += pos["quantity"] * quote.price_try
    return total


def rebalance(
    risk_profile: str,
    target_weights: dict[str, float],
    quotes: dict[str, market.Quote],
    cycle_id: int | None = None,
) -> list[Order]:
    """Portfoyu hedef agirliklara tasir ve uygulanan emirleri dondurur."""
    ensure_portfolios()
    row = storage.get_portfolio(risk_profile)
    if row is None:
        return []

    cash = float(row["cash"])
    total_fees = float(row["total_fees"])
    positions = storage.get_positions(risk_profile)

    total_value = cash + positions_value(positions, quotes)
    if total_value <= 0:
        log.warning("%s portfoyunun degeri sifir, rebalance atlaniyor", risk_profile)
        return []

    # CASH agirligi enstruman degil, nakit tamponudur.
    targets: dict[str, float] = {}
    for key, weight in target_weights.items():
        if key == "CASH":
            continue
        if quotes.get(key) is None:
            log.warning("%s icin fiyat yok, hedef agirligi atlaniyor", key)
            continue
        targets[key] = total_value * weight / 100.0

    current_values = {
        key: pos["quantity"] * quotes[key].price_try
        for key, pos in positions.items()
        if key in quotes
    }

    min_trade = total_value * MIN_TRADE_RATIO
    deltas: list[tuple[str, float]] = []
    for key in set(current_values) | set(targets):
        delta = targets.get(key, 0.0) - current_values.get(key, 0.0)
        # Hedefte olmayan pozisyonlar esikten bagimsiz tamamen kapatilir.
        if key not in targets or abs(delta) >= min_trade:
            if abs(delta) > 1e-9:
                deltas.append((key, delta))

    orders: list[Order] = []

    # Satislar once: aliminlar icin nakit yaratir.
    for key, delta in sorted(deltas, key=lambda item: item[1]):
        if delta >= 0:
            continue
        price = quotes[key].price_try
        available_qty = positions.get(key, {}).get("quantity", 0.0)
        sell_qty = min(available_qty, abs(delta) / price)
        if sell_qty <= 1e-12:
            continue
        amount = sell_qty * price
        fee = _fee(amount)
        cash += amount - fee
        total_fees += fee
        remaining = available_qty - sell_qty
        avg_cost = positions.get(key, {}).get("avg_cost", price)
        positions[key] = {"quantity": remaining, "avg_cost": avg_cost}
        storage.upsert_position(risk_profile, key, remaining, avg_cost)
        storage.insert_trade(risk_profile, key, "SELL", sell_qty, price, amount, fee, cycle_id)
        orders.append(Order(key, "SELL", sell_qty, price, amount, fee))

    buys = [(key, delta) for key, delta in deltas if delta > 0]
    requested = sum(delta for _, delta in buys)
    if requested > 0:
        # Komisyon sonrasi nakde sigacak sekilde olcekle; nakit negatife dusmemeli.
        target_cash = total_value * target_weights.get("CASH", 0.0) / 100.0
        spendable = max(0.0, cash - target_cash)
        fee_rate = settings.broker_fee_bps / 10_000.0
        budget = spendable / (1.0 + fee_rate)
        scale = min(1.0, budget / requested) if requested > 0 else 0.0

        for key, delta in buys:
            amount = delta * scale
            if amount < min_trade * 0.5:
                continue
            price = quotes[key].price_try
            quantity = amount / price
            fee = _fee(amount)
            if amount + fee > cash:
                continue
            cash -= amount + fee
            total_fees += fee
            existing = positions.get(key, {"quantity": 0.0, "avg_cost": 0.0})
            new_qty = existing["quantity"] + quantity
            new_avg = (
                (existing["quantity"] * existing["avg_cost"] + amount) / new_qty
                if new_qty > 0
                else price
            )
            positions[key] = {"quantity": new_qty, "avg_cost": new_avg}
            storage.upsert_position(risk_profile, key, new_qty, new_avg)
            storage.insert_trade(risk_profile, key, "BUY", quantity, price, amount, fee, cycle_id)
            orders.append(Order(key, "BUY", quantity, price, amount, fee))

    storage.update_portfolio_cash(risk_profile, cash, total_fees)
    log.info("%s portfoyunde %d emir uygulandi", risk_profile, len(orders))
    return orders


def valuation(risk_profile: str, quotes: dict[str, market.Quote]) -> PortfolioView:
    ensure_portfolios()
    row = storage.get_portfolio(risk_profile)
    positions = storage.get_positions(risk_profile)

    cash = float(row["cash"]) if row else settings.start_capital_try
    start_capital = float(row["start_capital"]) if row else settings.start_capital_try
    total_fees = float(row["total_fees"]) if row else 0.0
    started_at = storage.parse_iso(row["started_at"]) if row else None

    pos_value = positions_value(positions, quotes)
    total_value = cash + pos_value

    views: list[PositionView] = []
    for key, pos in positions.items():
        quote = quotes.get(key)
        if quote is None or pos["quantity"] <= 1e-12:
            continue
        inst_name, asset_class_tr = _position_meta(key)
        value = pos["quantity"] * quote.price_try
        cost = pos["quantity"] * pos["avg_cost"]
        views.append(
            PositionView(
                key=key,
                name=inst_name,
                asset_class_tr=asset_class_tr,
                quantity=pos["quantity"],
                price=quote.price_try,
                value=value,
                weight_pct=(value / total_value * 100.0) if total_value else 0.0,
                cost_basis=cost,
                pnl_abs=value - cost,
                pnl_pct=((value / cost - 1.0) * 100.0) if cost > 0 else 0.0,
                stale=quote.stale,
            )
        )
    views.sort(key=lambda v: -v.value)

    return PortfolioView(
        risk_profile=risk_profile,
        start_capital=start_capital,
        started_at=started_at,
        total_value=total_value,
        cash=cash,
        positions_value=pos_value,
        pnl_abs=total_value - start_capital,
        pnl_pct=((total_value / start_capital - 1.0) * 100.0) if start_capital else 0.0,
        total_fees=total_fees,
        trade_count=storage.trade_count(risk_profile),
        positions=views,
    )


def take_snapshot(
    risk_profile: str, quotes: dict[str, market.Quote], cycle_id: int | None = None
) -> PortfolioView:
    view = valuation(risk_profile, quotes)
    storage.insert_snapshot(
        risk_profile,
        view.total_value,
        view.cash,
        view.positions_value,
        view.pnl_abs,
        view.pnl_pct,
        cycle_id,
    )
    return view


# --- Benchmark -------------------------------------------------------------


def record_benchmark_start(quotes: dict[str, market.Quote]) -> None:
    """Ilk dongude referans varliklarin fiyatlarini kaydeder."""
    if storage.get_state(BENCHMARK_STATE_KEY):
        return
    start = {
        key: quotes[key].price_try for key in BENCHMARK_KEYS if quotes.get(key) is not None
    }
    if start:
        storage.set_state(BENCHMARK_STATE_KEY, start)


def benchmarks(quotes: dict[str, market.Quote]) -> dict[str, float]:
    """Baslangictan bu yana referans varliklarin yuzde getirisi."""
    start = storage.get_state(BENCHMARK_STATE_KEY) or {}
    result: dict[str, float] = {}
    for key, start_price in start.items():
        quote = quotes.get(key)
        if quote is None or not start_price:
            continue
        result[key] = (quote.price_try / float(start_price) - 1.0) * 100.0
    return result
