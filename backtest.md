# 🔬 Gecmise Donuk Test (Backtest)

Uretim: 2026-09-05 16:18 UTC · Gunluk ajanlar ~5 yil · F_intraday son 30 gun
Islem basi notional $625 · Referans sermaye $5000/ajan · Maliyet gidis-donus %0.10

> Bu test bot.py'nin GERCEK sinyal fonksiyonlarini kullanir; strateji yeniden yazilmadi.

## Maliyet dahil sonuclar

| Ajan | Islem | Kazanma % | Net P&L | Getiri % | Ort. Kazanc | Ort. Zarar | Profit Factor | Beklenti/islem | Max Dusus |
|---|---|---|---|---|---|---|---|---|---|
| A_trend | 35 | 46% | $+530.63 | +10.6% | $+56.14 | $-19.35 | 2.44 | $+15.16 | $120.42 |
| B_pullback | 55 | 55% | $+301.50 | +6.0% | $+21.81 | $-14.12 | 1.85 | $+5.48 | $98.52 |
| C_momentum | 78 | 38% | $+2035.27 | +40.7% | $+113.01 | $-28.23 | 2.50 | $+26.09 | $300.67 |
| D_crypto | 35 | 54% | $+1372.86 | +27.5% | $+101.69 | $-34.95 | 3.45 | $+39.22 | $126.65 |
| E_metals | 39 | 46% | $+510.51 | +10.2% | $+54.51 | $-22.41 | 2.08 | $+13.09 | $147.13 |
| F_intraday | 74 | 22% | $-49.47 | -1.0% | $+1.89 | $-1.37 | 0.38 | $-0.67 | $56.94 |

## Maliyetin etkisi

| Ajan | Maliyetsiz Net | Odenen Maliyet | Maliyetli Net | Maliyet kari yedi mi? |
|---|---|---|---|---|
| A_trend | $+552.50 | $21.88 | $+530.63 | hayir |
| B_pullback | $+335.87 | $34.38 | $+301.50 | hayir |
| C_momentum | $+2084.02 | $48.75 | $+2035.27 | hayir |
| D_crypto | $+1394.74 | $21.88 | $+1372.86 | hayir |
| E_metals | $+534.89 | $24.38 | $+510.51 | hayir |
| F_intraday | $-3.22 | $46.25 | $-49.47 | - |

## Al-tut (buy & hold) karsilastirmasi

Ayni notional ile sembolleri hic dokunmadan tutsaydin:

| Ajan | Strateji (net) | Al-tut | Strateji daha mi iyi? |
|---|---|---|---|
| A_trend | $+530.63 | $+2180.70 | HAYIR |
| B_pullback | $+301.50 | $+2460.00 | HAYIR |
| C_momentum | $+2035.27 | $+15918.49 | HAYIR |
| D_crypto | $+1372.86 | $+2549.90 | HAYIR |
| E_metals | $+510.51 | $+2323.20 | HAYIR |
| F_intraday | $-49.47 | $-14.33 | HAYIR |

## Nasil okunmali

- **Profit Factor < 1.0** -> strateji gecmiste para KAYBETTIRMIS.
- **Beklenti/islem <= $0** -> her islem ortalama zarar; sik islem yapmak zarari buyutur.
- **Al-tut'tan kotu** -> strateji deger katmamis; ayni parayla oturmak daha iyiymis.
- Islem sayisi 30'un altindaysa sonuc yine zayif sayilir.
- Backtest gecmise bakar; gelecegi garanti ETMEZ. Iyi cikan bir sonuc bile canlida bozulabilir.
  Ama KOTU cikan bir sonuc guclu kanittir: gecmiste hic calismamis bir kurali canlida beklemek mantiksiz.