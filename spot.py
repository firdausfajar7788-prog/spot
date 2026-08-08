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
    page_title="🤖 Crypto Bot PRO - MACD + Stoch RSI",
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
    .signal-sell {
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
    supabase = get_supabase()
    try:
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
    # Cooldown 10 menit per coin
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
            msg = f"⚡ SIGNAL ALERT!\n\nCoin: {symbol}\nSignal: {signal}\nTime: {now.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
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
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            response = requests.post(url, json={"chat_id": chat_id, "text": msg}, timeout=10)
            if response.status_code == 200:
                st.session_state.sent_signals[signal_key] = True
                st.session_state.last_telegram_time[symbol] = now
                # Cleanup
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
# ALGORITMA TRADING - MACD + STOCHASTIC RSI
# =========================================================
def analyze_macd_stoch(df, timeframe=""):
    if df is None or len(df) < 30:
        return None
    macd_line, signal_line, histogram = MACD(df)
    stoch_k, stoch_d, rsi = StochasticRSI(df)
    ema20 = EMA(df, 20)
    ema50 = EMA(df, 50)
    
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
    
    macd_golden_cross = (macd_prev < signal_prev) and (macd_val > signal_val)
    macd_death_cross = (macd_prev > signal_prev) and (macd_val < signal_val)
    stoch_golden_cross = (stoch_k_prev < stoch_d_prev) and (stoch_k_val > stoch_d_val)
    stoch_death_cross = (stoch_k_prev > stoch_d_prev) and (stoch_k_val < stoch_d_val)
    
    hist_increasing = hist_val > hist_prev
    hist_decreasing = hist_val < hist_prev
    hist_positive = hist_val > 0
    hist_negative = hist_val < 0
    
    bullish_trend = price > ema20_val > ema50_val
    bearish_trend = price < ema20_val < ema50_val
    volume_confirmed = volume_ratio > 1.2
    
    buy_score = 0
    sell_score = 0
    reasons = []
    
    if macd_val > signal_val:
        buy_score += 1
    if hist_positive:
        buy_score += 1
    if macd_golden_cross:
        buy_score += 2
    if hist_increasing and hist_positive:
        buy_score += 1
    if stoch_k_val < 20 and stoch_d_val < 20:
        buy_score += 2
    elif 20 <= stoch_k_val <= 40 and stoch_k_val > stoch_d_val:
        buy_score += 1
    if stoch_golden_cross and stoch_k_val < 40:
        buy_score += 2
    if stoch_k_val > stoch_d_val:
        buy_score += 0.5
    if bullish_trend:
        buy_score += 1
    elif price > ema20_val:
        buy_score += 0.5
    if volume_confirmed:
        buy_score += 0.5
    if rsi_val < 70:
        buy_score += 0.5
    
    if macd_val < signal_val:
        sell_score += 1
    if hist_negative:
        sell_score += 1
    if macd_death_cross:
        sell_score += 2
    if hist_decreasing and hist_positive:
        sell_score += 1
    if stoch_k_val > 80 and stoch_d_val > 80:
        sell_score += 2
    elif 80 <= stoch_k_val <= 95:
        sell_score += 1
    if stoch_death_cross and stoch_k_val > 80:
        sell_score += 2
    if stoch_k_val < stoch_d_val:
        sell_score += 0.5
    if bearish_trend:
        sell_score += 1
    elif price < ema20_val:
        sell_score += 0.5
    if rsi_val > 30:
        sell_score += 0.5
    
    action = "⏳ WAIT"
    signal_type = "HOLD"
    signal_strength = 0
    if buy_score >= 5:
        if buy_score >= 7 and stoch_golden_cross and macd_golden_cross:
            signal_type = "⭐⭐⭐ STRONG BUY"
            signal_strength = 3
            action = "🟢 STRONG BUY"
        elif buy_score >= 6 and (macd_golden_cross or stoch_golden_cross):
            signal_type = "⭐⭐ BUY"
            signal_strength = 2
            action = "🟢 BUY"
        else:
            signal_type = "⭐ BUY"
            signal_strength = 1
            action = "🟢 BUY"
    elif sell_score >= 5:
        if sell_score >= 7 and stoch_death_cross and macd_death_cross:
            signal_type = "⭐⭐⭐ STRONG SELL"
            signal_strength = 3
            action = "🔴 STRONG SELL"
        elif sell_score >= 6 and (macd_death_cross or stoch_death_cross):
            signal_type = "⭐⭐ SELL"
            signal_strength = 2
            action = "🔴 SELL"
        else:
            signal_type = "⭐ SELL"
            signal_strength = 1
            action = "🔴 SELL"
    elif stoch_k_val > 85 and hist_decreasing and hist_positive:
        signal_type = "💰 TAKE PROFIT"
        signal_strength = 2
        action = "💰 TAKE PROFIT"
        reasons = ["Stoch >85", "Histogram mulai mengecil"]
    else:
        if macd_val > signal_val and 20 <= stoch_k_val <= 80:
            signal_type = "🟡 HOLD"
            action = "🟡 HOLD"
        elif macd_val > signal_val and stoch_k_val < 20:
            signal_type = "🟡 WAIT (Stoch oversold, tunggu golden cross)"
            action = "⏳ WAIT"
        elif macd_val < signal_val and stoch_k_val > 80:
            signal_type = "🟡 WAIT (Stoch overbought, tunggu death cross)"
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
        "score": {"buy": buy_score, "sell": sell_score},
        "reasons": reasons if action in ["BUY", "STRONG BUY"] else [],
        "macd": {
            "dif": macd_val,
            "dea": signal_val,
            "histogram": hist_val,
            "histogram_prev": hist_prev,
            "golden_cross": macd_golden_cross,
            "death_cross": macd_death_cross,
            "hist_increasing": hist_increasing,
            "hist_decreasing": hist_decreasing,
            "hist_positive": hist_positive,
            "hist_negative": hist_negative
        },
        "stoch": {
            "k": stoch_k_val,
            "d": stoch_d_val,
            "golden_cross": stoch_golden_cross,
            "death_cross": stoch_death_cross,
            "k_prev": stoch_k_prev,
            "d_prev": stoch_d_prev
        },
        "rsi": rsi_val,
        "ema20": ema20_val,
        "ema50": ema50_val,
        "price": price,
        "volume_ratio": volume_ratio,
        "bullish_trend": bullish_trend,
        "bearish_trend": bearish_trend
    }

# =========================================================
# MULTI TIMEFRAME ANALYSIS
# =========================================================
def analyze_mtf_macd_stoch(symbol, timeframes=["15m", "1h", "4h"]):
    results = {}
    for tf in timeframes:
        df = get_data_safe(symbol, tf, min_candles=50)
        if df is not None:
            result = analyze_macd_stoch(df, tf)
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
            elif "SELL" in res["action"]:
                sell_count += 1
            else:
                hold_count += 1
    main_signal = "⏳ WAIT"
    main_strength = 0
    if buy_count >= 2:
        main_signal = "🟢 STRONG BUY (Multi TF)"
        main_strength = 3
    elif buy_count == 1 and hold_count >= 1:
        main_signal = "🟢 BUY"
        main_strength = 2
    elif sell_count >= 2:
        main_signal = "🔴 STRONG SELL (Multi TF)"
        main_strength = 3
    elif sell_count == 1 and hold_count >= 1:
        main_signal = "🔴 SELL"
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
    fig = make_subplots(
        rows=4, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.35, 0.2, 0.25, 0.2],
        subplot_titles=(f"Price - {symbol} {timeframe}", "RSI", "MACD", "Stochastic RSI")
    )
    fig.add_trace(go.Candlestick(x=df["Time"], open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
                                 increasing_line_color="#00ff88", decreasing_line_color="#ff3b5c", name="Price"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df["Time"], y=ema20, line=dict(color="#00a2ff", width=1.5), name="EMA20"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df["Time"], y=ema50, line=dict(color="#ffaa00", width=1.5, dash="dash"), name="EMA50"), row=1, col=1)
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
                      title=dict(text=f"<b>{symbol} - {timeframe} Analysis</b>", font=dict(color="#f1f5f9", size=20),
                                 x=0.5, xanchor="center"),
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

# =========================================================
# MAIN TITLE
# =========================================================
st.title("🤖 Crypto Bot PRO - MACD + Stoch RSI")
st.caption("Multi Timeframe: 15M | 1H | 4H | MACD + Stochastic RSI + EMA + Volume")

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
        send_telegram_test("🚀 Telegram Connected! Scanner PRO Aktif.")
        st.success("✅ Pesan test terkirim!")
    st.divider()
    st.subheader("📊 Status")
    st.metric("Total Coins", len(st.session_state.watchlist))
    stats = get_performance()
    st.metric("Total Signals", stats.get('total_signals', 0))
    st.caption(f"🔄 Auto Refresh: {refresh} detik")

# =========================================================
# AUTO REFRESH
# =========================================================
st_autorefresh(interval=refresh * 1000, key="refresh")

# =========================================================
# MAIN TABS
# =========================================================
tab1, tab2, tab3, tab4 = st.tabs([
    "📊 Scanner", "📈 Chart Analysis", "📋 History", "📊 Performance"
])

# ==================== TAB 1: SCANNER ====================
with tab1:
    st.subheader("📊 Signal Scanner - MACD + Stochastic RSI")
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

    for idx, symbol in enumerate(st.session_state.watchlist[:20]):
        progress_bar.progress((idx + 1) / len(st.session_state.watchlist[:20]))
        status_text.text(f"🔄 Scanning {symbol}...")
        result = analyze_mtf_macd_stoch(symbol, ["15m", "1h", "4h"])
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
            all_signals.append(signal_data)

            # Simpan pending signal jika sinyal kuat (BUY/SELL)
            if result["main_strength"] >= 2 and ("BUY" in result["main_signal"] or "SELL" in result["main_signal"]):
                # Hitung entry, TP, SL sederhana (gunakan harga terakhir 5M)
                df_5m = get_data_safe(symbol, "5m", min_candles=20)
                if df_5m is not None:
                    price = df_5m["Close"].iloc[-1]
                    # Menggunakan ATR untuk SL/TP
                    atr = AverageTrueRange(df_5m["High"], df_5m["Low"], df_5m["Close"], window=14).average_true_range().iloc[-1]
                    if pd.isna(atr) or atr == 0:
                        atr = price * 0.01
                    if "BUY" in result["main_signal"]:
                        entry = price
                        sl = entry - atr * 3
                        tp = entry + atr * 7
                    else:
                        entry = price
                        sl = entry + atr * 3
                        tp = entry - atr * 7
                    # Simpan ke pending jika belum ada
                    if symbol not in st.session_state.pending_signal:
                        st.session_state.pending_signal[symbol] = {
                            "signal": result["main_signal"],
                            "time": datetime.now(),
                            "entry": entry,
                            "sl": sl,
                            "tp": tp,
                            "timeframe": "5m"
                        }
                        # Kirim telegram sekali
                        sent = send_telegram_once(symbol, result["main_signal"], result)
                        if sent:
                            save_signal({
                                'symbol': symbol,
                                'signal': result["main_signal"],
                                'timestamp': datetime.now().isoformat()
                            })
                            stats = get_performance()
                            stats['total_signals'] = stats.get('total_signals', 0) + 1
                            update_performance(stats)

    progress_bar.empty()
    status_text.empty()

    if all_signals:
        df_signals = pd.DataFrame(all_signals)
        st.dataframe(df_signals, use_container_width=True, hide_index=True)
        # Tampilkan best signal
        buy_signals = [s for s in all_signals if "BUY" in s["Signal"]]
        if buy_signals:
            best = buy_signals[0]
            st.success(f"🏆 Best Buy Signal: **{best['Coin']}** | {best['Signal']}")
    else:
        st.info("ℹ️ Tidak ada data")

    # ========== TAMPILAN PENDING SIGNALS (DENGAN ENTRY, TP, SL) ==========
    if st.session_state.pending_signal:
        st.divider()
        st.subheader("⏳ Pending Signals - Entry, TP, SL")
        st.caption("Sinyal yang masih aktif menunggu eksekusi")
        pending_data = []
        for symbol, data in st.session_state.pending_signal.items():
            elapsed = (datetime.now() - data["time"]).seconds / 60
            remaining = max(0, hold_minutes - elapsed)
            entry = data.get("entry")
            sl = data.get("sl")
            tp = data.get("tp")
            if entry and sl and tp:
                if "BUY" in data["signal"]:
                    rr = (tp - entry) / (entry - sl) if (entry - sl) != 0 else 0
                else:
                    rr = (entry - tp) / (sl - entry) if (sl - entry) != 0 else 0
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
                    if "BUY" in data["signal"]:
                        rr = (tp - entry) / (entry - sl) if (entry - sl) != 0 else 0
                    else:
                        rr = (entry - tp) / (sl - entry) if (sl - entry) != 0 else 0
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
    st.subheader("📈 Chart Analysis")
    chart_coin = st.selectbox("Select Coin", st.session_state.watchlist, key="chart_select")
    chart_tf = st.selectbox("Timeframe", ["15m", "1h", "4h"], index=1)
    if chart_coin:
        df = get_data_safe(chart_coin, chart_tf, min_candles=50)
        if df is not None:
            result = analyze_macd_stoch(df, chart_tf)
            if result:
                col1, col2, col3, col4 = st.columns(4)
                if "BUY" in result["action"]:
                    signal_html = f'<div class="signal-buy">{result["action"]}</div>'
                elif "SELL" in result["action"]:
                    signal_html = f'<div class="signal-sell">{result["action"]}</div>'
                elif "TAKE PROFIT" in result["action"]:
                    signal_html = f'<div class="signal-take-profit">{result["action"]}</div>'
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
                    st.write(f"**Trend:** {'🟢 Bullish' if result['bullish_trend'] else '🔴 Bearish' if result['bearish_trend'] else '🟡 Sideways'}")
                    st.write(f"**EMA20:** {result['ema20']:.4f}")
                    st.write(f"**EMA50:** {result['ema50']:.4f}")
                    st.write(f"**Buy Score:** {result['score']['buy']:.1f} | **Sell Score:** {result['score']['sell']:.1f}")
                fig = create_chart(df, chart_coin, chart_tf)
                if fig:
                    st.plotly_chart(fig, use_container_width=True)
        else:
            st.error(f"❌ Tidak bisa mendapatkan data untuk {chart_coin}")

# ==================== TAB 3: HISTORY ====================
with tab3:
    st.subheader("📜 Signal History")
    history = get_signal_history(limit=100)
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

# ==================== TAB 4: PERFORMANCE ====================
with tab4:
    st.subheader("📊 Performance Statistics")
    stats = get_performance()
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Signals", stats.get("total_signals", 0))
    col2.metric("Wins", stats.get("wins", 0))
    col3.metric("Losses", stats.get("losses", 0))
    col4.metric("Win Rate", f"{stats.get('win_rate', 0):.1f}%")
    st.divider()
    st.subheader("📈 Trading Rules Summary")
    rules = {
        "BUY ⭐⭐⭐⭐⭐": "MACD histogram > 0, DIF > DEA, Stoch RSI 10-30, Golden Cross",
        "BUY ⭐⭐⭐⭐": "MACD DIF > DEA, Stoch 20-40 & mengarah naik",
        "HOLD ⭐⭐⭐⭐": "MACD masih naik, Stoch RSI 30-70",
        "TAKE PROFIT ⭐⭐⭐⭐": "Stoch RSI >85, Histogram mulai mengecil",
        "SELL ⭐⭐⭐⭐⭐": "Stoch RSI death cross di atas 80, MACD bearish crossover"
    }
    for rule, desc in rules.items():
        st.write(f"**{rule}:** {desc}")

# =========================================================
# FOOTER
# =========================================================
st.divider()
st.caption(f"""
🔄 Data dari Yahoo Finance | Timeframe: 15M, 1H, 4H  
📊 Indikator: MACD + Stochastic RSI + EMA20 + EMA50 + Volume  
💾 Database: Supabase PostgreSQL
""")
