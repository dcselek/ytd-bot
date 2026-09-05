"""Telegram bot arayuzu ve zamanlanmis analiz dongusu."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import time as dtime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import Forbidden, TelegramError
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from . import discipline, engine, formatting, market, portfolio, storage, watchlist
from .baskets import RISK_PROFILES, RISK_PROFILE_EMOJI, RISK_PROFILE_TR
from .config import settings

log = logging.getLogger(__name__)

PROFILE_CALLBACK_PREFIX = "profile:"


def _profile_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"{RISK_PROFILE_EMOJI[profile]} {RISK_PROFILE_TR[profile]}",
                    callback_data=f"{PROFILE_CALLBACK_PREFIX}{profile}",
                )
            ]
            for profile in RISK_PROFILES
        ]
    )


def _profile_of(chat_id: int) -> str:
    row = storage.get_subscriber(chat_id)
    return row["risk_profile"] if row else "mid"


async def _reply(update: Update, text: str, **kwargs) -> None:
    message = update.effective_message
    if message is None:
        return
    await message.reply_text(
        text, parse_mode=ParseMode.HTML, disable_web_page_preview=True, **kwargs
    )


def _parse_try_amount(raw: str) -> float | None:
    """100000 / 100.000 / 100,5 / 100.000,50 gibi TL tutarlarini parse eder."""
    text = (raw or "").upper().replace("TL", "").replace(" ", "").strip()
    if not text:
        return None
    try:
        if "," in text and "." in text:
            text = text.replace(".", "").replace(",", ".")
        elif "," in text:
            text = text.replace(",", ".")
        elif text.count(".") > 1:
            text = text.replace(".", "")
        elif "." in text:
            left, right = text.split(".", 1)
            if left.isdigit() and len(right) == 3:
                text = left + right
        value = float(text)
    except ValueError:
        return None
    return value if value > 0 else None


# --- Komutlar --------------------------------------------------------------


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    storage.upsert_subscriber(chat_id)
    await _reply(update, formatting.welcome_message(), reply_markup=_profile_keyboard())


async def cmd_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    current = _profile_of(update.effective_chat.id)
    await _reply(
        update,
        f"Şu anki profilin: <b>{RISK_PROFILE_TR[current]}</b>\n\nDeğiştirmek için seç:",
        reply_markup=_profile_keyboard(),
    )


async def on_profile_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    profile = query.data.removeprefix(PROFILE_CALLBACK_PREFIX)
    if profile not in RISK_PROFILES:
        return

    chat_id = update.effective_chat.id
    storage.upsert_subscriber(chat_id, profile)
    await query.edit_message_text(
        f"✅ Risk profilin <b>{RISK_PROFILE_TR[profile]}</b> olarak ayarlandı.\n\n"
        "Sepeti görmek için /sepet, temsilî portföy için /portfoy yazabilirsin.",
        parse_mode=ParseMode.HTML,
    )


async def cmd_basket(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    profile = _profile_of(update.effective_chat.id)
    state = engine.current_state()
    if state["analysis"] is None:
        await _reply(update, "Bot henüz ilk analizini yapmadı. Birkaç dakika içinde hazır olacak.")
        return

    row = storage.active_basket(profile)
    if row is None:
        await _reply(update, "Bu profil için henüz sepet oluşturulmadı.")
        return

    weights = json.loads(row["weights_json"])
    await _reply(
        update,
        formatting.basket_message(
            profile, weights, state["analysis"], market.cached_quotes(), state["stability"]
        ),
    )


async def cmd_portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    profile = _profile_of(update.effective_chat.id)
    quotes = market.cached_quotes()
    view = portfolio.valuation(profile, quotes)
    await _reply(update, formatting.portfolio_message(view, portfolio.benchmarks(quotes)))


async def cmd_performance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    quotes = market.cached_quotes()
    views = [portfolio.valuation(profile, quotes) for profile in RISK_PROFILES]
    await _reply(update, formatting.performance_overview(views, portfolio.benchmarks(quotes)))


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = engine.current_state()
    if state["analysis"] is None:
        await _reply(update, "Bot henüz ilk analizini yapmadı.")
        return
    await _reply(
        update,
        formatting.status_message(
            state["analysis"],
            state["decision"],
            state["stability"],
            state["last_run"],
            state["news_count"],
        ),
    )


async def cmd_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = engine.current_state()
    if state["analysis"] is None:
        await _reply(update, "Bot henüz ilk analizini yapmadı.")
        return
    await _reply(
        update, formatting.analysis_detail_message(state["analysis"], state["news_count"])
    )


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    profile = _profile_of(update.effective_chat.id)
    rows = storage.basket_history(profile, limit=8)
    await _reply(update, formatting.history_message(profile, rows))


async def cmd_notifications(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    row = storage.get_subscriber(chat_id)
    if row is None:
        storage.upsert_subscriber(chat_id)
        row = storage.get_subscriber(chat_id)

    new_value = not bool(row["notify"])
    storage.set_notify(chat_id, new_value)
    await _reply(
        update,
        "🔔 Bildirimler <b>açık</b>. Sepet değişimlerinde haber vereceğim."
        if new_value
        else "🔕 Bildirimler <b>kapalı</b>. Komutlarla her zaman kontrol edebilirsin.",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply(update, formatting.help_message())


async def cmd_version(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from ytdbot import __version__

    await _reply(
        update,
        f"🤖 <b>YTD Bot</b> · sürüm <code>{__version__}</code>\n"
        f"<a href=\"https://github.com/dcselek/ytd-bot/releases\">GitHub releases</a>",
    )


async def cmd_watchlist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Kullanici takip sepeti: /sepetim [ekle|sil|haber|vs|uyari|temizle|yardim] ..."""
    chat_id = update.effective_chat.id
    storage.upsert_subscriber(chat_id)
    args = [a.strip() for a in (context.args or []) if a.strip()]

    if not args:
        await _reply(update, "⏳ Sepetin fiyatlanıyor...")
        snap = await asyncio.to_thread(watchlist.snapshot, chat_id)
        await _reply(update, formatting.watchlist_message(snap))
        return

    action = args[0].lower()
    if action in ("yardim", "help", "?"):
        await _reply(update, formatting.watchlist_help_message())
        return

    if action in ("ekle", "add", "+"):
        if len(args) < 2:
            await _reply(
                update,
                "Kullanım: <code>/sepetim ekle TICKER [tefas|yahoo] [ağırlık]</code>\n"
                "Örnek: <code>/sepetim ekle MAC tefas 20</code>",
            )
            return
        await _reply(update, "⏳ Sembol doğrulanıyor...")
        result = await asyncio.to_thread(watchlist.add_item_from_args, chat_id, args[1:])
        await _reply(update, result.message)
        if result.ok:
            snap = await asyncio.to_thread(watchlist.snapshot, chat_id)
            await _reply(update, formatting.watchlist_message(snap))
        return

    if action in ("sil", "remove", "rm", "-"):
        if len(args) < 2:
            await _reply(update, "Kullanım: <code>/sepetim sil TICKER</code>")
            return
        result = watchlist.remove_item(chat_id, args[1])
        await _reply(update, result.message)
        return

    if action in ("temizle", "clear", "reset"):
        result = watchlist.clear_items(chat_id)
        await _reply(update, result.message)
        return

    if action in ("haber", "haberler", "news"):
        await _reply(update, "⏳ Sepetin için haberler taranıyor...")
        matches = await asyncio.to_thread(watchlist.related_news, chat_id)
        await _reply(update, formatting.watchlist_news_message(matches))
        return

    if action in ("analiz", "analysis", "analizet"):
        await _reply(update, "⏳ Sepetin analiz ediliyor (haber + fiyat)...")
        result = await asyncio.to_thread(watchlist.analyze_watchlist, chat_id)
        if result is None:
            await _reply(
                update,
                "Sepetin boş. Önce sembol ekle: <code>/sepetim ekle MAC tefas 20</code>",
            )
            return
        await _reply(update, formatting.watchlist_analysis_message(result))
        return

    if action in ("vs", "karsilastir", "compare"):
        profile = _profile_of(chat_id)
        await _reply(update, "⏳ Karşılaştırma hesaplanıyor...")
        result = await asyncio.to_thread(watchlist.compare_to_bot, chat_id, profile)
        await _reply(
            update,
            formatting.watchlist_compare_message(result, RISK_PROFILE_TR[profile]),
        )
        return

    if action in ("uyari", "alert", "uyarı"):
        if len(args) < 2 or args[1].lower() in ("kapat", "off", "0", "kapali", "kapalı"):
            result = watchlist.set_alert_threshold(chat_id, None)
            await _reply(update, result.message)
            return
        try:
            pct = float(args[1].replace(",", ".").replace("%", ""))
        except ValueError:
            await _reply(update, "Kullanım: <code>/sepetim uyari 3</code> veya <code>/sepetim uyari kapat</code>")
            return
        result = watchlist.set_alert_threshold(chat_id, pct)
        await _reply(update, result.message)
        return

    if action in ("butce", "bütçe", "budget", "sermaye"):
        if len(args) < 2 or args[1].lower() in ("kapat", "off", "0", "sil", "temizle"):
            result = watchlist.set_budget(chat_id, None)
            await _reply(update, result.message)
            return
        amount = _parse_try_amount(args[1])
        if amount is None:
            await _reply(
                update,
                "Kullanım: <code>/sepetim butce 100000</code> veya <code>/sepetim butce 100.000</code>",
            )
            return
        result = watchlist.set_budget(chat_id, amount)
        await _reply(update, result.message)
        if result.ok and amount > 0:
            snap = await asyncio.to_thread(watchlist.snapshot, chat_id)
            await _reply(update, formatting.watchlist_message(snap))
        return

    if action not in ("liste", "list", "goster", "show"):
        await _reply(
            update,
            "Bilinmeyen alt komut. <code>/sepetim yardim</code> yazın.\n"
            "Örnek: <code>/sepetim ekle MAC tefas 20</code>",
        )
        return

    snap = await asyncio.to_thread(watchlist.snapshot, chat_id)
    await _reply(update, formatting.watchlist_message(snap))


async def cmd_run_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if settings.admin_chat_ids and chat_id not in settings.admin_chat_ids:
        await _reply(update, "Bu komut yalnızca yöneticiler için.")
        return

    await _reply(update, "⏳ Analiz döngüsü çalışıyor, bu 1-2 dakika sürebilir...")
    result = await asyncio.to_thread(engine.run_cycle)
    await _reply(
        update,
        f"✅ Döngü tamamlandı.\nKarar: <b>"
        f"{discipline.ACTION_TR.get(result.decision.action, result.decision.action)}</b>\n"
        f"Görüş: {result.analysis.regime} (güven {result.analysis.confidence}/10)\n"
        f"Haber: {result.news_count}",
    )
    if result.any_change:
        await broadcast_changes(context.application, result)


# --- Zamanlanmis isler -----------------------------------------------------


async def scheduled_cycle(context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        result = await asyncio.to_thread(engine.run_cycle)
    except Exception:  # noqa: BLE001 - zamanlanmis is asla sessizce olmemeli
        log.exception("Zamanlanmis analiz dongusu basarisiz oldu")
        return

    log.info(
        "Dongu tamamlandi: karar=%s, degisim=%s", result.decision.action, result.any_change
    )
    if result.any_change:
        await broadcast_changes(context.application, result)


async def daily_digest(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Degisim olmasa da gunde bir kez kisa durum ozeti + sepet uyarilari."""
    state = engine.current_state()
    if state["analysis"] is None:
        return

    quotes = market.cached_quotes()
    bench = portfolio.benchmarks(quotes)

    for row in storage.subscribers_to_notify():
        profile = row["risk_profile"]
        chat_id = row["chat_id"]
        view = portfolio.valuation(profile, quotes)
        text = "\n".join(
            [
                "☀️ <b>Günlük özet</b>",
                "",
                formatting.regime_line(state["analysis"]),
                f"Sepet {formatting.fmt_number(state['stability'].get('days_held') or 0, 1)} "
                "gündür değişmedi.",
                "",
                f"{RISK_PROFILE_EMOJI[profile]} <b>{RISK_PROFILE_TR[profile]}</b> temsilî portföy: "
                f"{formatting.fmt_try(view.total_value)} · "
                f"{formatting.pnl_emoji(view.pnl_abs)} <b>{formatting.fmt_pct(view.pnl_pct)}</b>",
                (
                    f"<i>BIST 100 aynı dönemde {formatting.fmt_pct(bench['XU100'])}</i>"
                    if "XU100" in bench
                    else ""
                ),
                "",
                "Detay için /portfoy · /sepet · /sepetim · /durum",
                "",
                formatting.DISCLAIMER,
            ]
        )
        await _send(context.application, chat_id, text)

        # Kullanici takip sepeti uyarilari
        threshold = watchlist.get_alert_threshold(chat_id)
        if threshold:
            try:
                snap = await asyncio.to_thread(watchlist.snapshot, chat_id)
                hits = watchlist.alert_hits(chat_id, snap)
                if hits:
                    await _send(
                        context.application,
                        chat_id,
                        formatting.watchlist_alerts_message(hits, threshold),
                    )
            except Exception:  # noqa: BLE001
                log.exception("Watchlist uyari kontrolu basarisiz: %s", chat_id)


async def broadcast_changes(application: Application, result: engine.CycleResult) -> None:
    state_stability = discipline.stability_summary()
    for row in storage.subscribers_to_notify():
        profile = row["risk_profile"]
        outcome = result.outcomes.get(profile)
        if outcome is None or not outcome.changed:
            continue
        text = formatting.change_alert(
            profile,
            outcome.old_weights,
            outcome.new_weights,
            result.analysis,
            result.decision,
            state_stability,
        )
        await _send(application, row["chat_id"], text)


async def _send(application: Application, chat_id: int, text: str) -> None:
    try:
        await application.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Forbidden:
        log.info("Kullanici botu engellemis, bildirim kapatiliyor: %s", chat_id)
        storage.set_notify(chat_id, False)
    except TelegramError as exc:
        log.warning("Mesaj gonderilemedi (%s): %s", chat_id, exc)


# --- Uygulama --------------------------------------------------------------


async def _post_init(application: Application) -> None:
    await application.bot.set_my_commands(
        [
            ("sepet", "Botun temsilî sepeti"),
            ("sepetim", "Senin takip sepetin"),
            ("portfoy", "Temsilî portföy kâr/zarar"),
            ("performans", "Profillerin karşılaştırması"),
            ("durum", "Piyasa görüşü ve istikrar"),
            ("analiz", "Analiz detayı"),
            ("gecmis", "Sepet değişim geçmişi"),
            ("profil", "Risk profilini değiştir"),
            ("bildirim", "Bildirimleri aç/kapat"),
            ("surum", "Bot sürümü"),
            ("yardim", "Komut listesi"),
        ]
    )
    log.info("Bot hazir")


def build_application() -> Application:
    if not settings.telegram_token:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN tanimli degil. .env dosyasini olusturup token ekleyin."
        )

    storage.connect()
    portfolio.ensure_portfolios()

    application = (
        ApplicationBuilder().token(settings.telegram_token).post_init(_post_init).build()
    )

    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler(["yardim", "help"], cmd_help))
    application.add_handler(CommandHandler(["profil", "profile"], cmd_profile))
    application.add_handler(CommandHandler(["sepet", "basket"], cmd_basket))
    application.add_handler(CommandHandler(["sepetim", "watchlist", "mybasket"], cmd_watchlist))
    application.add_handler(CommandHandler(["portfoy", "portfolio"], cmd_portfolio))
    application.add_handler(CommandHandler(["performans", "performance"], cmd_performance))
    application.add_handler(CommandHandler(["durum", "status"], cmd_status))
    application.add_handler(CommandHandler(["analiz", "analysis"], cmd_analysis))
    application.add_handler(CommandHandler(["gecmis", "history"], cmd_history))
    application.add_handler(CommandHandler(["bildirim", "notifications"], cmd_notifications))
    application.add_handler(CommandHandler(["surum", "version"], cmd_version))
    application.add_handler(CommandHandler(["calistir", "runnow"], cmd_run_now))
    application.add_handler(
        CallbackQueryHandler(on_profile_selected, pattern=f"^{PROFILE_CALLBACK_PREFIX}")
    )

    job_queue = application.job_queue
    interval = settings.cycle_hours * 3600
    job_queue.run_repeating(scheduled_cycle, interval=interval, first=15, name="analysis_cycle")
    job_queue.run_daily(
        daily_digest,
        time=dtime(hour=9, minute=0, tzinfo=formatting.TR_TZ),
        name="daily_digest",
    )
    return application


def main() -> None:
    application = build_application()
    log.info("Bot baslatiliyor (dongu: %d saat)", settings.cycle_hours)
    application.run_polling(drop_pending_updates=True)
