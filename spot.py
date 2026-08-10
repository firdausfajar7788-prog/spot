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
    page_title="🚀 Momentum Scanner PRO - SPOT",
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
    .momentum-strong {
        background: linear-gradient(135deg, rgba(255,68,68,0.2), rgba(255,68,68,0.05));
        border: 1px solid #ff4444;
        border-radius: 12px;
        padding: 8px 16px;
        color: #ff4444;
        font-weight: 700;
        font-size: 14px;
    }
    .momentum-early {
        background: linear-gradient(135deg, rgba(255,170,0,0.2), rgba(255,170,0,0.05));
        border: 1px solid #ffaa00;
        border-radius: 12px;
        padding: 8px 16px;
        color: #ffaa00;
        font-weight: 700;
        font-size: 14px;
    }
    .momentum-developing {
        background: linear-gradient(135deg, rgba(0,200,255,0.2), rgba(0,200,255,0.05));
        border: 1px solid #00c8ff;
        border-radius: 12px;
        padding: 8px 16px;
        color: #00c8ff;
        font-weight: 700;
        font-size: 14px;
    }
    .momentum-weak {
        background: linear-gradient(135deg, rgba(150,150,150,0.2), rgba(150,150,150,0.05));
        border: 1px solid #969696;
        border-radius: 12px;
        padding: 8px 16px;
        color: #969696;
        font-weight: 700;
        font-size: 14px;
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
# DATABASE FUNCTIONS
# =========================================================
def get_watchlist():
    supabase = get_supabase()
    try:
        res = supabase.table("watchlist").select("symbol").order("added_at").execute()
        return [row["symbol"] for row in res.data] if res.data else ["BTC", "ETH", "SOL"]
    except:
        return ["BTC", "ETH", "SOL"]

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
        res = supabase.table("signal_history")\
            .select("id")\
            .eq("symbol", symbol)\
            .eq("signal", signal)\
            .gte("timestamp", five_min_ago)\
            .execute()
        
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
        supabase.table("performance").upsert(
            {"key": "performance_stats", "value": stats, "updated_at": datetime.now().isoformat()},
            on_conflict="key"
        ).execute()
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
    except Exception as e:
        st.error(f"❌ Database error: {e}")
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
        unrealized_pnl_percent = sum([p.get("pnl_percent", 0) for p in open_positions])
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
            "unrealized_pnl_percent": unrealized_pnl_percent,
            "realized_pnl": realized_pnl,
            "total_pnl": total_pnl
        }
    except Exception as e:
        return {
            "open_positions": [],
            "closed_positions": [],
            "total_open": 0,
            "total_closed": 0,
            "total_equity": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0,
            "unrealized_pnl": 0,
            "unrealized_pnl_percent": 0,
            "realized_pnl": 0,
            "total_pnl": 0
        }

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
    if last_time is not None:
        diff = (now - last_time).seconds / 60
        if diff < 10:
            return False

    signal_key = f"{symbol}_{signal}_{now.strftime('%Y%m%d_%H%M')}"
    if signal_key in st.session_state.sent_signals:
        return False

    try:
        bot_token = st.secrets.get("TELEGRAM_BOT_TOKEN", "")
        chat_id = st.secrets.get("TELEGRAM_CHAT_ID", "")
        if bot_token and chat_id:
            msg = f"⚡ MOMENTUM SCANNER!\n\nCoin: {symbol}\nSignal: {signal}\nTime: {now.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            
            if "EXIT" in signal:
                msg += "📌 Sinyal EXIT - Close posisi!\n"
            else:
                msg += "📌 Sinyal BUY - Entry posisi!\n"
            
            for tf in ["15m", "1h", "4h"]:
                if tf in result.get("timeframes", {}):
                    res = result["timeframes"][tf]
                    msg += f"\n{tf.upper()}:\n"
                    msg += f"  Action: {res.get('action', '')}\n"
                    msg += f"  MACD: {res['macd']['dif']:.4f}\n"
                    msg += f"  Hist: {res['macd']['histogram']:.4f}\n"
                    msg += f"  Stoch K: {res['stoch']['k']:.1f}\n"
                    msg += f"  Stoch D: {res['stoch']['d']:.1f}\n"
                    msg += f"  RSI: {res['rsi']:.1f}\n"
                    msg += f"  EMA100: {res.get('ema100', 0):.4f}\n"
            
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            response = requests.post(url, json={"chat_id": chat_id, "text": msg}, timeout=10)
            if response.status_code == 200:
                st.session_state.sent_signals[signal_key] = True
                st.session_state.last_telegram_time[symbol] = now
                return True
    except Exception as e:
        print(f"Telegram error: {e}")
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

def get_data_safe(symbol, interval, min_candles=150):
    periods = {
        "5m": ["3d", "7d", "14d"],
        "15m": ["7d", "14d", "30d"],
        "30m": ["14d", "30d"],
        "1h": ["14d", "30d", "60d"],
        "4h": ["30d", "60d", "90d"],
        "1d": ["180d", "1y"],
    }
    for period in periods.get(interval, ["14d", "30d"]):
        df = get_data(symbol, interval, period)
        if df is not None and len(df) >= min_candles:
            return df
    return None

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

def calculate_bollinger(df, window=20, std=2):
    bb = BollingerBands(close=df["Close"], window=window, window_dev=std)
    upper = bb.bollinger_hband()
    middle = bb.bollinger_mavg()
    lower = bb.bollinger_lband()
    width = (upper - lower) / middle.replace(0, pd.NA)
    return upper, middle, lower, width

# =========================================================
# MOMENTUM ENGINE
# =========================================================
def calculate_momentum_score(df, timeframe="1h"):
    """Score 0-10 untuk mendeteksi momentum bullish"""
    if df is None or len(df) < 150:
        return None

    close = df["Close"]
    ema20 = EMA(df, 20)
    ema50 = EMA(df, 50)
    ema100 = EMA(df, 100)
    adx = ADX(df, 14)

    macd_line, signal_line, histogram = MACD(df)
    _, _, rsi = StochasticRSI(df)
    _, _, _, bb_width = calculate_bollinger(df)

    volume_ma20 = df["Volume"].rolling(20).mean()
    volume_ratio = (
        df["Volume"].iloc[-1] / volume_ma20.iloc[-1]
        if volume_ma20.iloc[-1] > 0 else 1
    )

    price = float(close.iloc[-1])
    ema20_now = float(ema20.iloc[-1])
    ema50_now = float(ema50.iloc[-1])
    ema100_now = float(ema100.iloc[-1])
    adx_now = float(adx.iloc[-1]) if not pd.isna(adx.iloc[-1]) else 0

    macd_now = float(macd_line.iloc[-1])
    signal_now = float(signal_line.iloc[-1])
    hist_now = float(histogram.iloc[-1])
    hist_prev = float(histogram.iloc[-2])
    hist_prev2 = float(histogram.iloc[-3])
    rsi_now = float(rsi.iloc[-1])

    bb_width_now = float(bb_width.iloc[-1])
    bb_width_prev = float(bb_width.iloc[-2])

    hist_delta_now = hist_now - hist_prev
    hist_delta_prev = hist_prev - hist_prev2

    macd_accelerating = hist_delta_now > hist_delta_prev
    hist_improving = hist_now > hist_prev

    price_above_ema20 = price > ema20_now
    ema20_above_ema50 = ema20_now > ema50_now
    ema50_above_ema100 = ema50_now > ema100_now

    strong_trend = price_above_ema20 and ema20_above_ema50 and ema50_above_ema100
    bullish_structure = price_above_ema20 and ema20_above_ema50

    previous_high = float(df["High"].iloc[-21:-1].max())
    breakout = price > previous_high
    bb_expanding = bb_width_now > bb_width_prev

    score = 0.0
    reasons = []

    # Trend (0-3)
    if price_above_ema20:
        score += 1
        reasons.append("Harga > EMA20")
    if ema20_above_ema50:
        score += 1
        reasons.append("EMA20 > EMA50")
    if ema50_above_ema100:
        score += 1
        reasons.append("EMA50 > EMA100")

    # MACD (0-2)
    if macd_now > signal_now:
        score += 1
        reasons.append("MACD bullish")
    if hist_improving:
        score += 0.5
        reasons.append("Histogram membaik")
    if macd_accelerating:
        score += 0.5
        reasons.append("MACD acceleration")

    # Volume (0-1)
    if volume_ratio >= 1.5:
        score += 1
        reasons.append(f"Volume expansion {volume_ratio:.2f}x")

    # Breakout (0-1)
    if breakout:
        score += 1
        reasons.append("Breakout 20 candle")

    # Bollinger Band (0-0.5)
    if bb_expanding:
        score += 0.5
        reasons.append("BB mulai melebar")

    # RSI (0-0.5)
    if 45 <= rsi_now <= 65:
        score += 0.5
        reasons.append(f"RSI sehat {rsi_now:.1f}")

    # ADX (0-1) - tambahan
    if adx_now > 25:
        score += 1
        reasons.append(f"ADX kuat {adx_now:.1f}")
    elif adx_now > 20:
        score += 0.5
        reasons.append(f"ADX moderate {adx_now:.1f}")

    score = min(score, 10.0)

    # Status
    if score >= 8:
        status = "🔥 STRONG MOMENTUM"
    elif score >= 7:
        status = "🟢 EARLY MOMENTUM"
    elif score >= 5:
        status = "🟡 DEVELOPING"
    elif score >= 3:
        status = "⚪ WEAK"
    else:
        status = "🔴 NO MOMENTUM"

    extended = rsi_now > 75 or price > ema20_now * 1.10
    if extended:
        status = "⚠️ EXTENDED"

    return {
        "score": round(score, 1),
        "status": status,
        "price": price,
        "ema20": ema20_now,
        "ema50": ema50_now,
        "ema100": ema100_now,
        "adx": adx_now,
        "macd": macd_now,
        "signal": signal_now,
        "histogram": hist_now,
        "hist_improving": hist_improving,
        "macd_acceleration": macd_accelerating,
        "rsi": rsi_now,
        "volume_ratio": float(volume_ratio),
        "bb_width": bb_width_now,
        "bb_expanding": bb_expanding,
        "breakout": breakout,
        "bullish_structure": bullish_structure,
        "strong_trend": strong_trend,
        "reasons": reasons,
    }

def analyze_momentum_mtf(symbol, timeframes=("15m", "1h", "4h")):
    results = {}

    for tf in timeframes:
        df = get_data_safe(symbol, tf, min_candles=150)
        if df is None:
            continue

        result = calculate_momentum_score(df, tf)
        if result:
            results[tf] = result

    if not results:
        return None

    weights = {"15m": 0.20, "1h": 0.30, "4h": 0.50}
    weighted_score = 0.0
    total_weight = 0.0

    for tf, result in results.items():
        weight = weights.get(tf, 0.30)
        weighted_score += result["score"] * weight
        total_weight += weight

    final_score = weighted_score / total_weight if total_weight else 0

    if final_score >= 8:
        main_status = "🔥 STRONG MOMENTUM"
    elif final_score >= 7:
        main_status = "🟢 EARLY MOMENTUM"
    elif final_score >= 5:
        main_status = "🟡 DEVELOPING"
    else:
        main_status = "⚪ WAIT"

    return {
        "symbol": symbol,
        "score": round(final_score, 2),
        "status": main_status,
        "timeframes": results,
    }

def scan_momentum(symbol):
    result = analyze_momentum_mtf(symbol)
    if result is None:
        return None

    tf = result["timeframes"]
    return {
        "Coin": symbol,
        "Score": result["score"],
        "Status": result["status"],
        "4H": tf.get("4h", {}).get("score", 0),
        "1H": tf.get("1h", {}).get("score", 0),
        "15M": tf.get("15m", {}).get("score", 0),
        "ADX 1H": tf.get("1h", {}).get("adx", 0),
        "Volume 1H": tf.get("1h", {}).get("volume_ratio", 0),
        "RSI 1H": tf.get("1h", {}).get("rsi", 0),
        "Breakout 1H": tf.get("1h", {}).get("breakout", False),
        "BB Expand 1H": tf.get("1h", {}).get("bb_expanding", False),
    }

# =========================================================
# ALGORITMA TRADING SPOT
# =========================================================
def analyze_macd_stoch_spot(df, timeframe=""):
    if df is None or len(df) < 30:
        return None
    
    macd_line, signal_line, histogram = MACD(df)
    stoch_k, stoch_d, rsi = StochasticRSI(df)
    ema20 = EMA(df, 20)
    ema50 = EMA(df, 50)
    ema100 = EMA(df, 100)
    adx = ADX(df, 14)
    
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
    adx_val = adx.iloc[-1] if not pd.isna(adx.iloc[-1]) else 0
    
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
    
    if adx_val > 25:
        buy_score += 1
        buy_reasons.append(f"ADX kuat ({adx_val:.1f}) ✅")
    
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
        "adx": adx_val,
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

def analyze_mtf_macd_stoch_spot(symbol, timeframes=["15m", "1h", "4h"]):
    results = {}
    for tf in timeframes:
        df = get_data_safe(symbol, tf, min_candles=50)
        if df is not None:
            result = analyze_macd_stoch_spot(df, tf)
            if result:
                result["symbol"] = symbol
                results[tf] = result
    
    if not results:
        return None
    
    combined = {"symbol": symbol, "timeframes": results}
    buy_count = 0
    sell_count = 0
    hold_count = 0
    
    for tf in ["4h", "1h", "15m"]:
        if tf in results:
            res = results[tf]
            if "BUY" in res["action"]:
                buy_count += 1
            elif "EXIT" in res["action"]:
                sell_count += 1
            else:
                hold_count += 1
    
    main_signal = "⏳ WAIT"
    main_strength = 0
    
    if buy_count >= 3:
        main_signal = "🟢 STRONG BUY (All TF Bullish)"
        main_strength = 3
    elif buy_count == 2 and hold_count >= 1:
        main_signal = "🟢 BUY (2 TF Bullish)"
        main_strength = 2
    elif buy_count == 1 and hold_count >= 2:
        main_signal = "🟡 CAUTION (Only 1 TF Bullish)"
        main_strength = 1
    elif sell_count >= 2:
        main_signal = "🔴 EXIT (Multi TF)"
        main_strength = 3
    elif sell_count == 1 and hold_count >= 1:
        main_signal = "🔴 CAUTION EXIT"
        main_strength = 2
    else:
        main_signal = "🟡 HOLD / WAIT"
        main_strength = 1
    
    combined["main_signal"] = main_signal
    combined["main_strength"] = main_strength
    combined["buy_count"] = buy_count
    combined["sell_count"] = sell_count
    combined["hold_count"] = hold_count
    
    return combined

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
    adx = ADX(df, 14)
    
    fig = make_subplots(
        rows=5, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.02,
        row_heights=[0.30, 0.15, 0.20, 0.20, 0.15],
        subplot_titles=(f"Price - {symbol} {timeframe}", "RSI", "MACD", "Stochastic RSI", "ADX")
    )
    
    # Price + EMA
    fig.add_trace(go.Candlestick(x=df["Time"], open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
                                 increasing_line_color="#00ff88", decreasing_line_color="#ff3b5c", name="Price"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df["Time"], y=ema20, line=dict(color="#00a2ff", width=1.5), name="EMA20"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df["Time"], y=ema50, line=dict(color="#ffaa00", width=1.5, dash="dash"), name="EMA50"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df["Time"], y=ema100, line=dict(color="#ff00ff", width=1.5, dash="dot"), name="EMA100"), row=1, col=1)
    
    # RSI
    fig.add_trace(go.Scatter(x=df["Time"], y=rsi, line=dict(color="#a855f7", width=2), name="RSI"), row=2, col=1)
    fig.add_hline(y=70, line_dash="dash", line_color="red", row=2, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="green", row=2, col=1)
    
    # MACD
    fig.add_trace(go.Scatter(x=df["Time"], y=macd_line, line=dict(color="#00a2ff", width=1.5), name="DIF (MACD)"), row=3, col=1)
    fig.add_trace(go.Scatter(x=df["Time"], y=signal_line, line=dict(color="#ff00ff", width=1.5), name="DEA (Signal)"), row=3, col=1)
    colors = ["#00ff88" if h >= 0 else "#ff3b5c" for h in histogram]
    fig.add_trace(go.Bar(x=df["Time"], y=histogram, marker_color=colors, opacity=0.5, name="Histogram"), row=3, col=1)
    fig.add_hline(y=0, line_dash="solid", line_color="rgba(255,255,255,0.2)", row=3, col=1)
    
    # Stochastic RSI
    fig.add_trace(go.Scatter(x=df["Time"], y=stoch_k, line=dict(color="#ffaa00", width=1.5), name="Stoch K"), row=4, col=1)
    fig.add_trace(go.Scatter(x=df["Time"], y=stoch_d, line=dict(color="#ff00ff", width=1.5, dash="dash"), name="Stoch D"), row=4, col=1)
    fig.add_hline(y=80, line_dash="dash", line_color="red", row=4, col=1)
    fig.add_hline(y=20, line_dash="dash", line_color="green", row=4, col=1)
    
    # ADX
    fig.add_trace(go.Scatter(x=df["Time"], y=adx, line=dict(color="#00c8ff", width=2), name="ADX"), row=5, col=1)
    fig.add_hline(y=25, line_dash="dash", line_color="#00ff88", row=5, col=1, annotation_text="Strong Trend")
    
    fig.update_layout(template="plotly_dark", height=1000,
                      title=dict(text=f"<b>{symbol} - {timeframe} Analysis (SPOT)</b>", font=dict(color="#f1f5f9", size=20),
                                 x=0.5, xanchor="center"),
                      hovermode="x unified", dragmode="pan", xaxis_rangeslider_visible=False,
                      paper_bgcolor="#0a0a1a", plot_bgcolor="#0a0a1a", font=dict(color="#94a3b8"),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(size=10)),
                      margin=dict(l=10, r=10, t=50, b=10))
    fig.update_xaxes(gridcolor="rgba(255,255,255,0.03)")
    fig.update_yaxes(gridcolor="rgba(255,255,255,0.03)")
    return fig

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
    
    if highest_price:
        trailing_sl = highest_price * 0.95
        if price <= trailing_sl:
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
        
        if entry_time and isinstance(entry_time, datetime):
            holding_days = (datetime.now() - entry_time).days
            if holding_days > 7:
                return "⏰ TIME EXIT (7 days)", price
    
    return None, price

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

if not st.session_state.positions:
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

# =========================================================
# MAIN TITLE
# =========================================================
st.title("🚀 Crypto Momentum Scanner PRO - SPOT")
st.caption("Multi Timeframe: 15M | 1H | 4H | Momentum Score + ADX + Bollinger Band | Auto Position")

# =========================================================
# SIDEBAR
# =========================================================
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
    refresh = st.slider("🔄 Refresh (detik)", 10, 60, 30)
    hold_minutes = st.slider("Hold Signal (menit)", 5, 30, 15, key="hold_minutes")
    
    st.divider()
    st.subheader("📱 Telegram Alert")
    if st.button("🚀 Test Telegram", use_container_width=True):
        send_telegram_test("🚀 Telegram Connected! Momentum Scanner Aktif.")
        st.success("✅ Pesan test terkirim!")
    
    st.divider()
    st.subheader("📊 Status")
    st.metric("Total Coins", len(st.session_state.watchlist))
    stats = get_performance()
    st.metric("Total Signals", stats.get('total_signals', 0))
    st.metric("Open Positions", len(st.session_state.positions))
    st.caption(f"🔄 Auto Refresh: {refresh} detik")
    st.caption("📌 Mode: SPOT Momentum Scanner")

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

# ==================== TAB 1: MOMENTUM SCANNER ====================
with tab1:
    st.subheader("🚀 Momentum Scanner - SPOT")
    st.caption("Mendeteksi momentum bullish dengan multi timeframe + ADX + Bollinger Band")

    all_momentum = []
    coins = st.session_state.watchlist[:50]

    if coins:
        progress = st.progress(0)
        status_text = st.empty()

        for idx, symbol in enumerate(coins):
            progress.progress((idx + 1) / len(coins))
            status_text.text(f"🔍 Scanning {symbol}...")

            try:
                result = scan_momentum(symbol)
                if result:
                    all_momentum.append(result)
            except Exception as e:
                print(f"Error scanning {symbol}: {e}")

        progress.empty()
        status_text.empty()

    if all_momentum:
        df_momentum = pd.DataFrame(all_momentum)
        df_momentum = df_momentum.sort_values("Score", ascending=False).reset_index(drop=True)

        display_df = df_momentum.copy()
        display_df["Score"] = display_df["Score"].map(lambda x: f"{x:.2f}/10")
        display_df["ADX 1H"] = display_df["ADX 1H"].map(lambda x: f"{x:.1f}")
        display_df["Volume 1H"] = display_df["Volume 1H"].map(lambda x: f"{x:.2f}x")
        display_df["RSI 1H"] = display_df["RSI 1H"].map(lambda x: f"{x:.1f}")
        display_df["Breakout 1H"] = display_df["Breakout 1H"].map(lambda x: "✅" if x else "❌")
        display_df["BB Expand 1H"] = display_df["BB Expand 1H"].map(lambda x: "📈" if x else "➖")

        st.dataframe(display_df, use_container_width=True, hide_index=True)

        # Top momentum
        top = df_momentum.iloc[0]
        st.success(
            f"🏆 Top Momentum: **{top['Coin']}** | "
            f"Score **{top['Score']:.2f}/10** | {top['Status']}"
        )

        # Detail top momentum
        with st.expander(f"🔎 Detail {top['Coin']}"):
            detailed = analyze_momentum_mtf(top["Coin"])

            if detailed:
                for tf in ["4h", "1h", "15m"]:
                    if tf not in detailed["timeframes"]:
                        continue

                    r = detailed["timeframes"][tf]
                    st.markdown(f"### {tf.upper()} — {r['score']:.1f}/10 — {r['status']}")

                    c1, c2, c3, c4, c5 = st.columns(5)
                    c1.metric("Price", format_price(r["price"]))
                    c2.metric("RSI", f"{r['rsi']:.1f}")
                    c3.metric("ADX", f"{r['adx']:.1f}")
                    c4.metric("Volume", f"{r['volume_ratio']:.2f}x")
                    c5.metric("BB", "Expanding" if r["bb_expanding"] else "Not")

                    st.write(
                        f"MACD: `{r['macd']:.6f}` | "
                        f"Histogram: `{r['histogram']:.6f}` | "
                        f"Breakout: {'✅' if r['breakout'] else '❌'}"
                    )

                    if r["reasons"]:
                        st.write("**Reasons:**")
                        for reason in r["reasons"]:
                            st.write(f"- {reason}")

        # Filter: Only show coins with score >= 6
        st.divider()
        st.subheader("🎯 High Quality Momentum (Score >= 6)")
        high_quality = df_momentum[df_momentum["Score"] >= 6]
        if not high_quality.empty:
            hq_display = high_quality.copy()
            hq_display["Score"] = hq_display["Score"].map(lambda x: f"{x:.2f}/10")
            hq_display["ADX 1H"] = hq_display["ADX 1H"].map(lambda x: f"{x:.1f}")
            hq_display["Volume 1H"] = hq_display["Volume 1H"].map(lambda x: f"{x:.2f}x")
            hq_display["RSI 1H"] = hq_display["RSI 1H"].map(lambda x: f"{x:.1f}")
            hq_display["Breakout 1H"] = hq_display["Breakout 1H"].map(lambda x: "✅" if x else "❌")
            st.dataframe(hq_display[["Coin", "Score", "Status", "ADX 1H", "Volume 1H", "RSI 1H", "Breakout 1H"]], 
                        use_container_width=True, hide_index=True)
        else:
            st.info("Tidak ada coin dengan score >= 6 saat ini.")
    else:
        st.info("ℹ️ Belum ada data momentum. Pastikan watchlist berisi coin yang valid.")

# ==================== TAB 2: CHART ANALYSIS ====================
with tab2:
    st.subheader("📈 Chart Analysis - SPOT")
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
                col1.metric("Stoch K", f"{result['stoch']['k']:.1f}")
                col2.metric("Stoch D", f"{result['stoch']['d']:.1f}")
                col3.metric("RSI", f"{result['rsi']:.1f}")
                col4.metric("ADX", f"{result.get('adx', 0):.1f}")
                
                with st.expander("📋 Signal Details", expanded=True):
                    if result["reasons"]:
                        for reason in result["reasons"]:
                            st.write(f"• {reason}")
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

# ==================== TAB 3: POSITIONS ====================
with tab3:
    st.subheader("📊 Portfolio Management")
    
    portfolio_data = get_portfolio_summary()
    open_positions = portfolio_data["open_positions"]
    closed_positions = portfolio_data["closed_positions"]
    
    # Update positions
    for pos in open_positions:
        try:
            symbol = pos["symbol"]
            position_id = pos["id"]
            entry = pos["entry_price"]
            sl = pos["stop_loss"]
            tp = pos["take_profit"]
            position_size = pos.get("position_size", 1)
            
            df = get_data_safe(symbol, "15m", min_candles=20)
            if df is not None and not df.empty:
                current_price = df["Close"].iloc[-1]
                
                highest = pos.get("highest_price", entry)
                if current_price > highest:
                    highest = current_price
                
                pnl = (current_price - entry) * position_size
                pnl_percent = (current_price / entry - 1) * 100
                
                update_position_in_db(position_id, {
                    "current_price": current_price,
                    "highest_price": highest,
                    "pnl": pnl,
                    "pnl_percent": pnl_percent
                })
                
                exit_signal, exit_price = check_exit_conditions(
                    {"entry": entry, "sl": sl, "tp": tp, "entry_time": pos.get("entry_time")}, 
                    df, 
                    highest
                )
                
                if exit_signal:
                    pnl_exit = (exit_price - entry) * position_size
                    pnl_percent_exit = (exit_price / entry - 1) * 100
                    
                    close_position_in_db(position_id, exit_price, exit_signal, pnl_exit, pnl_percent_exit)
                    
                    save_signal({
                        'symbol': symbol,
                        'signal': f"EXIT - {exit_signal}",
                        'exit_price': exit_price,
                        'profit_pct': pnl_percent_exit,
                        'timestamp': datetime.now().isoformat()
                    })
                    
                    if symbol in st.session_state.positions:
                        del st.session_state.positions[symbol]
                    
                    st.rerun()
        except Exception as e:
            print(f"Error updating {pos.get('symbol', 'unknown')}: {e}")
            continue
    
    # Refresh data
    portfolio_data = get_portfolio_summary()
    open_positions = portfolio_data["open_positions"]
    closed_positions = portfolio_data["closed_positions"]
    
    # Portfolio Summary
    st.subheader("💰 Portfolio Summary")
    
    col1, col2, col3, col4, col5 = st.columns(5)
    
    total_equity = portfolio_data["total_equity"]
    total_pnl = portfolio_data["total_pnl"]
    
    col1.metric(
        "📊 Total Equity", 
        f"${total_equity:,.2f}",
        delta=f"+${total_pnl:,.2f}" if total_pnl >= 0 else f"-${abs(total_pnl):,.2f}"
    )
    
    col2.metric(
        "📈 Realized PNL",
        f"${portfolio_data['realized_pnl']:,.2f}",
        delta=f"{portfolio_data['win_rate']:.1f}% Win Rate"
    )
    
    col3.metric(
        "📉 Unrealized PNL",
        f"${portfolio_data['unrealized_pnl']:,.2f}",
        delta=f"{portfolio_data['unrealized_pnl_percent']:.2f}%"
    )
    
    col4.metric(
        "🔄 Total PNL",
        f"${total_pnl:,.2f}",
        delta=f"{(total_pnl/max(1, total_equity) * 100):.2f}%"
    )
    
    col5.metric(
        "🎯 Win Rate",
        f"{portfolio_data['win_rate']:.1f}%",
        delta=f"{portfolio_data['wins']}W / {portfolio_data['losses']}L"
    )
    
    st.divider()
    
    # Open Positions
    st.subheader("📋 Open Positions")
    
    if open_positions:
        pos_data = []
        for pos in open_positions:
            pnl = pos.get("pnl", 0)
            pnl_percent = pos.get("pnl_percent", 0)
            
            if pnl > 0:
                pnl_color = "🟢"
            elif pnl < 0:
                pnl_color = "🔴"
            else:
                pnl_color = "🟡"
            
            entry_time = pos.get("entry_time", "")
            if entry_time and isinstance(entry_time, str):
                try:
                    entry_time = datetime.fromisoformat(entry_time.replace('Z', '+00:00')).strftime("%Y-%m-%d %H:%M")
                except:
                    entry_time = entry_time[:16] if len(entry_time) > 16 else entry_time
            
            pos_data.append({
                "Coin": pos["symbol"],
                "Entry": format_price(pos["entry_price"]),
                "Current": format_price(pos.get("current_price", pos["entry_price"])),
                "SL": format_price(pos["stop_loss"]),
                "TP": format_price(pos["take_profit"]),
                "Size": f"{pos.get('position_size', 1):.4f}",
                "PNL": f"{pnl_color} ${pnl:.2f} ({pnl_percent:.2f}%)",
                "Entry Time": entry_time
            })
        
        df_open = pd.DataFrame(pos_data)
        st.dataframe(df_open, use_container_width=True, hide_index=True)
    else:
        st.info("📭 Tidak ada posisi terbuka")
    
    st.divider()
    
    # Closed Positions
    st.subheader("📊 Closed Positions")
    
    if closed_positions:
        closed_data = []
        for pos in closed_positions[:50]:
            pnl = pos.get("pnl", 0)
            pnl_percent = pos.get("pnl_percent", 0)
            
            if pnl > 0:
                pnl_color = "🟢"
            elif pnl < 0:
                pnl_color = "🔴"
            else:
                pnl_color = "🟡"
            
            exit_reason = pos.get("exit_reason", "UNKNOWN")
            exit_emoji = "✅" if "TP" in exit_reason else "❌" if "SL" in exit_reason else "🔄"
            
            exit_time = pos.get("exit_time", "")
            if exit_time and isinstance(exit_time, str):
                try:
                    exit_time = datetime.fromisoformat(exit_time.replace('Z', '+00:00')).strftime("%Y-%m-%d %H:%M")
                except:
                    exit_time = exit_time[:16] if len(exit_time) > 16 else exit_time
            
            closed_data.append({
                "Coin": pos["symbol"],
                "Entry": format_price(pos["entry_price"]),
                "Exit": format_price(pos.get("exit_price", pos["entry_price"])),
                "PNL": f"{pnl_color} ${pnl:.2f} ({pnl_percent:.2f}%)",
                "Exit Reason": f"{exit_emoji} {exit_reason}",
                "Exit Time": exit_time
            })
        
        df_closed = pd.DataFrame(closed_data)
        st.dataframe(df_closed, use_container_width=True, hide_index=True)
        
        st.divider()
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Trades", portfolio_data["total_closed"])
        col2.metric("Wins", portfolio_data["wins"])
        col3.metric("Losses", portfolio_data["losses"])
        col4.metric("Win Rate", f"{portfolio_data['win_rate']:.1f}%")
    else:
        st.info("Belum ada posisi yang ditutup")

# ==================== TAB 4: HISTORY ====================
with tab4:
    st.subheader("📜 Signal History")
    
    history = get_signal_history(limit=200)
    if history:
        df_history = pd.DataFrame(history)
        if 'id' in df_history.columns:
            df_history = df_history.drop('id', axis=1)
        st.dataframe(df_history, use_container_width=True, hide_index=True)
        
        csv = df_history.to_csv(index=False)
        st.download_button(label="📥 Download CSV", data=csv,
                           file_name=f"history_{datetime.now().strftime('%Y%m%d')}.csv", mime="text/csv")
    else:
        st.info("Belum ada sinyal")

# ==================== TAB 5: PERFORMANCE ====================
with tab5:
    st.subheader("📊 Performance Statistics")
    
    stats = get_performance()
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Signals", stats.get("total_signals", 0))
    col2.metric("Wins", stats.get("wins", 0))
    col3.metric("Losses", stats.get("losses", 0))
    col4.metric("Win Rate", f"{stats.get('win_rate', 0):.1f}%")
    
    st.divider()
    st.subheader("📈 SPOT Trading Rules Summary")
    rules = {
        "BUY ⭐⭐⭐⭐⭐": "MACD histogram > 0, DIF > DEA, Stoch RSI 10-30, Golden Cross, EMA100+",
        "BUY ⭐⭐⭐⭐": "MACD DIF > DEA, Stoch 20-40 & mengarah naik, bullish trend",
        "HOLD ⭐⭐⭐⭐": "MACD masih naik, Stoch RSI 30-70",
        "EXIT ⭐⭐⭐⭐": "Stoch RSI >85, Histogram mulai mengecil, MACD death cross",
        "STOP LOSS": "Harga turun 3x ATR dari entry"
    }
    for rule, desc in rules.items():
        st.write(f"**{rule}:** {desc}")

# =========================================================
# FOOTER
# =========================================================
st.divider()
st.caption(f"""
🔄 Data dari Yahoo Finance | Timeframe: 15M, 1H, 4H  
📊 Indikator: MACD + Stoch RSI + EMA20/50/100 + ADX + Volume + Bollinger Band  
💾 Database: Supabase PostgreSQL  
📌 Mode: SPOT Momentum Scanner + Auto Position
""")
