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
# DETEKSI WHIPSAW (False Breakout)
# =========================================================
def detect_whipsaw(df, lookback=20, buffer_pct=0.5):
    """
    Deteksi whipsaw: breakout palsu yang berbalik arah.
    - Harga menembus resistance/support
    - Tapi tidak bertahan (close kembali ke range)
    - Volume tidak mendukung breakout
    """
    if df is None or len(df) < lookback + 5:
        return {"is_whipsaw": False, "score": 0, "direction": "NONE", "reasons": []}
    
    # Ambil data terakhir
    high = df["High"]
    low = df["Low"]
    close = df["Close"]
    
    # Support & Resistance dari range
    recent_high = high.tail(lookback).max()
    recent_low = low.tail(lookback).min()
    range_mid = (recent_high + recent_low) / 2
    range_width = (recent_high - recent_low) / range_mid if range_mid != 0 else 0
    
    # Harga saat ini dan sebelumnya
    current_close = close.iloc[-1]
    prev_close = close.iloc[-2] if len(close) > 1 else current_close
    high_last = high.iloc[-1]
    low_last = low.iloc[-1]
    
    # Volume
    vol_ma = df["Volume"].rolling(10).mean().iloc[-1]
    vol_current = df["Volume"].iloc[-1]
    vol_ratio = vol_current / vol_ma if vol_ma > 0 else 1
    
    # Bollinger Band
    upper, middle, lower = BollingerBands(df, window=20, std=2)
    bb_upper = upper.iloc[-1] if not pd.isna(upper.iloc[-1]) else recent_high * 1.05
    bb_lower = lower.iloc[-1] if not pd.isna(lower.iloc[-1]) else recent_low * 0.95
    bb_middle = middle.iloc[-1] if not pd.isna(middle.iloc[-1]) else range_mid
    
    # ADX
    adx = ADX(df, 14)
    adx_now = adx.iloc[-1] if not pd.isna(adx.iloc[-1]) else 0
    
    # =========================================================
    # DETEKSI BREAKOUT PALSU (WHIPSAW)
    # =========================================================
    score = 0
    reasons = []
    direction = "NONE"
    is_whipsaw = False
    
    # === 1. FALSE BREAKOUT ATAS ===
    # Harga menembus resistance/BB atas, tapi kembali
    if high_last > recent_high * 1.005 or high_last > bb_upper:
        # Cek apakah close kembali ke bawah resistance
        if current_close < recent_high * 0.995:
            score += 3
            reasons.append("Fake breakout atas (kembali ke range)")
            direction = "FAKE_BREAKOUT_UP"
            
            # Cek volume (breakout harus tinggi, tapi tidak sustain)
            if vol_ratio < 1.2:
                score += 2
                reasons.append("Volume rendah, breakout tidak valid")
            if adx_now < 25:
                score += 1
                reasons.append("ADX rendah, tidak ada tren kuat")
            
            # Cek jika candle panjang naik lalu ditutup bearish
            if prev_close > current_close and high_last - low_last > range_width * 0.5:
                score += 2
                reasons.append("Candle panjang naik lalu ditutup turun")
    
    # === 2. FALSE BREAKOUT BAWAH ===
    # Harga menembus support/BB bawah, tapi kembali
    if low_last < recent_low * 0.995 or low_last < bb_lower:
        if current_close > recent_low * 1.005:
            score += 3
            reasons.append("Fake breakout bawah (kembali ke range)")
            direction = "FAKE_BREAKOUT_DOWN"
            
            if vol_ratio < 1.2:
                score += 2
                reasons.append("Volume rendah, breakout tidak valid")
            if adx_now < 25:
                score += 1
                reasons.append("ADX rendah, tidak ada tren kuat")
            
            if prev_close < current_close and high_last - low_last > range_width * 0.5:
                score += 2
                reasons.append("Candle panjang turun lalu ditutup naik")
    
    # === 3. SIDEWAYS + WHIPSAW ===
    # Jika harga masih dalam range tapi sering naik-turun
    if recent_high - recent_low < range_mid * 0.05:  # Range sempit
        if abs(current_close - prev_close) / prev_close > 0.01:  # Pergerakan >1%
            score += 1
            reasons.append("Range sempit tapi volatilitas tinggi (whipsaw)")
    
    # === 4. CLOSE DI TENGAH RANGE ===
    # Jika close dekat dengan middle range setelah breakout
    if abs(current_close - range_mid) / range_mid < 0.01:
        if score >= 3:
            score += 1
            reasons.append("Close di tengah range, konfirmasi whipsaw")
    
    # === 5. MACD DIVERGENCE ===
    macd_line, signal_line, histogram = MACD(df)
    if len(macd_line) > 10:
        macd_hist_prev = histogram.iloc[-2] if len(histogram) > 1 else 0
        macd_hist_now = histogram.iloc[-1]
        
        # Histogram menurun setelah breakout
        if macd_hist_now < macd_hist_prev and score >= 3:
            score += 1
            reasons.append("MACD histogram menurun (momentum hilang)")
    
    # =========================================================
    # KEPUTUSAN
    # =========================================================
    if score >= 5:
        is_whipsaw = True
        if "FAKE_BREAKOUT_UP" in direction:
            status = "🔴 FALSE BREAKOUT UP (Sell Signal)"
        elif "FAKE_BREAKOUT_DOWN" in direction:
            status = "🔴 FALSE BREAKOUT DOWN (Buy Signal)"
        else:
            status = "🟡 WHIPSAW DETECTED"
    elif score >= 3:
        is_whipsaw = True
        status = "🟡 POTENTIAL WHIPSAW"
    else:
        status = "🟢 NO WHIPSAW"
    
    return {
        "is_whipsaw": is_whipsaw,
        "score": score,
        "status": status,
        "direction": direction,
        "reasons": reasons,
        "range_high": recent_high,
        "range_low": recent_low,
        "range_width": range_width,
        "adx": adx_now,
        "vol_ratio": vol_ratio
    }


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
# POSITIONS DATABASE FUNCTIONS
# =========================================================

def save_position_to_db(symbol, entry, sl, tp, position_size=1):
    """Simpan posisi baru ke database"""
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
    """Dapatkan summary portofolio dari database"""
    supabase = get_supabase()
    try:
        open_positions = get_open_positions_from_db()
        closed_positions = get_closed_positions_from_db(limit=100)
        
        # Total equity
        total_equity = sum([p.get("current_price", 0) * p.get("position_size", 1) for p in open_positions])
        
        # Unrealized PNL (dari open positions)
        unrealized_pnl = sum([p.get("pnl", 0) for p in open_positions])
        unrealized_pnl_percent = sum([p.get("pnl_percent", 0) for p in open_positions])
        
        # Realized PNL (dari closed positions)
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
        print(f"Error get portfolio summary: {e}")
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

        # ========== TAMBAHKAN DETEKSI WHIPSAW ==========
    whipsaw = detect_whipsaw(df, lookback=20, buffer_pct=0.5)
    
    # ========== MODIFIKASI KEPUTUSAN ==========
    # Jika whipsaw terdeteksi, jangan entry
    if whipsaw["is_whipsaw"]:
        buy_score = max(0, buy_score - 3)  # Kurangi buy score
        exit_score = max(0, exit_score - 1)
        reasons.append(f"⚠️ {whipsaw['status']}")
        
        # Jika false breakout, arah sebaliknya
        if "FAKE_BREAKOUT_UP" in whipsaw["direction"]:
            # False breakout up = harga akan turun
            sell_score += 2
            reasons.append("🔴 Fake breakout up, bias bearish")
        elif "FAKE_BREAKOUT_DOWN" in whipsaw["direction"]:
            # False breakout down = harga akan naik
            buy_score += 1
            reasons.append("🟢 Fake breakout down, bias bullish")
    
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

def analyze_mtf_macd_stoch_spot(symbol, timeframes=["15m", "1h", "4h"]):
    """Analisis multi timeframe untuk SPOT - 3 dari 3 bullish"""
    results = {}
    
    for tf in timeframes:
        try:
            df = get_data_safe(symbol, tf, min_candles=50)
            if df is not None:
                result = analyze_macd_stoch_spot(df, tf)
                if result:
                    result["symbol"] = symbol
                    results[tf] = result
        except Exception as e:
            print(f"Error getting data for {symbol} {tf}: {e}")
            continue
    
    if not results:
        return None
    
    combined = {"symbol": symbol, "timeframes": results}
    buy_count = 0
    sell_count = 0
    hold_count = 0
        # ========== TAMBAHKAN UNTUK WHIPSAW ==========
    whipsaw_scores = []
    whipsaw_status = []
    
    for tf in ["4h", "1h", "15m"]:
        if tf in results:
            res = results[tf]
            if "BUY" in res["action"]:
                buy_count += 1
            elif "EXIT" in res["action"]:
                sell_count += 1
            else:
                hold_count += 1

                # Kumpulkan whipsaw dari setiap timeframe
            if "whipsaw" in res:
                whipsaw_scores.append(res["whipsaw"]["score"])
                whipsaw_status.append(res["whipsaw"]["status"])

        # ========== WHIPSAW MULTI TIMEFRAME ==========
    # Jika whipsaw terdeteksi di 2+ timeframe, tandai
    whipsaw_count = sum(1 for s in whipsaw_status if "WHIPSAW" in s or "FALSE" in s)
    whipsaw_avg_score = sum(whipsaw_scores) / len(whipsaw_scores) if whipsaw_scores else 0
    
    combined["whipsaw_detected"] = whipsaw_count >= 2
    combined["whipsaw_score"] = whipsaw_avg_score
    combined["whipsaw_status"] = "🔴 WHIPSAW" if whipsaw_count >= 2 else "🟢 CLEAR"
    
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

    if combined["whipsaw_detected"]:
    main_strength = max(1, main_strength - 1)
    main_signal += " ⚠️ WHIPSAW"
    
    combined["main_signal"] = main_signal
    combined["main_strength"] = main_strength
    combined["buy_count"] = buy_count
    combined["sell_count"] = sell_count
    combined["hold_count"] = hold_count
    combined["total_score"] = 50 + (buy_count * 10)  # Tambahan untuk score
    
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
    entry_time = position.get("entry_time")
    if entry_time:
        # Pastikan entry_time adalah datetime
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

# 🔥 TAMBAHKAN INI UNTUK KONTROL REFRESH
if "last_refresh" not in st.session_state:
    st.session_state.last_refresh = datetime.now()
if "last_scan" not in st.session_state:
    st.session_state.last_scan = datetime.now()
if "is_processing" not in st.session_state:
    st.session_state.is_processing = False
if "scan_results" not in st.session_state:
    st.session_state.scan_results = []

# 🔥 LOAD POSITIONS DARI DATABASE
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
    refresh = st.slider("🔄 Refresh (detik)", 15, 120, 30)
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
    
    # ========== CEK APAKAH PERLU SCAN ==========
    now = datetime.now()
    time_since_scan = (now - st.session_state.get("last_scan", now)).seconds
    
    # Hanya scan jika sudah lewat 30 detik
    if time_since_scan > 30 or "last_scan" not in st.session_state:
        st.session_state.last_scan = now
        
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
                    signal_data = {
                        "Coin": symbol,
                        "Signal": result["main_signal"],
                        "Strength": "⭐" * result.get("main_strength", 1),
                                            # ========== TAMBAHKAN WHIPSAW ==========
                        "Whipsaw": result.get("whipsaw_status", "🟢 CLEAR"),
                        "Whipsaw Score": f"{result.get('whipsaw_score', 0):.1f}",
                        # =======================================
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

                    # CEK POSISI DI DATABASE
                    existing_positions = get_open_positions_from_db()
                    existing_symbols = [p["symbol"] for p in existing_positions]
                    
                    # SIMPAN POSISI JIKA BUY
                    if result["main_strength"] >= 2 and "BUY" in result["main_signal"]:
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
                                position_size = 1
                                
                                st.session_state.pending_signal[symbol] = {
                                    "signal": result["main_signal"],
                                    "time": datetime.now(),
                                    "entry": entry,
                                    "sl": sl,
                                    "tp": tp,
                                    "timeframe": "5m"
                                }
                                
                                saved_pos = save_position_to_db(symbol, entry, sl, tp, position_size)
                                if saved_pos:
                                    st.session_state.positions[symbol] = {
                                        "entry": entry,
                                        "sl": sl,
                                        "tp": tp,
                                        "entry_time": datetime.now(),
                                        "highest_price": entry,
                                        "id": saved_pos["id"],
                                        "position_size": position_size
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
                    
                    # SIMPAN EXIT
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
        
        # Simpan hasil scan ke session state
        st.session_state.scan_results = all_signals
    else:
        # Gunakan hasil scan sebelumnya
        all_signals = st.session_state.get("scan_results", [])

    # ========== TAMPILKAN HASIL ==========
    if all_signals:
        df_signals = pd.DataFrame(all_signals)
        st.dataframe(df_signals, use_container_width=True, hide_index=True)
        
        buy_signals = [s for s in all_signals if "BUY" in s["Signal"]]
        if buy_signals:
            best = buy_signals[0]
            st.success(f"🏆 Best Buy Signal: **{best['Coin']}** | {best['Signal']}")
        else:
            st.info("ℹ️ Tidak ada sinyal BUY saat ini")
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
                    if "whipsaw" in result:
                    ws = result["whipsaw"]
                    st.write(f"**Whipsaw Status:** {ws['status']}")
                    st.write(f"**Whipsaw Score:** {ws['score']}/10")
                    if ws["reasons"]:
                        for reason in ws["reasons"]:
                            st.write(f"  • {reason}")
                    st.write(f"**Range:** ${ws['range_low']:.4f} - ${ws['range_high']:.4f}")
                    st.write(f"**ADX:** {ws['adx']:.1f} | **Volume Ratio:** {ws['vol_ratio']:.2f}x")
                    fig = create_chart(df, chart_coin, chart_tf)
                    if fig:
                        st.plotly_chart(fig, use_container_width=True)
            else:
                st.error(f"❌ Tidak bisa mendapatkan data untuk {chart_coin}")

# ==================== TAB 3: POSITIONS ====================
# ==================== TAB 3: POSITIONS ====================
with tab3:
    st.subheader("📋 Open Positions - SPOT")
    
    # ========== CEK APAKAH PERLU UPDATE ==========
    now = datetime.now()
    time_since_refresh = (now - st.session_state.get("last_refresh", now)).seconds
    show_whipsaw = st.checkbox("⚠️ Show whipsaw positions", value=False)
    
    if not show_whipsaw:
        # Filter posisi yang tidak whipsaw
        # (Ini hanya contoh, sesuaikan dengan logika Anda)
        pass
    # =============================================
    
    # Hanya update jika sudah lewat 30 detik atau positions kosong
    if time_since_refresh > 30 or not st.session_state.positions:
        st.session_state.last_refresh = now
        
        # ========== UPDATE POSISI ==========
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
                
                position_for_exit = {
                    "entry": pos["entry"],
                    "sl": pos.get("sl"),
                    "tp": pos.get("tp"),
                    "entry_time": entry_time
                }
                
                exit_signal, exit_price = check_exit_conditions(
                    position_for_exit, 
                    df, 
                    highest
                )
                
                pos["current_price"] = current_price
                pos["highest_price"] = highest
                
                if exit_signal:
                    # Hitung PNL
                    pnl = (exit_price - pos["entry"]) * pos.get("position_size", 1)
                    pnl_percent = (exit_price / pos["entry"] - 1) * 100
                    
                    # ========== UPDATE KE DATABASE ==========
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
                    
            except Exception as e:
                updated_positions[symbol] = pos
                print(f"Error updating {symbol}: {e}")
        
        # Hapus posisi yang sudah exit
        for symbol in positions_to_remove:
            if symbol in st.session_state.positions:
                del st.session_state.positions[symbol]
        
        st.session_state.positions = updated_positions
    
    # ========== TAMPILKAN OPEN POSITIONS ==========
    if st.session_state.positions:
        pos_data = []
        for symbol, pos in st.session_state.positions.items():
            try:
                current_price = pos.get("current_price", pos["entry"])
                pnl_percent = (current_price / pos['entry'] - 1) * 100
                pnl = (current_price - pos['entry']) * pos.get("position_size", 1)
                
                if pnl > 0:
                    pnl_color = "🟢"
                elif pnl < 0:
                    pnl_color = "🔴"
                else:
                    pnl_color = "🟡"
                
                entry_time = pos.get("entry_time")
                if isinstance(entry_time, datetime):
                    entry_time_str = entry_time.strftime("%Y-%m-%d %H:%M")
                else:
                    entry_time_str = str(entry_time)[:16] if entry_time else ""
                
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
            except Exception as e:
                continue
        
        if pos_data:
            df_pos = pd.DataFrame(pos_data)
            st.dataframe(df_pos, use_container_width=True, hide_index=True)
            
            # ========== SUMMARY STATISTICS ==========
            st.divider()
            st.subheader("📊 Portfolio Summary")
            
            total_positions = len(pos_data)
            total_profit = 0
            winning_positions = 0
            losing_positions = 0
            
            for p in pos_data:
                pnl_str = p["PNL"].replace("🟢", "").replace("🔴", "").replace("🟡", "").replace("$", "").replace("(", "").replace(")", "").replace("%", "").strip()
                try:
                    # Ambil angka pertama sebelum spasi
                    parts = pnl_str.split()
                    if parts:
                        profit = float(parts[0])
                        total_profit += profit
                        if profit > 0:
                            winning_positions += 1
                        elif profit < 0:
                            losing_positions += 1
                except:
                    pass
            
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Total Positions", total_positions)
            col2.metric("Winning", winning_positions)
            col3.metric("Losing", losing_positions)
            col4.metric("Total PNL", f"${total_profit:.2f}")
    else:
        st.info("📭 Tidak ada posisi terbuka")
    
    st.divider()
    
    # ========== CLOSED POSITIONS (DARI DATABASE) ==========
    st.subheader("📊 Closed Positions")
    
    # ========== AMBIL DARI DATABASE ==========
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
                
                if pnl > 0:
                    pnl_color = "🟢"
                    wins += 1
                elif pnl < 0:
                    pnl_color = "🔴"
                    losses += 1
                else:
                    pnl_color = "🟡"
                
                total_profit_closed += pnl
                
                exit_reason = pos.get("exit_reason", "UNKNOWN")
                exit_emoji = "✅" if "TP" in exit_reason else "❌" if "SL" in exit_reason else "🔄"
                
                entry_time = pos.get("entry_time", "")
                if entry_time and isinstance(entry_time, str):
                    try:
                        entry_time = datetime.fromisoformat(entry_time.replace('Z', '+00:00')).strftime("%Y-%m-%d %H:%M")
                    except:
                        entry_time = entry_time[:16] if len(entry_time) > 16 else entry_time
                
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
                    "Entry Time": entry_time,
                    "Exit Time": exit_time
                })
            except Exception as e:
                continue
        
        if closed_data:
            df_closed = pd.DataFrame(closed_data)
            st.dataframe(df_closed, use_container_width=True, hide_index=True)
            
            # ========== CLOSED POSITIONS SUMMARY ==========
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

        # Ambil data history dan hitung whipsaw
    history = get_signal_history(limit=200)
    if history:
        whipsaw_count = len([h for h in history if "WHIPSAW" in h.get("signal", "")])
        total_signals = len(history)
        whipsaw_percent = (whipsaw_count / total_signals * 100) if total_signals > 0 else 0
        
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Signals", total_signals)
        col2.metric("Whipsaw Signals", whipsaw_count)
        col3.metric("Whipsaw Rate", f"{whipsaw_percent:.1f}%")
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
