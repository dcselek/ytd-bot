"""SQLite kalici depolama katmani."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS subscribers (
    chat_id      INTEGER PRIMARY KEY,
    risk_profile TEXT    NOT NULL DEFAULT 'mid',
    income_pref  TEXT    NOT NULL DEFAULT 'growth',
    bot_capital  REAL,
    notify       INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS cycles (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ran_at         TEXT NOT NULL,
    regime         TEXT NOT NULL,
    confidence     INTEGER NOT NULL,
    horizon_weeks  INTEGER NOT NULL,
    decision       TEXT NOT NULL,
    analysis_json  TEXT NOT NULL,
    decision_json  TEXT NOT NULL,
    news_count     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS baskets (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    risk_profile TEXT NOT NULL,
    regime       TEXT NOT NULL,
    weights_json TEXT NOT NULL,
    rationale    TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    retired_at   TEXT,
    cycle_id     INTEGER,
    active       INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_baskets_active ON baskets (risk_profile, active);

CREATE TABLE IF NOT EXISTS basket_changes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    risk_profile  TEXT NOT NULL,
    old_basket_id INTEGER,
    new_basket_id INTEGER NOT NULL,
    old_regime    TEXT,
    new_regime    TEXT NOT NULL,
    changed_at    TEXT NOT NULL,
    kind          TEXT NOT NULL,
    reason_json   TEXT NOT NULL,
    held_days     REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS portfolios (
    risk_profile   TEXT PRIMARY KEY,
    cash           REAL NOT NULL,
    start_capital  REAL NOT NULL,
    started_at     TEXT NOT NULL,
    total_fees     REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS positions (
    risk_profile   TEXT NOT NULL,
    instrument_key TEXT NOT NULL,
    quantity       REAL NOT NULL,
    avg_cost       REAL NOT NULL,
    PRIMARY KEY (risk_profile, instrument_key)
);

CREATE TABLE IF NOT EXISTS trades (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    risk_profile   TEXT NOT NULL,
    instrument_key TEXT NOT NULL,
    side           TEXT NOT NULL,
    quantity       REAL NOT NULL,
    price          REAL NOT NULL,
    amount         REAL NOT NULL,
    fee            REAL NOT NULL,
    executed_at    TEXT NOT NULL,
    cycle_id       INTEGER
);

CREATE TABLE IF NOT EXISTS snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    risk_profile    TEXT NOT NULL,
    taken_at        TEXT NOT NULL,
    total_value     REAL NOT NULL,
    cash            REAL NOT NULL,
    positions_value REAL NOT NULL,
    pnl_abs         REAL NOT NULL,
    pnl_pct         REAL NOT NULL,
    cycle_id        INTEGER
);
CREATE INDEX IF NOT EXISTS idx_snapshots_profile ON snapshots (risk_profile, taken_at);

CREATE TABLE IF NOT EXISTS price_cache (
    instrument_key TEXT PRIMARY KEY,
    price_try      REAL NOT NULL,
    change_1d_pct  REAL NOT NULL DEFAULT 0,
    change_5d_pct  REAL NOT NULL DEFAULT 0,
    change_20d_pct REAL NOT NULL DEFAULT 0,
    as_of          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS news_items (
    hash         TEXT PRIMARY KEY,
    source       TEXT NOT NULL,
    title        TEXT NOT NULL,
    summary      TEXT NOT NULL DEFAULT '',
    link         TEXT NOT NULL DEFAULT '',
    published_at TEXT,
    tier         INTEGER NOT NULL DEFAULT 3,
    fetched_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_watchlist (
    chat_id    INTEGER NOT NULL,
    ticker     TEXT    NOT NULL,
    weight     REAL    NOT NULL DEFAULT 0,
    name       TEXT    NOT NULL DEFAULT '',
    currency   TEXT    NOT NULL DEFAULT '',
    exchange   TEXT    NOT NULL DEFAULT '',
    created_at TEXT    NOT NULL,
    PRIMARY KEY (chat_id, ticker)
);
CREATE INDEX IF NOT EXISTS idx_watchlist_chat ON user_watchlist (chat_id);
"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


_connection: sqlite3.Connection | None = None


def connect() -> sqlite3.Connection:
    global _connection
    if _connection is None:
        settings.db_path.parent.mkdir(parents=True, exist_ok=True)
        _connection = sqlite3.connect(settings.db_path, check_same_thread=False)
        _connection.row_factory = sqlite3.Row
        _connection.execute("PRAGMA journal_mode=WAL")
        _connection.execute("PRAGMA foreign_keys=ON")
        _connection.executescript(SCHEMA)
        _migrate(_connection)
        _connection.commit()
    return _connection


def _migrate(conn: sqlite3.Connection) -> None:
    """Mevcut DB'lere yeni kolonlar ekler."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(subscribers)").fetchall()}
    if "income_pref" not in cols:
        conn.execute(
            "ALTER TABLE subscribers ADD COLUMN income_pref TEXT NOT NULL DEFAULT 'growth'"
        )
    if "bot_capital" not in cols:
        conn.execute("ALTER TABLE subscribers ADD COLUMN bot_capital REAL")


@contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


# --- app_state -------------------------------------------------------------


def get_state(key: str, default: Any = None) -> Any:
    row = connect().execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    return json.loads(row["value"])


def set_state(key: str, value: Any) -> None:
    with tx() as conn:
        conn.execute(
            "INSERT INTO app_state (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value, ensure_ascii=False)),
        )


# --- subscribers -----------------------------------------------------------


def upsert_subscriber(
    chat_id: int,
    risk_profile: str | None = None,
    income_pref: str | None = None,
) -> None:
    with tx() as conn:
        conn.execute(
            "INSERT INTO subscribers (chat_id, risk_profile, income_pref, created_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(chat_id) DO NOTHING",
            (chat_id, risk_profile or "mid", income_pref or "growth", iso(utcnow())),
        )
        if risk_profile:
            conn.execute(
                "UPDATE subscribers SET risk_profile = ? WHERE chat_id = ?",
                (risk_profile, chat_id),
            )
        if income_pref:
            conn.execute(
                "UPDATE subscribers SET income_pref = ? WHERE chat_id = ?",
                (income_pref, chat_id),
            )


def set_bot_capital(chat_id: int, amount: float | None) -> None:
    with tx() as conn:
        conn.execute(
            "UPDATE subscribers SET bot_capital = ? WHERE chat_id = ?",
            (amount, chat_id),
        )


def get_bot_capital(chat_id: int) -> float | None:
    row = get_subscriber(chat_id)
    if row is None:
        return None
    try:
        value = row["bot_capital"]
    except (KeyError, IndexError):
        return None
    if value is None:
        return None
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    return amount if amount > 0 else None


def get_subscriber(chat_id: int) -> sqlite3.Row | None:
    return connect().execute(
        "SELECT * FROM subscribers WHERE chat_id = ?", (chat_id,)
    ).fetchone()


def set_notify(chat_id: int, notify: bool) -> None:
    with tx() as conn:
        conn.execute(
            "UPDATE subscribers SET notify = ? WHERE chat_id = ?", (1 if notify else 0, chat_id)
        )


def subscribers_to_notify() -> list[sqlite3.Row]:
    return list(
        connect().execute("SELECT * FROM subscribers WHERE notify = 1 ORDER BY chat_id").fetchall()
    )


# --- price cache -----------------------------------------------------------


def save_prices(quotes: dict[str, dict[str, Any]]) -> None:
    now = iso(utcnow())
    with tx() as conn:
        for key, q in quotes.items():
            conn.execute(
                "INSERT INTO price_cache "
                "(instrument_key, price_try, change_1d_pct, change_5d_pct, change_20d_pct, as_of) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(instrument_key) DO UPDATE SET "
                "price_try = excluded.price_try, change_1d_pct = excluded.change_1d_pct, "
                "change_5d_pct = excluded.change_5d_pct, change_20d_pct = excluded.change_20d_pct, "
                "as_of = excluded.as_of",
                (
                    key,
                    q["price_try"],
                    q.get("change_1d_pct", 0.0),
                    q.get("change_5d_pct", 0.0),
                    q.get("change_20d_pct", 0.0),
                    q.get("as_of") or now,
                ),
            )


def load_cached_prices() -> dict[str, dict[str, Any]]:
    rows = connect().execute("SELECT * FROM price_cache").fetchall()
    return {row["instrument_key"]: dict(row) for row in rows}


# --- news ------------------------------------------------------------------


def save_news(items: list[dict[str, Any]]) -> int:
    """Yeni haberleri kaydeder, daha once gorulmemis olanlarin sayisini dondurur."""
    now = iso(utcnow())
    inserted = 0
    with tx() as conn:
        for item in items:
            cur = conn.execute(
                "INSERT INTO news_items "
                "(hash, source, title, summary, link, published_at, tier, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(hash) DO NOTHING",
                (
                    item["hash"],
                    item["source"],
                    item["title"],
                    item.get("summary", ""),
                    item.get("link", ""),
                    item.get("published_at"),
                    item.get("tier", 3),
                    now,
                ),
            )
            inserted += cur.rowcount or 0
    return inserted


def news_seen(hashes: list[str]) -> set[str]:
    if not hashes:
        return set()
    placeholders = ",".join("?" for _ in hashes)
    rows = connect().execute(
        f"SELECT hash FROM news_items WHERE hash IN ({placeholders})", hashes
    ).fetchall()
    return {row["hash"] for row in rows}


# --- cycles ----------------------------------------------------------------


def insert_cycle(
    regime: str,
    confidence: int,
    horizon_weeks: int,
    decision: str,
    analysis: dict[str, Any],
    decision_detail: dict[str, Any],
    news_count: int,
) -> int:
    with tx() as conn:
        cur = conn.execute(
            "INSERT INTO cycles "
            "(ran_at, regime, confidence, horizon_weeks, decision, analysis_json, decision_json, news_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                iso(utcnow()),
                regime,
                confidence,
                horizon_weeks,
                decision,
                json.dumps(analysis, ensure_ascii=False),
                json.dumps(decision_detail, ensure_ascii=False),
                news_count,
            ),
        )
        return int(cur.lastrowid)


def latest_cycle() -> sqlite3.Row | None:
    return connect().execute("SELECT * FROM cycles ORDER BY id DESC LIMIT 1").fetchone()


def recent_cycles(limit: int = 10) -> list[sqlite3.Row]:
    return list(
        connect().execute("SELECT * FROM cycles ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    )


# --- baskets ---------------------------------------------------------------


def active_basket(risk_profile: str) -> sqlite3.Row | None:
    return connect().execute(
        "SELECT * FROM baskets WHERE risk_profile = ? AND active = 1 ORDER BY id DESC LIMIT 1",
        (risk_profile,),
    ).fetchone()


def insert_basket(
    risk_profile: str,
    regime: str,
    weights: dict[str, float],
    rationale: str,
    cycle_id: int | None,
) -> int:
    now = iso(utcnow())
    with tx() as conn:
        conn.execute(
            "UPDATE baskets SET active = 0, retired_at = ? WHERE risk_profile = ? AND active = 1",
            (now, risk_profile),
        )
        cur = conn.execute(
            "INSERT INTO baskets (risk_profile, regime, weights_json, rationale, created_at, cycle_id, active) "
            "VALUES (?, ?, ?, ?, ?, ?, 1)",
            (
                risk_profile,
                regime,
                json.dumps(weights, ensure_ascii=False),
                rationale,
                now,
                cycle_id,
            ),
        )
        return int(cur.lastrowid)


def insert_basket_change(
    risk_profile: str,
    old_basket_id: int | None,
    new_basket_id: int,
    old_regime: str | None,
    new_regime: str,
    kind: str,
    reason: dict[str, Any],
    held_days: float,
) -> None:
    with tx() as conn:
        conn.execute(
            "INSERT INTO basket_changes "
            "(risk_profile, old_basket_id, new_basket_id, old_regime, new_regime, changed_at, kind, reason_json, held_days) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                risk_profile,
                old_basket_id,
                new_basket_id,
                old_regime,
                new_regime,
                iso(utcnow()),
                kind,
                json.dumps(reason, ensure_ascii=False),
                held_days,
            ),
        )


def basket_history(risk_profile: str, limit: int = 10) -> list[sqlite3.Row]:
    return list(
        connect().execute(
            "SELECT * FROM basket_changes WHERE risk_profile = ? ORDER BY id DESC LIMIT ?",
            (risk_profile, limit),
        ).fetchall()
    )


# --- portfolio -------------------------------------------------------------


def get_portfolio(risk_profile: str) -> sqlite3.Row | None:
    return connect().execute(
        "SELECT * FROM portfolios WHERE risk_profile = ?", (risk_profile,)
    ).fetchone()


def create_portfolio(risk_profile: str, start_capital: float) -> None:
    with tx() as conn:
        conn.execute(
            "INSERT INTO portfolios (risk_profile, cash, start_capital, started_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(risk_profile) DO NOTHING",
            (risk_profile, start_capital, start_capital, iso(utcnow())),
        )


def update_portfolio_cash(risk_profile: str, cash: float, total_fees: float) -> None:
    with tx() as conn:
        conn.execute(
            "UPDATE portfolios SET cash = ?, total_fees = ? WHERE risk_profile = ?",
            (cash, total_fees, risk_profile),
        )


def get_positions(risk_profile: str) -> dict[str, dict[str, float]]:
    rows = connect().execute(
        "SELECT instrument_key, quantity, avg_cost FROM positions WHERE risk_profile = ?",
        (risk_profile,),
    ).fetchall()
    return {
        row["instrument_key"]: {"quantity": row["quantity"], "avg_cost": row["avg_cost"]}
        for row in rows
    }


def upsert_position(risk_profile: str, key: str, quantity: float, avg_cost: float) -> None:
    with tx() as conn:
        if quantity <= 1e-12:
            conn.execute(
                "DELETE FROM positions WHERE risk_profile = ? AND instrument_key = ?",
                (risk_profile, key),
            )
            return
        conn.execute(
            "INSERT INTO positions (risk_profile, instrument_key, quantity, avg_cost) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(risk_profile, instrument_key) DO UPDATE SET "
            "quantity = excluded.quantity, avg_cost = excluded.avg_cost",
            (risk_profile, key, quantity, avg_cost),
        )


def insert_trade(
    risk_profile: str,
    key: str,
    side: str,
    quantity: float,
    price: float,
    amount: float,
    fee: float,
    cycle_id: int | None,
) -> None:
    with tx() as conn:
        conn.execute(
            "INSERT INTO trades "
            "(risk_profile, instrument_key, side, quantity, price, amount, fee, executed_at, cycle_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (risk_profile, key, side, quantity, price, amount, fee, iso(utcnow()), cycle_id),
        )


def insert_snapshot(
    risk_profile: str,
    total_value: float,
    cash: float,
    positions_value: float,
    pnl_abs: float,
    pnl_pct: float,
    cycle_id: int | None,
) -> None:
    with tx() as conn:
        conn.execute(
            "INSERT INTO snapshots "
            "(risk_profile, taken_at, total_value, cash, positions_value, pnl_abs, pnl_pct, cycle_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                risk_profile,
                iso(utcnow()),
                total_value,
                cash,
                positions_value,
                pnl_abs,
                pnl_pct,
                cycle_id,
            ),
        )


def latest_snapshot(risk_profile: str) -> sqlite3.Row | None:
    return connect().execute(
        "SELECT * FROM snapshots WHERE risk_profile = ? ORDER BY id DESC LIMIT 1",
        (risk_profile,),
    ).fetchone()


def snapshots_since(risk_profile: str, since: datetime) -> list[sqlite3.Row]:
    return list(
        connect().execute(
            "SELECT * FROM snapshots WHERE risk_profile = ? AND taken_at >= ? ORDER BY taken_at",
            (risk_profile, iso(since)),
        ).fetchall()
    )


def trade_count(risk_profile: str) -> int:
    row = connect().execute(
        "SELECT COUNT(*) AS n FROM trades WHERE risk_profile = ?", (risk_profile,)
    ).fetchone()
    return int(row["n"]) if row else 0


# --- user watchlist --------------------------------------------------------


def list_watchlist(chat_id: int) -> list[sqlite3.Row]:
    return list(
        connect()
        .execute(
            "SELECT * FROM user_watchlist WHERE chat_id = ? ORDER BY weight DESC, ticker ASC",
            (chat_id,),
        )
        .fetchall()
    )


def watchlist_count(chat_id: int) -> int:
    row = connect().execute(
        "SELECT COUNT(*) AS n FROM user_watchlist WHERE chat_id = ?", (chat_id,)
    ).fetchone()
    return int(row["n"]) if row else 0


def get_watchlist_item(chat_id: int, ticker: str) -> sqlite3.Row | None:
    return connect().execute(
        "SELECT * FROM user_watchlist WHERE chat_id = ? AND ticker = ?",
        (chat_id, ticker),
    ).fetchone()


def upsert_watchlist_item(
    chat_id: int,
    ticker: str,
    weight: float,
    name: str,
    currency: str,
    exchange: str,
) -> None:
    with tx() as conn:
        conn.execute(
            "INSERT INTO user_watchlist "
            "(chat_id, ticker, weight, name, currency, exchange, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(chat_id, ticker) DO UPDATE SET "
            "weight = excluded.weight, name = excluded.name, "
            "currency = excluded.currency, exchange = excluded.exchange",
            (chat_id, ticker, weight, name, currency, exchange, iso(utcnow())),
        )


def remove_watchlist_item(chat_id: int, ticker: str) -> bool:
    with tx() as conn:
        cur = conn.execute(
            "DELETE FROM user_watchlist WHERE chat_id = ? AND ticker = ?",
            (chat_id, ticker),
        )
        return bool(cur.rowcount)


def clear_watchlist(chat_id: int) -> int:
    with tx() as conn:
        cur = conn.execute("DELETE FROM user_watchlist WHERE chat_id = ?", (chat_id,))
        return int(cur.rowcount or 0)
