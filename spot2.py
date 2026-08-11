import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import yfinance as yf
import requests
from datetime import datetime, timedelta
import warnings
import os
from dotenv import load_dotenv
from streamlit_autorefresh import st_autorefresh
from supabase import create_client, Client
from ta.volatility import AverageTrueRange, BollingerBands
from ta.trend import ADXIndicator

load_dotenv()
warnings.filterwarnings('ignore')

# =========================================================
# PAGE CONFIG
# =========================================================
st.set_page_config(
    page_title="🤖 Crypto Bot PRO - Bottom Momentum Scanner",
    layout="wide",
    initial_sidebar_state="expanded"
)

# =========================================================
# CSS KUSTOM
# =========================================================
st.markdown("""
<style>
    .stApp { background: #0a0a1a; }
    [data-testid="stMetric"] {
        background: linear-gradient(145deg, #111827, #0b1220);
        border: 1px solid #1e293b;
        border-radius: 16px;
        padding: 16px;
        box-shadow: 0 4px 20px rgba(0,255,255,0.05);
    }
    [data-testid="stMetric"]:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 30px rgba(0,255,255,0.1);
    }
    .signal-buy {
        background: linear-gradient(135deg, rgba(0,255,136,0.15), rgba(0,255,136,0.05));
        border: 1px solid #00ff88;
        border-radius: 12px;
        padding: 12px 20px;
        color: #00ff88;
        font-weight: 600;
        font-size: 18px;
    }
    .signal-exit {
        background: linear-gradient(135deg, rgba(255,59,92,0.15), rgba(255,59,92,0.05));
        border: 1px solid #ff3b5c;
        border-radius: 12px;
        padding: 12px 20px;
        color: #ff3b5c;
        font-weight: 600;
        font-size: 18px;
    }
    .signal-hold {
        background: linear-gradient(135deg, rgba(255,170,0,0.15), rgba(255,170,0,0.05));
        border: 1px solid #ffaa00;
        border-radius: 12px;
        padding: 12px 20px;
        color: #ffaa00;
        font-weight: 600;
        font-size: 18px;
    }
    .bottom-strong {
        background: linear-gradient(135deg, rgba(0,255,136,0.25), rgba(0,255,136,0.05));
        border: 2px solid #00ff88;
        border-radius: 12px;
        padding: 12px 20px;
        color: #00ff88;
        font-weight: 700;
        font-size: 18px;
        text-align: center;
    }
    .bottom-momentum {
        background: linear-gradient(135deg, rgba(255,170,0,0.2), rgba(255,170,0,0.05));
        border: 1px solid #ffaa00;
        border-radius: 12px;
        padding: 12px 20px;
        color: #ffaa00;
        font-weight: 700;
        font-size: 16px;
        text-align: center;
    }
    .pending-signal {
        background: linear-gradient(135deg, rgba(255,170,0,0.15), rgba(255,170,0,0.05));
        border: 1px solid #ffaa00;
        border-radius: 12px;
        padding: 12px 20px;
        color: #ffaa00;
        font-weight: 600;
        font-size: 16px;
        animation: blink 1.5s infinite;
    }
    @keyframes blink {
        0% { opacity: 1; }
        50% { opacity: 0.5; }
        100% { opacity: 1; }
    }
    .stButton > button {
        background: linear-gradient(145deg, #00ff88, #00cc66);
        color: #000;
        font-weight: 700;
        border: none;
        border-radius: 10px;
        padding: 10px 24px;
        transition: all 0.3s ease;
    }
    .stButton > button:hover {
        transform: scale(1.03);
        box-shadow: 0 0 30px rgba(0,255,255,0.3);
    }
</style>
""", unsafe_allow_html=True)

# =========================================================
# SUPABASE CONNECTION
# =========================================================
@st.cache_resource
def get_supabase() -> Client:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        try:
            url = st.secrets["supabase"]["url"]
            key = st.secrets["supabase"]["key"]
        except:
            st.error("❌ SUPABASE_URL atau SUPABASE_KEY tidak ditemukan")
            st.stop()
    return create_client(url, key)

# =========================================================
# INDIKATOR TEKNIKAL
# =========================================================
def EMA(df, period=20):
    return df["Close"].ewm(span=period, adjust=False).mean()

def MACD(df, fast=12, slow=26, signal=9):
    ema_fast = EMA(df, fast)
    ema_slow = EMA(df, slow)
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram

def StochasticRSI(df, period=14, smooth_k=3, smooth_d=3):
    delta = df["Close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    stoch_rsi = (rsi - rsi.rolling(period).min()) / (rsi.rolling(period).max() - rsi.rolling(period).min()) * 100
    k = stoch_rsi.rolling(smooth_k).mean()
    d = k.rolling(smooth_d).mean()
    return k, d, rsi

def ADX(df, period=14):
    try:
        adx = ADXIndicator(df["High"], df["Low"], df["Close"], window=period)
        return adx.adx()
    except:
        return pd.Series([0] * len(df))

# =========================================================
# DETEKSI WHIPSAW
# =========================================================
def detect_whipsaw(df, lookback=20):
    if df is None or len(df) < lookback + 5:
        return {"is_whipsaw": False, "score": 0, "status": "🟢 CLEAR", "direction": "NONE", "reasons": [], "range_high": 0, "range_low": 0, "vol_ratio": 0, "adx": 0}
    
    high = df["High"]
    low = df["Low"]
    close = df["Close"]
    
    recent_high = high.tail(lookback).max()
    recent_low = low.tail(lookback).min()
    range_mid = (recent_high + recent_low) / 2
    
    current_close = close.iloc[-1]
    high_last = high.iloc[-1]
    low_last = low.iloc[-1]
    
    vol_ma = df["Volume"].rolling(10).mean().iloc[-1]
    vol_ratio = df["Volume"].iloc[-1] / vol_ma if vol_ma > 0 else 1
    
    try:
        bb = BollingerBands(close=df["Close"], window=20, window_dev=2)
        bb_upper = bb.bollinger_hband().iloc[-1]
        bb_lower = bb.bollinger_lband().iloc[-1]
    except:
        bb_upper = recent_high * 1.05
        bb_lower = recent_low * 0.95
    
    try:
        adx = ADXIndicator(df["High"], df["Low"], df["Close"], window=14)
        adx_now = adx.adx().iloc[-1] if not pd.isna(adx.adx().iloc[-1]) else 0
    except:
        adx_now = 0
    
    score = 0
    reasons = []
    direction = "NONE"
    
    # FALSE BREAKOUT ATAS
    if high_last > recent_high * 1.005 or high_last > bb_upper:
        if current_close < recent_high * 0.995:
            score += 3
            reasons.append("Fake breakout atas")
            direction = "FAKE_UP"
            if vol_ratio < 1.2:
                score += 2
                reasons.append("Volume rendah")
            if adx_now < 25:
                score += 1
                reasons.append("ADX rendah")
    
    # FALSE BREAKOUT BAWAH
    if low_last < recent_low * 0.995 or low_last < bb_lower:
        if current_close > recent_low * 1.005:
            score += 3
            reasons.append("Fake breakout bawah")
            direction = "FAKE_DOWN"
            if vol_ratio < 1.2:
                score += 2
                reasons.append("Volume rendah")
            if adx_now < 25:
                score += 1
                reasons.append("ADX rendah")
    
    if score >= 4:
        is_whipsaw = True
        status = "⚠️ WHIPSAW"
    else:
        is_whipsaw = False
        status = "✅ CLEAR"
    
    return {
        "is_whipsaw": is_whipsaw,
        "score": score,
        "status": status,
        "direction": direction,
        "reasons": reasons,
        "range_high": float(recent_high),
        "range_low": float(recent_low),
        "vol_ratio": float(vol_ratio),
        "adx": float(adx_now)
    }

# =========================================================
# DETEKSI BOTTOM
# =========================================================
def detect_bottom(df, lookback=30):
    if df is None or len(df) < lookback:
        return {"is_bottom": False, "score": 0, "status": "⚪ NO BOTTOM", "reasons": [], "support": 0, "rsi": 50, "volume_ratio": 1}
    
    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    
    current_price = close.iloc[-1]
    recent_low = low.tail(lookback).min()
    support_level = recent_low
    near_support = current_price <= support_level * 1.02
    
    try:
        _, _, rsi = StochasticRSI(df)
        rsi_now = rsi.iloc[-1]
    except:
        rsi_now = 50
    
    try:
        stoch_k, stoch_d, _ = StochasticRSI(df)
        stoch_k_now = stoch_k.iloc[-1]
        stoch_d_now = stoch_d.iloc[-1]
        stoch_oversold = stoch_k_now < 20 and stoch_d_now < 20
    except:
        stoch_oversold = False
    
    try:
        macd_line, signal_line, histogram = MACD(df)
        hist_now = histogram.iloc[-1]
        hist_prev = histogram.iloc[-2] if len(histogram) > 1 else hist_now
        hist_improving = hist_now > hist_prev
        macd_prev = macd_line.iloc[-2] if len(macd_line) > 1 else macd_line.iloc[-1]
        signal_prev = signal_line.iloc[-2] if len(signal_line) > 1 else signal_line.iloc[-1]
        macd_now = macd_line.iloc[-1]
        signal_now = signal_line.iloc[-1]
        golden_cross = (macd_prev < signal_prev) and (macd_now > signal_now)
    except:
        hist_improving = False
        golden_cross = False
    
    vol_ma = df["Volume"].rolling(10).mean().iloc[-1]
    vol_ratio = df["Volume"].iloc[-1] / vol_ma if vol_ma > 0 else 1
    volume_spike = vol_ratio > 1.8
    
    score = 0
    reasons = []
    
    if near_support:
        score += 2
        reasons.append(f"Near support ${support_level:.4f}")
    
    if rsi_now < 30:
        score += 2
        reasons.append(f"RSI oversold ({rsi_now:.1f})")
    elif rsi_now < 40:
        score += 1
        reasons.append(f"RSI low ({rsi_now:.1f})")
    
    if stoch_oversold:
        score += 2
        reasons.append("Stoch oversold")
    
    if golden_cross:
        score += 2
        reasons.append("MACD golden cross")
    
    if hist_improving:
        score += 1
        reasons.append("Histogram improving")
    
    if volume_spike:
        score += 1
        reasons.append(f"Volume spike {vol_ratio:.1f}x")
    
    score = min(score, 10)
    
    if score >= 7:
        status = "🔥 STRONG BOTTOM"
        is_bottom = True
    elif score >= 5:
        status = "🟢 BOTTOM"
        is_bottom = True
    elif score >= 3:
        status = "🟡 POTENTIAL BOTTOM"
        is_bottom = False
    else:
        status = "⚪ NO BOTTOM"
        is_bottom = False
    
    return {
        "is_bottom": is_bottom,
        "score": score,
        "status": status,
        "reasons": reasons,
        "support": support_level,
        "rsi": rsi_now,
        "volume_ratio": vol_ratio,
        "golden_cross": golden_cross
    }

# =========================================================
# BOTTOM MOMENTUM SCORE (GABUNGAN)
# =========================================================
def calculate_bottom_momentum_score(result, df):
    if df is None or len(df) < 30:
        return {"total_score": 0, "bottom_score": 0, "momentum_score": 0, "status": "⚪ NO DATA", "action": "⏳ WAIT", "entry": False, "reasons": []}
    
    # BOTTOM SCORE
    bottom = detect_bottom(df, lookback=30)
    bottom_score = bottom["score"]
    
    # MOMENTUM SCORE
    momentum_score = 0
    momentum_reasons = []
    
    if result["macd"]["dif"] > result["macd"]["dea"]:
        momentum_score += 1
        momentum_reasons.append("MACD DIF > DEA")
    if result["macd"]["golden_cross"]:
        momentum_score += 1
        momentum_reasons.append("⭐ MACD Golden Cross!")
    if result["macd"]["hist_increasing"] and result["macd"]["hist_positive"]:
        momentum_score += 1
        momentum_reasons.append("Histogram menguat")
    
    if result["stoch"]["golden_cross"] and result["stoch"]["k"] < 40:
        momentum_score += 2
        momentum_reasons.append("⭐ Stoch Golden Cross!")
    if result["stoch"]["k"] > result["stoch"]["d"]:
        momentum_score += 1
        momentum_reasons.append("Stoch K > D")
    
    if result.get("strong_bullish", False):
        momentum_score += 2
        momentum_reasons.append("Strong Bullish (EMA100+)")
    elif result.get("bullish_trend", False):
        momentum_score += 1
        momentum_reasons.append("Bullish Trend")
    
    if result.get("volume_ratio", 0) > 1.5:
        momentum_score += 1
        momentum_reasons.append(f"Volume {result['volume_ratio']:.2f}x")
    
    rsi = result.get("rsi", 50)
    if 30 <= rsi <= 60:
        momentum_score += 1
        momentum_reasons.append(f"RSI ideal ({rsi:.1f})")
    
    momentum_score = min(momentum_score, 10.0)
    
    # TOTAL SCORE
    total_score = bottom_score + momentum_score
    
    # STATUS
    if bottom_score >= 5 and momentum_score >= 5:
        status = "🔥 STRONG BOTTOM MOMENTUM"
        action = "🟢 STRONG BUY"
        entry = True
    elif bottom_score >= 4 and momentum_score >= 4:
        status = "🟢 BOTTOM MOMENTUM"
        action = "🟢 BUY"
        entry = True
    elif bottom_score >= 3 and momentum_score >= 3:
        status = "🟡 POTENTIAL BOTTOM"
        action = "⏳ WAIT"
        entry = False
    else:
        status = "⚪ NO BOTTOM MOMENTUM"
        action = "⏳ WAIT"
        entry = False
    
    return {
        "total_score": round(total_score, 1),
        "bottom_score": round(bottom_score, 1),
        "momentum_score": round(momentum_score, 1),
        "status": status,
        "action": action,
        "entry": entry,
        "reasons": bottom["reasons"] + momentum_reasons,
        "bottom": bottom
    }

# =========================================================
# ANALISIS UTAMA
# =========================================================
def analyze_macd_stoch_spot(df, timeframe=""):
    if df is None or len(df) < 30:
        return None
    
    macd_line, signal_line, histogram = MACD(df)
    stoch_k, stoch_d, rsi = StochasticRSI(df)
    ema20 = EMA(df, 20)
    ema50 = EMA(df, 50)
    ema100 = EMA(df, 100)
    
    last = df.iloc[-1]
    price = last["Close"]
    volume = last["Volume"]
    vol_ma = df["Volume"].rolling(10).mean().iloc[-1]
    volume_ratio = volume / vol_ma if vol_ma > 0 else 1
    
    macd_val = macd_line.iloc[-1]
    signal_val = signal_line.iloc[-1]
    hist_val = histogram.iloc[-1]
    hist_prev = histogram.iloc[-2] if len(histogram) > 1 else hist_val
    macd_prev = macd_line.iloc[-2] if len(macd_line) > 1 else macd_val
    signal_prev = signal_line.iloc[-2] if len(signal_line) > 1 else signal_val
    
    stoch_k_val = stoch_k.iloc[-1]
    stoch_d_val = stoch_d.iloc[-1]
    stoch_k_prev = stoch_k.iloc[-2] if len(stoch_k) > 1 else stoch_k_val
    stoch_d_prev = stoch_d.iloc[-2] if len(stoch_d) > 1 else stoch_d_val
    rsi_val = rsi.iloc[-1]
    
    ema20_val = ema20.iloc[-1]
    ema50_val = ema50.iloc[-1]
    ema100_val = ema100.iloc[-1] if len(ema100) > 0 else price
    
    macd_golden_cross = (macd_prev < signal_prev) and (macd_val > signal_val)
    macd_death_cross = (macd_prev > signal_prev) and (macd_val < signal_val)
    stoch_golden_cross = (stoch_k_prev < stoch_d_prev) and (stoch_k_val > stoch_d_val)
    stoch_death_cross = (stoch_k_prev > stoch_d_prev) and (stoch_k_val < stoch_d_val)
    
    hist_increasing = hist_val > hist_prev
    hist_decreasing = hist_val < hist_prev
    hist_positive = hist_val > 0
    
    strong_bullish = price > ema20_val > ema50_val > ema100_val
    bullish_trend = price > ema20_val > ema50_val
    bearish_trend = price < ema20_val < ema50_val
    
    volume_confirmed = volume_ratio > 1.5
    
    # BUY SCORE
    buy_score = 0
    buy_reasons = []
    
    if macd_val > signal_val:
        buy_score += 1
        buy_reasons.append("MACD DIF > DEA ✅")
    if hist_positive:
        buy_score += 1
        buy_reasons.append("Histogram positif ✅")
    if macd_golden_cross:
        buy_score += 2
        buy_reasons.append("⭐ MACD Golden Cross!")
    if hist_increasing and hist_positive:
        buy_score += 1
        buy_reasons.append("Histogram menguat ✅")
    
    if stoch_k_val < 20 and stoch_d_val < 20:
        buy_score += 2
        buy_reasons.append("⭐ Stoch Oversold (<20)")
    elif 20 <= stoch_k_val <= 40 and stoch_k_val > stoch_d_val:
        buy_score += 1
        buy_reasons.append("Stoch 20-40 & menguat ✅")
    if stoch_golden_cross and stoch_k_val < 40:
        buy_score += 2
        buy_reasons.append("⭐ Stoch Golden Cross!")
    if stoch_k_val > stoch_d_val:
        buy_score += 0.5
        buy_reasons.append("Stoch K > D ✅")
    
    if strong_bullish:
        buy_score += 2
        buy_reasons.append("⭐ Strong Bullish (EMA100+)")
    elif bullish_trend:
        buy_score += 1
        buy_reasons.append("Bullish Trend ✅")
    elif price > ema20_val:
        buy_score += 0.5
        buy_reasons.append("Harga > EMA20 ✅")
    
    if volume_confirmed:
        buy_score += 1
        buy_reasons.append("Volume tinggi ✅")
    
    if 30 <= rsi_val <= 60:
        buy_score += 1
        buy_reasons.append(f"RSI ideal ({rsi_val:.1f}) ✅")
    elif rsi_val < 70:
        buy_score += 0.5
        buy_reasons.append(f"RSI sehat ({rsi_val:.1f}) ✅")
    
    # EXIT SCORE
    exit_score = 0
    exit_reasons = []
    
    if macd_val < signal_val:
        exit_score += 1
        exit_reasons.append("MACD DIF < DEA ⚠️")
    if hist_decreasing and hist_positive:
        exit_score += 1
        exit_reasons.append("Histogram mengecil ⚠️")
    if macd_death_cross:
        exit_score += 2
        exit_reasons.append("⭐ MACD Death Cross!")
    
    if stoch_k_val > 80 and stoch_d_val > 80:
        exit_score += 2
        exit_reasons.append("⭐ Stoch Overbought (>80)")
    if stoch_death_cross and stoch_k_val > 80:
        exit_score += 2
        exit_reasons.append("⭐ Stoch Death Cross!")
    
    if bearish_trend:
        exit_score += 1
        exit_reasons.append("Bearish Trend ⚠️")
    
    if rsi_val > 70:
        exit_score += 0.5
        exit_reasons.append(f"RSI overbought ({rsi_val:.1f})")
    
    # BOTTOM MOMENTUM
    bm = calculate_bottom_momentum_score(
        {
            "macd": {
                "dif": macd_val,
                "dea": signal_val,
                "histogram": hist_val,
                "golden_cross": macd_golden_cross,
                "hist_increasing": hist_increasing,
                "hist_positive": hist_positive
            },
            "stoch": {
                "k": stoch_k_val,
                "d": stoch_d_val,
                "golden_cross": stoch_golden_cross
            },
            "strong_bullish": strong_bullish,
            "bullish_trend": bullish_trend,
            "volume_ratio": volume_ratio,
            "rsi": rsi_val
        },
        df
    )
    
    if bm["entry"]:
        buy_score += bm["bottom_score"] * 0.5
        buy_reasons.append(f"📉 {bm['status']}")
        for reason in bm["reasons"]:
            buy_reasons.append(f"  • {reason}")
    
    # KEPUTUSAN
    action = "⏳ WAIT"
    signal_type = "HOLD"
    signal_strength = 0
    is_buy = False
    reasons = []
    
    if buy_score >= 6:
        if buy_score >= 8 and stoch_golden_cross and macd_golden_cross and strong_bullish:
            signal_type = "⭐⭐⭐ STRONG BUY"
            signal_strength = 3
            action = "🟢 STRONG BUY"
            is_buy = True
            reasons = buy_reasons
        elif buy_score >= 7 and (macd_golden_cross or stoch_golden_cross):
            signal_type = "⭐⭐ BUY"
            signal_strength = 2
            action = "🟢 BUY"
            is_buy = True
            reasons = buy_reasons
        else:
            signal_type = "⭐ BUY"
            signal_strength = 1
            action = "🟢 BUY"
            is_buy = True
            reasons = buy_reasons
    
    elif exit_score >= 4:
        if exit_score >= 6 and stoch_death_cross and macd_death_cross:
            signal_type = "🔴 STRONG EXIT"
            signal_strength = 3
            action = "🔴 EXIT"
            reasons = exit_reasons
        else:
            signal_type = "🔴 EXIT / TAKE PROFIT"
            signal_strength = 2
            action = "🔴 EXIT"
            reasons = exit_reasons
    
    else:
        if macd_val > signal_val and 20 <= stoch_k_val <= 80:
            signal_type = "🟡 HOLD"
            action = "🟡 HOLD"
        elif macd_val > signal_val and stoch_k_val < 20:
            signal_type = "🟡 WAIT (Oversold, tunggu golden cross)"
            action = "⏳ WAIT"
        else:
            signal_type = "🟡 HOLD / WAIT"
            action = "⏳ WAIT"
    
    return {
        "symbol": None,
        "timeframe": timeframe,
        "action": action,
        "signal_type": signal_type,
        "signal_strength": signal_strength,
        "is_buy": is_buy,
        "score": {"buy": buy_score, "exit": exit_score},
        "reasons": reasons,
        "bottom_momentum": bm,
        "macd": {
            "dif": macd_val,
            "dea": signal_val,
            "histogram": hist_val,
            "golden_cross": macd_golden_cross,
            "death_cross": macd_death_cross,
            "hist_increasing": hist_increasing,
            "hist_decreasing": hist_decreasing,
            "hist_positive": hist_positive
        },
        "stoch": {
            "k": stoch_k_val,
            "d": stoch_d_val,
            "golden_cross": stoch_golden_cross,
            "death_cross": stoch_death_cross
        },
        "rsi": rsi_val,
        "ema20": ema20_val,
        "ema50": ema50_val,
        "ema100": ema100_val,
        "price": price,
        "volume_ratio": volume_ratio,
        "bullish_trend": bullish_trend,
        "bearish_trend": bearish_trend,
        "strong_bullish": strong_bullish
    }

# =========================================================
# MULTI TIMEFRAME
# =========================================================
def analyze_mtf_macd_stoch_spot(symbol, timeframes=["15m", "1h", "4h"]):
    results = {}
    for tf in timeframes:
        try:
            df = get_data_safe(symbol, tf, min_candles=50)
            if df is not None:
                result = analyze_macd_stoch_spot(df, tf)
                if result:
                    result["symbol"] = symbol
                    results[tf] = result
        except:
            continue
    
    if not results:
        return None
    
    combined = {"symbol": symbol, "timeframes": results}
    buy_count = 0
    sell_count = 0
    hold_count = 0
    
    bm_scores = []
    
    for tf in ["4h", "1h", "15m"]:
        if tf in results:
            res = results[tf]
            if "BUY" in res["action"]:
                buy_count += 1
            elif "EXIT" in res["action"]:
                sell_count += 1
            else:
                hold_count += 1
            
            if "bottom_momentum" in res:
                bm_scores.append(res["bottom_momentum"]["total_score"])
    
    main_signal = "⏳ WAIT"
    main_strength = 0
    avg_bm = sum(bm_scores) / len(bm_scores) if bm_scores else 0
    
    if buy_count >= 3 and avg_bm >= 10:
        main_signal = "🔥 STRONG BOTTOM MOMENTUM (All TF)"
        main_strength = 3
    elif buy_count >= 2 and avg_bm >= 8:
        main_signal = "🟢 BOTTOM MOMENTUM (2 TF)"
        main_strength = 2
    elif buy_count == 1 and avg_bm >= 5:
        main_signal = "🟡 POTENTIAL BOTTOM"
        main_strength = 1
    elif sell_count >= 2:
        main_signal = "🔴 EXIT (Multi TF)"
        main_strength = 3
    else:
        main_signal = "🟡 HOLD / WAIT"
        main_strength = 1
    
    combined["main_signal"] = main_signal
    combined["main_strength"] = main_strength
    combined["buy_count"] = buy_count
    combined["sell_count"] = sell_count
    combined["hold_count"] = hold_count
    combined["avg_bottom_momentum"] = avg_bm
    
    return combined

# =========================================================
# GET DATA
# =========================================================
@st.cache_data(ttl=30, show_spinner=False)
def get_data(symbol, interval, period):
    try:
        ticker = f"{symbol}-USD"
        df = yf.download(ticker, interval=interval, period=period, progress=False)
        if df.empty:
            ticker = symbol
            df = yf.download(ticker, interval=interval, period=period, progress=False)
        if df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.reset_index()
        df.rename(columns={df.columns[0]: "Time"}, inplace=True)
        df["Time"] = pd.to_datetime(df["Time"])
        return df
    except:
        return None

def get_data_safe(symbol, interval, min_candles=20):
    periods = {
        "1m": ["1d", "5d", "7d"],
        "5m": ["2d", "5d", "7d", "14d"],
        "15m": ["5d", "7d", "14d", "30d"],
        "30m": ["7d", "14d", "30d"],
        "1h": ["7d", "14d", "30d", "60d"],
        "4h": ["14d", "30d", "60d", "90d"],
        "1d": ["30d", "60d", "90d", "1y"],
    }
    for period in periods.get(interval, ["7d", "14d", "30d"]):
        df = get_data(symbol, interval, period)
        if df is not None and len(df) >= min_candles:
            return df
    return None

# =========================================================
# DATABASE FUNCTIONS
# =========================================================
def get_watchlist():
    supabase = get_supabase()
    try:
        res = supabase.table("watchlist").select("symbol").order("added_at").execute()
        return [row["symbol"] for row in res.data] if res.data else ["BTC", "ETH", "SOL", "XRP", "ADA"]
    except:
        return ["BTC", "ETH", "SOL", "XRP", "ADA"]

def add_coin(symbol):
    supabase = get_supabase()
    try:
        supabase.table("watchlist").insert({"symbol": symbol.upper()}).execute()
        return True
    except:
        return False

def remove_coin(symbol):
    supabase = get_supabase()
    try:
        res = supabase.table("watchlist").delete().eq("symbol", symbol.upper()).execute()
        return len(res.data) > 0
    except:
        return False

def save_signal(data):
    supabase = get_supabase()
    try:
        symbol = data.get("symbol")
        signal = data.get("signal")
        five_min_ago = (datetime.now() - timedelta(minutes=5)).isoformat()
        res = supabase.table("signal_history").select("id").eq("symbol", symbol).eq("signal", signal).gte("timestamp", five_min_ago).execute()
        if res.data and len(res.data) > 0:
            return False
        data["timestamp"] = datetime.now().isoformat()
        supabase.table("signal_history").insert(data).execute()
        return True
    except:
        return False

def get_signal_history(limit=100):
    supabase = get_supabase()
    try:
        res = supabase.table("signal_history").select("*").order("timestamp", desc=True).limit(limit).execute()
        return res.data
    except:
        return []

def update_performance(stats):
    supabase = get_supabase()
    try:
        supabase.table("performance").upsert({"key": "performance_stats", "value": stats, "updated_at": datetime.now().isoformat()}, on_conflict="key").execute()
        return True
    except:
        return False

def get_performance():
    supabase = get_supabase()
    default = {"total_signals": 0, "wins": 0, "losses": 0, "total_profit": 0, "win_rate": 0}
    try:
        res = supabase.table("performance").select("value").eq("key", "performance_stats").execute()
        if res.data and len(res.data) > 0:
            return res.data[0]["value"]
        return default
    except:
        return default

# =========================================================
# POSITIONS DATABASE FUNCTIONS
# =========================================================
def save_position_to_db(symbol, entry, sl, tp, position_size=1):
    supabase = get_supabase()
    try:
        data = {
            "symbol": symbol,
            "entry_price": float(entry),
            "current_price": float(entry),
            "stop_loss": float(sl),
            "take_profit": float(tp),
            "highest_price": float(entry),
            "position_size": float(position_size),
            "entry_time": datetime.now().isoformat(),
            "status": "OPEN",
            "pnl": 0,
            "pnl_percent": 0
        }
        result = supabase.table("positions").insert(data).execute()
        if result.data and len(result.data) > 0:
            return result.data[0]
        return None
    except:
        return None

def get_open_positions_from_db():
    supabase = get_supabase()
    try:
        res = supabase.table("positions").select("*").eq("status", "OPEN").order("entry_time", desc=True).execute()
        return res.data if res.data else []
    except:
        return []

def get_closed_positions_from_db(limit=100):
    supabase = get_supabase()
    try:
        res = supabase.table("positions").select("*").eq("status", "CLOSED").order("exit_time", desc=True).limit(limit).execute()
        return res.data if res.data else []
    except:
        return []

def update_position_in_db(position_id, updates):
    supabase = get_supabase()
    try:
        updates["updated_at"] = datetime.now().isoformat()
        supabase.table("positions").update(updates).eq("id", position_id).execute()
        return True
    except:
        return False

def close_position_in_db(position_id, exit_price, exit_reason, pnl, pnl_percent):
    supabase = get_supabase()
    try:
        updates = {
            "status": "CLOSED",
            "current_price": float(exit_price),
            "exit_price": float(exit_price),
            "exit_reason": exit_reason,
            "pnl": float(pnl),
            "pnl_percent": float(pnl_percent),
            "exit_time": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }
        supabase.table("positions").update(updates).eq("id", position_id).execute()
        return True
    except:
        return False

def get_portfolio_summary():
    supabase = get_supabase()
    try:
        open_positions = get_open_positions_from_db()
        closed_positions = get_closed_positions_from_db(limit=100)
        total_equity = sum([p.get("current_price", 0) * p.get("position_size", 1) for p in open_positions])
        unrealized_pnl = sum([p.get("pnl", 0) for p in open_positions])
        realized_pnl = sum([p.get("pnl", 0) for p in closed_positions])
        total_pnl = unrealized_pnl + realized_pnl
        total_closed = len(closed_positions)
        wins = len([p for p in closed_positions if p.get("pnl", 0) > 0])
        win_rate = (wins / total_closed * 100) if total_closed > 0 else 0
        return {
            "open_positions": open_positions,
            "closed_positions": closed_positions,
            "total_open": len(open_positions),
            "total_closed": total_closed,
            "total_equity": total_equity,
            "wins": wins,
            "losses": total_closed - wins,
            "win_rate": win_rate,
            "unrealized_pnl": unrealized_pnl,
            "realized_pnl": realized_pnl,
            "total_pnl": total_pnl
        }
    except:
        return {"open_positions": [], "closed_positions": [], "total_open": 0, "total_closed": 0, "total_equity": 0, "wins": 0, "losses": 0, "win_rate": 0, "unrealized_pnl": 0, "realized_pnl": 0, "total_pnl": 0}

# =========================================================
# TELEGRAM FUNCTIONS
# =========================================================
if "sent_signals" not in st.session_state:
    st.session_state.sent_signals = {}
if "last_telegram_time" not in st.session_state:
    st.session_state.last_telegram_time = {}

def send_telegram_once(symbol, signal, result):
    now = datetime.now()
    last_time = st.session_state.last_telegram_time.get(symbol)
    if last_time is not None and (now - last_time).seconds / 60 < 10:
        return False
    signal_key = f"{symbol}_{signal}_{now.strftime('%Y%m%d_%H%M')}"
    if signal_key in st.session_state.sent_signals:
        return False
    try:
        bot_token = st.secrets.get("TELEGRAM_BOT_TOKEN", "")
        chat_id = st.secrets.get("TELEGRAM_CHAT_ID", "")
        if bot_token and chat_id:
            msg = f"⚡ BOTTOM MOMENTUM SIGNAL!\n\nCoin: {symbol}\nSignal: {signal}\nTime: {now.strftime('%Y-%m-%d %H:%M:%S')}"
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            response = requests.post(url, json={"chat_id": chat_id, "text": msg}, timeout=10)
            if response.status_code == 200:
                st.session_state.sent_signals[signal_key] = True
                st.session_state.last_telegram_time[symbol] = now
                return True
    except:
        pass
    return False

def send_telegram_test(message):
    try:
        bot_token = st.secrets.get("TELEGRAM_BOT_TOKEN", "")
        chat_id = st.secrets.get("TELEGRAM_CHAT_ID", "")
        if bot_token and chat_id:
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            requests.post(url, json={"chat_id": chat_id, "text": message}, timeout=10)
            return True
    except:
        pass
    return False

# =========================================================
# CHECK EXIT CONDITIONS
# =========================================================
def check_exit_conditions(position, df, highest_price=None):
    if df is None or len(df) < 10:
        return None, None
    price = df["Close"].iloc[-1]
    macd_line, signal_line, histogram = MACD(df)
    stoch_k, stoch_d, _ = StochasticRSI(df)
    if position.get("tp") and price >= position["tp"]:
        return "✅ TP HIT", price
    if position.get("sl") and price <= position["sl"]:
        return "❌ SL HIT", price
    if highest_price and price <= highest_price * 0.95:
        return "📉 TRAILING SL", price
    if len(macd_line) > 1 and len(stoch_k) > 1:
        macd_death = (macd_line.iloc[-2] > signal_line.iloc[-2]) and (macd_line.iloc[-1] < signal_line.iloc[-1])
        stoch_death = (stoch_k.iloc[-2] > stoch_d.iloc[-2]) and (stoch_k.iloc[-1] < stoch_d.iloc[-1])
        if macd_death and stoch_death:
            return "🔄 REVERSAL EXIT", price
    entry_time = position.get("entry_time")
    if entry_time:
        if isinstance(entry_time, str):
            try:
                entry_time = datetime.fromisoformat(entry_time.replace('Z', '+00:00'))
            except:
                try:
                    entry_time = datetime.strptime(entry_time, '%Y-%m-%d %H:%M:%S.%f')
                except:
                    entry_time = None
        if entry_time and isinstance(entry_time, datetime) and (datetime.now() - entry_time).days > 7:
            return "⏰ TIME EXIT (7 days)", price
    return None, price

# =========================================================
# FORMAT PRICE
# =========================================================
def format_price(value):
    if pd.isna(value) or value is None:
        return "-"
    if value >= 1000:
        return f"$ {value:,.2f}"
    elif value >= 100:
        return f"$ {value:,.3f}"
    elif value >= 1:
        return f"$ {value:,.4f}"
    elif value >= 0.01:
        return f"$ {value:,.6f}"
    else:
        return f"$ {value:,.8f}"

# =========================================================
# CREATE CHART
# =========================================================
def create_chart(df, symbol, timeframe):
    if df is None or len(df) < 30:
        return None
    macd_line, signal_line, histogram = MACD(df)
    stoch_k, stoch_d, rsi = StochasticRSI(df)
    ema20 = EMA(df, 20)
    ema50 = EMA(df, 50)
    ema100 = EMA(df, 100)
    
    fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.03,
                        row_heights=[0.35, 0.2, 0.25, 0.2],
                        subplot_titles=(f"Price - {symbol} {timeframe}", "RSI", "MACD", "Stochastic RSI"))
    
    fig.add_trace(go.Candlestick(x=df["Time"], open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
                                 increasing_line_color="#00ff88", decreasing_line_color="#ff3b5c", name="Price"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df["Time"], y=ema20, line=dict(color="#00a2ff", width=1.5), name="EMA20"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df["Time"], y=ema50, line=dict(color="#ffaa00", width=1.5, dash="dash"), name="EMA50"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df["Time"], y=ema100, line=dict(color="#ff00ff", width=1.5, dash="dot"), name="EMA100"), row=1, col=1)
    
    fig.add_trace(go.Scatter(x=df["Time"], y=rsi, line=dict(color="#a855f7", width=2), name="RSI"), row=2, col=1)
    fig.add_hline(y=70, line_dash="dash", line_color="red", row=2, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="green", row=2, col=1)
    
    fig.add_trace(go.Scatter(x=df["Time"], y=macd_line, line=dict(color="#00a2ff", width=1.5), name="DIF (MACD)"), row=3, col=1)
    fig.add_trace(go.Scatter(x=df["Time"], y=signal_line, line=dict(color="#ff00ff", width=1.5), name="DEA (Signal)"), row=3, col=1)
    colors = ["#00ff88" if h >= 0 else "#ff3b5c" for h in histogram]
    fig.add_trace(go.Bar(x=df["Time"], y=histogram, marker_color=colors, opacity=0.5, name="Histogram"), row=3, col=1)
    fig.add_hline(y=0, line_dash="solid", line_color="rgba(255,255,255,0.2)", row=3, col=1)
    
    fig.add_trace(go.Scatter(x=df["Time"], y=stoch_k, line=dict(color="#ffaa00", width=1.5), name="Stoch K"), row=4, col=1)
    fig.add_trace(go.Scatter(x=df["Time"], y=stoch_d, line=dict(color="#ff00ff", width=1.5, dash="dash"), name="Stoch D"), row=4, col=1)
    fig.add_hline(y=80, line_dash="dash", line_color="red", row=4, col=1)
    fig.add_hline(y=20, line_dash="dash", line_color="green", row=4, col=1)
    
    fig.update_layout(template="plotly_dark", height=900,
                      title=dict(text=f"<b>{symbol} - {timeframe} Analysis (Bottom Momentum)</b>", font=dict(color="#f1f5f9", size=20), x=0.5, xanchor="center"),
                      hovermode="x unified", dragmode="pan", xaxis_rangeslider_visible=False,
                      paper_bgcolor="#0a0a1a", plot_bgcolor="#0a0a1a", font=dict(color="#94a3b8"),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(size=10)),
                      margin=dict(l=10, r=10, t=50, b=10))
    fig.update_xaxes(gridcolor="rgba(255,255,255,0.03)")
    fig.update_yaxes(gridcolor="rgba(255,255,255,0.03)")
    return fig

# =========================================================
# INITIALIZATION
# =========================================================
if "watchlist" not in st.session_state:
    st.session_state.watchlist = get_watchlist()
if "pending_signal" not in st.session_state:
    st.session_state.pending_signal = {}
if "signal_history" not in st.session_state:
    st.session_state.signal_history = get_signal_history()
if "performance_stats" not in st.session_state:
    st.session_state.performance_stats = get_performance()
if "positions" not in st.session_state:
    st.session_state.positions = {}
if "last_refresh" not in st.session_state:
    st.session_state.last_refresh = datetime.now()
if "last_scan" not in st.session_state:
    st.session_state.last_scan = datetime.now()
if "scan_results" not in st.session_state:
    st.session_state.scan_results = []

if not st.session_state.positions:
    try:
        db_positions = get_open_positions_from_db()
        for pos in db_positions:
            st.session_state.positions[pos["symbol"]] = {
                "entry": pos["entry_price"],
                "sl": pos["stop_loss"],
                "tp": pos["take_profit"],
                "entry_time": datetime.fromisoformat(pos["entry_time"]) if pos.get("entry_time") else datetime.now(),
                "highest_price": pos.get("highest_price", pos["entry_price"]),
                "id": pos["id"],
                "position_size": pos.get("position_size", 1)
            }
    except:
        pass

# =========================================================
# SIDEBAR
# =========================================================
st.title("📊 Bottom Momentum Scanner PRO")
st.caption("Multi Timeframe: 15M | 1H | 4H | Bottom Detection + Momentum Score | Buy from Bottom")

with st.sidebar:
    st.header("⚙️ Settings")
    st.subheader("📋 Watchlist")
    st.success("☁️ Supabase Connected")
    
    col_add1, col_add2 = st.columns([3, 1])
    with col_add1:
        new_coin = st.text_input("Add Coin", placeholder="BTC", label_visibility="collapsed")
    with col_add2:
        if st.button("➕", use_container_width=True):
            if new_coin:
                coin = new_coin.upper().strip()
                if coin not in st.session_state.watchlist:
                    if add_coin(coin):
                        st.session_state.watchlist.append(coin)
                        st.rerun()
                    else:
                        st.error("❌ Gagal tambah coin!")
                else:
                    st.warning(f"⚠️ {coin} already exists!")
    
    st.markdown("**Your Coins:**")
    cols = st.columns(3)
    for idx, coin in enumerate(st.session_state.watchlist):
        col_idx = idx % 3
        with cols[col_idx]:
            if st.button(f"✕ {coin}", key=f"del_{coin}", use_container_width=True):
                if remove_coin(coin):
                    st.session_state.watchlist.remove(coin)
                    st.rerun()
                else:
                    st.error(f"❌ Gagal hapus {coin}!")
    
    st.divider()
    st.subheader("📊 Scanner Settings")
    refresh = st.slider("🔄 Refresh (detik)", 15, 120, 30)
    hold_minutes = st.slider("Hold Signal (menit)", 5, 30, 15, key="hold_minutes")
    
    st.divider()
    st.subheader("📱 Telegram Alert")
    if st.button("🚀 Test Telegram", use_container_width=True):
        send_telegram_test("🚀 Telegram Connected! Bottom Momentum Scanner Aktif.")
        st.success("✅ Pesan test terkirim!")
    
    st.divider()
    st.subheader("📊 Status")
    st.metric("Total Coins", len(st.session_state.watchlist))
    stats = get_performance()
    st.metric("Total Signals", stats.get('total_signals', 0))
    st.metric("Open Positions", len(st.session_state.positions))
    st.caption(f"🔄 Auto Refresh: {refresh} detik")
    st.caption("📌 Mode: Bottom Momentum Scanner")

# =========================================================
# AUTO REFRESH
# =========================================================
st_autorefresh(interval=refresh * 1000, key="refresh")

# =========================================================
# MAIN TABS
# =========================================================
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📊 Scanner", "📈 Chart Analysis", "📋 Positions", "📜 History", "📊 Performance"
])

# =========================================================
# TAB 1: SCANNER
# =========================================================
with tab1:
    st.subheader("📊 Bottom Momentum Scanner")
    st.caption("Mencari koin di titik terendah yang sudah mulai momentum - BELI DARI BAWAH")
    
    now = datetime.now()
    time_since_scan = (now - st.session_state.get("last_scan", now)).seconds
    
    if time_since_scan > 30 or "last_scan" not in st.session_state:
        st.session_state.last_scan = now
        all_signals = []
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        current_time = datetime.now()
        expired = []
        for symbol, data in st.session_state.pending_signal.items():
            if (current_time - data["time"]).seconds / 60 > hold_minutes:
                expired.append(symbol)
        for sym in expired:
            if sym in st.session_state.pending_signal:
                del st.session_state.pending_signal[sym]
        
        coins_to_scan = st.session_state.watchlist[:50]
        total_coins = len(coins_to_scan)
        
        for idx, symbol in enumerate(coins_to_scan):
            try:
                progress_bar.progress((idx + 1) / total_coins if total_coins > 0 else 0)
                status_text.text(f"🔄 Scanning {symbol}... ({idx+1}/{total_coins})")
                
                result = analyze_mtf_macd_stoch_spot(symbol, ["15m", "1h", "4h"])
                
                if result:
                    df_1h = get_data_safe(symbol, "1h", min_candles=30)
                    bm = detect_bottom(df_1h) if df_1h is not None else {"score": 0, "status": "⚪ N/A"}
                    
                    signal_data = {
                        "Coin": symbol,
                        "Signal": result["main_signal"],
                        "Strength": "⭐" * result.get("main_strength", 1),
                        "Bottom Score": f"{bm['score']}/10",
                        "Bottom Status": bm["status"],
                        "Avg BM": f"{result.get('avg_bottom_momentum', 0):.1f}",
                    }
                    
                    for tf in ["15m", "1h", "4h"]:
                        if tf in result["timeframes"]:
                            res = result["timeframes"][tf]
                            signal_data[f"{tf.upper()} Action"] = res["action"]
                            signal_data[f"{tf.upper()} MACD"] = f"{res['macd']['dif']:.4f}"
                            signal_data[f"{tf.upper()} Hist"] = f"{res['macd']['histogram']:.4f}"
                            signal_data[f"{tf.upper()} Stoch K"] = f"{res['stoch']['k']:.1f}"
                            signal_data[f"{tf.upper()} Stoch D"] = f"{res['stoch']['d']:.1f}"
                            signal_data[f"{tf.upper()} RSI"] = f"{res['rsi']:.1f}"
                    
                    all_signals.append(signal_data)
                    
                    # BUY ENTRY
                    if result["main_strength"] >= 2 and "BUY" in result["main_signal"]:
                        existing_positions = get_open_positions_from_db()
                        existing_symbols = [p["symbol"] for p in existing_positions]
                        
                        if symbol not in st.session_state.pending_signal and symbol not in existing_symbols:
                            df_5m = get_data_safe(symbol, "5m", min_candles=20)
                            if df_5m is not None:
                                price = df_5m["Close"].iloc[-1]
                                atr = AverageTrueRange(df_5m["High"], df_5m["Low"], df_5m["Close"], window=14).average_true_range().iloc[-1]
                                if pd.isna(atr) or atr == 0:
                                    atr = price * 0.01
                                entry = price
                                sl = entry - atr * 3
                                tp = entry + atr * 7
                                
                                st.session_state.pending_signal[symbol] = {
                                    "signal": result["main_signal"],
                                    "time": datetime.now(),
                                    "entry": entry,
                                    "sl": sl,
                                    "tp": tp,
                                    "timeframe": "5m"
                                }
                                
                                saved_pos = save_position_to_db(symbol, entry, sl, tp, 1)
                                if saved_pos:
                                    st.session_state.positions[symbol] = {
                                        "entry": entry,
                                        "sl": sl,
                                        "tp": tp,
                                        "entry_time": datetime.now(),
                                        "highest_price": entry,
                                        "id": saved_pos["id"],
                                        "position_size": 1
                                    }
                                    st.success(f"✅ Position opened for {symbol} at ${entry:.4f}")
                                    
                                    sent = send_telegram_once(symbol, result["main_signal"], result)
                                    if sent:
                                        save_signal({
                                            'symbol': symbol,
                                            'signal': result["main_signal"],
                                            'entry_price': entry,
                                            'stop_loss': sl,
                                            'take_profit': tp,
                                            'timestamp': datetime.now().isoformat()
                                        })
                                        stats = get_performance()
                                        stats['total_signals'] = stats.get('total_signals', 0) + 1
                                        update_performance(stats)
                                else:
                                    if symbol in st.session_state.pending_signal:
                                        del st.session_state.pending_signal[symbol]
                                    st.error(f"❌ Gagal membuka posisi untuk {symbol}")
                    
                    elif "EXIT" in result["main_signal"] and symbol in st.session_state.positions:
                        sent = send_telegram_once(symbol, result["main_signal"], result)
                        if sent:
                            save_signal({
                                'symbol': symbol,
                                'signal': result["main_signal"],
                                'timestamp': datetime.now().isoformat()
                            })
                            
            except Exception as e:
                print(f"Error scanning {symbol}: {e}")
                continue
        
        progress_bar.empty()
        status_text.empty()
        st.session_state.scan_results = all_signals
    else:
        all_signals = st.session_state.get("scan_results", [])
    
    if all_signals:
        df_signals = pd.DataFrame(all_signals)
        st.dataframe(df_signals, use_container_width=True, hide_index=True)
        
        # ========== TOP BOTTOM MOMENTUM PICKS ==========
        st.divider()
        st.subheader("🏆 Best Bottom Momentum Picks")
        
        df_filtered = df_signals[df_signals["Bottom Score"].str.replace("/10", "").astype(float) >= 4]
        if not df_filtered.empty:
            st.success(f"🔥 Found {len(df_filtered)} bottom opportunities!")
            
            for _, row in df_filtered.iterrows():
                bottom_score = float(row["Bottom Score"].replace("/10", ""))
                if bottom_score >= 7:
                    st.markdown(f"""
                    <div style="background: linear-gradient(135deg, rgba(0,255,136,0.25), rgba(0,255,136,0.05)); 
                                border: 2px solid #00ff88; border-radius: 12px; padding: 16px; margin: 8px 0;">
                        <b style="color: #00ff88; font-size: 20px;">🚀 {row['Coin']}</b>
                        <span style="color: #00ff88; font-size: 18px;">{row['Signal']}</span><br>
                        Bottom Score: <b style="color: #00ff88;">{row['Bottom Score']}</b> | 
                        Status: {row['Bottom Status']}
                    </div>
                    """, unsafe_allow_html=True)
                elif bottom_score >= 5:
                    st.markdown(f"""
                    <div style="background: linear-gradient(135deg, rgba(255,170,0,0.2), rgba(255,170,0,0.05)); 
                                border: 1px solid #ffaa00; border-radius: 12px; padding: 14px; margin: 6px 0;">
                        <b style="color: #ffaa00; font-size: 18px;">🟢 {row['Coin']}</b>
                        <span style="color: #ffaa00;">{row['Signal']}</span><br>
                        Bottom Score: <b style="color: #ffaa00;">{row['Bottom Score']}</b>
                    </div>
                    """, unsafe_allow_html=True)
            
            best = df_filtered.iloc[0]
            st.success(f"🏆 **BEST BOTTOM PICK: {best['Coin']}** | Bottom Score: {best['Bottom Score']}")
        else:
            st.info("ℹ️ No bottom opportunities found yet")
        
        buy_signals = [s for s in all_signals if "BUY" in s["Signal"]]
        if buy_signals:
            best = buy_signals[0]
            st.info(f"📈 Best Buy Signal: **{best['Coin']}** | {best['Signal']}")
    else:
        st.info("ℹ️ Tidak ada data")
    
    if st.session_state.pending_signal:
        st.divider()
        st.subheader("⏳ Pending Signals - Entry, TP, SL")
        st.caption("Sinyal BUY yang masih aktif")
        
        pending_data = []
        for symbol, data in st.session_state.pending_signal.items():
            elapsed = (datetime.now() - data["time"]).seconds / 60
            remaining = max(0, hold_minutes - elapsed)
            entry = data.get("entry")
            sl = data.get("sl")
            tp = data.get("tp")
            rr = (tp - entry) / (entry - sl) if entry and sl and tp and (entry - sl) != 0 else 0
            
            pending_data.append({
                "Coin": symbol,
                "Signal": data["signal"],
                "Entry": format_price(entry),
                "TP": format_price(tp),
                "SL": format_price(sl),
                "RR": f"{rr:.2f}",
                "Time Left": f"{remaining:.0f}m",
            })
        
        if pending_data:
            df_pending = pd.DataFrame(pending_data)
            st.dataframe(df_pending, use_container_width=True, hide_index=True)

# =========================================================
# TAB 2: CHART ANALYSIS
# =========================================================
with tab2:
    st.subheader("📈 Chart Analysis - Bottom Momentum")
    chart_coin = st.selectbox("Select Coin", st.session_state.watchlist, key="chart_select")
    chart_tf = st.selectbox("Timeframe", ["15m", "1h", "4h"], index=1)
    
    if chart_coin:
        df = get_data_safe(chart_coin, chart_tf, min_candles=50)
        if df is not None:
            result = analyze_macd_stoch_spot(df, chart_tf)
            if result:
                col1, col2, col3, col4 = st.columns(4)
                if "BUY" in result["action"]:
                    signal_html = f'<div class="signal-buy">{result["action"]}</div>'
                elif "EXIT" in result["action"]:
                    signal_html = f'<div class="signal-exit">{result["action"]}</div>'
                else:
                    signal_html = f'<div class="signal-hold">{result["action"]}</div>'
                col1.markdown(signal_html, unsafe_allow_html=True)
                col2.metric("MACD DIF", f"{result['macd']['dif']:.4f}")
                col3.metric("MACD DEA", f"{result['macd']['dea']:.4f}")
                col4.metric("Histogram", f"{result['macd']['histogram']:.4f}")
                
                col1, col2, col3, col4 = st.columns(4)
                bm = result.get("bottom_momentum", {})
                col1.metric("Bottom Score", f"{bm.get('bottom_score', 0):.1f}/10")
                col2.metric("Momentum Score", f"{bm.get('momentum_score', 0):.1f}/10")
                col3.metric("Total Score", f"{bm.get('total_score', 0):.1f}/20")
                col4.metric("RSI", f"{result['rsi']:.1f}")
                
                with st.expander("📋 Signal Details", expanded=True):
                    if result["reasons"]:
                        for reason in result["reasons"]:
                            st.write(f"• {reason}")
                    
                    if bm.get("status"):
                        st.write(f"**Bottom Momentum Status:** {bm['status']}")
                    
                    st.write(f"**Trend:** {'🟢 Strong Bullish (EMA100+)' if result['strong_bullish'] else '🟢 Bullish' if result['bullish_trend'] else '🔴 Bearish' if result['bearish_trend'] else '🟡 Sideways'}")
                    st.write(f"**EMA20:** {result['ema20']:.4f}")
                    st.write(f"**EMA50:** {result['ema50']:.4f}")
                    st.write(f"**EMA100:** {result['ema100']:.4f}")
                    st.write(f"**Buy Score:** {result['score']['buy']:.1f} | **Exit Score:** {result['score']['exit']:.1f}")
                
                fig = create_chart(df, chart_coin, chart_tf)
                if fig:
                    st.plotly_chart(fig, use_container_width=True)
        else:
            st.error(f"❌ Tidak bisa mendapatkan data untuk {chart_coin}")

# =========================================================
# TAB 3: POSITIONS
# =========================================================
with tab3:
    st.subheader("📋 Open Positions - SPOT")
    
    now = datetime.now()
    time_since_refresh = (now - st.session_state.get("last_refresh", now)).seconds
    
    if time_since_refresh > 30 or not st.session_state.positions:
        st.session_state.last_refresh = now
        updated_positions = {}
        positions_to_remove = []
        
        for symbol, pos in st.session_state.positions.items():
            try:
                df = get_data_safe(symbol, "15m", min_candles=20)
                if df is None or df.empty:
                    updated_positions[symbol] = pos
                    continue
                
                current_price = df["Close"].iloc[-1]
                highest = pos.get("highest_price", pos["entry"])
                if current_price > highest:
                    highest = current_price
                
                entry_time = pos.get("entry_time")
                if isinstance(entry_time, str):
                    try:
                        entry_time = datetime.fromisoformat(entry_time.replace('Z', '+00:00'))
                    except:
                        try:
                            entry_time = datetime.strptime(entry_time, '%Y-%m-%d %H:%M:%S.%f')
                        except:
                            entry_time = datetime.now()
                elif entry_time is None:
                    entry_time = datetime.now()
                
                position_for_exit = {"entry": pos["entry"], "sl": pos.get("sl"), "tp": pos.get("tp"), "entry_time": entry_time}
                exit_signal, exit_price = check_exit_conditions(position_for_exit, df, highest)
                
                pos["current_price"] = current_price
                pos["highest_price"] = highest
                
                if exit_signal:
                    pnl = (exit_price - pos["entry"]) * pos.get("position_size", 1)
                    pnl_percent = (exit_price / pos["entry"] - 1) * 100
                    position_id = pos.get("id")
                    if position_id:
                        close_position_in_db(position_id, exit_price, exit_signal, pnl, pnl_percent)
                    save_signal({
                        'symbol': symbol,
                        'signal': f"EXIT - {exit_signal}",
                        'exit_price': exit_price,
                        'profit_pct': pnl_percent,
                        'timestamp': datetime.now().isoformat()
                    })
                    positions_to_remove.append(symbol)
                    st.success(f"✅ {symbol} closed: {exit_signal} at ${exit_price:.4f}")
                else:
                    updated_positions[symbol] = pos
            except:
                updated_positions[symbol] = pos
        
        for symbol in positions_to_remove:
            if symbol in st.session_state.positions:
                del st.session_state.positions[symbol]
        st.session_state.positions = updated_positions
    
    if st.session_state.positions:
        pos_data = []
        for symbol, pos in st.session_state.positions.items():
            try:
                current_price = pos.get("current_price", pos["entry"])
                pnl_percent = (current_price / pos['entry'] - 1) * 100
                pnl = (current_price - pos['entry']) * pos.get("position_size", 1)
                pnl_color = "🟢" if pnl > 0 else "🔴" if pnl < 0 else "🟡"
                entry_time = pos.get("entry_time")
                entry_time_str = entry_time.strftime("%Y-%m-%d %H:%M") if isinstance(entry_time, datetime) else str(entry_time)[:16] if entry_time else ""
                
                pos_data.append({
                    "Coin": symbol,
                    "Entry": format_price(pos.get("entry")),
                    "Current": format_price(current_price),
                    "SL": format_price(pos.get("sl")),
                    "TP": format_price(pos.get("tp")),
                    "Size": f"{pos.get('position_size', 1):.4f}",
                    "PNL": f"{pnl_color} ${pnl:.2f} ({pnl_percent:.2f}%)",
                    "Entry Time": entry_time_str
                })
            except:
                continue
        
        if pos_data:
            df_pos = pd.DataFrame(pos_data)
            st.dataframe(df_pos, use_container_width=True, hide_index=True)
            
            st.divider()
            st.subheader("📊 Portfolio Summary")
            total_positions = len(pos_data)
            total_profit = 0
            winning = 0
            losing = 0
            for p in pos_data:
                try:
                    profit = float(p["PNL"].split("$")[1].split(" ")[0])
                    total_profit += profit
                    if profit > 0:
                        winning += 1
                    elif profit < 0:
                        losing += 1
                except:
                    pass
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Total Positions", total_positions)
            col2.metric("Winning", winning)
            col3.metric("Losing", losing)
            col4.metric("Total PNL", f"${total_profit:.2f}")
    else:
        st.info("📭 Tidak ada posisi terbuka")
    
    st.divider()
    st.subheader("📊 Closed Positions")
    closed_positions = get_closed_positions_from_db(limit=100)
    
    if closed_positions:
        closed_data = []
        total_profit_closed = 0
        wins = 0
        losses = 0
        
        for pos in closed_positions:
            try:
                pnl = pos.get("pnl", 0)
                pnl_percent = pos.get("pnl_percent", 0)
                pnl_color = "🟢" if pnl > 0 else "🔴" if pnl < 0 else "🟡"
                if pnl > 0:
                    wins += 1
                elif pnl < 0:
                    losses += 1
                total_profit_closed += pnl
                
                exit_reason = pos.get("exit_reason", "UNKNOWN")
                exit_emoji = "✅" if "TP" in exit_reason else "❌" if "SL" in exit_reason else "🔄"
                
                entry_time = pos.get("entry_time", "")[:16] if pos.get("entry_time") else ""
                exit_time = pos.get("exit_time", "")[:16] if pos.get("exit_time") else ""
                
                closed_data.append({
                    "Coin": pos["symbol"],
                    "Entry": format_price(pos["entry_price"]),
                    "Exit": format_price(pos.get("exit_price", pos["entry_price"])),
                    "PNL": f"{pnl_color} ${pnl:.2f} ({pnl_percent:.2f}%)",
                    "Exit Reason": f"{exit_emoji} {exit_reason}",
                    "Exit Time": exit_time
                })
            except:
                continue
        
        if closed_data:
            df_closed = pd.DataFrame(closed_data)
            st.dataframe(df_closed, use_container_width=True, hide_index=True)
            
            st.divider()
            col1, col2, col3, col4, col5 = st.columns(5)
            total_closed = len(closed_data)
            win_rate = (wins / total_closed * 100) if total_closed > 0 else 0
            col1.metric("Total Trades", total_closed)
            col2.metric("Wins", wins)
            col3.metric("Losses", losses)
            col4.metric("Win Rate", f"{win_rate:.1f}%")
            col5.metric("Total PNL", f"${total_profit_closed:.2f}")
    else:
        st.info("Belum ada posisi yang ditutup")

# =========================================================
# TAB 4: HISTORY
# =========================================================
with tab4:
    st.subheader("📜 Signal History")
    history = get_signal_history(limit=200)
    if history:
        df_history = pd.DataFrame(history)
        if 'id' in df_history.columns:
            df_history = df_history.drop('id', axis=1)
        st.dataframe(df_history, use_container_width=True, hide_index=True)
        csv = df_history.to_csv(index=False)
        st.download_button(label="📥 Download CSV", data=csv, file_name=f"history_{datetime.now().strftime('%Y%m%d')}.csv", mime="text/csv")
    else:
        st.info("Belum ada sinyal")

# =========================================================
# TAB 5: PERFORMANCE
# =========================================================
with tab5:
    st.subheader("📊 Performance Statistics")
    stats = get_performance()
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Signals", stats.get("total_signals", 0))
    col2.metric("Wins", stats.get("wins", 0))
    col3.metric("Losses", stats.get("losses", 0))
    col4.metric("Win Rate", f"{stats.get('win_rate', 0):.1f}%")
    
    st.divider()
    st.subheader("📊 Bottom Momentum Statistics")
    history = get_signal_history(limit=200)
    if history:
        bottom_signals = len([h for h in history if "BOTTOM" in h.get("signal", "")])
        total_signals = len(history)
        bottom_rate = (bottom_signals / total_signals * 100) if total_signals > 0 else 0
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Signals", total_signals)
        col2.metric("Bottom Signals", bottom_signals)
        col3.metric("Bottom Rate", f"{bottom_rate:.1f}%")
    
    st.divider()
    st.subheader("📈 Trading Rules Summary")
    rules = {
        "🔥 STRONG BOTTOM MOMENTUM": "Bottom Score ≥ 5, Momentum Score ≥ 5 → BELI!",
        "🟢 BOTTOM MOMENTUM": "Bottom Score ≥ 4, Momentum Score ≥ 4 → AKUMULASI",
        "🟡 POTENTIAL BOTTOM": "Bottom Score ≥ 3, Momentum Score ≥ 3 → PANTAU",
        "🔴 EXIT": "Stoch RSI >85, Histogram mengecil, MACD death cross",
        "⛔ STOP LOSS": "Harga turun 3x ATR dari entry"
    }
    for rule, desc in rules.items():
        st.write(f"**{rule}:** {desc}")

# =========================================================
# FOOTER
# =========================================================
st.divider()
st.caption(f"""
🔄 Data dari Yahoo Finance | Timeframe: 15M, 1H, 4H  
📊 Indikator: MACD + Stoch RSI + EMA20/50/100 + Bottom Detection + Momentum Score  
💾 Database: Supabase PostgreSQL  
📌 Mode: Bottom Momentum Scanner - BELI DARI BAWAH
""")
