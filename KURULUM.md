# 🤖 AI Trading Bot — GitHub Actions Kurulum Rehberi (En Güvenli 7/24)

Bu bot, 4 stratejiyi **Alpaca paper (demo) hesabında** çalıştırır — **gerçek para YOK**.
GitHub'ın bulutunda 7/24 döner; senin bilgisayarının açık olmasına gerek yoktur.

> **Güvenlik:** Bot ilk çalıştığında **DRY_RUN** modundadır — yani hiç emir vermez,
> sadece bağlanır, sinyalleri hesaplar ve rapor eder. Her şeyin çalıştığını görünce
> tek bir ayarla paper işlemleri açarız.

---

## Adım 1 — GitHub hesabı aç (ücretsiz)
1. github.com adresine git → **Sign up** → e-posta + şifre ile hesap oluştur.
   (Bu hesabı ben açamam; kimlik/şifre senindir.)

## Adım 2 — Yeni depo (repository) oluştur
1. Sağ üstte **+** → **New repository**.
2. İsim: `trading-bot` yaz.
3. **Private** (özel) seç — kimse göremesin.
4. **Create repository**.

## Adım 3 — Dosyaları yükle
Sana gönderdiğim `trading-bot` klasöründeki dosyaları depoya ekle:
`bot.py`, `requirements.txt`, `KURULUM.md` ve `.github/workflows/trade.yml`

**Kolay yol:** Depo sayfasında **Add file → Upload files** → dosyaları sürükle bırak.
> Not: `.github/workflows/trade.yml` bir alt klasördedir. Yüklerken dosya adını
> `.github/workflows/trade.yml` olarak yazarsan GitHub klasörü otomatik oluşturur.

## Adım 4 — Anahtarları GÜVENLİ ekle (Secrets)
> Önce Alpaca'da **Generate New Keys** ile anahtarları YENİLE (chat'e yapıştırılanları
> kullanma). Yeni Secret'i buraya, doğrudan GitHub'a koy — bir daha kimseye gösterme.

1. Depo sayfasında **Settings → Secrets and variables → Actions**.
2. **New repository secret** ile iki tane ekle:
   - İsim: `ALPACA_API_KEY_ID`  → Değer: Alpaca **Key** (PK... ile başlayan)
   - İsim: `ALPACA_API_SECRET_KEY` → Değer: Alpaca **Secret**
3. Aynı sayfada **Variables** sekmesi → **New repository variable**:
   - İsim: `DRY_RUN` → Değer: `true`   (güvenli başlangıç — emir yok)

## Adım 5 — Actions'ı çalıştır
1. Üstte **Actions** sekmesi → uyarı çıkarsa **I understand... enable**.
2. Soldan **AI Trading Bot** → **Run workflow** (elle ilk deneme).
3. Çalışan işe tıkla → **run-bot** → logları izle.
   Şunu görmelisin: `BAGLANTI OK ... MOD: DRY_RUN` ve her sembol için sinyal satırları.

✅ Buraya kadar geldiyse: bağlantı ve mantık **güvenle** çalışıyor demektir.

## Adım 6 — Paper işlemleri aç (hazır olunca)
1. **Settings → Secrets and variables → Actions → Variables**.
2. `DRY_RUN` değişkenini **`false`** yap.
3. Artık bot, **paper (sanal para)** ile gerçekten alım-satım yapar ve trailing stop'ları yönetir.
4. Sonuçları: depodaki **`trades.csv`** dosyasından ve Alpaca panelindeki
   Paper hesabın **Orders/Positions** ekranından izlersin.

---

## Zamanlama
`.github/workflows/trade.yml` her **15 dakikada** çalışacak şekilde ayarlı.
Kripto ajanı 7/24; hisse ajanları ABD borsası açıkken işlem yapar.

## Güvenlik özeti
- Her şey **PAPER** — gerçek para riski yok.
- Anahtarlar **şifreli secret** olarak durur; kodda/loglarda görünmez.
- İşlem başına ~**%1 risk** ($200 üzerinden ~$2) + **trailing stop** kod içine gömülü.
- Gerçek paraya geçmek istersek: ayrı bir "live" kurulum + senin onayınla — bu bot buna otomatik geçmez.

## Takıldığında
Logda hata görürsen, o log satırlarını bana yapıştır — düzeltip yeni `bot.py` veririm.
Bu ilk sürümü birlikte, adım adım sağlamlaştıracağız.
