"""
GECMISE DONUK TEST (BACKTEST)
============================
bot.py'nin GERCEK sinyal fonksiyonlarini kullanarak her ajani gecmis veride
bastan sona calistirir. Amac: 8 hafta beklemeden "bu kurallarin hic edge'i
var miydi?" sorusunu cevaplamak.

ONEMLI: Strateji mantigi burada YENIDEN YAZILMADI - bot.py'den import edilir.
Boylece test edilen sey, canlida calisan kodun ta kendisidir.

Cikti: backtest.md (repoya yazilir)
Calistirma: GitHub Actions -> "Backtest" workflow (elle tetiklenir)
"""
import os, sys, json, traceback
from datetime import datetime, timezone, timedelta
import pandas as pd

import bot   # ayni klasordeki bot.py

from alpaca.data.historical import StockHistoricalDataClient, CryptoHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

YEARS        = int(os.environ.get("BACKTEST_YEARS", "5"))
INTRADAY_DAYS= int(os.environ.get("BACKTEST_INTRADAY_DAYS", "30"))
OUT          = "backtest.md"

CAP    = bot.STARTING_CAPITAL
TRAIL  = bot.TRAIL_PCT
ITRAIL = bot.INTRADAY_TRAIL_PCT
NOTIONAL = max(bot.MIN_NOTIONAL, (CAP * bot.RISK_PCT) / TRAIL)
COST_RT  = bot.COST_BPS_PER_SIDE / 10000.0 * 2.0    # gidis-donus oran


def fetch(sc, cc, symbol, asset, bar):
    if bar == "intraday":
        tf, start = TimeFrame(15, TimeFrameUnit.Minute), datetime.now(timezone.utc)-timedelta(days=INTRADAY_DAYS)
    else:
        tf, start = TimeFrame.Day, datetime.now(timezone.utc)-timedelta(days=365*YEARS+420)
    if asset == "crypto":
        df = cc.get_crypto_bars(CryptoBarsRequest(symbol_or_symbols=[symbol], timeframe=tf, start=start)).df
    else:
        df = sc.get_stock_bars(StockBarsRequest(symbol_or_symbols=[symbol], timeframe=tf, start=start)).df
    if df is None or df.empty: return None
    if isinstance(df.index, pd.MultiIndex): df = df.xs(symbol, level=0)
    return df


def simulate(df, cfg, apply_cost=True):
    """bot.py'nin kurallariyla birebir: gunde tek karar, tamamlanmis mum, trailing stop."""
    trades = []
    intraday = cfg.get("bar") == "intraday"
    trail = ITRAIL if intraday else TRAIL
    warm  = (bot.INTRADAY_SMA_BARS + bot.INTRADAY_BREAK_BARS + 2) if intraday else 210
    if df is None or len(df) <= warm + 5:
        return trades, "yetersiz veri"
    pos = None
    for i in range(warm, len(df)):
        w = df.iloc[:i+1]
        price = float(w["close"].iloc[-1])
        if pos:
            if price > pos["peak"]:
                pos["peak"] = price
                pos["stop"] = max(pos["stop"], price*(1-trail))
            if intraday:
                same_day = pd.Timestamp(df.index[i]).date() == pd.Timestamp(pos["t"]).date()
                hit = price <= pos["stop"] or bot.intraday_exit_signal(w) or not same_day
            else:
                hit = price <= pos["stop"] or bot.trend_break_exit(w)
            if hit:
                gross = NOTIONAL * (price/pos["entry"] - 1.0)
                cost  = NOTIONAL * COST_RT if apply_cost else 0.0
                trades.append({"in": pos["t"], "out": df.index[i], "entry": pos["entry"],
                               "exit": price, "gross": gross, "cost": cost, "net": gross-cost})
                pos = None
                continue
        else:
            if intraday:
                sig, _ = bot.intraday_entry_signal(w, 120)
            else:
                sig, _ = bot.entry_signal(w, cfg["type"])
            if sig:
                pos = {"entry": price, "peak": price, "stop": price*(1-trail), "t": df.index[i]}
    return trades, None


def stats(trades):
    if not trades:
        return {"n":0,"wins":0,"losses":0,"win_rate":0.0,"net":0.0,"gross":0.0,"costs":0.0,
                "avg_win":0.0,"avg_loss":0.0,"pf":0.0,"expectancy":0.0,"maxdd":0.0,"ret_pct":0.0}
    nets  = [t["net"] for t in trades]
    wins  = [x for x in nets if x > 0]; losses = [x for x in nets if x <= 0]
    eq = CAP; peak = CAP; maxdd = 0.0
    for x in nets:
        eq += x; peak = max(peak, eq); maxdd = max(maxdd, peak-eq)
    gross_w = sum(wins); gross_l = abs(sum(losses))
    return {
        "n": len(nets), "wins": len(wins), "losses": len(losses),
        "win_rate": len(wins)/len(nets)*100,
        "net": sum(nets), "gross": sum(t["gross"] for t in trades),
        "costs": sum(t["cost"] for t in trades),
        "avg_win": (gross_w/len(wins)) if wins else 0.0,
        "avg_loss": (-gross_l/len(losses)) if losses else 0.0,
        "pf": (gross_w/gross_l) if gross_l > 0 else float("inf"),
        "expectancy": sum(nets)/len(nets),
        "maxdd": maxdd, "ret_pct": sum(nets)/CAP*100,
    }


def buy_hold(df):
    if df is None or len(df) < 2: return 0.0
    return NOTIONAL * (float(df["close"].iloc[-1])/float(df["close"].iloc[0]) - 1.0)


def main():
    if not bot.API_KEY or not bot.API_SECRET:
        print("HATA: ALPACA secret'leri yok"); sys.exit(1)
    sc = StockHistoricalDataClient(bot.API_KEY, bot.API_SECRET)
    cc = CryptoHistoricalDataClient(bot.API_KEY, bot.API_SECRET)

    per_agent, notes, bh_total = {}, [], {}
    for sname, cfg in bot.STRATEGIES.items():
        all_tr, all_tr_nc, bh = [], [], 0.0
        for sym in cfg["symbols"]:
            try:
                df = fetch(sc, cc, sym, cfg["asset"], cfg.get("bar","day"))
                if df is None:
                    notes.append(f"{sname}/{sym}: veri cekilemedi"); continue
                tr, err = simulate(df, cfg, apply_cost=True)
                tr_nc, _ = simulate(df, cfg, apply_cost=False)
                if err: notes.append(f"{sname}/{sym}: {err}")
                all_tr += tr; all_tr_nc += tr_nc
                bh += buy_hold(df)
                print(f"{sname}/{sym}: {len(df)} mum, {len(tr)} islem")
            except Exception as e:
                notes.append(f"{sname}/{sym}: HATA {e}"); traceback.print_exc()
        per_agent[sname] = (stats(all_tr), stats(all_tr_nc))
        bh_total[sname] = bh

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    L = [f"# 🔬 Gecmise Donuk Test (Backtest)", "",
         f"Uretim: {now} · Gunluk ajanlar ~{YEARS} yil · F_intraday son {INTRADAY_DAYS} gun",
         f"Islem basi notional ${NOTIONAL:.0f} · Referans sermaye ${CAP:.0f}/ajan · "
         f"Maliyet gidis-donus %{COST_RT*100:.2f}", "",
         "> Bu test bot.py'nin GERCEK sinyal fonksiyonlarini kullanir; strateji yeniden yazilmadi.", "",
         "## Maliyet dahil sonuclar", "",
         "| Ajan | Islem | Kazanma % | Net P&L | Getiri % | Ort. Kazanc | Ort. Zarar | Profit Factor | Beklenti/islem | Max Dusus |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for sn, (s, _) in per_agent.items():
        pf = "∞" if s["pf"] == float("inf") else f"{s['pf']:.2f}"
        L.append(f"| {sn} | {s['n']} | {s['win_rate']:.0f}% | ${s['net']:+.2f} | {s['ret_pct']:+.1f}% | "
                 f"${s['avg_win']:+.2f} | ${s['avg_loss']:+.2f} | {pf} | ${s['expectancy']:+.2f} | ${s['maxdd']:.2f} |")

    L += ["", "## Maliyetin etkisi", "",
          "| Ajan | Maliyetsiz Net | Odenen Maliyet | Maliyetli Net | Maliyet kari yedi mi? |",
          "|---|---|---|---|---|"]
    for sn, (s, nc) in per_agent.items():
        ate = "EVET" if (nc["net"] > 0 and s["net"] <= 0) else ("-" if nc["net"] <= 0 else "hayir")
        L.append(f"| {sn} | ${nc['net']:+.2f} | ${s['costs']:.2f} | ${s['net']:+.2f} | {ate} |")

    L += ["", "## Al-tut (buy & hold) karsilastirmasi", "",
          "Ayni notional ile sembolleri hic dokunmadan tutsaydin:", "",
          "| Ajan | Strateji (net) | Al-tut | Strateji daha mi iyi? |", "|---|---|---|---|"]
    for sn, (s, _) in per_agent.items():
        L.append(f"| {sn} | ${s['net']:+.2f} | ${bh_total[sn]:+.2f} | "
                 f"{'EVET' if s['net'] > bh_total[sn] else 'HAYIR'} |")

    L += ["", "## Nasil okunmali", "",
          "- **Profit Factor < 1.0** -> strateji gecmiste para KAYBETTIRMIS.",
          "- **Beklenti/islem <= $0** -> her islem ortalama zarar; sik islem yapmak zarari buyutur.",
          "- **Al-tut'tan kotu** -> strateji deger katmamis; ayni parayla oturmak daha iyiymis.",
          "- Islem sayisi 30'un altindaysa sonuc yine zayif sayilir.",
          "- Backtest gecmise bakar; gelecegi garanti ETMEZ. Iyi cikan bir sonuc bile canlida bozulabilir.",
          "  Ama KOTU cikan bir sonuc guclu kanittir: gecmiste hic calismamis bir kurali canlida beklemek mantiksiz."]
    if notes:
        L += ["", "## Notlar / eksik veri", ""] + [f"- {n}" for n in notes]

    with open(OUT, "w") as f:
        f.write("\n".join(L))
    print(f"\n{OUT} yazildi ({len(per_agent)} ajan)")

if __name__ == "__main__":
    main()
