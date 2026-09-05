# YTD Bot - disciplined sample portfolio bot

Telegram uzerinden, orta-uzun vadeli yatirimcilara yonelik (egitim/deneysel) bir
"temsilci sepet" botudur.

Bot her 4 saatte bir:
- RSS ile haber toplar ve onem siniflar (kritik / onemli / genel)
- Piyasa verisini (fiyat + momentum) TL bazinda modeler (yfinance)
- Regim (bullish/balanced/bearish) uretir
- "Disiplin kurallari" ile sepetin sadece gerekli durumlarda degismesine karar verir
- Degisim olursa temsilci portfoyu gunceller ve gerekcesiyle birlikte bildirir

## Ozellikler
- LLM opsiyonel: `ANTHROPIC_API_KEY` varsa Anthropic ile JSON tabanli analiz
- LLM yoksa: anahtar kelime tabanli deterministik yedek analiz
- Sık gorus degisikligini engelleyen disiplin kurallari
- 3 risk profilinde (Dusuk/Orta/Yuksek) temsilci portfoy

## Kurulum (Windows / PowerShell)
```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

`.env` dosyasini doldurun:
- `TELEGRAM_BOT_TOKEN`: BotFather'dan aldiginiz token
- `ADMIN_CHAT_IDS`: /calistir komutunu sadece adminlerde acmak icin chat id'leri (virgul ile)
- `ANTHROPIC_API_KEY`: opsiyonel (bos birakirsaniz LLM kullanilmaz)
- `ANTHROPIC_MODEL`: varsayilan `claude-sonnet-4-5`

## Botu baslatma
```powershell
.\.venv\Scripts\python.exe run_bot.py
```

## Telegram komutlari
- `/sepet`: Guncel sepet (agirliklar + gerekceler)
- `/portfoy`: Temsilci portfoyun kâr/zarar + referans karsilastirmasi
- `/performans`: 3 risk profilini yan yana karsilastirir
- `/durum`: Son karar + degisim olasiligi
- `/analiz`: Analizin detayli gerekceleri
- `/gecmis`: Sepet degisim gecmisi
- `/profil`: Risk profilini degistirir
- `/bildirim`: Bildirim acik/kapali
- `/calistir`: Analiz dongusunu elle tetikler (admin chat ile sinirlanabilir)

## Telegram'siz tek dongu calistirma
```powershell
.\.venv\Scripts\python.exe run_cycle.py
```

Mesaj formatini metin olarak gormek icin:
```powershell
.\.venv\Scripts\python.exe run_cycle.py --messages
```

## Not (yatirim tavsiyesi degildir)
Bu proje yatirim tavsiyesi uretmez; egitim ve deneysel amaclarla hazirlanmistir.

## License
Lutfen projenize uygun bir lisans secin (ornegin MIT/Apache-2.0) ve repo'ya `LICENSE` dosyasi ekleyin.

<!--

Haberleri ve piyasa verisini düzenli olarak okuyup **orta-uzun vadeli** yatırımcılar için
üç risk profilinde temsilî sepet oluşturan Telegram botu.

Botun ayırt edici özelliği: **sık görüş değiştirmemesi.** Arka planda 4 saatte bir çalışır,
ama sepete ancak katı kurallar sağlanınca dokunur.

## Nasıl çalışır

```
Her 4 saatte bir:
  1. 9 RSS kaynağından haber topla, önem sırasına ayır (kritik / önemli / genel)
  2. 22 enstrümanın TL bazlı fiyat ve momentum verisini çek
  3. Piyasa görüşü üret: yükseliş / dengeli / düşüş + güven skoru (1-10)
  4. Disiplin kurallarından geçir: "sepet değişebilir mi?"
  5. Değişebiliyorsa sepeti güncelle, temsilî portföyü taşı, kullanıcıya nedeniyle bildir
```

### Disiplin kuralları (botun karakteri)

Bu kurallar `ytdbot/discipline.py` içinde ve `.env` üzerinden ayarlanabilir:

| Kural | Varsayılan | Amaç |
|---|---|---|
| Minimum sepet ömrü | 14 gün | Sepet kurulduktan sonra en az bu süre korunur |
| Görüş onayı | 3 ardışık döngü | Tek seferlik sinyalle işlem yapılmaz |
| Güven eşiği | 6/10 | Altındaki sinyaller gürültü sayılır, onay serisini bozmaz |
| Acil istisna | Kritik haber + güven 8/10 | Merkez bankası/savaş gibi temel gelişmelerde süre kuralı aşılabilir |
| Kademeli geçiş | 2 adım, 3 gün ara | Yeni sepete tek hamlede geçilmez |
| Ağırlık ayarı eşiği | %5 sapma, 7 günde bir | Küçük sapmalar için komisyon ödenmez |

Her değişim gerekçesiyle birlikte kaydedilir ve `/gecmis` ile görüntülenebilir.

### Temsilî portföy

Üç risk profilinin her biri **100.000 TL** ile başlar. Sepet değiştiğinde gerçek piyasa
fiyatlarından alım/satım yapılır, komisyon (varsayılan %0,15) düşülür. `/portfoy` komutu
başlangıçtan bu yana kâr/zararı ve aynı dönemde BIST 100, likit fon, gram altın ve doların
ne yaptığını gösterir. Gerçek para kullanılmaz.

## Kurulum

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

`.env` dosyasını doldurun:

1. **Telegram token** — Telegram'da [@BotFather](https://t.me/BotFather)'a `/newbot` yazıp
   bot oluşturun, verdiği token'ı `TELEGRAM_BOT_TOKEN` alanına yazın.
2. **Anthropic API anahtarı** (opsiyonel) — `ANTHROPIC_API_KEY` doldurulursa haberler LLM ile
   yorumlanır. Boş bırakılırsa bot momentum ve anahtar kelime tabanlı yedek analize düşer,
   yani anahtar olmadan da çalışır.

Botu başlatın:

```powershell
.\.venv\Scripts\python.exe run_bot.py
```

Telegram'da botunuza `/start` yazın ve risk profilinizi seçin. İlk analiz döngüsü
başlatmadan ~15 saniye sonra çalışır.

## Komutlar

| Komut | Ne yapar |
|---|---|
| `/sepet` | Güncel sepet, ağırlıklar, istikrar bilgisi ve gerekçeler |
| `/portfoy` | Temsilî portföyün kâr/zarar durumu ve referans karşılaştırması |
| `/performans` | Üç risk profilinin yan yana karşılaştırması |
| `/durum` | Piyasa görüşü, son karar ve değişim olasılığı |
| `/analiz` | Analizin detaylı gerekçeleri, riskler, sektör görüşleri |
| `/gecmis` | Sepet değişim geçmişi ve nedenleri |
| `/profil` | Risk profilini değiştir |
| `/bildirim` | Bildirimleri aç/kapat |
| `/calistir` | Analiz döngüsünü elle tetikle (`ADMIN_CHAT_IDS` ile kısıtlanabilir) |

## Geliştirme araçları

```powershell
# Telegram olmadan tek bir analiz döngüsü çalıştır
.\.venv\Scripts\python.exe run_cycle.py

# Telegram'a gidecek mesajların metin halini de gör
.\.venv\Scripts\python.exe run_cycle.py --messages

# Disiplin kurallarını zamanı ileri sararak test et (ağ gerekmez)
.\.venv\Scripts\python.exe scripts\simulate_discipline.py

# Veri kaynaklarının canlı olup olmadığını kontrol et
.\.venv\Scripts\python.exe scripts\check_sources.py
```

Simülasyon, botun bir ay boyunca 13 döngüde yalnızca gerekli müdahaleleri yaptığını,
düşük güvenli panik sinyallerini yoksaydığını ve kritik gelişmede acil istisnayı
devreye aldığını gösterir.

## Proje yapısı

```
ytdbot/
  config.py      Ortam değişkenlerinden ayarlar
  universe.py    Enstrüman evreni (22 enstrüman + 2 sentetik)
  market.py      yfinance fiyat çekimi, TL bazına çevirme, önbellek
  news.py        RSS toplama, önem sınıflandırması
  analysis.py    LLM analizi + kural tabanlı yedek
  baskets.py     Risk profili x görüş -> enstrüman ağırlıkları
  discipline.py  Sepetin ne zaman değişebileceğine karar veren kurallar
  portfolio.py   Temsilî portföy, alım/satım, kâr/zarar, referanslar
  formatting.py  Telegram mesaj şablonları
  engine.py      Döngü orkestrasyonu
  bot.py         Telegram komutları ve zamanlayıcı
  storage.py     SQLite kalıcı depolama
```

## Sınırlar

- Fiyat verisi Yahoo Finance üzerinden gelir; gecikmeli olabilir ve BIST endeksleri
  ETF yerine endeks olarak modellenir.
- Likit fon getirisi gerçek fon verisi değil, `MONEY_MARKET_ANNUAL_RATE` ile sentetik
  olarak modellenir.
- Kural tabanlı yedek analiz haber içeriğini yorumlamaz, yalnızca anahtar kelime tarar.
- Bu proje yatırım tavsiyesi üretmez; eğitim ve deneysel amaçlıdır.
-->
