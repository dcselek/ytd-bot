# YTD Bot

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Telegram](https://img.shields.io/badge/Telegram-Bot-26A5E4.svg)](https://core.telegram.org/bots)
[![Anthropic](https://img.shields.io/badge/LLM-Anthropic%20(optional)-black.svg)](https://www.anthropic.com/)
[![GitHub stars](https://img.shields.io/github/stars/dcselek/ytd-bot?style=social)](https://github.com/dcselek/ytd-bot)

Haberleri ve piyasa verisini düzenli okuyup **orta-uzun vadeli** yatırımcılar için
üç risk profilinde **temsilî sepet** oluşturan Telegram botu.

Botun ayırt edici özelliği: **sık görüş değiştirmemesi.** Arka planda 4 saatte bir
çalışır; sepete ancak disiplin kuralları sağlanınca dokunur.

> Bu proje yatırım tavsiyesi değildir. Eğitim ve deneysel amaçlıdır.

## Nasıl çalışır

```
Her 4 saatte bir:
  1. RSS kaynaklarından haber topla, önem sırasına ayır (kritik / önemli / genel)
  2. Enstrümanların TL bazlı fiyat ve momentum verisini çek
  3. Piyasa görüşü üret: yükseliş / dengeli / düşüş + güven skoru (1-10)
  4. Disiplin kurallarından geçir: "sepet değişebilir mi?"
  5. Değişebiliyorsa sepeti güncelle, temsilî portföyü taşı, gerekçeyle bildir
```

### Disiplin kuralları

Kurallar `ytdbot/discipline.py` içinde ve `.env` üzerinden ayarlanır:

| Kural | Varsayılan | Amaç |
|---|---|---|
| Minimum sepet ömrü | 14 gün | Sepet kurulduktan sonra en az bu süre korunur |
| Görüş onayı | 3 ardışık döngü | Tek seferlik sinyalle işlem yapılmaz |
| Güven eşiği | 6/10 | Altındaki sinyaller gürültü sayılır |
| Acil istisna | Kritik haber + güven 8/10 | Temel gelişmelerde süre kuralı aşılabilir |
| Ağırlık ayarı eşiği | %5 sapma | Küçük sapmalar için komisyon ödenmez |

### Temsilî portföy

Üç risk profilinin her biri **100.000 TL** ile başlar. Gerçek piyasa fiyatlarıyla
alım/satım simüle edilir, komisyon düşülür. Gerçek para kullanılmaz.

## Kurulum

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

`.env` dosyasını doldurun:

1. **Telegram token** — [@BotFather](https://t.me/BotFather) ile bot oluşturup
   `TELEGRAM_BOT_TOKEN` alanına yazın.
2. **Anthropic API anahtarı** (opsiyonel) — `ANTHROPIC_API_KEY` doldurulursa LLM
   analizi çalışır. Boş bırakılırsa kural tabanlı yedek analize düşer.

Botu başlatın:

```powershell
.\.venv\Scripts\python.exe run_bot.py
```

Telegram'da `/start` yazıp risk profilinizi seçin.

## Komutlar

| Komut | Ne yapar |
|---|---|
| `/sepet` | Güncel sepet, ağırlıklar, gerekçeler |
| `/portfoy` | Temsilî portföy kâr/zarar + referanslar |
| `/performans` | Üç risk profilinin karşılaştırması |
| `/durum` | Piyasa görüşü, son karar |
| `/analiz` | Analiz detayları |
| `/gecmis` | Sepet değişim geçmişi |
| `/profil` | Risk profilini değiştir |
| `/bildirim` | Bildirimleri aç/kapat |
| `/calistir` | Analiz döngüsünü elle tetikle |

## Geliştirme

```powershell
# Telegram olmadan tek döngü
.\.venv\Scripts\python.exe run_cycle.py

# Mesaj metinlerini de gör
.\.venv\Scripts\python.exe run_cycle.py --messages

# Disiplin kurallarını simüle et
.\.venv\Scripts\python.exe scripts\simulate_discipline.py

# Veri kaynaklarını kontrol et
.\.venv\Scripts\python.exe scripts\check_sources.py
```

## Proje yapısı

```
ytdbot/
  config.py      Ortam değişkenleri
  universe.py    Enstrüman evreni
  market.py      Fiyat çekimi (yfinance)
  news.py        RSS toplama
  analysis.py    LLM + kural tabanlı yedek
  baskets.py     Risk profili → ağırlıklar
  discipline.py  Sepet değişim kuralları
  portfolio.py   Temsilî portföy
  engine.py      Döngü orkestrasyonu
  bot.py         Telegram komutları
  storage.py     SQLite depolama
```

## Sınırlar

- Fiyat verisi Yahoo Finance üzerinden gelir; gecikmeli olabilir.
- Likit fon getirisi `MONEY_MARKET_ANNUAL_RATE` ile sentetik modellenir.
- Kural tabanlı yedek analiz yalnızca anahtar kelime tarar.
- Bu proje yatırım tavsiyesi üretmez.

## Lisans

[MIT](./LICENSE)
