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
from alpaca.data.timeframe import TimeFrame

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

STATE_FILE = "state.json"
TRADES_LOG = "trades.csv"
REPORT_MD = "report.md"
DASH_HTML = "dashboard.html"

STRATEGIES = {
    "A_trend":     {"type": "trend",    "symbols": ["SPY", "QQQ"],            "asset": "stock"},
    "B_pullback":  {"type": "pullback", "symbols": ["AAPL", "MSFT"],         "asset": "stock"},
    "C_momentum":  {"type": "momentum", "symbols": ["NVDA", "AMZN", "GOOGL"], "asset": "stock"},
    "D_crypto":    {"type": "trend",    "symbols": ["BTC/USD", "ETH/USD"],   "asset": "crypto"},
    "E_metals":    {"type": "trend",    "symbols": ["GLD", "SLV"],     "asset": "stock"},
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

def get_bars(sc, cc, symbol, asset):
    start = datetime.now(timezone.utc) - timedelta(days=400)
    if asset == "crypto":
        df = cc.get_crypto_bars(CryptoBarsRequest(symbol_or_symbols=[symbol], timeframe=TimeFrame.Day, start=start)).df
    else:
        df = sc.get_stock_bars(StockBarsRequest(symbol_or_symbols=[symbol], timeframe=TimeFrame.Day, start=start)).df
    if df is None or df.empty: return None
    if isinstance(df.index, pd.MultiIndex): df = df.xs(symbol, level=0)
    return df

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

# ----------------------------------------------------------------------------
def stats_init(state):
    st = state.setdefault("_stats", {})
    for sn in STRATEGIES:
        st.setdefault(sn, {"realized": 0.0, "count": 0, "wins": 0, "losses": 0, "peak_equity": STARTING_CAPITAL})
    return st

def build_report(state, positions):
    st = state.get("_stats", {})
    rows = []
    for sn in STRATEGIES:
        s = st.get(sn, {"realized":0.0,"count":0,"wins":0,"losses":0,"peak_equity":STARTING_CAPITAL})
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
            "equity": equity, "pnl_total": equity - STARTING_CAPITAL, "drawdown": drawdown,
        })
    rows.sort(key=lambda r: r["pnl_total"], reverse=True)
    return rows

def write_report_md(rows):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"# 🏆 Ajan Turnuvası — Karne", f"", f"Son güncelleme: {now} · Başlangıç: ${STARTING_CAPITAL:.0f}/ajan · PAPER (demo)", "",
             "| # | Ajan | Toplam P&L | Getiri % | İşlem | Kazanma % | Gerçekleşen | Açık P&L | Max Düşüş |",
             "|---|------|-----------|---------|-------|-----------|-------------|----------|-----------|"]
    for i, r in enumerate(rows, 1):
        medal = ["🥇","🥈","🥉","4️⃣"][i-1] if i <= 4 else str(i)
        ret = r["pnl_total"]/STARTING_CAPITAL*100
        lines.append(f"| {medal} | {r['agent']} | ${r['pnl_total']:+.2f} | {ret:+.1f}% | {r['count']} | "
                     f"{r['win_rate']:.0f}% | ${r['realized']:+.2f} | ${r['open_pnl']:+.2f} | ${r['drawdown']:.2f} |")
    lines += ["", "> Kazanan = en çok kazanan değil; **iyi getiri + düşük düşüş + tutarlılık.** Yeterli işlem birikene kadar (20-30+) sonuçlar erken sayılır."]
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
        medal = ["🥇","🥈","🥉","4️⃣"][i-1] if i <= 4 else str(i)
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

    for sname, cfg in STRATEGIES.items():
        for symbol in cfg["symbols"]:
            try:
                is_crypto = cfg["asset"] == "crypto"
                if not is_crypto and not clock.is_open:
                    log(f"{sname}/{symbol}: borsa kapali, atlandi"); continue
                df = get_bars(sc, cc, symbol, cfg["asset"])
                if df is None: log(f"{sname}/{symbol}: veri yok"); continue
                last = float(df["close"].iloc[-1])
                pk = symbol.replace("/", "")
                held = positions.get(pk) or positions.get(symbol)

                if held:
                    stt = state.get(pk, {"stop": last*(1-TRAIL_PCT), "peak": last})
                    if last > stt["peak"]:
                        stt["peak"] = last; stt["stop"] = max(stt["stop"], last*(1-TRAIL_PCT))
                    state[pk] = stt
                    exit_now = last <= stt["stop"] or trend_break_exit(df)
                    reason = "trailing stop" if last <= stt["stop"] else "trend kirildi (SMA50)"
                    if exit_now:
                        try: realized = float(held.unrealized_pl)
                        except Exception: realized = 0.0
                        log(f"{sname}/{symbol}: CIKIS ({reason}) fiyat=${last:.2f} P&L=${realized:+.2f}")
                        if not DRY_RUN:
                            trading.close_position(pk)
                            stats[sname]["realized"] += realized
                            stats[sname]["count"] += 1
                            stats[sname]["wins" if realized >= 0 else "losses"] += 1
                            append_trade([datetime.now(timezone.utc), sname, symbol, "SELL", "all", last, reason, f"{realized:.2f}"])
                        state.pop(pk, None)
                    else:
                        log(f"{sname}/{symbol}: TUTULUYOR fiyat=${last:.2f} stop=${stt['stop']:.2f}")
                    continue

                sig, why = entry_signal(df, cfg["type"])
                if sig:
                    log(f"{sname}/{symbol}: GIRIS ({why}) fiyat=${last:.2f} ~${target_notional:.0f}")
                    if not DRY_RUN:
                        order = MarketOrderRequest(symbol=symbol, notional=round(target_notional,2),
                                                   side=OrderSide.BUY,
                                                   time_in_force=TimeInForce.GTC if is_crypto else TimeInForce.DAY)
                        trading.submit_order(order)
                        state[pk] = {"stop": last*(1-TRAIL_PCT), "peak": last}
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
