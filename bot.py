"""
AI Trading Operator — 4 AjanlI Paper Trading Botu (v2 + Karne/Dashboard)
========================================================================
GUVENLIK: DRY_RUN=true iken hicbir emir gonderilmez (sadece rapor).
DRY_RUN=false iken PAPER (sanal para) ile gercek paper islem yapar.
Her sey PAPER (demo) hesapta calisir — gercek para YOK.

v2: Her calismada ajan bazli KARNE hesaplar ve repoya yazar:
  - report.md      (GitHub'da tablo olarak gorunur)
  - dashboard.html (sik gorsel panel)
"""

import os
import sys
import json
import traceback
from datetime import datetime, timedelta, timezone

import pandas as pd

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical import StockHistoricalDataClient, CryptoHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.data.enums import Adjustment

# ----------------------------------------------------------------------------
# AYARLAR
# ----------------------------------------------------------------------------
API_KEY    = os.environ.get("ALPACA_API_KEY_ID", "")
API_SECRET = os.environ.get("ALPACA_API_SECRET_KEY", "")
DRY_RUN = os.environ.get("DRY_RUN", "true").lower() != "false"
STARTING_CAPITAL = float(os.environ.get("STARTING_CAPITAL", "200"))  # ajan basi referans

RISK_PCT = 0.01
TRAIL_PCT = 0.08
MIN_NOTIONAL = 1.0

# Islem maliyeti modeli (spread + kayma tahmini). Tek yon icin baz puan (1 bps = %0.01).
# Gidis-donus toplam maliyet = 2 x COST_BPS_PER_SIDE. Gercekci olmak icin sifir DEGIL.
COST_BPS_PER_SIDE = float(os.environ.get("COST_BPS_PER_SIDE", "5"))  # %0.05 tek yon

# Gun ici (intraday) ajan parametreleri
INTRADAY_TRAIL_PCT   = 0.015   # gun ici daha sik trailing stop
INTRADAY_SMA_BARS    = 20      # 15dk mumda SMA periyodu
INTRADAY_BREAK_BARS  = 8       # kirilim icin bakilan onceki mum sayisi
INTRADAY_CLOSE_BUFFER_MIN = 10 # kapanisa bu kadar dk kala pozisyon zorla kapatilir
INTRADAY_NO_ENTRY_MIN     = 30 # kapanisa bu kadar dk kala yeni giris YOK

STATE_FILE = "state.json"
TRADES_LOG = "trades.csv"
REPORT_MD = "report.md"
DASH_HTML = "dashboard.html"

# bar = "day"      -> gunluk mum, gunde BIR kez sinyal karari (trailing stop her turda kontrol edilir)
# bar = "intraday" -> 15 dakikalik mum, gun ici al-sat, gun sonunda zorla kapanir
STRATEGIES = {
    "A_trend":     {"type": "trend",    "symbols": ["SPY", "QQQ"],            "asset": "stock",  "bar": "day"},
    "B_pullback":  {"type": "pullback", "symbols": ["AAPL", "MSFT"],          "asset": "stock",  "bar": "day"},
    "C_momentum":  {"type": "momentum", "symbols": ["NVDA", "AMZN", "GOOGL"], "asset": "stock",  "bar": "day"},
    "D_crypto":    {"type": "trend",    "symbols": ["BTC/USD", "ETH/USD"],    "asset": "crypto", "bar": "day"},
    "E_metals":    {"type": "trend",    "symbols": ["GLD", "SLV"],            "asset": "stock",  "bar": "day"},
    "F_intraday":  {"type": "intraday", "symbols": ["IWM", "DIA"],            "asset": "stock",  "bar": "intraday"},
}

# sembol -> ajan haritasi (pozisyon anahtari da dahil, BTC/USD ve BTCUSD)
AGENT_OF = {}
for _sn, _cfg in STRATEGIES.items():
    for _sym in _cfg["symbols"]:
        AGENT_OF[_sym] = _sn
        AGENT_OF[_sym.replace("/", "")] = _sn

# ----------------------------------------------------------------------------
def log(msg):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{ts}] {msg}", flush=True)

def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def append_trade(row):
    header = not os.path.exists(TRADES_LOG)
    with open(TRADES_LOG, "a") as f:
        if header:
            f.write("time,strategy,symbol,action,qty_or_notional,price,reason,realized_pnl\n")
        f.write(",".join(str(x) for x in row) + "\n")

def sma(s, n): return s.rolling(n).mean()
def rsi(s, n=14):
    d = s.diff(); up = d.clip(lower=0).rolling(n).mean(); dn = (-d.clip(upper=0)).rolling(n).mean()
    return 100 - (100 / (1 + up / dn.replace(0, 1e-9)))
def atr(df, n=14):
    hl = df["high"]-df["low"]; hc=(df["high"]-df["close"].shift()).abs(); lc=(df["low"]-df["close"].shift()).abs()
    return pd.concat([hl,hc,lc],axis=1).max(axis=1).rolling(n).mean()

def get_bars(sc, cc, symbol, asset, bar="day"):
    """bar='day' -> gunluk mum (400 gun) | bar='intraday' -> 15 dakikalik mum (10 gun)"""
    if bar == "intraday":
        tf = TimeFrame(15, TimeFrameUnit.Minute)
        start = datetime.now(timezone.utc) - timedelta(days=10)
    else:
        tf = TimeFrame.Day
        start = datetime.now(timezone.utc) - timedelta(days=400)
    if asset == "crypto":
        df = cc.get_crypto_bars(CryptoBarsRequest(symbol_or_symbols=[symbol], timeframe=tf, start=start)).df
    else:
        df = sc.get_stock_bars(StockBarsRequest(symbol_or_symbols=[symbol], timeframe=tf, start=start, adjustment=Adjustment.ALL)).df
    if df is None or df.empty: return None
    if isinstance(df.index, pd.MultiIndex): df = df.xs(symbol, level=0)
    return df

def completed_daily(df):
    """Son mum BUGUNE aitse yarim demektir; gun ici surekli degisir ve sinyali titretir.
    Sinyal kararlari SADECE tamamlanmis mumlarla verilir."""
    if df is None or df.empty: return df
    try:
        last_day = pd.Timestamp(df.index[-1]).date()
        if last_day >= datetime.now(timezone.utc).date() and len(df) > 1:
            return df.iloc[:-1]
    except Exception:
        pass
    return df

def decision_key(pk):
    return f"_lastdec_{pk}"

def daily_decision_due(state, pk):
    """Gunluk-mum ajanlari icin: bu sembolde bugun zaten sinyal karari verildi mi?"""
    return state.get(decision_key(pk)) != datetime.now(timezone.utc).strftime("%Y-%m-%d")

def mark_daily_decision(state, pk):
    state[decision_key(pk)] = datetime.now(timezone.utc).strftime("%Y-%m-%d")

def round_trip_cost(notional):
    """Gidis-donus tahmini islem maliyeti (spread + kayma), dolar cinsinden."""
    return abs(float(notional)) * (COST_BPS_PER_SIDE / 10000.0) * 2.0

def entry_signal(df, stype):
    if len(df) < 210: return False, "yetersiz veri"
    close = df["close"]; last = close.iloc[-1]; s200 = sma(close,200).iloc[-1]
    if pd.isna(s200) or last <= s200: return False, "trend alti (SMA200)"
    if stype == "trend":
        if last >= df["high"].rolling(20).max().iloc[-2]: return True, "20g zirve kirilimi"
        return False, "kirilim yok"
    if stype == "pullback":
        r = rsi(close)
        if r.iloc[-2] < 35 <= r.iloc[-1]: return True, "RSI dipten donus"
        return False, "RSI sinyali yok"
    if stype == "momentum":
        ret = last/close.iloc[-21]-1 if len(close) > 21 else 0
        if ret > 0.05: return True, f"momentum +{ret*100:.1f}%"
        return False, "momentum zayif"
    return False, "bilinmeyen"

def trend_break_exit(df):
    s50 = sma(df["close"],50).iloc[-1]
    return (not pd.isna(s50)) and df["close"].iloc[-1] < s50

# --- gun ici (15 dakikalik mum) strateji ---
def intraday_entry_signal(df, min_to_close):
    """15dk mum: SMA20 uzerinde + son 8 mumun zirvesini kirma. Kapanisa yakin giris yok."""
    if df is None or len(df) < INTRADAY_SMA_BARS + INTRADAY_BREAK_BARS + 2:
        return False, "yetersiz veri"
    if min_to_close is not None and min_to_close <= INTRADAY_NO_ENTRY_MIN:
        return False, f"kapanisa {min_to_close:.0f}dk kaldi, giris yok"
    close = df["close"]; last = float(close.iloc[-1])
    s20 = sma(close, INTRADAY_SMA_BARS).iloc[-1]
    if pd.isna(s20) or last <= s20:
        return False, "SMA20 alti"
    prior_high = float(df["high"].iloc[-(INTRADAY_BREAK_BARS+1):-1].max())
    if last > prior_high:
        return True, f"{INTRADAY_BREAK_BARS} mum zirve kirilimi"
    return False, "kirilim yok"

def intraday_exit_signal(df):
    """15dk mumda SMA20 altina donus -> cikis."""
    if df is None or len(df) < INTRADAY_SMA_BARS + 1: return False
    s20 = sma(df["close"], INTRADAY_SMA_BARS).iloc[-1]
    return (not pd.isna(s20)) and float(df["close"].iloc[-1]) < float(s20)

def minutes_to_close(clock):
    try:
        return (clock.next_close - datetime.now(timezone.utc)).total_seconds() / 60.0
    except Exception:
        return None

# ----------------------------------------------------------------------------
def stats_init(state):
    st = state.setdefault("_stats", {})
    for sn in STRATEGIES:
        st.setdefault(sn, {"realized": 0.0, "count": 0, "wins": 0, "losses": 0, "peak_equity": STARTING_CAPITAL})
        st[sn].setdefault("costs", 0.0)   # kumulatif tahmini islem maliyeti
    return st

def build_report(state, positions):
    st = state.get("_stats", {})
    rows = []
    for sn in STRATEGIES:
        s = st.get(sn, {"realized":0.0,"count":0,"wins":0,"losses":0,"peak_equity":STARTING_CAPITAL,"costs":0.0})
        # acik pozisyonlarin gerceklesmemis P&L'i
        open_pnl = 0.0
        for pk, p in positions.items():
            if AGENT_OF.get(pk) == sn:
                try: open_pnl += float(p.unrealized_pl)
                except Exception: pass
        equity = STARTING_CAPITAL + s["realized"] + open_pnl
        peak = max(s.get("peak_equity", STARTING_CAPITAL), equity)
        s["peak_equity"] = peak
        drawdown = peak - equity
        win_rate = (s["wins"]/s["count"]*100) if s["count"] else 0.0
        rows.append({
            "agent": sn, "count": s["count"], "wins": s["wins"], "losses": s["losses"],
            "win_rate": win_rate, "realized": s["realized"], "open_pnl": open_pnl,
            "costs": s.get("costs", 0.0),
            "equity": equity, "pnl_total": equity - STARTING_CAPITAL, "drawdown": drawdown,
        })
    rows.sort(key=lambda r: r["pnl_total"], reverse=True)
    return rows

def write_report_md(rows):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"# 🏆 Ajan Turnuvası — Karne", f"", f"Son güncelleme: {now} · Başlangıç: ${STARTING_CAPITAL:.0f}/ajan · PAPER (demo)", "",
             "| # | Ajan | Toplam P&L | Getiri % | İşlem | Kazanma % | Gerçekleşen | Açık P&L | Maliyet | Max Düşüş |",
             "|---|------|-----------|---------|-------|-----------|-------------|----------|---------|-----------|"]
    for i, r in enumerate(rows, 1):
        medal = ["🥇","🥈","🥉"][i-1] if i <= 3 else str(i)
        ret = r["pnl_total"]/STARTING_CAPITAL*100
        lines.append(f"| {medal} | {r['agent']} | ${r['pnl_total']:+.2f} | {ret:+.1f}% | {r['count']} | "
                     f"{r['win_rate']:.0f}% | ${r['realized']:+.2f} | ${r['open_pnl']:+.2f} | "
                     f"${r.get('costs',0.0):.2f} | ${r['drawdown']:.2f} |")
    lines += ["", "> Kazanan = en çok kazanan değil; **iyi getiri + düşük düşüş + tutarlılık.** Yeterli işlem birikene kadar (20-30+) sonuçlar erken sayılır.",
              "", f"> **Gerçekleşen** rakamlar işlem maliyeti düşülmüş nettir (tek yön {COST_BPS_PER_SIDE:.0f} bps spread+kayma varsayımı). "
                  f"**Maliyet** sütunu bugüne kadar ödenen tahmini toplam maliyeti gösterir. Maliyet muhasebesi 2026-09-04'te başladı."]
    with open(REPORT_MD, "w") as f:
        f.write("\n".join(lines))

def write_dashboard_html(rows):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    maxabs = max([abs(r["pnl_total"]) for r in rows] + [1.0])
    cards = ""
    for i, r in enumerate(rows, 1):
        pos = r["pnl_total"] >= 0
        col = "#16a34a" if pos else "#dc2626"
        w = min(100, abs(r["pnl_total"])/maxabs*100)
        ret = r["pnl_total"]/STARTING_CAPITAL*100
        medal = ["🥇","🥈","🥉"][i-1] if i <= 3 else str(i)
        cards += f"""
        <div class="card">
          <div class="rank">{medal}</div>
          <div class="body">
            <div class="name">{r['agent']}</div>
            <div class="pnl" style="color:{col}">${r['pnl_total']:+.2f} <span class="ret">({ret:+.1f}%)</span></div>
            <div class="bar"><div class="fill" style="width:{w:.0f}%;background:{col}"></div></div>
            <div class="meta">İşlem: {r['count']} · Kazanma: {r['win_rate']:.0f}% · Max Düşüş: ${r['drawdown']:.2f}</div>
          </div>
        </div>"""
    html = f"""<!DOCTYPE html><html lang="tr"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Ajan Turnuvası</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Segoe UI',system-ui,sans-serif;background:#0f172a;color:#e2e8f0;padding:24px;max-width:760px;margin:0 auto}}
h1{{font-size:22px;margin-bottom:4px}} .sub{{color:#94a3b8;font-size:13px;margin-bottom:20px}}
.card{{display:flex;gap:16px;align-items:center;background:#1e293b;border:1px solid #334155;border-radius:12px;padding:16px;margin-bottom:12px}}
.rank{{font-size:28px;width:44px;text-align:center}}
.body{{flex:1}} .name{{font-weight:700;font-size:15px}} .pnl{{font-size:20px;font-weight:800;margin:2px 0}}
.ret{{font-size:13px;opacity:.8}}
.bar{{height:8px;background:#0f172a;border-radius:6px;overflow:hidden;margin:6px 0}}
.fill{{height:100%;border-radius:6px}} .meta{{color:#94a3b8;font-size:12px}}
.note{{color:#64748b;font-size:12px;margin-top:16px;line-height:1.5}}
</style></head><body>
<h1>🏆 Ajan Turnuvası — Canlı Karne</h1>
<div class="sub">Son güncelleme: {now} · Başlangıç ${STARTING_CAPITAL:.0f}/ajan · PAPER (demo, gerçek para yok)</div>
{cards}
<div class="note">Kazanan = en çok kazanan değil; iyi getiri + düşük düşüş + tutarlılık. Yeterli işlem (20-30+) birikene kadar sonuçlar erkendir. Bu panel her çalışmada otomatik güncellenir.</div>
</body></html>"""
    with open(DASH_HTML, "w") as f:
        f.write(html)

# ----------------------------------------------------------------------------
def main():
    if not API_KEY or not API_SECRET:
        log("HATA: ALPACA secret'leri tanimli degil."); sys.exit(1)

    trading = TradingClient(API_KEY, API_SECRET, paper=True)
    sc = StockHistoricalDataClient(API_KEY, API_SECRET)
    cc = CryptoHistoricalDataClient(API_KEY, API_SECRET)

    acct = trading.get_account()
    log(f"BAGLANTI OK | durum={acct.status} | nakit=${acct.cash} | portfoy=${acct.portfolio_value}")
    log(f"MOD: {'DRY_RUN (emir YOK)' if DRY_RUN else 'CANLI PAPER (sanal para ile emir)'}")
    clock = trading.get_clock()
    log(f"ABD borsasi acik mi: {clock.is_open}")

    positions = {p.symbol: p for p in trading.get_all_positions()}
    state = load_state()
    stats = stats_init(state)

    per_pos_risk = STARTING_CAPITAL * RISK_PCT
    target_notional = max(MIN_NOTIONAL, per_pos_risk / TRAIL_PCT)

    mtc = minutes_to_close(clock)
    if mtc is not None:
        log(f"Kapanisa kalan sure: {mtc:.0f} dk")

    for sname, cfg in STRATEGIES.items():
        bar_type = cfg.get("bar", "day")
        for symbol in cfg["symbols"]:
            try:
                is_crypto = cfg["asset"] == "crypto"
                if not is_crypto and not clock.is_open:
                    log(f"{sname}/{symbol}: borsa kapali, atlandi"); continue

                df = get_bars(sc, cc, symbol, cfg["asset"], bar=bar_type)
                if df is None: log(f"{sname}/{symbol}: veri yok"); continue
                last = float(df["close"].iloc[-1])
                pk = symbol.replace("/", "")
                held = positions.get(pk) or positions.get(symbol)

                trail = INTRADAY_TRAIL_PCT if bar_type == "intraday" else TRAIL_PCT

                # ---------------------------------------------------------
                # POZISYON VARSA
                # ---------------------------------------------------------
                if held:
                    stt = state.get(pk, {"stop": last*(1-trail), "peak": last, "notional": target_notional})
                    if last > stt["peak"]:
                        stt["peak"] = last; stt["stop"] = max(stt["stop"], last*(1-trail))
                    state[pk] = stt

                    exit_now = False; reason = ""
                    # 1) Trailing stop -> HER turda kontrol edilir (koruma amacli)
                    if last <= stt["stop"]:
                        exit_now, reason = True, "trailing stop"
                    elif bar_type == "intraday":
                        # 2a) Gun ici: kapanisa yakin zorla kapat (gecelik risk yok)
                        if mtc is not None and mtc <= INTRADAY_CLOSE_BUFFER_MIN:
                            exit_now, reason = True, "gun sonu kapanis"
                        elif intraday_exit_signal(df):
                            exit_now, reason = True, "15dk SMA20 alti"
                    else:
                        # 2b) Gunluk: sinyalle cikis SADECE gunde bir kez, TAMAMLANMIS mumla
                        if daily_decision_due(state, pk):
                            if trend_break_exit(completed_daily(df)):
                                exit_now, reason = True, "trend kirildi (SMA50)"

                    if exit_now:
                        try: gross = float(held.unrealized_pl)
                        except Exception: gross = 0.0
                        cost = round_trip_cost(stt.get("notional", target_notional))
                        realized = gross - cost
                        log(f"{sname}/{symbol}: CIKIS ({reason}) fiyat=${last:.2f} "
                            f"brut=${gross:+.2f} maliyet=${cost:.2f} net=${realized:+.2f}")
                        if not DRY_RUN:
                            trading.close_position(pk)
                            stats[sname]["realized"] += realized
                            stats[sname]["costs"] = stats[sname].get("costs", 0.0) + cost
                            stats[sname]["count"] += 1
                            stats[sname]["wins" if realized >= 0 else "losses"] += 1
                            append_trade([datetime.now(timezone.utc), sname, symbol, "SELL", "all", last,
                                          f"{reason} (maliyet ${cost:.2f})", f"{realized:.2f}"])
                        state.pop(pk, None)
                        if bar_type == "intraday":
                            # gun ici ajan: ayni sembolde ayni gun ikinci tur YOK (churn engeli)
                            state[f"_intraday_done_{pk}"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                        else:
                            mark_daily_decision(state, pk)
                    else:
                        log(f"{sname}/{symbol}: TUTULUYOR fiyat=${last:.2f} stop=${stt['stop']:.2f}")
                        if bar_type != "intraday" and daily_decision_due(state, pk):
                            mark_daily_decision(state, pk)
                    continue

                # ---------------------------------------------------------
                # POZISYON YOKSA -> GIRIS
                # ---------------------------------------------------------
                if bar_type == "intraday":
                    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                    if state.get(f"_intraday_done_{pk}") == today:
                        log(f"{sname}/{symbol}: bugun zaten bir tur yapildi, yeni giris yok"); continue
                    sig, why = intraday_entry_signal(df, mtc)
                else:
                    if not daily_decision_due(state, pk):
                        log(f"{sname}/{symbol}: bugunun karari zaten verildi, atlandi"); continue
                    sig, why = entry_signal(completed_daily(df), cfg["type"])
                    mark_daily_decision(state, pk)

                if sig:
                    log(f"{sname}/{symbol}: GIRIS ({why}) fiyat=${last:.2f} ~${target_notional:.0f}")
                    if not DRY_RUN:
                        order = MarketOrderRequest(symbol=symbol, notional=round(target_notional,2),
                                                   side=OrderSide.BUY,
                                                   time_in_force=TimeInForce.GTC if is_crypto else TimeInForce.DAY)
                        trading.submit_order(order)
                        state[pk] = {"stop": last*(1-trail), "peak": last, "notional": target_notional}
                        append_trade([datetime.now(timezone.utc), sname, symbol, "BUY", target_notional, last, why, "0.00"])
                else:
                    log(f"{sname}/{symbol}: sinyal yok ({why}) fiyat=${last:.2f}")
            except Exception as e:
                log(f"{sname}/{symbol}: HATA -> {e}"); traceback.print_exc()

    # KARNE
    try:
        rows = build_report(state, positions)
        write_report_md(rows)
        write_dashboard_html(rows)
        log("Karne guncellendi: report.md + dashboard.html")
        for r in rows:
            log(f"  {r['agent']}: P&L ${r['pnl_total']:+.2f} | islem {r['count']} | dusus ${r['drawdown']:.2f}")
    except Exception as e:
        log(f"Karne hatasi: {e}"); traceback.print_exc()

    save_state(state)
    log("Tur tamamlandi.")

if __name__ == "__main__":
    main()
