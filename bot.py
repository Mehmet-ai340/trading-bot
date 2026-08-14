"""
AI Trading Operator — 4 Ajanlı Paper Trading Botu (v1)
=======================================================
GÜVENLİK: Varsayılan olarak DRY_RUN=True. Yani HİÇBİR emir gönderilmez;
sadece Alpaca'ya bağlanır, verileri çeker, 4 stratejinin sinyallerini
hesaplar ve rapor eder. Boru hattının çalıştığını gördükten sonra
GitHub'da DRY_RUN secret'ini "false" yaparak PAPER (sanal para) işlemleri açarsın.

Her şey PAPER (demo) hesapta çalışır — gerçek para YOK.
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
# AYARLAR (Config)
# ----------------------------------------------------------------------------
API_KEY    = os.environ.get("ALPACA_API_KEY_ID", "")
API_SECRET = os.environ.get("ALPACA_API_SECRET_KEY", "")

# GÜVENLİK ANAHTARI: "false" yapana kadar hiç emir gönderilmez.
DRY_RUN = os.environ.get("DRY_RUN", "true").lower() != "false"

# Gerçekçi $200 simülasyonu: pozisyonlar bu sanal sermayeye göre boyutlanır
# (paper hesabın 100.000$ olsa da biz 200$ gibi davranırız).
STARTING_CAPITAL = float(os.environ.get("STARTING_CAPITAL", "200"))
RISK_PCT = 0.01          # işlem başına maks risk = sermayenin %1'i (= $2)
TRAIL_PCT = 0.08         # trailing stop mesafesi (%8) — risk buradan hesaplanır
MIN_NOTIONAL = 1.0       # Alpaca minimum emir tutarı ($1)

STATE_FILE = "state.json"     # trailing stop seviyeleri burada tutulur
TRADES_LOG = "trades.csv"     # her işlem buraya yazılır

# 4 AJAN — her ajan KENDİ sembol evreninde çalışır (çakışma olmaz, P&L ayrışır)
STRATEGIES = {
    "A_trend":     {"type": "trend",    "symbols": ["SPY", "QQQ"],            "asset": "stock"},
    "B_pullback":  {"type": "pullback", "symbols": ["AAPL", "MSFT"],         "asset": "stock"},
    "C_momentum":  {"type": "momentum", "symbols": ["NVDA", "AMZN", "GOOGL"], "asset": "stock"},
    "D_crypto":    {"type": "trend",    "symbols": ["BTC/USD", "ETH/USD"],   "asset": "crypto"},
}

# ----------------------------------------------------------------------------
# YARDIMCILAR
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
            f.write("time,strategy,symbol,action,qty_or_notional,price,reason\n")
        f.write(",".join(str(x) for x in row) + "\n")

# ---- İndikatörler ----
def sma(series, n):
    return series.rolling(n).mean()

def rsi(series, n=14):
    delta = series.diff()
    up = delta.clip(lower=0).rolling(n).mean()
    down = (-delta.clip(upper=0)).rolling(n).mean()
    rs = up / down.replace(0, 1e-9)
    return 100 - (100 / (1 + rs))

def atr(df, n=14):
    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift()).abs()
    lc = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.rolling(n).mean()

# ---- Veri çekme ----
def get_bars(stock_client, crypto_client, symbol, asset):
    start = datetime.now(timezone.utc) - timedelta(days=400)
    if asset == "crypto":
        req = CryptoBarsRequest(symbol_or_symbols=[symbol], timeframe=TimeFrame.Day, start=start)
        df = crypto_client.get_crypto_bars(req).df
    else:
        req = StockBarsRequest(symbol_or_symbols=[symbol], timeframe=TimeFrame.Day, start=start)
        df = stock_client.get_stock_bars(req).df
    if df is None or df.empty:
        return None
    # multi-index (symbol, timestamp) -> tek sembol düzleştir
    if isinstance(df.index, pd.MultiIndex):
        df = df.xs(symbol, level=0)
    return df

# ---- Sinyal mantığı ----
def entry_signal(df, stype):
    """Giriş sinyali var mı? (sadece LONG)"""
    if len(df) < 210:
        return False, "yetersiz veri"
    close = df["close"]
    last = close.iloc[-1]
    sma200 = sma(close, 200).iloc[-1]
    if pd.isna(sma200) or last <= sma200:
        return False, "trend altı (SMA200)"

    if stype == "trend":
        high20 = df["high"].rolling(20).max().iloc[-2]  # önceki 20 günün zirvesi
        if last >= high20:
            return True, "20g zirve kırılımı"
        return False, "kırılım yok"

    if stype == "pullback":
        r = rsi(close).iloc[-1]
        r_prev = rsi(close).iloc[-2]
        if r_prev < 35 and r >= 35:  # aşırı satımdan dönüş
            return True, "RSI dipten dönüş"
        return False, "RSI sinyali yok"

    if stype == "momentum":
        ret = (last / close.iloc[-21] - 1) if len(close) > 21 else 0
        if ret > 0.05:  # son ~1 ayda güçlü
            return True, f"momentum +{ret*100:.1f}%"
        return False, "momentum zayıf"

    return False, "bilinmeyen strateji"

def trend_break_exit(df):
    close = df["close"]
    sma50 = sma(close, 50).iloc[-1]
    return (not pd.isna(sma50)) and close.iloc[-1] < sma50

# ----------------------------------------------------------------------------
# ANA DÖNGÜ
# ----------------------------------------------------------------------------
def main():
    if not API_KEY or not API_SECRET:
        log("HATA: ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY secret'leri tanımlı değil.")
        sys.exit(1)

    trading = TradingClient(API_KEY, API_SECRET, paper=True)
    stock_client = StockHistoricalDataClient(API_KEY, API_SECRET)
    crypto_client = CryptoHistoricalDataClient(API_KEY, API_SECRET)

    # 1) Bağlantı testi
    acct = trading.get_account()
    log(f"BAGLANTI OK | durum={acct.status} | nakit=${acct.cash} | portfoy=${acct.portfolio_value}")
    log(f"MOD: {'DRY_RUN (emir YOK, sadece rapor)' if DRY_RUN else 'CANLI PAPER (sanal para ile emir)'}")

    clock = trading.get_clock()
    log(f"ABD borsasi acik mi: {clock.is_open}")

    positions = {p.symbol: p for p in trading.get_all_positions()}
    state = load_state()

    # 2) Her ajan / her sembol için karar
    per_pos_risk = STARTING_CAPITAL * RISK_PCT          # $ risk (ör. $2)
    target_notional = max(MIN_NOTIONAL, per_pos_risk / TRAIL_PCT)  # ~$25 pozisyon

    for sname, cfg in STRATEGIES.items():
        for symbol in cfg["symbols"]:
            try:
                is_crypto = cfg["asset"] == "crypto"
                # Hisse stratejileri borsa kapalıysa işlem yapmaz; kripto 7/24
                if not is_crypto and not clock.is_open:
                    log(f"{sname}/{symbol}: borsa kapali, atlandi")
                    continue

                df = get_bars(stock_client, crypto_client, symbol, cfg["asset"])
                if df is None:
                    log(f"{sname}/{symbol}: veri yok, atlandi")
                    continue

                last = float(df["close"].iloc[-1])
                pos_key = symbol.replace("/", "")  # kripto pozisyon anahtarı (BTCUSD)
                held = positions.get(pos_key) or positions.get(symbol)

                # --- POZISYON VARSA: trailing stop yönet ---
                if held:
                    st = state.get(pos_key, {"stop": last * (1 - TRAIL_PCT), "peak": last})
                    if last > st["peak"]:
                        st["peak"] = last
                        st["stop"] = max(st["stop"], last * (1 - TRAIL_PCT))
                    state[pos_key] = st

                    exit_now = last <= st["stop"] or trend_break_exit(df)
                    reason = "trailing stop" if last <= st["stop"] else "trend kirildi (SMA50)"
                    if exit_now:
                        log(f"{sname}/{symbol}: CIKIS ({reason}) fiyat=${last:.2f} stop=${st['stop']:.2f}")
                        if not DRY_RUN:
                            trading.close_position(pos_key)
                            append_trade([datetime.now(timezone.utc), sname, symbol, "SELL", "all", last, reason])
                        state.pop(pos_key, None)
                    else:
                        log(f"{sname}/{symbol}: TUTULUYOR fiyat=${last:.2f} stop=${st['stop']:.2f}")
                    continue

                # --- POZISYON YOKSA: giriş sinyali ara ---
                sig, why = entry_signal(df, cfg["type"])
                if sig:
                    log(f"{sname}/{symbol}: GIRIS sinyali ({why}) fiyat=${last:.2f} ~${target_notional:.0f} alinacak")
                    if not DRY_RUN:
                        order = MarketOrderRequest(
                            symbol=symbol, notional=round(target_notional, 2),
                            side=OrderSide.BUY,
                            time_in_force=TimeInForce.GTC if is_crypto else TimeInForce.DAY,
                        )
                        trading.submit_order(order)
                        state[pos_key] = {"stop": last * (1 - TRAIL_PCT), "peak": last}
                        append_trade([datetime.now(timezone.utc), sname, symbol, "BUY", target_notional, last, why])
                else:
                    log(f"{sname}/{symbol}: sinyal yok ({why}) fiyat=${last:.2f}")

            except Exception as e:
                log(f"{sname}/{symbol}: HATA -> {e}")
                traceback.print_exc()

    save_state(state)
    log("Tur tamamlandi.")

if __name__ == "__main__":
    main()
