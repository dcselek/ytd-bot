# Changelog

Bu proje [Semantic Versioning](https://semver.org/lang/tr/) kullanır.

## [0.4.0] — 2026-09-07

### Eklenen
- Bot sepeti **hisse + endeks + yerli/yabancı fon-ETF** karışık seçebilir (fon zorunlu değil)
- **`/tercih`** — pasif gelir (temettü/borçlanma) vs büyüme tercihi
- **`/bakiye`** — botun yönettiği sepet için kullanıcı bakiyesi; `/sepet` tutarları buna göre ölçekler

### Değişen
- Sepet motoru doğrudan enstrümanları ve opsiyonel fon/ETF katalogunu birlikte skorlar
- Risk × gelir tercihi için ayrı sepet/portföy anahtarları (`mid`, `mid_passive`, …)

## [0.3.0] — 2026-09-05

### Eklenen
- **`/sepetim analiz`** — kullanıcı sepetine özel LLM/kural tabanlı değerlendirme
- **`/sepetim butce`** — sepet bütçesi (TL); ağırlığa göre tahmini tutar/adet + kaba PnL

### Değişen
- README: analiz / bütçe komutları

## [0.2.0] — 2026-09-05

### Eklenen
- **TEFAS fon desteği** — kısa kodlar (`MAC`, `TTE`…) önce TEFAS’tan çözülür
- `/sepetim ekle … tefas|yahoo` ile venue zorlama
- `/sepetim vs` — kullanıcı sepeti vs bot sepeti (~20g)
- `/sepetim uyari N` — 1 günlük ±%N hareket uyarısı

## [0.1.0] — 2026-09-05

İlk public release.

[0.4.0]: https://github.com/dcselek/ytd-bot/releases/tag/v0.4.0
[0.3.0]: https://github.com/dcselek/ytd-bot/releases/tag/v0.3.0
[0.2.0]: https://github.com/dcselek/ytd-bot/releases/tag/v0.2.0
[0.1.0]: https://github.com/dcselek/ytd-bot/releases/tag/v0.1.0
