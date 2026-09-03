"""Windows konsolunda da Turkce karakter bozulmadan calisan log ayari."""

from __future__ import annotations

import logging
import sys

from .config import BASE_DIR


def configure(level: int = logging.INFO) -> None:
    log_dir = BASE_DIR / "data"
    log_dir.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)-22s %(message)s", datefmt="%H:%M:%S"
    )

    stream = sys.stdout
    if hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

    console = logging.StreamHandler(stream)
    console.setFormatter(formatter)

    file_handler = logging.FileHandler(log_dir / "bot.log", encoding="utf-8")
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    root.addHandler(console)
    root.addHandler(file_handler)

    # Kutuphanelerin gurultusunu kisiyoruz.
    for noisy in ("httpx", "telegram.ext.Application", "apscheduler", "yfinance", "peewee"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
