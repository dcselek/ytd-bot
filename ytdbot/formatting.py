"""Telegram mesaj sablonlari (HTML parse mode)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from html import escape as _html_escape

from . import discipline, market, storage, universe
from .analysis import REGIME_EMOJI, REGIME_TR, Analysis
from .baskets import RISK_PROFILE_DESC, RISK_PROFILE_EMOJI, RISK_PROFILE_TR
from .config import settings
from .portfolio import PortfolioView

TR_TZ = timezone(timedelta(hours=3))

DISCLAIMER = (
    "<i>Bu içerik yatırım tavsiyesi değildir; eğitim ve bilgilendirme amaçlıdır. "
    "Portföy tamamen temsilîdir, gerçek para kullanılmaz.</i>"
)

BENCHMARK_LABELS = {
    "XU100": "BIST 100",
    "MONEY_MARKET": "Likit fon",
    "GOLD_GRAM": "Gram altın",
    "USDTRY": "Dolar",
}


def escape(text: object) -> str:
    """Telegram HTML icin kacis. Kesme isareti/tirnak entity'ye cevrilmez ki
    Turkce metinler ("BIST 100'un") ekranda bozuk gorunmesin."""
    return _html_escape(str(text), quote=False)


def fmt_number(value: float, decimals: int = 2) -> str:
    """Türk sayı biçimi: 1.234,56"""
    text = f"{value:,.{decimals}f}"
    return text.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def fmt_try(value: float, decimals: int = 2) -> str:
    return f"{fmt_number(value, decimals)} TL"


def fmt_pct(value: float, decimals: int = 2) -> str:
    sign = "+" if value >= 0 else ""
    return f"{sign}{fmt_number(value, decimals)}%"


def _running_text(days: float) -> str:
    if days < 1:
        return "bugün başladı"
    return f"{fmt_number(days, 0)} gündür takipte"


def pnl_emoji(value: float) -> str:
    if value > 0.01:
        return "🟢"
    if value < -0.01:
        return "🔴"
    return "⚪"


def fmt_date(dt: datetime | None, with_time: bool = True) -> str:
    if dt is None:
        return "—"
    local = dt.astimezone(TR_TZ)
    return local.strftime("%d.%m.%Y %H:%M") if with_time else local.strftime("%d.%m.%Y")


def regime_line(analysis: Analysis) -> str:
    emoji = REGIME_EMOJI.get(analysis.regime, "")
    return (
        f"{emoji} <b>{REGIME_TR.get(analysis.regime, analysis.regime)}</b> "
        f"· güven {analysis.confidence}/10 · ufuk ~{analysis.horizon_weeks} hafta"
    )


def weights_block(
    weights: dict[str, float], quotes: dict[str, market.Quote] | None = None
) -> str:
    lines = []
    for key, weight in sorted(weights.items(), key=lambda kv: -kv[1]):
        inst = universe.get(key)
        # Enstruman adlari kendini anlatiyor; yalnizca hisselerde sektor bilgisi ekliyoruz.
        detail = f" · <i>{escape(', '.join(inst.sectors))}</i>" if inst.sectors else ""
        suffix = ""
        if quotes and key not in ("CASH", "MONEY_MARKET"):
            quote = quotes.get(key)
            if quote:
                suffix = f" <i>(20 günde {fmt_pct(quote.change_20d_pct, 1)})</i>"
        lines.append(
            f"• <b>%{fmt_number(weight, 1)}</b> — {escape(inst.name)}{detail}{suffix}"
        )
    return "\n".join(lines)


def basket_message(
    risk_profile: str,
    weights: dict[str, float],
    analysis: Analysis,
    quotes: dict[str, market.Quote],
    stability: dict,
) -> str:
    locked_until = stability.get("locked_until")
    days_held = stability.get("days_held")

    parts = [
        f"{RISK_PROFILE_EMOJI[risk_profile]} <b>{RISK_PROFILE_TR[risk_profile]} sepeti</b>",
        f"<i>{escape(RISK_PROFILE_DESC[risk_profile])}</i>",
        "",
        regime_line(analysis),
        "",
        weights_block(weights, quotes),
        "",
        "🔒 <b>İstikrar</b>",
        f"• Sepet {fmt_number(days_held or 0, 1)} gündür yürürlükte"
        if days_held is not None
        else "• Sepet yeni kuruldu",
        f"• En erken değişim: {fmt_date(locked_until, with_time=False)} "
        f"(minimum {stability['min_lifetime_days']} gün kuralı)",
        f"• Sonraki ağırlık kontrolü: {fmt_date(stability.get('next_review_at'), with_time=False)}",
    ]

    if stability.get("in_transition"):
        parts.append(
            f"• ⏳ Kademeli geçiş sürüyor: adım "
            f"{stability['transition_step']}/{stability['transition_steps']}"
        )
    if stability.get("pending_regime"):
        parts.append(
            f"• 👀 İzlemede: {REGIME_TR.get(stability['pending_regime'], '')} görüşü "
            f"{stability['pending_streak']}/{stability['required_streak']} doğrulamada"
        )

    if analysis.summary_tr:
        parts += ["", "🧭 <b>Değerlendirme</b>", escape(analysis.summary_tr)]

    if analysis.drivers:
        parts += ["", "📌 <b>Gerekçeler</b>"]
        parts += [f"• {escape(driver)}" for driver in analysis.drivers]

    parts += ["", DISCLAIMER]
    return "\n".join(parts)


def portfolio_message(view: PortfolioView, bench: dict[str, float]) -> str:
    emoji = pnl_emoji(view.pnl_abs)
    parts = [
        f"{RISK_PROFILE_EMOJI[view.risk_profile]} <b>{RISK_PROFILE_TR[view.risk_profile]} "
        "— temsilî portföy</b>",
        "",
        f"Başlangıç: <b>{fmt_try(view.start_capital, 0)}</b> "
        f"({fmt_date(view.started_at, with_time=False)})",
        f"Güncel değer: <b>{fmt_try(view.total_value)}</b>",
        f"{emoji} Kâr/Zarar: <b>{fmt_try(view.pnl_abs)} ({fmt_pct(view.pnl_pct)})</b>",
        "",
        f"<i>{_running_text(view.days_running)} · "
        f"{int(view.trade_count)} işlem · komisyon {fmt_try(view.total_fees)}</i>",
    ]

    if view.positions:
        parts += ["", "📦 <b>Pozisyonlar</b>"]
        for pos in view.positions:
            flag = " ⚠️" if pos.stale else ""
            parts.append(
                f"• {escape(pos.name)} — %{fmt_number(pos.weight_pct, 1)} · "
                f"{fmt_try(pos.value)} · {pnl_emoji(pos.pnl_abs)} {fmt_pct(pos.pnl_pct, 1)}{flag}"
            )
    parts.append(f"• Nakit — {fmt_try(view.cash)}")

    if bench:
        parts += ["", "📊 <b>Aynı dönemde referanslar</b>"]
        for key, pct in bench.items():
            label = BENCHMARK_LABELS.get(key, key)
            parts.append(f"• {label}: {pnl_emoji(pct)} {fmt_pct(pct)}")
        parts.append(
            f"• <b>Bu sepet: {pnl_emoji(view.pnl_pct)} {fmt_pct(view.pnl_pct)}</b>"
        )

    parts += ["", DISCLAIMER]
    return "\n".join(parts)


def status_message(
    analysis: Analysis,
    decision: discipline.Decision,
    stability: dict,
    last_run: datetime | None,
    news_count: int,
) -> str:
    parts = [
        "🧭 <b>Bot durumu</b>",
        "",
        regime_line(analysis),
        f"Analiz kaynağı: {'LLM' if analysis.source == 'llm' else 'kural tabanlı yedek'}",
        "",
        f"Son çalışma: {fmt_date(last_run)} · {news_count} haber okundu",
        f"Çalışma sıklığı: {settings.cycle_hours} saatte bir",
        "",
        "🔒 <b>İstikrar</b>",
        f"• Yürürlükteki görüş: {REGIME_TR.get(stability['regime'], stability['regime'])}",
        f"• Son değişim: {fmt_date(stability.get('last_change_at'))}",
        f"• Değişim olasılığı: <b>{stability_probability_tr(decision.change_probability)}</b>",
        f"• Sonraki ağırlık kontrolü: {fmt_date(stability.get('next_review_at'), with_time=False)}",
        "",
        f"⚙️ <b>Son karar:</b> {escape(discipline.ACTION_TR.get(decision.action, decision.action))}",
    ]
    parts += [f"• {escape(reason)}" for reason in decision.reasons]
    if decision.blocked_reasons:
        parts += ["", "⏸️ <b>Neden beklemede</b>"]
        parts += [f"• {escape(reason)}" for reason in decision.blocked_reasons]

    parts += ["", DISCLAIMER]
    return "\n".join(parts)


def stability_probability_tr(value: str) -> str:
    return {
        "cok dusuk": "çok düşük",
        "dusuk": "düşük",
        "orta": "orta",
        "yuksek": "yüksek",
    }.get(value, value)


def change_alert(
    risk_profile: str,
    old_weights: dict[str, float],
    new_weights: dict[str, float],
    analysis: Analysis,
    decision: discipline.Decision,
    stability: dict,
) -> str:
    """Danışman tarzı sepet değişim bildirimi."""
    is_switch = decision.action in (discipline.SWITCH, discipline.SWITCH_STEP)
    header = (
        "🔔 <b>SEPET DEĞİŞİMİ</b>" if is_switch else "🔧 <b>AĞIRLIK AYARI</b>"
    )

    parts = [
        f"{header} — {RISK_PROFILE_EMOJI[risk_profile]} {RISK_PROFILE_TR[risk_profile]}",
        "",
    ]

    if is_switch:
        parts.append(
            f"Görüş: <b>{REGIME_TR.get(decision.current_regime, decision.current_regime)}</b> → "
            f"<b>{REGIME_TR.get(decision.target_regime, decision.target_regime)}</b>"
        )
    else:
        parts.append(
            f"Görüş aynı kalıyor: <b>{REGIME_TR.get(decision.target_regime, '')}</b>. "
            "Yalnızca ağırlıklar hedefe çekiliyor."
        )

    parts += [
        f"Önceki sepet {fmt_number(decision.days_held, 1)} gün yürürlükte kaldı.",
        "",
        "📌 <b>Neden değişiyor?</b>",
    ]
    parts += [f"• {escape(reason)}" for reason in decision.reasons]

    parts += ["", "📦 <b>Yeni sepet</b>"]
    keys = sorted(set(old_weights) | set(new_weights), key=lambda k: -new_weights.get(k, 0.0))
    for key in keys:
        old = old_weights.get(key, 0.0)
        new = new_weights.get(key, 0.0)
        if abs(new - old) < 0.05 and new == 0:
            continue
        name = escape(universe.get(key).name)
        if new <= 0.05:
            parts.append(f"• <s>{name}</s> — çıkarıldı (önceki %{fmt_number(old, 1)})")
        elif old <= 0.05:
            parts.append(f"• {name} — <b>%{fmt_number(new, 1)}</b> (yeni)")
        elif abs(new - old) >= 0.05:
            arrow = "↗" if new > old else "↘"
            parts.append(
                f"• {name} — <b>%{fmt_number(new, 1)}</b> {arrow} "
                f"(önceki %{fmt_number(old, 1)})"
            )
        else:
            parts.append(f"• {name} — %{fmt_number(new, 1)} (değişmedi)")

    if decision.transition_ratio < 1.0:
        parts += [
            "",
            f"⏳ <b>Kademeli geçiş:</b> adım {decision.transition_step}/"
            f"{discipline.TRANSITION_STEPS}. Hedefe tek hamlede geçmiyoruz; "
            f"kalan kısım ~{discipline.TRANSITION_STEP_DAYS} gün sonra uygulanacak.",
        ]

    parts += [
        "",
        "💡 <i>Sık pozisyon değiştiren bir bot değiliz. Bu değişim, birden fazla "
        "doğrulama döngüsünden geçtiği ve minimum bekleme süresi tamamlandığı için "
        "yapılıyor. Acele etmenize gerek yok.</i>",
    ]

    if analysis.risks:
        parts += ["", "⚠️ <b>Bu görüşü bozabilecekler</b>"]
        parts += [f"• {escape(risk)}" for risk in analysis.risks]

    parts += ["", DISCLAIMER]
    return "\n".join(parts)


def history_message(risk_profile: str, rows: list) -> str:
    parts = [
        f"🗓️ <b>{RISK_PROFILE_TR[risk_profile]} — değişim geçmişi</b>",
        "",
    ]
    if not rows:
        parts.append("Henüz kayıtlı bir değişim yok.")
        parts += ["", DISCLAIMER]
        return "\n".join(parts)

    for row in rows:
        reason = json.loads(row["reason_json"])
        reasons = reason.get("reasons") or []
        kind = {
            "rebalance": "Ağırlık ayarı",
            "transition": "Kademeli geçiş adımı",
        }.get(row["kind"], "Sepet değişimi")
        old_regime = REGIME_TR.get(row["old_regime"] or "", "—")
        new_regime = REGIME_TR.get(row["new_regime"], row["new_regime"])
        parts.append(
            f"<b>{fmt_date(storage.parse_iso(row['changed_at']), with_time=False)}</b> — {kind}"
        )
        parts.append(f"   {old_regime} → {new_regime}")
        if row["held_days"]:
            parts.append(f"   Önceki sepet {fmt_number(row['held_days'], 1)} gün kaldı")
        if reasons:
            parts.append(f"   <i>{escape(reasons[0])}</i>")
        parts.append("")

    parts.append(DISCLAIMER)
    return "\n".join(parts)


def analysis_detail_message(analysis: Analysis, news_count: int) -> str:
    parts = [
        "📰 <b>Analiz detayı</b>",
        "",
        regime_line(analysis),
        f"<i>{news_count} haber başlığı ve TL bazlı fiyat verisi değerlendirildi.</i>",
    ]
    if analysis.summary_tr:
        parts += ["", escape(analysis.summary_tr)]
    if analysis.drivers:
        parts += ["", "📌 <b>Görüşü destekleyenler</b>"]
        parts += [f"• {escape(d)}" for d in analysis.drivers]
    if analysis.risks:
        parts += ["", "⚠️ <b>Riskler</b>"]
        parts += [f"• {escape(r)}" for r in analysis.risks]
    if analysis.tier1_events:
        parts += ["", "🚨 <b>Kritik gelişmeler</b>"]
        parts += [f"• {escape(e)}" for e in analysis.tier1_events]
    if analysis.sector_views:
        parts += ["", "🏭 <b>Sektör görüşleri</b>"]
        view_tr = {"positive": "pozitif", "neutral": "nötr", "negative": "negatif"}
        for sector, view in analysis.sector_views.items():
            parts.append(f"• {escape(sector)}: {view_tr.get(view, view)}")

    parts += ["", DISCLAIMER]
    return "\n".join(parts)


def welcome_message() -> str:
    return "\n".join(
        [
            "👋 <b>Hoş geldin!</b>",
            "",
            "Ben haberleri ve piyasa verisini düzenli olarak okuyup "
            "<b>orta-uzun vadeli</b> yatırımcılar için temsilî sepetler oluşturan bir botum.",
            "",
            "Nasıl çalışıyorum:",
            f"• Her {settings.cycle_hours} saatte bir haberleri ve fiyatları tararım.",
            f"• Ama sepeti <b>en az {settings.min_basket_lifetime_days} gün</b> değiştirmem.",
            f"• Görüş değişimi için sinyalin {settings.regime_confirmation_cycles} ardışık "
            "döngüde doğrulanması gerekir.",
            "• Değişim yaparsam nedenini danışman gibi tek tek açıklarım.",
            "",
            "Ayrıca <b>/sepetim</b> ile kendi takip sepetini oluşturabilirsin "
            "(farklı ülke borsaları dahil).",
            "",
            f"Her risk profili için <b>{fmt_try(settings.start_capital_try, 0)}</b> temsilî "
            "sermaye ile başlıyorum ve kâr/zararı şeffaf şekilde takip ediyorum.",
            "",
            "Önce risk profilini seç:",
        ]
    )


def help_message() -> str:
    return "\n".join(
        [
            "📖 <b>Komutlar</b>",
            "",
            "/sepet — Botun temsilî sepeti ve gerekçeleri",
            "/sepetim — Senin takip sepetin (analiz / haber / vs)",
            "/portfoy — Temsilî portföyün kâr/zarar durumu",
            "/performans — Tüm risk profillerinin karşılaştırması",
            "/durum — Piyasa görüşü, istikrar ve son karar",
            "/analiz — Botun genel piyasa analizi",
            "/gecmis — Sepet değişim geçmişi",
            "/profil — Risk profilini değiştir",
            "/bildirim — Bildirimleri aç/kapat",
            "/surum — Bot sürümü",
            "/yardim — Bu mesaj",
            "",
            DISCLAIMER,
        ]
    )


def watchlist_help_message() -> str:
    return "\n".join(
        [
            "🧺 <b>Senin sepetin (/sepetim)</b>",
            "",
            "Botun temsilî sepetinden bağımsızdır. Kendi takip listen:",
            "",
            "<code>/sepetim</code> — liste + TL fiyatlar",
            "<code>/sepetim ekle AAPL 30</code> — hisse/ETF (Yahoo)",
            "<code>/sepetim ekle MAC tefas 20</code> — TEFAS fonu",
            "<code>/sepetim ekle MAC yahoo</code> — aynı kodun ABD karşılığı",
            "<code>/sepetim sil TEFAS:MAC</code> — çıkar",
            "<code>/sepetim haber</code> — ilgili haberler",
            "<code>/sepetim analiz</code> — sepetine özel değerlendirme",
            "<code>/sepetim butce 100000</code> — sepet bütçesi (TL)",
            "<code>/sepetim butce kapat</code> — bütçeyi temizle",
            "<code>/sepetim vs</code> — bot sepetiyle 20g karşılaştırma",
            "<code>/sepetim uyari 3</code> — 1g ±%3 hareket uyarısı",
            "<code>/sepetim uyari kapat</code> — uyarıyı kapat",
            "<code>/sepetim temizle</code> — tümünü sil",
            "",
            "📌 <b>TEFAS notu:</b> Kısa fon kodları (MAC, TTE…) Yahoo’da ABD "
            "hissesiyle (NYSE/PCX) çakışabilir. Bot otomatik önce TEFAS’a bakar; "
            "zorlamak için <code>tefas</code> / <code>yahoo</code> yazın.",
            "",
            f"En fazla {settings.max_watchlist_items} sembol.",
            "",
            DISCLAIMER,
        ]
    )


def watchlist_message(snap) -> str:
    from .watchlist import WatchSnapshot

    assert isinstance(snap, WatchSnapshot)
    parts = [
        "🧺 <b>Senin takip sepetin</b>",
        "<i>Bot önerisi değil — senin tanımladığın liste.</i>",
        "",
    ]
    if snap.budget_try:
        parts.append(f"💵 Bütçe: <b>{fmt_try(snap.budget_try, 0)}</b>")
        parts.append("")

    if not snap.items:
        parts += [
            "Sepetin boş.",
            "",
            "Hisse: <code>/sepetim ekle AAPL 25</code>",
            "TEFAS fon: <code>/sepetim ekle MAC tefas 20</code>",
            "Bütçe: <code>/sepetim butce 100000</code>",
            "Yardım: <code>/sepetim yardim</code>",
            "",
            DISCLAIMER,
        ]
        return "\n".join(parts)

    for item in snap.items:
        weight_bit = f"%{fmt_number(item.weight, 0)} · " if item.weight else ""
        if item.exchange == "TEFAS" or item.ticker.startswith("TEFAS:"):
            exch = " · <b>TEFAS</b>"
            display = item.ticker.removeprefix("TEFAS:")
        else:
            exch = f" · {escape(item.exchange)}" if item.exchange else ""
            display = item.ticker

        budget_bit = ""
        if item.allocated_try is not None:
            budget_bit = f" · tahmini {fmt_try(item.allocated_try, 0)}"
            if item.approx_qty is not None:
                budget_bit += f" (~{fmt_number(item.approx_qty, 4)} adet)"

        if item.quote:
            q = item.quote
            native = ""
            if q.currency and q.currency != "TRY":
                native = f" ({fmt_number(q.price_native, 2)} {escape(q.currency)})"
            parts.append(
                f"• <b>{escape(display)}</b> — {escape(item.name)}{exch}\n"
                f"  {weight_bit}{fmt_try(q.price_try)}{native}{budget_bit}\n"
                f"  1g {pnl_emoji(q.change_1d_pct)} {fmt_pct(q.change_1d_pct, 1)} · "
                f"5g {fmt_pct(q.change_5d_pct, 1)} · "
                f"20g {fmt_pct(q.change_20d_pct, 1)}"
            )
        else:
            parts.append(
                f"• <b>{escape(display)}</b> — {escape(item.name)}{exch}\n"
                f"  {weight_bit}<i>fiyat alınamadı</i>{budget_bit}"
            )

    parts.append("")
    if snap.weight_sum > 0:
        parts.append(f"Ağırlık toplamı: <b>%{fmt_number(snap.weight_sum, 1)}</b>")
        if abs(snap.weight_sum - 100) > 0.5:
            parts.append("<i>Toplam 100 değil; ağırlıklı özet yine de hesaplanır.</i>")
        if snap.budget_try and snap.allocated_sum_try is not None:
            unused = snap.budget_try - snap.allocated_sum_try
            parts.append(
                f"Dağıtılan: <b>{fmt_try(snap.allocated_sum_try, 0)}</b>"
                + (f" · kalan {fmt_try(unused, 0)}" if abs(unused) >= 1 else "")
            )
    if snap.weighted_1d_pct is not None:
        line = (
            f"Sepet özeti (ağırlıklı): 1g {pnl_emoji(snap.weighted_1d_pct)} "
            f"<b>{fmt_pct(snap.weighted_1d_pct, 1)}</b> · "
            f"5g {fmt_pct(snap.weighted_5d_pct or 0, 1)} · "
            f"20g {fmt_pct(snap.weighted_20d_pct or 0, 1)}"
        )
        parts.append(line)
    if snap.approx_pnl_1d_try is not None and snap.budget_try:
        parts.append(
            f"Bütçeye göre kaba PnL: 1g {pnl_emoji(snap.approx_pnl_1d_try)} "
            f"<b>{fmt_try(snap.approx_pnl_1d_try)}</b> · "
            f"20g {pnl_emoji(snap.approx_pnl_20d_try or 0)} "
            f"<b>{fmt_try(snap.approx_pnl_20d_try or 0)}</b>"
        )
        parts.append("<i>PnL, bütçe × ağırlıklı getiridir; gerçek işlem simülasyonu değildir.</i>")

    parts += [
        "",
        "Haber: /sepetim haber · Analiz: /sepetim analiz · Bütçe: /sepetim butce",
        "",
        DISCLAIMER,
    ]
    return "\n".join(parts)


def watchlist_news_message(matches: list) -> str:
    parts = [
        "📰 <b>Sepetinle ilgili haberler</b>",
        "",
    ]
    if not matches:
        parts += [
            "Eşleşen haber bulunamadı.",
            "Sepete sembol ekleyip tekrar deneyin: <code>/sepetim ekle …</code>",
            "",
            DISCLAIMER,
        ]
        return "\n".join(parts)

    for article, tickers in matches:
        stamp = (
            article.published_at.astimezone(TR_TZ).strftime("%d.%m %H:%M")
            if article.published_at
            else "—"
        )
        tag = ", ".join(t.removeprefix("TEFAS:") for t in tickers[:3])
        link = f' — <a href="{escape(article.link)}">link</a>' if article.link else ""
        parts.append(
            f"[T{article.tier}] <b>{escape(tag)}</b> · {escape(article.source)} · {stamp}\n"
            f"{escape(article.title)}{link}"
        )
        parts.append("")

    parts.append(DISCLAIMER)
    return "\n".join(parts)


def watchlist_compare_message(result, profile_tr: str) -> str:
    parts = [
        "⚖️ <b>Sepetin vs bot sepeti</b>",
        f"<i>Bot profili: {escape(profile_tr)} · son ~20 işlem günü (yaklaşık)</i>",
        "",
    ]
    if result.watch_items == 0:
        parts += ["Senin sepetin boş. Önce <code>/sepetim ekle …</code>", "", DISCLAIMER]
        return "\n".join(parts)

    w = result.watch_20d
    b = result.bot_20d
    parts.append(
        f"🧺 Senin sepetin: "
        + (f"{pnl_emoji(w)} <b>{fmt_pct(w, 1)}</b>" if w is not None else "<i>hesaplanamadı</i>")
    )
    parts.append(
        f"🤖 Bot sepeti: "
        + (f"{pnl_emoji(b)} <b>{fmt_pct(b, 1)}</b>" if b is not None else "<i>henüz yok</i>")
    )
    if w is not None and b is not None:
        diff = w - b
        parts.append(f"Fark: <b>{fmt_pct(diff, 1)}</b> (sen − bot)")
    parts += [
        "",
        "<i>Bu bir yarışma skoru değil; eğitim amaçlı kaba karşılaştırmadır.</i>",
        "",
        DISCLAIMER,
    ]
    return "\n".join(parts)


def watchlist_alerts_message(hits: list, threshold: float) -> str:
    parts = [
        f"🚨 <b>Sepet uyarısı</b> (±%{fmt_number(threshold, 1)} / 1g)",
        "",
    ]
    for item in hits:
        q = item.quote
        display = item.ticker.removeprefix("TEFAS:")
        parts.append(
            f"• <b>{escape(display)}</b> — {escape(item.name)}: "
            f"{pnl_emoji(q.change_1d_pct)} <b>{fmt_pct(q.change_1d_pct, 1)}</b>"
        )
    parts += ["", DISCLAIMER]
    return "\n".join(parts)


def watchlist_analysis_message(analysis) -> str:
    tone_tr = {
        "positive": ("📈", "Olumlu eğilim"),
        "mixed": ("⚖️", "Karışık / temkinli"),
        "negative": ("📉", "Temkinli / olumsuz"),
    }
    emoji, label = tone_tr.get(analysis.tone, ("⚖️", analysis.tone))
    source = "LLM" if analysis.source == "llm" else "kural tabanlı yedek"
    parts = [
        "🧺📰 <b>Senin sepetinin analizi</b>",
        "<i>Botun genel piyasa analizinden bağımsız — sadece senin listen.</i>",
        "",
        f"{emoji} <b>{label}</b> · güven {analysis.confidence}/10 · kaynak: {source}",
        f"{analysis.item_count} sembol · {analysis.news_count} eşleşen haber",
    ]
    if analysis.weighted_20d_pct is not None:
        parts.append(
            f"Ağırlıklı getiri: 1g {fmt_pct(analysis.weighted_1d_pct or 0, 1)} · "
            f"5g {fmt_pct(analysis.weighted_5d_pct or 0, 1)} · "
            f"20g <b>{fmt_pct(analysis.weighted_20d_pct, 1)}</b>"
        )
    if analysis.summary_tr:
        parts += ["", escape(analysis.summary_tr)]
    if analysis.drivers:
        parts += ["", "📌 <b>Gözlemler</b>"]
        parts += [f"• {escape(d)}" for d in analysis.drivers]
    if analysis.highlights:
        parts += ["", "🔎 <b>Öne çıkanlar</b>"]
        parts += [f"• {escape(h)}" for h in analysis.highlights]
    if analysis.risks:
        parts += ["", "⚠️ <b>Riskler</b>"]
        parts += [f"• {escape(r)}" for r in analysis.risks]
    parts += [
        "",
        "Genel piyasa analizi: /analiz · Sepet: /sepetim",
        "",
        DISCLAIMER,
    ]
    return "\n".join(parts)


def performance_overview(views: list[PortfolioView], bench: dict[str, float]) -> str:
    parts = ["🏁 <b>Performans karşılaştırması</b>", ""]
    for view in sorted(views, key=lambda v: -v.pnl_pct):
        parts.append(
            f"{RISK_PROFILE_EMOJI[view.risk_profile]} <b>{RISK_PROFILE_TR[view.risk_profile]}</b>: "
            f"{fmt_try(view.total_value)} · {pnl_emoji(view.pnl_abs)} "
            f"<b>{fmt_pct(view.pnl_pct)}</b> ({fmt_try(view.pnl_abs)})"
        )
    if bench:
        parts += ["", "📊 <b>Referanslar</b>"]
        for key, pct in bench.items():
            parts.append(f"• {BENCHMARK_LABELS.get(key, key)}: {pnl_emoji(pct)} {fmt_pct(pct)}")

    first = views[0] if views else None
    if first:
        parts += [
            "",
            f"<i>Her profil {fmt_try(first.start_capital, 0)} ile başladı · "
            f"{_running_text(first.days_running)}</i>",
        ]
    parts += ["", DISCLAIMER]
    return "\n".join(parts)
