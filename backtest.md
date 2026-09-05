# 🔬 Gecmise Donuk Test (Backtest)

Uretim: 2026-09-05 16:10 UTC · Gunluk ajanlar ~5 yil · F_intraday son 30 gun
Islem basi notional $625 · Referans sermaye $5000/ajan · Maliyet gidis-donus %0.10

> Bu test bot.py'nin GERCEK sinyal fonksiyonlarini kullanir; strateji yeniden yazilmadi.

## Maliyet dahil sonuclar

| Ajan | Islem | Kazanma % | Net P&L | Getiri % | Ort. Kazanc | Ort. Zarar | Profit Factor | Beklenti/islem | Max Dusus |
|---|---|---|---|---|---|---|---|---|---|
| A_trend | 33 | 48% | $+563.81 | +11.3% | $+54.91 | $-18.51 | 2.79 | $+17.09 | $78.92 |
| B_pullback | 52 | 58% | $+285.09 | +5.7% | $+19.85 | $-14.12 | 1.92 | $+5.48 | $94.32 |
| C_momentum | 61 | 41% | $+1458.14 | +29.2% | $+111.54 | $-36.95 | 2.10 | $+23.90 | $590.81 |
| D_crypto | 35 | 54% | $+1372.86 | +27.5% | $+101.69 | $-34.95 | 3.45 | $+39.22 | $126.65 |
| E_metals | 39 | 46% | $+510.51 | +10.2% | $+54.51 | $-22.41 | 2.08 | $+13.09 | $147.13 |
| F_intraday | 73 | 22% | $-48.26 | -1.0% | $+1.89 | $-1.38 | 0.39 | $-0.66 | $55.73 |

## Maliyetin etkisi

| Ajan | Maliyetsiz Net | Odenen Maliyet | Maliyetli Net | Maliyet kari yedi mi? |
|---|---|---|---|---|
| A_trend | $+584.43 | $20.62 | $+563.81 | hayir |
| B_pullback | $+317.59 | $32.50 | $+285.09 | hayir |
| C_momentum | $+1496.27 | $38.12 | $+1458.14 | hayir |
| D_crypto | $+1394.74 | $21.88 | $+1372.86 | hayir |
| E_metals | $+534.89 | $24.38 | $+510.51 | hayir |
| F_intraday | $-2.63 | $45.62 | $-48.26 | - |

## Al-tut (buy & hold) karsilastirmasi

Ayni notional ile sembolleri hic dokunmadan tutsaydin:

| Ajan | Strateji (net) | Al-tut | Strateji daha mi iyi? |
|---|---|---|---|
| A_trend | $+563.81 | $+1985.14 | HAYIR |
| B_pullback | $+285.09 | $+764.09 | HAYIR |
| C_momentum | $+1458.14 | $-1336.66 | EVET |
| D_crypto | $+1372.86 | $+2549.83 | HAYIR |
| E_metals | $+510.51 | $+2323.20 | HAYIR |
| F_intraday | $-48.26 | $-15.01 | HAYIR |

## Nasil okunmali

- **Profit Factor < 1.0** -> strateji gecmiste para KAYBETTIRMIS.
- **Beklenti/islem <= $0** -> her islem ortalama zarar; sik islem yapmak zarari buyutur.
- **Al-tut'tan kotu** -> strateji deger katmamis; ayni parayla oturmak daha iyiymis.
- Islem sayisi 30'un altindaysa sonuc yine zayif sayilir.
- Backtest gecmise bakar; gelecegi garanti ETMEZ. Iyi cikan bir sonuc bile canlida bozulabilir.
  Ama KOTU cikan bir sonuc guclu kanittir: gecmiste hic calismamis bir kurali canlida beklemek mantiksiz.