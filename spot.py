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
from ta.volatility import AverageTrueRange

load_dotenv()
warnings.filterwarnings('ignore')

# =========================================================
# PAGE CONFIG
# =========================================================
st.set_page_config(
    page_title="🤖 Crypto Bot PRO - SPOT (MACD + Stoch RSI)",
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
    .signal-take-profit {
        background: linear-gradient(135deg, rgba(0,150,255,0.15), rgba(0,150,255,0.05));
        border: 1px solid #0096ff;
        border-radius: 12px;
        padding: 12px 20px;
        color: #0096ff;
        font-weight: 600;
        font-size: 18px;
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
        return [row["symbol"] for row in res.data] if res.data else ["BTC"]
    except:
        return ["BTC"]

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
    """Simpan sinyal dengan cegah duplikat"""
    supabase = get_supabase()
    try:
        # Cek duplikat dalam 5 menit terakhir
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
            return False  # Duplikat, skip save
        
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
# TELEGRAM FUNCTIONS - ANTI DUPLICATE
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
            msg = f"⚡ SPOT SIGNAL!\n\nCoin: {symbol}\nSignal: {signal}\nTime: {now.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            
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
                for key in list(st.session_state.sent_signals.keys()):
                    try:
                        ts_str = key.split('_')[-1]
                        ts = datetime.strptime(ts_str, '%Y%m%d_%H%M')
                        if (now - ts).seconds > 3600:
                            del st.session_state.sent_signals[key]
                    except:
                        pass
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
# GET DATA (YAHOO FINANCE)
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

# =========================================================
# ALGORITMA TRADING SPOT - MACD + STOCHASTIC RSI
# =========================================================
def analyze_macd_stoch_spot(df, timeframe=""):
    """Versi SPOT - hanya BUY dan EXIT (tanpa SELL)"""
    if df is None or len(df) < 30:
        return None
    
    macd_line, signal_line, histogram = MACD(df)
    stoch_k, stoch_d, rsi = StochasticRSI(df)
    ema20 = EMA(df, 20)
    ema50 = EMA(df, 50)
    ema100 = EMA(df, 100)  # Tambahan untuk spot
    
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
    
    # =========================================================
    # DETEKSI SINYAL
    # =========================================================
    macd_golden_cross = (macd_prev < signal_prev) and (macd_val > signal_val)
    macd_death_cross = (macd_prev > signal_prev) and (macd_val < signal_val)
    stoch_golden_cross = (stoch_k_prev < stoch_d_prev) and (stoch_k_val > stoch_d_val)
    stoch_death_cross = (stoch_k_prev > stoch_d_prev) and (stoch_k_val < stoch_d_val)
    
    hist_increasing = hist_val > hist_prev
    hist_decreasing = hist_val < hist_prev
    hist_positive = hist_val > 0
    
    # Trend untuk spot (lebih ketat dengan EMA100)
    strong_bullish = price > ema20_val > ema50_val > ema100_val
    bullish_trend = price > ema20_val > ema50_val
    bearish_trend = price < ema20_val < ema50_val
    
    volume_confirmed = volume_ratio > 1.5  # Lebih ketat untuk spot
    
    # =========================================================
    # BUY SCORE (Lebih ketat)
    # =========================================================
    buy_score = 0
    buy_reasons = []
    
    # 1. MACD (minimal 3 poin)
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
    
    # 2. Stoch RSI (minimal 3 poin)
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
    
    # 3. Trend (minimal 2 poin)
    if strong_bullish:
        buy_score += 2
        buy_reasons.append("⭐ Strong Bullish (EMA100+)")
    elif bullish_trend:
        buy_score += 1
        buy_reasons.append("Bullish Trend ✅")
    elif price > ema20_val:
        buy_score += 0.5
        buy_reasons.append("Harga > EMA20 ✅")
    
    # 4. Volume (1 poin)
    if volume_confirmed:
        buy_score += 1
        buy_reasons.append("Volume tinggi ✅")
    
    # 5. RSI ideal (1 poin)
    if 30 <= rsi_val <= 60:
        buy_score += 1
        buy_reasons.append(f"RSI ideal ({rsi_val:.1f}) ✅")
    elif rsi_val < 70:
        buy_score += 0.5
        buy_reasons.append(f"RSI sehat ({rsi_val:.1f}) ✅")
    
    # =========================================================
    # EXIT SCORE (Untuk close position)
    # =========================================================
    exit_score = 0
    exit_reasons = []
    
    # 1. MACD Bearish
    if macd_val < signal_val:
        exit_score += 1
        exit_reasons.append("MACD DIF < DEA ⚠️")
    if hist_decreasing and hist_positive:
        exit_score += 1
        exit_reasons.append("Histogram mengecil ⚠️")
    if macd_death_cross:
        exit_score += 2
        exit_reasons.append("⭐ MACD Death Cross!")
    
    # 2. Stoch Overbought
    if stoch_k_val > 80 and stoch_d_val > 80:
        exit_score += 2
        exit_reasons.append("⭐ Stoch Overbought (>80)")
    if stoch_death_cross and stoch_k_val > 80:
        exit_score += 2
        exit_reasons.append("⭐ Stoch Death Cross!")
    
    # 3. Trend Bearish
    if bearish_trend:
        exit_score += 1
        exit_reasons.append("Bearish Trend ⚠️")
    
    # 4. RSI terlalu tinggi
    if rsi_val > 70:
        exit_score += 0.5
        exit_reasons.append(f"RSI overbought ({rsi_val:.1f})")
    
    # =========================================================
    # KEPUTUSAN AKHIR
    # =========================================================
    action = "⏳ WAIT"
    signal_type = "HOLD"
    signal_strength = 0
    is_buy = False
    reasons = []
    
    # BUY - Minimal score 6 untuk spot (lebih ketat)
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
    
    # EXIT (jika sudah punya posisi)
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
    
    # HOLD
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
# MULTI TIMEFRAME ANALYSIS - SPOT
# =========================================================
def analyze_mtf_macd_stoch_spot(symbol, timeframes=["15m", "1h", "4h"]):
    """Analisis multi timeframe untuk SPOT - 3 dari 3 bullish"""
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
    
    # Spot: butuh 3 dari 3 bullish
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
# POSITIONS DATABASE FUNCTIONS (LENGKAP)
# =========================================================

def save_position_to_db(symbol, entry, sl, tp, position_size=0):
    """Simpan posisi baru ke database"""
    supabase = get_supabase()
    try:
        data = {
            "symbol": symbol,
            "entry_price": entry,
            "current_price": entry,
            "stop_loss": sl,
            "take_profit": tp,
            "highest_price": entry,
            "position_size": position_size,
            "entry_time": datetime.now().isoformat(),
            "status": "OPEN",
            "pnl": 0,
            "pnl_percent": 0
        }
        result = supabase.table("positions").insert(data).execute()
        if result.data:
            return result.data[0]  # Return inserted data with id
        return None
    except Exception as e:
        print(f"Error save position: {e}")
        return None

def get_open_positions_from_db():
    """Ambil semua posisi OPEN dari database"""
    supabase = get_supabase()
    try:
        res = supabase.table("positions").select("*").eq("status", "OPEN").order("entry_time", desc=True).execute()
        return res.data if res.data else []
    except:
        return []

def get_closed_positions_from_db(limit=100):
    """Ambil posisi CLOSED dari database"""
    supabase = get_supabase()
    try:
        res = supabase.table("positions").select("*").eq("status", "CLOSED").order("exit_time", desc=True).limit(limit).execute()
        return res.data if res.data else []
    except:
        return []

def update_position_in_db(position_id, updates):
    """Update posisi di database"""
    supabase = get_supabase()
    try:
        updates["updated_at"] = datetime.now().isoformat()
        supabase.table("positions").update(updates).eq("id", position_id).execute()
        return True
    except:
        return False

def close_position_in_db(position_id, exit_price, exit_reason, pnl, pnl_percent):
    """Close posisi di database"""
    supabase = get_supabase()
    try:
        updates = {
            "status": "CLOSED",
            "current_price": exit_price,
            "exit_price": exit_price,
            "exit_reason": exit_reason,
            "pnl": pnl,
            "pnl_percent": pnl_percent,
            "exit_time": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }
        supabase.table("positions").update(updates).eq("id", position_id).execute()
        return True
    except:
        return False

def get_portfolio_summary():
    """Dapatkan summary portofolio dari database"""
    supabase = get_supabase()
    try:
        # Ambil semua posisi OPEN
        open_positions = get_open_positions_from_db()
        
        # Ambil semua posisi CLOSED (terakhir 100)
        closed_positions = get_closed_positions_from_db(limit=100)
        
        # Hitung unrealized PNL (dari open positions)
        unrealized_pnl = sum([p.get("pnl", 0) for p in open_positions])
        unrealized_pnl_percent = sum([p.get("pnl_percent", 0) for p in open_positions])
        
        # Hitung realized PNL (dari closed positions)
        realized_pnl = sum([p.get("pnl", 0) for p in closed_positions])
        
        # Total PNL
        total_pnl = unrealized_pnl + realized_pnl
        
        # Win rate
        total_closed = len(closed_positions)
        wins = len([p for p in closed_positions if p.get("pnl", 0) > 0])
        win_rate = (wins / total_closed * 100) if total_closed > 0 else 0
        
        return {
            "open_positions": open_positions,
            "closed_positions": closed_positions,
            "total_open": len(open_positions),
            "total_closed": total_closed,
            "wins": wins,
            "losses": total_closed - wins,
            "win_rate": win_rate,
            "unrealized_pnl": unrealized_pnl,
            "unrealized_pnl_percent": unrealized_pnl_percent,
            "realized_pnl": realized_pnl,
            "total_pnl": total_pnl
        }
    except Exception as e:
        print(f"Error get portfolio summary: {e}")
        return {
            "open_positions": [],
            "closed_positions": [],
            "total_open": 0,
            "total_closed": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0,
            "unrealized_pnl": 0,
            "unrealized_pnl_percent": 0,
            "realized_pnl": 0,
            "total_pnl": 0
        }

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
    
    fig = make_subplots(
        rows=4, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.35, 0.2, 0.25, 0.2],
        subplot_titles=(f"Price - {symbol} {timeframe}", "RSI", "MACD", "Stochastic RSI")
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
    
    fig.update_layout(template="plotly_dark", height=900,
                      title=dict(text=f"<b>{symbol} - {timeframe} Analysis (SPOT)</b>", font=dict(color="#f1f5f9", size=20),
                                 x=0.5, xanchor="center"),
                      hovermode="x unified", dragmode="pan", xaxis_rangeslider_visible=False,
                      paper_bgcolor="#0a0a1a", plot_bgcolor="#0a0a1a", font=dict(color="#94a3b8"),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(size=10)),
                      margin=dict(l=10, r=10, t=50, b=10))
    fig.update_xaxes(gridcolor="rgba(255,255,255,0.03)")
    fig.update_yaxes(gridcolor="rgba(255,255,255,0.03)")
    return fig

# =========================================================
# CHECK EXIT CONDITIONS - SPOT
# =========================================================
def check_exit_conditions(position, df, highest_price=None):
    """Cek kondisi exit untuk posisi yang sudah masuk (Spot)"""
    if df is None or len(df) < 10:
        return None, None
    
    price = df["Close"].iloc[-1]
    macd_line, signal_line, histogram = MACD(df)
    stoch_k, stoch_d, _ = StochasticRSI(df)
    
    # 1. Take Profit
    if position.get("tp") and price >= position["tp"]:
        return "✅ TP HIT", price
    
    # 2. Stop Loss
    if position.get("sl") and price <= position["sl"]:
        return "❌ SL HIT", price
    
    # 3. Trailing Stop (5% dari highest)
    if highest_price:
        trailing_sl = highest_price * 0.95
        if price <= trailing_sl:
            return "📉 TRAILING SL", price
    
    # 4. MACD Death Cross + Stoch Death Cross
    if len(macd_line) > 1 and len(stoch_k) > 1:
        macd_death = (macd_line.iloc[-2] > signal_line.iloc[-2]) and (macd_line.iloc[-1] < signal_line.iloc[-1])
        stoch_death = (stoch_k.iloc[-2] > stoch_d.iloc[-2]) and (stoch_k.iloc[-1] < stoch_d.iloc[-1])
        if macd_death and stoch_death:
            return "🔄 REVERSAL EXIT", price
    
    # 5. Time-based exit (7 hari)
    if position.get("entry_time"):
        holding_days = (datetime.now() - position["entry_time"]).days
        if holding_days > 7:
            return "⏰ TIME EXIT (7 days)", price
    
    return None, price

# =========================================================
# INITIALIZATION - LOAD POSITIONS FROM DATABASE
# =========================================================
if "watchlist" not in st.session_state:
    st.session_state.watchlist = get_watchlist()
if "pending_signal" not in st.session_state:
    st.session_state.pending_signal = {}
if "signal_history" not in st.session_state:
    st.session_state.signal_history = get_signal_history()
if "performance_stats" not in st.session_state:
    st.session_state.performance_stats = get_performance()

# 🔥 LOAD POSITIONS DARI DATABASE
if "positions" not in st.session_state:
    st.session_state.positions = {}

# Jika positions kosong, load dari database
if not st.session_state.positions:
    db_positions = get_open_positions_from_db()
    for pos in db_positions:
        st.session_state.positions[pos["symbol"]] = {
            "entry": pos["entry_price"],
            "sl": pos["stop_loss"],
            "tp": pos["take_profit"],
            "entry_time": datetime.fromisoformat(pos["entry_time"]),
            "highest_price": pos.get("highest_price", pos["entry_price"]),
            "id": pos["id"],
            "position_size": pos.get("position_size", 0)
        }

# =========================================================
# MAIN TITLE
# =========================================================
st.title("🤖 Crypto Bot PRO - SPOT Trading")
st.caption("Multi Timeframe: 15M | 1H | 4H | MACD + Stochastic RSI + EMA100 | BUY & EXIT Only")

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
    st.subheader("📊 Trading Settings")
    refresh = st.slider("🔄 Refresh (detik)", 10, 60, 30)
    hold_minutes = st.slider("Hold Signal (menit)", 5, 30, 15, key="hold_minutes")
    
    st.divider()
    st.subheader("📱 Telegram Alert")
    if st.button("🚀 Test Telegram", use_container_width=True):
        send_telegram_test("🚀 Telegram Connected! SPOT Scanner Aktif.")
        st.success("✅ Pesan test terkirim!")
    
    st.divider()
    st.subheader("📊 Status")
    st.metric("Total Coins", len(st.session_state.watchlist))
    stats = get_performance()
    st.metric("Total Signals", stats.get('total_signals', 0))
    st.metric("Open Positions", len(st.session_state.positions))
    st.caption(f"🔄 Auto Refresh: {refresh} detik")
    st.caption("📌 Mode: SPOT (BUY & EXIT Only)")

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

# ==================== TAB 1: SCANNER ====================
 
 
with tab1:
    st.subheader("📊 Signal Scanner - SPOT (BUY & EXIT)")
    
    all_signals = []
    progress_bar = st.progress(0)
    status_text = st.empty()

    # Hapus pending signal yang kadaluarsa
    current_time = datetime.now()
    expired = []
    for symbol, data in st.session_state.pending_signal.items():
        elapsed = (current_time - data["time"]).seconds / 60
        if elapsed > hold_minutes:
            expired.append(symbol)
    for sym in expired:
        del st.session_state.pending_signal[sym]

    for idx, symbol in enumerate(st.session_state.watchlist[:50]):
        progress_bar.progress((idx + 1) / len(st.session_state.watchlist[:50]))
        status_text.text(f"🔄 Scanning {symbol}...")
        
        result = analyze_mtf_macd_stoch_spot(symbol, ["15m", "1h", "4h"])
        
        if result:
            signal_data = {
                "Coin": symbol,
                "Signal": result["main_signal"],
                "Strength": "⭐" * result.get("main_strength", 1),
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
                    signal_data[f"{tf.upper()} EMA100"] = f"{res.get('ema100', 0):.4f}"
            
            all_signals.append(signal_data)

            # Simpan pending signal jika sinyal BUY kuat
            if result["main_strength"] >= 2 and "BUY" in result["main_signal"]:
                df_5m = get_data_safe(symbol, "5m", min_candles=20)
                if df_5m is not None:
                    price = df_5m["Close"].iloc[-1]
                    atr = AverageTrueRange(df_5m["High"], df_5m["Low"], df_5m["Close"], window=14).average_true_range().iloc[-1]
                    if pd.isna(atr) or atr == 0:
                        atr = price * 0.01
                    
                    entry = price
                    sl = entry - atr * 3
                    tp = entry + atr * 7
                    position_size = 1  # Atau sesuai setting
            
                    if symbol not in st.session_state.pending_signal:
                        st.session_state.pending_signal[symbol] = {
                            "signal": result["main_signal"],
                            "time": datetime.now(),
                            "entry": entry,
                            "sl": sl,
                            "tp": tp,
                            "timeframe": "5m"
                        }
                        
                        # 🔥 SIMPAN KE DATABASE
                        saved_pos = save_position_to_db(symbol, entry, sl, tp, position_size)
                        if saved_pos:
                            st.session_state.positions[symbol] = {
                                "entry": entry,
                                "sl": sl,
                                "tp": tp,
                                "entry_time": datetime.now(),
                                "highest_price": entry,
                                "id": saved_pos["id"]
                            }
                            st.success(f"✅ Position opened for {symbol} at ${entry:.2f}")
                        
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
            
            # Simpan sinyal EXIT
            elif "EXIT" in result["main_signal"] and symbol in st.session_state.positions:
                sent = send_telegram_once(symbol, result["main_signal"], result)
                if sent:
                    save_signal({
                        'symbol': symbol,
                        'signal': result["main_signal"],
                        'timestamp': datetime.now().isoformat()
                    })

    progress_bar.empty()
    status_text.empty()

    if all_signals:
        df_signals = pd.DataFrame(all_signals)
        st.dataframe(df_signals, use_container_width=True, hide_index=True)
        
        buy_signals = [s for s in all_signals if "BUY" in s["Signal"]]
        if buy_signals:
            best = buy_signals[0]
            st.success(f"🏆 Best Buy Signal: **{best['Coin']}** | {best['Signal']}")
    else:
        st.info("ℹ️ Tidak ada data")

    # ========== TAMPILAN PENDING SIGNALS ==========
    if st.session_state.pending_signal:
        st.divider()
        st.subheader("⏳ Pending Signals - Entry, TP, SL")
        st.caption("Sinyal BUY yang masih aktif menunggu eksekusi")
        
        pending_data = []
        for symbol, data in st.session_state.pending_signal.items():
            elapsed = (datetime.now() - data["time"]).seconds / 60
            remaining = max(0, hold_minutes - elapsed)
            entry = data.get("entry")
            sl = data.get("sl")
            tp = data.get("tp")
            
            if entry and sl and tp:
                rr = (tp - entry) / (entry - sl) if (entry - sl) != 0 else 0
            else:
                rr = 0
            
            pending_data.append({
                "Coin": symbol,
                "Signal": data["signal"],
                "Entry": format_price(entry),
                "TP": format_price(tp),
                "SL": format_price(sl),
                "RR": f"{rr:.2f}",
                "Time Left": f"{remaining:.0f}m",
                "Timeframe": data.get("timeframe", "5m")
            })
        
        if pending_data:
            df_pending = pd.DataFrame(pending_data)
            st.dataframe(df_pending, use_container_width=True, hide_index=True)
        
        # Card per coin
        st.caption("Detail per coin:")
        cols = st.columns(min(len(st.session_state.pending_signal), 4))
        for idx, (symbol, data) in enumerate(st.session_state.pending_signal.items()):
            col_idx = idx % len(cols)
            with cols[col_idx]:
                elapsed = (datetime.now() - data["time"]).seconds / 60
                remaining = max(0, hold_minutes - elapsed)
                entry = data.get("entry")
                sl = data.get("sl")
                tp = data.get("tp")
                
                if entry and sl and tp:
                    rr = (tp - entry) / (entry - sl) if (entry - sl) != 0 else 0
                else:
                    rr = 0
                
                st.markdown(f"""
                <div class="pending-signal">
                    <b>{symbol}</b><br>
                    {data['signal']}<br>
                    📈 Entry: {format_price(entry)}<br>
                    🎯 TP: {format_price(tp)}<br>
                    🛑 SL: {format_price(sl)}<br>
                    📊 RR: {rr:.2f}<br>
                    ⏱️ {remaining:.0f}m remaining
                </div>
                """, unsafe_allow_html=True)

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
                col4.metric("Volume Ratio", f"{result['volume_ratio']:.2f}x")
                
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
 
# ==================== TAB 3: POSITIONS (VERSION 2 - DATABASE) ====================
with tab3:
    st.subheader("📊 Portfolio Management")
    
    # ========== AMBIL DATA DARI DATABASE ==========
    portfolio_data = get_portfolio_summary()
    open_positions = portfolio_data["open_positions"]
    closed_positions = portfolio_data["closed_positions"]
    
    # ========== UPDATE POSISI YANG SEDANG BERJALAN ==========
    for pos in open_positions:
        symbol = pos["symbol"]
        position_id = pos["id"]
        entry = pos["entry_price"]
        sl = pos["stop_loss"]
        tp = pos["take_profit"]
        
        # Ambil harga terkini
        df = get_data_safe(symbol, "15m", min_candles=20)
        if df is not None:
            current_price = df["Close"].iloc[-1]
            
            # Update highest price untuk trailing stop
            highest = pos.get("highest_price", entry)
            if current_price > highest:
                highest = current_price
            
            # Hitung PNL
            pnl = (current_price - entry) * pos.get("position_size", 0)
            pnl_percent = (current_price / entry - 1) * 100
            
            # Update di database
            update_position_in_db(position_id, {
                "current_price": current_price,
                "highest_price": highest,
                "pnl": pnl,
                "pnl_percent": pnl_percent
            })
            
            # Cek kondisi exit
            exit_signal, exit_price = check_exit_conditions(
                {"entry": entry, "sl": sl, "tp": tp, "entry_time": pos["entry_time"]}, 
                df, 
                highest
            )
            
            # Auto exit jika ada sinyal
            if exit_signal:
                pnl_exit = (exit_price - entry) * pos.get("position_size", 0)
                pnl_percent_exit = (exit_price / entry - 1) * 100
                
                close_position_in_db(position_id, exit_price, exit_signal, pnl_exit, pnl_percent_exit)
                
                # Simpan ke signal_history
                save_signal({
                    'symbol': symbol,
                    'signal': f"EXIT - {exit_signal}",
                    'exit_price': exit_price,
                    'profit_pct': pnl_percent_exit,
                    'timestamp': datetime.now().isoformat()
                })
                
                st.rerun()
    
    # ========== REFRESH DATA SETELAH UPDATE ==========
    portfolio_data = get_portfolio_summary()
    open_positions = portfolio_data["open_positions"]
    closed_positions = portfolio_data["closed_positions"]
    
    # ========== PORTFOLIO SUMMARY (SEPERTI WALLET) ==========
    st.subheader("💰 Portfolio Summary")
    
    col1, col2, col3, col4, col5 = st.columns(5)
    
    # Total Equity (harga current semua posisi + cash - unrealized)
    total_equity = sum([p.get("current_price", 0) * p.get("position_size", 0) for p in open_positions])
    
    col1.metric(
        "📊 Total Equity", 
        f"${total_equity:,.2f}",
        delta=f"+${portfolio_data['total_pnl']:,.2f}" if portfolio_data['total_pnl'] >= 0 else f"-${abs(portfolio_data['total_pnl']):,.2f}"
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
        f"${portfolio_data['total_pnl']:,.2f}",
        delta=f"{(portfolio_data['total_pnl']/max(1, total_equity) * 100):.2f}%"
    )
    
    col5.metric(
        "🎯 Win Rate",
        f"{portfolio_data['win_rate']:.1f}%",
        delta=f"{portfolio_data['wins']}W / {portfolio_data['losses']}L"
    )
    
    st.divider()
    
    # ========== OPEN POSITIONS (TABEL) ==========
    st.subheader("📋 Open Positions")
    
    if open_positions:
        pos_data = []
        for pos in open_positions:
            pnl = pos.get("pnl", 0)
            pnl_percent = pos.get("pnl_percent", 0)
            
            # Warna PNL
            if pnl > 0:
                pnl_color = "🟢"
            elif pnl < 0:
                pnl_color = "🔴"
            else:
                pnl_color = "🟡"
            
            pos_data.append({
                "Coin": pos["symbol"],
                "Entry": format_price(pos["entry_price"]),
                "Current": format_price(pos.get("current_price", pos["entry_price"])),
                "SL": format_price(pos["stop_loss"]),
                "TP": format_price(pos["take_profit"]),
                "Size": f"{pos.get('position_size', 0):.4f}",
                "PNL": f"{pnl_color} ${pnl:.2f} ({pnl_percent:.2f}%)",
                "Entry Time": datetime.fromisoformat(pos["entry_time"]).strftime("%Y-%m-%d %H:%M")
            })
        
        df_open = pd.DataFrame(pos_data)
        st.dataframe(df_open, use_container_width=True, hide_index=True)
    else:
        st.info("📭 Tidak ada posisi terbuka")
    
    st.divider()
    
    # ========== CLOSED POSITIONS (TABEL) ==========
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
            
            closed_data.append({
                "Coin": pos["symbol"],
                "Entry": format_price(pos["entry_price"]),
                "Exit": format_price(pos.get("exit_price", pos["entry_price"])),
                "PNL": f"{pnl_color} ${pnl:.2f} ({pnl_percent:.2f}%)",
                "Exit Reason": f"{exit_emoji} {exit_reason}",
                "Exit Time": datetime.fromisoformat(pos["exit_time"]).strftime("%Y-%m-%d %H:%M")
            })
        
        df_closed = pd.DataFrame(closed_data)
        st.dataframe(df_closed, use_container_width=True, hide_index=True)
    else:
        st.info("Belum ada posisi yang ditutup")
    
    # ========== CLOSED POSITIONS SUMMARY ==========
    if closed_positions:
        st.divider()
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Trades", len(closed_positions))
        col2.metric("Wins", portfolio_data["wins"])
        col3.metric("Losses", portfolio_data["losses"])
        col4.metric("Win Rate", f"{portfolio_data['win_rate']:.1f}%")

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
📊 Indikator: MACD + Stochastic RSI + EMA20 + EMA50 + EMA100 + Volume  
💾 Database: Supabase PostgreSQL  
📌 Mode: SPOT (BUY & EXIT Only)
""")
