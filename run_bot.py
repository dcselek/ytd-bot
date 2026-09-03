"""Telegram botunu baslatir (zamanlanmis analiz dongusuyle birlikte)."""

from __future__ import annotations

from ytdbot import bot, logging_setup


def main() -> None:
    logging_setup.configure()
    bot.main()


if __name__ == "__main__":
    main()
