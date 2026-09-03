"""Ortam degiskenlerinden yuklenen ayarlar."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


def _str(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


@dataclass(frozen=True)
class Settings:
    telegram_token: str = field(default_factory=lambda: _str("TELEGRAM_BOT_TOKEN"))
    admin_chat_ids: tuple[int, ...] = field(
        default_factory=lambda: tuple(
            int(part) for part in _str("ADMIN_CHAT_IDS").replace(" ", "").split(",") if part
        )
    )

    anthropic_api_key: str = field(default_factory=lambda: _str("ANTHROPIC_API_KEY"))
    anthropic_model: str = field(
        default_factory=lambda: _str("ANTHROPIC_MODEL", "claude-sonnet-4-5")
    )

    db_path: Path = field(default_factory=lambda: BASE_DIR / _str("DB_PATH", "data/ytdbot.sqlite3"))

    # Bot arka planda bu sikligla kosar; karar degisimi bundan cok daha nadirdir.
    cycle_hours: int = field(default_factory=lambda: _int("CYCLE_HOURS", 4))

    # Temsili portfoy
    start_capital_try: float = field(default_factory=lambda: _float("START_CAPITAL_TRY", 100_000.0))
    broker_fee_bps: float = field(default_factory=lambda: _float("BROKER_FEE_BPS", 15.0))

    # Para piyasasi / likit fon icin varsayilan yillik getiri (yuzde).
    money_market_annual_rate: float = field(
        default_factory=lambda: _float("MONEY_MARKET_ANNUAL_RATE", 42.0)
    )

    # "Advisor discipline" parametreleri
    min_basket_lifetime_days: int = field(
        default_factory=lambda: _int("MIN_BASKET_LIFETIME_DAYS", 14)
    )
    regime_confirmation_cycles: int = field(
        default_factory=lambda: _int("REGIME_CONFIRMATION_CYCLES", 3)
    )
    min_switch_confidence: int = field(default_factory=lambda: _int("MIN_SWITCH_CONFIDENCE", 6))
    emergency_switch_confidence: int = field(
        default_factory=lambda: _int("EMERGENCY_SWITCH_CONFIDENCE", 8)
    )
    min_weight_drift_pct: float = field(default_factory=lambda: _float("MIN_WEIGHT_DRIFT_PCT", 5.0))

    news_lookback_hours: int = field(default_factory=lambda: _int("NEWS_LOOKBACK_HOURS", 12))
    max_news_items: int = field(default_factory=lambda: _int("MAX_NEWS_ITEMS", 40))

    @property
    def has_llm(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def money_market_daily_rate(self) -> float:
        return self.money_market_annual_rate / 100.0 / 365.0


settings = Settings()
