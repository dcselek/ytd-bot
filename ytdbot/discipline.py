"""Advisor discipline motoru.

Bot 4 saatte bir kosar ama sepetin sik degismesi orta-uzun vadeli yatirimciya zarar
verir (islem maliyeti, vergi, psikolojik yorgunluk). Bu modul "degisebilir mi?"
sorusuna karar verir ve degisimi kademeli hale getirir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from . import news, storage
from .analysis import BALANCED, REGIME_TR, Analysis
from .config import settings

HOLD = "hold"
REBALANCE = "rebalance"
SWITCH = "switch"
SWITCH_STEP = "switch_step"

ACTION_TR = {
    HOLD: "Değişiklik yok, sepet korunuyor",
    REBALANCE: "Ağırlık ayarı",
    SWITCH: "Sepet değişimi başlıyor",
    SWITCH_STEP: "Kademeli geçiş adımı",
}

# Rejim degisimi tek hamlede degil, birkac gun arayla iki adimda uygulanir.
TRANSITION_STEPS = 2
TRANSITION_STEP_DAYS = 3

# Ayni rejim icinde agirlik ayari icin bekleme suresi.
REVIEW_INTERVAL_DAYS = 7

STATE_REGIME = "regime"
STATE_PENDING = "pending_regime"
STATE_LAST_CHANGE = "last_change_at"
STATE_NEXT_REVIEW = "next_review_at"
STATE_TRANSITION = "transition"


@dataclass
class Decision:
    action: str
    target_regime: str
    current_regime: str
    transition_ratio: float = 1.0
    transition_step: int = 0
    reasons: list[str] = field(default_factory=list)
    blocked_reasons: list[str] = field(default_factory=list)
    days_held: float = 0.0
    next_review_at: datetime | None = None
    change_probability: str = "dusuk"
    pending_streak: int = 0
    required_streak: int = 0

    @property
    def changes_basket(self) -> bool:
        return self.action in (REBALANCE, SWITCH, SWITCH_STEP)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "target_regime": self.target_regime,
            "current_regime": self.current_regime,
            "transition_ratio": self.transition_ratio,
            "transition_step": self.transition_step,
            "reasons": self.reasons,
            "blocked_reasons": self.blocked_reasons,
            "days_held": round(self.days_held, 2),
            "next_review_at": storage.iso(self.next_review_at) if self.next_review_at else None,
            "change_probability": self.change_probability,
            "pending_streak": self.pending_streak,
            "required_streak": self.required_streak,
        }


def current_regime() -> str:
    return storage.get_state(STATE_REGIME, BALANCED)


def last_change_at() -> datetime | None:
    return storage.parse_iso(storage.get_state(STATE_LAST_CHANGE))


def next_review_at() -> datetime | None:
    return storage.parse_iso(storage.get_state(STATE_NEXT_REVIEW))


def active_transition() -> dict[str, Any] | None:
    return storage.get_state(STATE_TRANSITION)


def days_since_last_change(now: datetime | None = None) -> float:
    now = now or storage.utcnow()
    changed = last_change_at()
    if changed is None:
        return 1e6  # hic sepet kurulmamis: sure kisiti yok
    return (now - changed).total_seconds() / 86400.0


def _change_probability(streak: int, required: int, confidence: int, days_held: float) -> str:
    if days_held < settings.min_basket_lifetime_days:
        return "cok dusuk"
    if streak == 0:
        return "dusuk"
    ratio = streak / max(required, 1)
    if ratio >= 0.67 and confidence >= settings.min_switch_confidence:
        return "yuksek"
    if ratio >= 0.34:
        return "orta"
    return "dusuk"


def evaluate(analysis: Analysis, news_items: list[news.NewsItem]) -> Decision:
    """Analiz sonucunu disiplin kurallarindan geciren karar fonksiyonu."""
    now = storage.utcnow()
    current = current_regime()
    days_held = days_since_last_change(now)
    review_due_at = next_review_at()
    required = settings.regime_confirmation_cycles

    # 1) Yururlukte kademeli gecis varsa once onu tamamla.
    transition = active_transition()
    if transition:
        return _advance_transition(transition, now, current, days_held)

    # 2) Hic sepet yoksa ilk kurulum.
    if last_change_at() is None:
        return Decision(
            action=SWITCH,
            target_regime=analysis.regime,
            current_regime=current,
            transition_ratio=1.0,
            transition_step=TRANSITION_STEPS,
            reasons=["İlk sepet kurulumu: geçmiş pozisyon olmadığı için doğrudan uygulanıyor."],
            days_held=0.0,
            next_review_at=now + timedelta(days=REVIEW_INTERVAL_DAYS),
            change_probability="dusuk",
            required_streak=required,
        )

    tier1 = news.tier1_items(news_items)

    # 3) Onerilen rejim yururlukteki ile ayni: sadece periyodik agirlik ayari.
    if analysis.regime == current:
        storage.set_state(STATE_PENDING, None)
        if review_due_at is None or now >= review_due_at:
            return Decision(
                action=REBALANCE,
                target_regime=current,
                current_regime=current,
                reasons=[
                    f"Piyasa görüşü aynı ({REGIME_TR[current]}); "
                    f"{REVIEW_INTERVAL_DAYS} günlük periyodik ağırlık kontrolü yapılıyor.",
                ],
                days_held=days_held,
                next_review_at=now + timedelta(days=REVIEW_INTERVAL_DAYS),
                change_probability=_change_probability(0, required, analysis.confidence, days_held),
                required_streak=required,
            )
        return Decision(
            action=HOLD,
            target_regime=current,
            current_regime=current,
            reasons=[
                f"Görüş değişmedi ({REGIME_TR[current]}). "
                f"Sepet {days_held:.1f} gündür yürürlükte.",
            ],
            days_held=days_held,
            next_review_at=review_due_at,
            change_probability=_change_probability(0, required, analysis.confidence, days_held),
            required_streak=required,
        )

    # 4) Guven esigi altindaki farkli yondeki sinyaller gurultu kabul edilir ve
    #    devam eden onay serisini bozmaz. Aksi halde tek bir panik basligi,
    #    haftalardir olgunlasan bir gorusu sifirlayabilirdi.
    if analysis.confidence < settings.min_switch_confidence:
        pending = storage.get_state(STATE_PENDING) or {}
        return Decision(
            action=HOLD,
            target_regime=current,
            current_regime=current,
            reasons=[
                f"Görüş değişmedi ({REGIME_TR[current]}). "
                f"Sepet {days_held:.1f} gündür yürürlükte."
            ],
            blocked_reasons=[
                f"{REGIME_TR[analysis.regime]} yönünde bir sinyal var ama güven skoru "
                f"{analysis.confidence}/10 (eşik {settings.min_switch_confidence}/10). "
                "Gürültü kabul edip dikkate almıyoruz."
            ],
            days_held=days_held,
            next_review_at=review_due_at,
            change_probability=_change_probability(
                int(pending.get("streak", 0)), required, analysis.confidence, days_held
            ),
            pending_streak=int(pending.get("streak", 0)),
            required_streak=required,
        )

    # 5) Farkli rejim oneriliyor: onay serisini guncelle.
    pending = storage.get_state(STATE_PENDING) or {}
    if pending.get("regime") == analysis.regime:
        streak = int(pending.get("streak", 0)) + 1
        first_seen = pending.get("first_seen") or storage.iso(now)
    else:
        streak = 1
        first_seen = storage.iso(now)
    storage.set_state(
        STATE_PENDING,
        {"regime": analysis.regime, "streak": streak, "first_seen": first_seen},
    )

    emergency = bool(tier1) and analysis.confidence >= settings.emergency_switch_confidence
    blocked: list[str] = []

    if streak < required:
        blocked.append(
            f"Yeni görüş ({REGIME_TR[analysis.regime]}) henüz {streak}/{required} "
            "doğrulama döngüsünde. Tek seferlik sinyalle sepet değiştirmiyoruz."
        )
    if days_held < settings.min_basket_lifetime_days and not emergency:
        blocked.append(
            f"Mevcut sepet {days_held:.1f} gündür yürürlükte; minimum "
            f"{settings.min_basket_lifetime_days} gün kuralını bekliyoruz "
            "(temel bir gelişme olmadıkça)."
        )

    if blocked:
        return Decision(
            action=HOLD,
            target_regime=current,
            current_regime=current,
            reasons=[
                f"Sinyaller {REGIME_TR[analysis.regime]} yönünü işaret ediyor, "
                "ancak henüz harekete geçmiyoruz."
            ],
            blocked_reasons=blocked,
            days_held=days_held,
            next_review_at=review_due_at,
            change_probability=_change_probability(
                streak, required, analysis.confidence, days_held
            ),
            pending_streak=streak,
            required_streak=required,
        )

    reasons = [
        f"Piyasa görüşü {REGIME_TR[current]} yönünden {REGIME_TR[analysis.regime]} "
        "yönüne döndü.",
        f"Yeni görüş {streak} ardışık döngüde doğrulandı (gereken: {required}).",
        f"Güven skoru {analysis.confidence}/10, beklenen etki süresi "
        f"~{analysis.horizon_weeks} hafta.",
        f"Önceki sepet {days_held:.1f} gün yürürlükte kaldı.",
    ]
    if emergency and days_held < settings.min_basket_lifetime_days:
        reasons.append(
            "Temel nitelikte bir gelişme ve yüksek güven skoru nedeniyle minimum "
            "bekleme süresi istisnai olarak aşıldı: "
            + "; ".join(item.title for item in tier1[:2])
        )

    return Decision(
        action=SWITCH,
        target_regime=analysis.regime,
        current_regime=current,
        transition_ratio=1.0 / TRANSITION_STEPS,
        transition_step=1,
        reasons=reasons,
        days_held=days_held,
        next_review_at=now + timedelta(days=REVIEW_INTERVAL_DAYS),
        change_probability="yuksek",
        pending_streak=streak,
        required_streak=required,
    )


def _advance_transition(
    transition: dict[str, Any],
    now: datetime,
    current: str,
    days_held: float,
) -> Decision:
    """Yururlukteki kademeli gecisin bir sonraki adimini uygular ya da bekletir."""
    target = transition.get("target_regime", current)
    step = int(transition.get("step", 1))
    next_step_at = storage.parse_iso(transition.get("next_step_at"))

    if next_step_at and now < next_step_at:
        remaining = (next_step_at - now).total_seconds() / 3600.0
        return Decision(
            action=HOLD,
            target_regime=target,
            current_regime=current,
            transition_step=step,
            transition_ratio=step / TRANSITION_STEPS,
            reasons=[
                f"{REGIME_TR.get(target, target)} sepetine kademeli geçiş sürüyor "
                f"({step}/{TRANSITION_STEPS}). Sonraki adım ~{remaining:.0f} saat sonra.",
                "Geçişi tek hamlede yapmıyoruz; böylece işlem maliyeti ve "
                "zamanlama riski azalıyor.",
            ],
            days_held=days_held,
            change_probability="dusuk",
        )

    next_step = step + 1
    return Decision(
        action=SWITCH_STEP,
        target_regime=target,
        current_regime=current,
        transition_step=next_step,
        transition_ratio=min(1.0, next_step / TRANSITION_STEPS),
        reasons=[
            f"Kademeli geçişin {next_step}/{TRANSITION_STEPS}. adımı uygulanıyor "
            f"({REGIME_TR.get(target, target)} sepetine doğru).",
        ],
        days_held=days_held,
        next_review_at=now + timedelta(days=REVIEW_INTERVAL_DAYS),
        change_probability="dusuk",
    )


def commit(decision: Decision) -> None:
    """Karar uygulandiktan sonra disiplin durumunu kalici hale getirir."""
    now = storage.utcnow()

    if decision.action == REBALANCE:
        storage.set_state(STATE_NEXT_REVIEW, storage.iso(decision.next_review_at or now))
        return

    if decision.action in (SWITCH, SWITCH_STEP):
        storage.set_state(STATE_REGIME, decision.target_regime)
        # Minimum omur sayaci gecisin BASLANGICINDAN isler. Kademeli gecisin ikinci
        # adimi yeni bir karar degil, ayni kararin tamamlanmasidir; sayaci sifirlarsa
        # sepet gercekte oldugundan daha "yeni" gorunur.
        if decision.action == SWITCH:
            storage.set_state(STATE_LAST_CHANGE, storage.iso(now))
        storage.set_state(STATE_PENDING, None)
        storage.set_state(STATE_NEXT_REVIEW, storage.iso(now + timedelta(days=REVIEW_INTERVAL_DAYS)))

        if decision.transition_step >= TRANSITION_STEPS:
            storage.set_state(STATE_TRANSITION, None)
        else:
            storage.set_state(
                STATE_TRANSITION,
                {
                    "target_regime": decision.target_regime,
                    "step": decision.transition_step,
                    "next_step_at": storage.iso(now + timedelta(days=TRANSITION_STEP_DAYS)),
                },
            )


def stability_summary() -> dict[str, Any]:
    """Kullaniciya gosterilecek istikrar bilgileri."""
    now = storage.utcnow()
    changed = last_change_at()
    review = next_review_at()
    transition = active_transition()
    pending = storage.get_state(STATE_PENDING) or {}

    return {
        "regime": current_regime(),
        "last_change_at": changed,
        "days_held": days_since_last_change(now) if changed else None,
        "next_review_at": review,
        "min_lifetime_days": settings.min_basket_lifetime_days,
        "locked_until": (
            changed + timedelta(days=settings.min_basket_lifetime_days) if changed else None
        ),
        "in_transition": bool(transition),
        "transition_step": int(transition.get("step", 0)) if transition else 0,
        "transition_steps": TRANSITION_STEPS,
        "pending_regime": pending.get("regime"),
        "pending_streak": int(pending.get("streak", 0)) if pending else 0,
        "required_streak": settings.regime_confirmation_cycles,
    }
