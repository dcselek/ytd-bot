"""TEFAS (Türkiye Elektronik Fon Alım Satım Platformu) veri katmani.

Yahoo Finance kisa TR fon kodlarini siklikla ABD hisseleriyle (NYSE/PCX)
karistirir. Bu modul tefasmak uzerinden resmi TEFAS fiyatini kullanir.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from . import storage

log = logging.getLogger(__name__)

TEFAS_PREFIX = "TEFAS:"
_CODE_RE = re.compile(r"^[A-Z]{2,5}$")


@dataclass
class TefasMeta:
    code: str
    name: str
    category: str = ""


@dataclass
class TefasQuote:
    code: str
    name: str
    price_try: float
    change_1d_pct: float
    change_5d_pct: float
    change_20d_pct: float
    as_of: datetime


def is_tefas_ticker(ticker: str) -> bool:
    return (ticker or "").upper().startswith(TEFAS_PREFIX)


def strip_prefix(ticker: str) -> str:
    raw = (ticker or "").strip().upper()
    if raw.startswith(TEFAS_PREFIX):
        return raw[len(TEFAS_PREFIX) :]
    return raw


def storage_ticker(code: str) -> str:
    return f"{TEFAS_PREFIX}{code.upper()}"


def looks_like_fund_code(raw: str) -> bool:
    """Noktasiz 2-5 harfli kodlar TEFAS adayi (MAC, TTE, AAL...)."""
    code = strip_prefix(raw).replace(".", "")
    return bool(_CODE_RE.match(code))


def resolve_fund(raw: str) -> TefasMeta | None:
    code = strip_prefix(raw)
    if not _CODE_RE.match(code):
        return None
    try:
        from tefasmak import fon_anlik_bilgi
    except ImportError:
        log.warning("tefasmak yuklu degil; TEFAS cozumlemesi atlandi")
        return None

    try:
        info = fon_anlik_bilgi(code)
    except Exception as exc:  # noqa: BLE001
        log.warning("TEFAS anlik bilgi basarisiz (%s): %s", code, exc)
        return None

    if not info or not info.get("fonKodu"):
        return None

    return TefasMeta(
        code=str(info["fonKodu"]).upper(),
        name=str(info.get("fonUnvan") or code)[:160],
        category=str(info.get("fonKategori") or "")[:80],
    )


def _pct(series: list[float], periods: int) -> float:
    if len(series) <= periods:
        return 0.0
    prev = series[-1 - periods]
    if prev == 0:
        return 0.0
    return (series[-1] / prev - 1.0) * 100.0


def fetch_quotes(codes: list[str]) -> dict[str, TefasQuote]:
    """TEFAS fon kodlari icin TL fiyat + momentum."""
    if not codes:
        return {}

    try:
        from tefasmak import PERIYOD_3AY, fon_anlik_bilgi, fon_fiyat_gecmisi
    except ImportError:
        log.warning("tefasmak yuklu degil; TEFAS fiyatlari atlandi")
        return {}

    result: dict[str, TefasQuote] = {}
    for raw in codes:
        code = strip_prefix(raw)
        try:
            hist = fon_fiyat_gecmisi(code, PERIYOD_3AY) or []
            prices = [float(row["fiyat"]) for row in hist if row.get("fiyat") is not None]
            info = fon_anlik_bilgi(code) or {}
            if not prices and info.get("sonFiyat") is not None:
                prices = [float(info["sonFiyat"])]
            if not prices:
                continue

            last_price = float(info.get("sonFiyat") or prices[-1])
            # Anlik getiri varsa 1g icin onu tercih et.
            change_1d = float(info["gunlukGetiri"]) if info.get("gunlukGetiri") is not None else _pct(prices, 1)
            as_of = storage.utcnow()
            if hist and hist[-1].get("tarih"):
                try:
                    as_of = datetime.strptime(hist[-1]["tarih"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                except ValueError:
                    pass

            result[storage_ticker(code)] = TefasQuote(
                code=code,
                name=str(info.get("fonUnvan") or (hist[-1].get("fonUnvan") if hist else code)),
                price_try=last_price,
                change_1d_pct=change_1d,
                change_5d_pct=_pct(prices, 5),
                change_20d_pct=_pct(prices, 20),
                as_of=as_of,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("TEFAS fiyat cekilemedi (%s): %s", code, exc)
    return result
