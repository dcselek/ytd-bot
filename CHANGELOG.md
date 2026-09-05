# Changelog

Bu proje [Semantic Versioning](https://semver.org/lang/tr/) kullanır.

## [0.2.0] — 2026-09-05

### Eklenen
- **TEFAS fon desteği** — kısa kodlar (`MAC`, `TTE`…) önce TEFAS’tan çözülür; Yahoo/NYSE/PCX çakışması engellenir
- `/sepetim ekle … tefas|yahoo` ile venue zorlama
- `/sepetim vs` — kullanıcı sepeti vs bot sepeti (~20g)
- `/sepetim uyari N` — 1 günlük ±%N hareket uyarısı (günlük özette)

### Değişen
- README: TEFAS / uyarı / karşılaştırma dokümantasyonu

## [0.1.0] — 2026-09-05

İlk public release.

### Eklenen
- Telegram bot: haber + piyasa analizi, disiplinli temsilî sepetler
- Üç risk profili (düşük / orta / yüksek) ve SQLite kalıcı depolama
- Opsiyonel Anthropic LLM analizi; yoksa kural tabanlı yedek
- **`/sepetim`** — kullanıcı takip sepeti (çoklu borsa ticker, TL fiyat, haber filtresi)
- MIT lisans, README, bot ikonu

[0.2.0]: https://github.com/dcselek/ytd-bot/releases/tag/v0.2.0
[0.1.0]: https://github.com/dcselek/ytd-bot/releases/tag/v0.1.0
