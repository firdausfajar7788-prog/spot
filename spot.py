import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import yfinance as yf
import requests
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from streamlit_autorefresh import st_autorefresh
from datetime import datetime, timedelta
import time
import json

# =========================================================
# PAGE CONFIG
# =========================================================
st.set_page_config(
    page_title="🐢 Crypto Spot Scanner PRO",
    layout="wide",
    initial_sidebar_state="expanded"
)

# =========================================================
# CSS KUSTOM
# =========================================================
st.markdown("""
<style>
    .stApp {
        background: #0a0a1a;
    }
    
    [data-testid="stMetric"] {
        background: linear-gradient(145deg, #111827, #0b1220);
        border: 1px solid #1e293b;
        border-radius: 16px;
        padding: 16px;
        box-shadow: 0 4px 20px rgba(0,255,255,0.05);
        transition: all 0.3s ease;
    }
    [data-testid="stMetric"]:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 30px rgba(0,255,255,0.1);
    }
    [data-testid="stMetricLabel"] {
        color: #94a3b8;
        font-size: 13px;
        font-weight: 500;
    }
    [data-testid="stMetricValue"] {
        color: #f1f5f9;
        font-size: 24px;
        font-weight: 700;
    }
    
    .signal-buy {
        background: linear-gradient(135deg, rgba(0,255,136,0.15), rgba(0,255,136,0.05));
        border: 1px solid #00ff88;
        border-radius: 12px;
        padding: 12px 20px;
        color: #00ff88;
        font-weight: 600;
        font-size: 18px;
        box-shadow: 0 0 30px rgba(0,255,136,0.1);
    }
    .signal-sell {
        background: linear-gradient(135deg, rgba(255,59,92,0.15), rgba(255,59,92,0.05));
        border: 1px solid #ff3b5c;
        border-radius: 12px;
        padding: 12px 20px;
        color: #ff3b5c;
        font-weight: 600;
        font-size: 18px;
        box-shadow: 0 0 30px rgba(255,59,92,0.1);
    }
    .signal-wait {
        background: linear-gradient(135deg, rgba(255,170,0,0.15), rgba(255,170,0,0.05));
        border: 1px solid #ffaa00;
        border-radius: 12px;
        padding: 12px 20px;
        color: #ffaa00;
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
    
    .position-card {
        background: linear-gradient(145deg, #111827, #0b1220);
        border: 1px solid #1e293b;
        border-radius: 12px;
        padding: 16px;
        margin: 8px 0;
        transition: all 0.3s ease;
    }
    .position-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 30px rgba(0,255,255,0.1);
    }
    .position-profit {
        color: #00ff88;
        font-weight: 700;
    }
    .position-loss {
        color: #ff3b5c;
        font-weight: 700;
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
        box-shadow: 0 0 30px rgba(0,255,136,0.3);
    }
    
    .risk-badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 12px;
        font-weight: 600;
    }
    .risk-low {
        background: rgba(0,255,136,0.2);
        color: #00ff88;
        border: 1px solid rgba(0,255,136,0.3);
    }
    .risk-medium {
        background: rgba(255,170,0,0.2);
        color: #ffaa00;
        border: 1px solid rgba(255,170,0,0.3);
    }
    .risk-high {
        background: rgba(255,59,92,0.2);
        color: #ff3b5c;
        border: 1px solid rgba(255,59,92,0.3);
    }
</style>
""", unsafe_allow_html=True)

# =========================================================
# GOOGLE SHEETS CONNECTION
# =========================================================
@st.cache_resource
def load_sheet():
    try:
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(
            dict(st.secrets["gcp_service_account"]),
            scope
        )
        client = gspread.authorize(creds)
        return client.open("CryptoWatchlist").sheet1
    except Exception as e:
        st.error(f"❌ Gagal konek ke Google Sheets: {e}")
        return None

# =========================================================
# FUNGSI MANAJEMEN WATCHLIST
# =========================================================
def get_watchlist():
    sheet = load_sheet()
    if sheet:
        try:
            symbols = sheet.col_values(1)
            watchlist = [x.strip().upper() for x in symbols if x.strip()]
            if watchlist:
                return watchlist
        except:
            pass
    return ["BTC", "ETH", "SOL", "ADA", "XRP", "DOGE", "AVAX", "LINK"]

def add_coin_to_watchlist(coin):
    sheet = load_sheet()
    if sheet:
        try:
            sheet.append_row([coin.upper().strip()])
            return True
        except:
            return False
    return False

def remove_coin_from_watchlist(coin):
    sheet = load_sheet()
    if sheet:
        try:
            cell = sheet.find(coin.upper().strip())
            if cell:
                sheet.delete_rows(cell.row)
                return True
        except:
            return False
    return False

# =========================================================
# INISIALISASI SESSION STATE
# =========================================================
if "watchlist" not in st.session_state:
    st.session_state.watchlist = get_watchlist()

if "last_alert" not in st.session_state:
    st.session_state.last_alert = {}

if "selected_coin" not in st.session_state:
    st.session_state.selected_coin = st.session_state.watchlist[0] if st.session_state.watchlist else "BTC"

if "pending_signal" not in st.session_state:
    st.session_state.pending_signal = {}

if "active_positions" not in st.session_state:
    st.session_state.active_positions = {}

if "signal_history" not in st.session_state:
    st.session_state.signal_history = []

if "performance_stats" not in st.session_state:
    st.session_state.performance_stats = {
        "total_signals": 0,
        "wins": 0,
        "losses": 0,
        "total_profit": 0,
        "winning_trades": [],
        "losing_trades": []
    }

if "last_daily_update" not in st.session_state:
    st.session_state.last_daily_update = datetime.now() - timedelta(days=1)

# =========================================================
# TELEGRAM FUNCTIONS
# =========================================================
def send_telegram(message):
    try:
        BOT_TOKEN = st.secrets.get("TELEGRAM_BOT_TOKEN", "8819178689:AAHBU4dTqoIUfGvkarKRZLI6wbfKJh6g0RU")
        CHAT_ID = st.secrets.get("TELEGRAM_CHAT_ID", "999556266")
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        response = requests.post(url, json={"chat_id": CHAT_ID, "text": message}, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"Telegram error: {e}")
        return False

def send_telegram_with_photo(caption, image_path):
    """Kirim notifikasi dengan gambar"""
    try:
        BOT_TOKEN = st.secrets.get("TELEGRAM_BOT_TOKEN", "8819178689:AAHBU4dTqoIUfGvkarKRZLI6wbfKJh6g0RU")
        CHAT_ID = st.secrets.get("TELEGRAM_CHAT_ID", "999556266")
        
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
        with open(image_path, 'rb') as photo:
            files = {'photo': photo}
            data = {'chat_id': CHAT_ID, 'caption': caption}
            response = requests.post(url, files=files, data=data)
        return response.status_code == 200
    except Exception as e:
        print(f"Telegram photo error: {e}")
        return False

# =========================================================
# TITLE
# =========================================================
st.title("🐢 Crypto Spot Scanner PRO")
st.caption("Daily & 4H Analysis for Spot Trading | Risk Management 2% per Trade")

# =========================================================
# SIDEBAR
# =========================================================
with st.sidebar:
    st.header("⚙️ Settings")
    
    st.subheader("📋 Watchlist")
    
    sheet = load_sheet()
    if sheet:
        st.success("✅ Google Sheets Connected")
    else:
        st.error("❌ Google Sheets Error")
    
    col_add1, col_add2 = st.columns([3, 1])
    with col_add1:
        new_coin = st.text_input("Add Coin", placeholder="PEPE", label_visibility="collapsed")
    with col_add2:
        if st.button("➕", use_container_width=True):
            if new_coin:
                coin = new_coin.upper().strip()
                if coin not in st.session_state.watchlist:
                    if add_coin_to_watchlist(coin):
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
                if remove_coin_from_watchlist(coin):
                    st.session_state.watchlist.remove(coin)
                    st.rerun()
                else:
                    st.error(f"❌ Gagal hapus {coin}!")
    
    st.divider()
    
    st.subheader("📊 Trading Settings")
    refresh = st.slider("🔄 Refresh (menit)", 1, 30, 5, help="Refresh interval untuk scan")
    currency = st.selectbox("💱 Currency", ["USD", "IDR"])
    
    st.subheader("💰 Risk Management (Spot)")
    total_capital = st.number_input("Total Capital (USD)", 100, 100000, 10000, step=100)
    risk_per_trade = st.slider("Risk per Trade (%)", 0.5, 5.0, 2.0, 0.5)
    max_positions = st.slider("Max Positions", 1, 10, 5)
    
    st.subheader("🎯 Entry Strategy")
    rr_sl = st.slider(
        "Stop Loss (ATR)",
        min_value=3.0,
        max_value=8.0,
        value=5.0,
        step=0.5,
        help="SL untuk spot lebih longgar (5-8 ATR)"
    )
    rr_tp = st.slider(
        "Take Profit (ATR)",
        min_value=8.0,
        max_value=20.0,
        value=12.0,
        step=0.5,
        help="TP untuk spot lebih besar (10-15 ATR)"
    )
    
    use_trailing = st.toggle(
        "🚀 Use Trailing Stop",
        value=True,
        help="Trailing stop dengan 1.5 ATR untuk mengunci profit"
    )
    
    min_confirmations = st.slider(
        "Minimal Konfirmasi",
        min_value=1,
        max_value=3,
        value=2,
        help="Butuh minimal berapa konfirmasi sebelum entry"
    )
    
    st.divider()
    
    st.subheader("📱 Telegram Settings")
    send_telegram_alerts = st.checkbox("✅ Send Telegram Alerts", value=True)
    send_daily_update = st.checkbox("📊 Send Daily Update", value=True)
    send_chart_with_signal = st.checkbox("📈 Send Chart with Signal", value=False)
    
    if st.button("🚀 Test Telegram", use_container_width=True):
        if send_telegram("🐢 Spot Scanner PRO Connected!"):
            st.success("✅ Pesan test terkirim!")
        else:
            st.error("❌ Gagal kirim pesan!")
    
    st.divider()
    
    st.subheader("📊 Status")
    st.metric("Total Coins", len(st.session_state.watchlist))
    st.metric("Active Positions", len(st.session_state.active_positions))
    st.metric("Pending Signals", len(st.session_state.pending_signal))
    win_rate = (st.session_state.performance_stats['wins'] / max(1, st.session_state.performance_stats['total_signals']) * 100)
    st.metric("Win Rate", f"{win_rate:.1f}%")

# =========================================================
# AUTO REFRESH
# =========================================================
st_autorefresh(interval=refresh * 60 * 1000, key="refresh")

# =========================================================
# USD TO IDR
# =========================================================
@st.cache_data(ttl=3600)
def get_usd_idr():
    try:
        url = "https://open.er-api.com/v6/latest/USD"
        response = requests.get(url, timeout=10)
        data = response.json()
        return data["rates"]["IDR"]
    except:
        return 16000

usd_to_idr = get_usd_idr()
currency_rate = usd_to_idr if currency == "IDR" else 1
currency_symbol = "Rp" if currency == "IDR" else "$"

# =========================================================
# FORMAT PRICE
# =========================================================
def format_price(value):
    if pd.isna(value) or value is None:
        return "-"
    if currency == "IDR":
        return f"Rp {value:,.0f}"
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

def format_percentage(value):
    if pd.isna(value) or value is None:
        return "-"
    return f"{value:+.1f}%"

# =========================================================
# GET DATA - SPOT TIMEFRAMES
# =========================================================
@st.cache_data(ttl=60)
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

def get_data_safe(symbol, interval, min_candles=30):
    periods = {
        "15m": ["5d", "7d", "14d", "30d"],
        "1h": ["7d", "14d", "30d", "60d"],
        "4h": ["14d", "30d", "60d", "90d"],
        "1d": ["30d", "60d", "90d", "1y", "2y"],
        "1wk": ["1y", "2y", "5y"]
    }
    for period in periods.get(interval, ["30d", "60d", "90d"]):
        df = get_data(symbol, interval, period)
        if df is not None and len(df) >= min_candles:
            return df
    return None

# =========================================================
# INDIKATOR TEKNIKAL
# =========================================================
def EMA(df, period=20):
    return df["Close"].ewm(span=period, adjust=False).mean()

def SMA(df, period=20):
    return df["Close"].rolling(period).mean()

def RSI(df, period=14):
    delta = df["Close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def MACD(df):
    ema12 = EMA(df, 12)
    ema26 = EMA(df, 26)
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal
    return macd, signal, hist

def ATR(df, period=14):
    high_low = df["High"] - df["Low"]
    high_close = abs(df["High"] - df["Close"].shift())
    low_close = abs(df["Low"] - df["Close"].shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def ADX(df, period=14):
    try:
        high = df["High"]
        low = df["Low"]
        close = df["Close"]
        plus_dm = high.diff()
        minus_dm = low.diff()
        plus_dm[plus_dm < 0] = 0
        minus_dm[minus_dm > 0] = 0
        tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
        atr = tr.rolling(period).mean()
        plus_di = 100 * (plus_dm.rolling(period).mean() / atr)
        minus_di = 100 * (minus_dm.abs().rolling(period).mean() / atr)
        dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
        return dx.rolling(period).mean()
    except:
        return pd.Series([0] * len(df))

def BollingerBands(df, period=20, std=2):
    sma = df["Close"].rolling(period).mean()
    rolling_std = df["Close"].rolling(period).std()
    upper = sma + (rolling_std * std)
    lower = sma - (rolling_std * std)
    return upper, sma, lower

# =========================================================
# FUNGSI ANALISIS TREND
# =========================================================
def analyze_trend(df, timeframe_name):
    if df is None or len(df) < 20:
        return "⚠️ Insufficient Data"
    
    df = df.copy()
    df["EMA20"] = EMA(df, 20)
    df["EMA50"] = EMA(df, 50)
    df["ADX"] = ADX(df)
    
    last = df.iloc[-1]
    price = last["Close"]
    ema20 = last["EMA20"] if not pd.isna(last["EMA20"]) else price
    ema50 = last["EMA50"] if not pd.isna(last["EMA50"]) else price
    adx = last["ADX"] if not pd.isna(last["ADX"]) else 0
    
    if price > ema20 > ema50 and adx > 25:
        return "🟢 STRONG BULLISH"
    elif price > ema20 > ema50:
        return "🟢 BULLISH"
    elif price < ema20 < ema50 and adx > 25:
        return "🔴 STRONG BEARISH"
    elif price < ema20 < ema50:
        return "🔴 BEARISH"
    else:
        return "🟡 SIDEWAYS"

# =========================================================
# RISK MANAGEMENT - SPOT VERSION
# =========================================================
def calculate_position_size(entry_price, stop_loss, total_capital, risk_per_trade):
    """Hitung ukuran posisi untuk spot trading"""
    if stop_loss is None or entry_price is None:
        return 0
    
    risk_amount = total_capital * (risk_per_trade / 100)
    risk_per_unit = abs(entry_price - stop_loss)
    
    if risk_per_unit == 0:
        return 0
    
    position_size = risk_amount / risk_per_unit
    
    # Maksimum 50% dari modal untuk satu posisi
    max_position = (total_capital * 0.5) / entry_price
    position_size = min(position_size, max_position)
    
    return position_size

def calculate_risk_management_spot(df, entry_signal, entry_price, rr_sl=5.0, rr_tp=12.0, use_trailing=True):
    """Risk management untuk spot dengan RR 5:12"""
    
    # ATR periode 20 untuk stabilitas
    atr = ATR(df, period=20)
    atr_value = atr.iloc[-1] if len(atr) > 0 and not pd.isna(atr.iloc[-1]) else 0.01
    
    # Minimal ATR 1% dari harga untuk spot
    min_atr = entry_price * 0.01
    atr_value = max(atr_value, min_atr)
    
    # === HITUNG SL & TP ===
    if entry_signal and "BUY" in entry_signal:
        stop_loss = entry_price - atr_value * rr_sl
        take_profit = entry_price + atr_value * rr_tp
        
        # Trailing stop untuk BUY
        if use_trailing and len(df) > 10:
            highest_high = df["High"].tail(10).max()
            new_sl = max(highest_high - atr_value * 1.5, stop_loss)
            stop_loss = max(new_sl, stop_loss)
        
    elif entry_signal and "SELL" in entry_signal:
        stop_loss = entry_price + atr_value * rr_sl
        take_profit = entry_price - atr_value * rr_tp
        
        # Trailing stop untuk SELL
        if use_trailing and len(df) > 10:
            lowest_low = df["Low"].tail(10).min()
            new_sl = min(lowest_low + atr_value * 1.5, stop_loss)
            stop_loss = min(new_sl, stop_loss)
    
    else:
        stop_loss = take_profit = None
    
    # Validasi: SL minimal 2%
    if stop_loss and abs(stop_loss - entry_price) / entry_price < 0.02:
        stop_loss = entry_price * 0.98 if entry_signal and "BUY" in entry_signal else entry_price * 1.02
    
    return stop_loss, take_profit, atr_value

# =========================================================
# ANALISIS SPOT (DAILY TIMEFRAME)
# =========================================================
def analyze_spot(symbol, buffer_pct=0.5, rr_sl=5.0, rr_tp=12.0, use_trailing=True, min_confirmations=2):
    """
    Analisis khusus untuk spot trading dengan timeframe daily
    """
    # --- DAILY (Trend Utama) ---
    df_daily = get_data_safe(symbol, "1d", min_candles=50)
    if df_daily is None:
        return None
    
    # --- 4H (Momentum) ---
    df_4h = get_data_safe(symbol, "4h", min_candles=50)
    if df_4h is None:
        df_4h = df_daily.copy()
    
    # --- 1H (Entry) ---
    df_1h = get_data_safe(symbol, "1h", min_candles=50)
    if df_1h is None:
        df_1h = df_4h.copy()
    
    # --- TREND ANALYSIS ---
    trend_daily = analyze_trend(df_daily, "1D")
    trend_4h = analyze_trend(df_4h, "4H")
    trend_1h = analyze_trend(df_1h, "1H")
    
    # --- DAILY INDICATORS ---
    df_daily["RSI"] = RSI(df_daily, 14)
    df_daily["MACD"], df_daily["MACD_SIGNAL"], df_daily["MACD_HIST"] = MACD(df_daily)
    
    last_daily = df_daily.iloc[-1]
    rsi_daily = last_daily["RSI"] if not pd.isna(last_daily["RSI"]) else 50
    macd_hist = last_daily["MACD_HIST"] if not pd.isna(last_daily["MACD_HIST"]) else 0
    macd_line = last_daily["MACD"] if not pd.isna(last_daily["MACD"]) else 0
    macd_signal = last_daily["MACD_SIGNAL"] if not pd.isna(last_daily["MACD_SIGNAL"]) else 0
    
    # --- SUPPORT/RESISTANCE (Monthly) ---
    monthly_high = df_daily["High"].tail(30).max()
    monthly_low = df_daily["Low"].tail(30).min()
    pivot = (monthly_high + monthly_low + df_daily["Close"].tail(30).mean()) / 3
    resistance = 2 * pivot - monthly_low
    support = 2 * pivot - monthly_high
    
    # --- KONFIRMASI 3 HARI ---
    last_3_days = df_daily.tail(3)
    bullish_days = sum(last_3_days["Close"] > last_3_days["Open"])
    bearish_days = sum(last_3_days["Close"] < last_3_days["Open"])
    
    # --- VOLUME SPIKE (Daily) ---
    vol_ma = df_daily["Volume"].tail(20).mean()
    vol_spike = df_daily["Volume"].iloc[-1] > vol_ma * 1.3 if vol_ma > 0 else False
    
    # --- HITUNG KONFIRMASI ---
    confirmations = 0
    if "BULLISH" in trend_daily:
        confirmations += 1
    if bullish_days >= 2:
        confirmations += 1
    if rsi_daily < 60 and rsi_daily > 30:
        confirmations += 1
    if macd_hist > 0:
        confirmations += 1
    if vol_spike:
        confirmations += 1
    
    # --- ENTRY SIGNAL ---
    entry_signal = None
    price = df_1h["Close"].iloc[-1]
    
    # Check if price near support
    at_support = price <= support * 1.02
    at_resistance = price >= resistance * 0.98
    
    if confirmations >= min_confirmations:
        if "BULLISH" in trend_daily and at_support and rsi_daily < 55:
            entry_signal = "🟢 BUY (Support + Daily Bullish)"
        elif "BULLISH" in trend_daily and bullish_days >= 2 and rsi_daily < 50:
            entry_signal = "🟢 BUY (3-Day Confirmation)"
        elif "BEARISH" in trend_daily and at_resistance and rsi_daily > 45:
            entry_signal = "🔴 SELL (Resistance + Daily Bearish)"
    
    # --- RISK MANAGEMENT ---
    if entry_signal:
        entry_price = df_1h["Close"].iloc[-1]
        stop_loss, take_profit, atr_value = calculate_risk_management_spot(
            df_1h,
            entry_signal,
            entry_price,
            rr_sl=rr_sl,
            rr_tp=rr_tp,
            use_trailing=use_trailing
        )
    else:
        entry_price = stop_loss = take_profit = None
        atr_value = 0.01
    
    return {
        "symbol": symbol,
        "trend_daily": trend_daily,
        "trend_4h": trend_4h,
        "trend_1h": trend_1h,
        "support": support,
        "resistance": resistance,
        "confirmations": confirmations,
        "entry_signal": entry_signal,
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "rsi_daily": rsi_daily,
        "price": price,
        "atr": atr_value,
        "bullish_days": bullish_days,
        "bearish_days": bearish_days,
        "vol_spike": vol_spike,
        "df_daily": df_daily.tail(100),
        "df_4h": df_4h.tail(60),
        "df_1h": df_1h.tail(50)
    }

# =========================================================
# CREATE CHART - SPOT VERSION
# =========================================================
def create_chart_spot(result, symbol, currency_rate):
    fig = make_subplots(
        rows=4, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.4, 0.2, 0.2, 0.2],
        subplot_titles=("Daily Price (1D)", "RSI (1D)", "MACD (1D)", "Volume (1D)")
    )
    
    df = result["df_daily"]
    
    # === ROW 1: CANDLESTICK DAILY ===
    fig.add_trace(
        go.Candlestick(
            x=df["Time"],
            open=df["Open"] * currency_rate,
            high=df["High"] * currency_rate,
            low=df["Low"] * currency_rate,
            close=df["Close"] * currency_rate,
            increasing_line_color="#00ff88",
            decreasing_line_color="#ff3b5c",
            name="Daily Price"
        ),
        row=1, col=1
    )
    
    # EMA20 & EMA50 Daily
    fig.add_trace(
        go.Scatter(
            x=df["Time"],
            y=df["Close"].ewm(span=20).mean() * currency_rate,
            line=dict(color="#00a2ff", width=2),
            name="EMA20"
        ),
        row=1, col=1
    )
    fig.add_trace(
        go.Scatter(
            x=df["Time"],
            y=df["Close"].ewm(span=50).mean() * currency_rate,
            line=dict(color="#ffaa00", width=2, dash="dash"),
            name="EMA50"
        ),
        row=1, col=1
    )
    
    # Support/Resistance
    fig.add_hline(
        y=result["support"] * currency_rate,
        line_dash="dot",
        line_color="#00ff88",
        annotation_text=f"S {format_price(result['support'] * currency_rate)}",
        row=1, col=1
    )
    fig.add_hline(
        y=result["resistance"] * currency_rate,
        line_dash="dot",
        line_color="#ff3b5c",
        annotation_text=f"R {format_price(result['resistance'] * currency_rate)}",
        row=1, col=1
    )
    
    # Entry/SL/TP
    if result["entry_signal"] and result["entry_price"]:
        fig.add_hline(
            y=result["entry_price"] * currency_rate,
            line_dash="solid",
            line_color="#00ff88",
            annotation_text="ENTRY",
            row=1, col=1
        )
        if result["stop_loss"]:
            fig.add_hline(
                y=result["stop_loss"] * currency_rate,
                line_dash="dash",
                line_color="#ff0000",
                annotation_text=f"SL {format_price(result['stop_loss'] * currency_rate)}",
                row=1, col=1
            )
        if result["take_profit"]:
            fig.add_hline(
                y=result["take_profit"] * currency_rate,
                line_dash="dash",
                line_color="#00ff00",
                annotation_text=f"TP {format_price(result['take_profit'] * currency_rate)}",
                row=1, col=1
            )
    
    # === ROW 2: RSI ===
    rsi = RSI(df)
    fig.add_trace(
        go.Scatter(
            x=df["Time"],
            y=rsi,
            line=dict(color="#a855f7", width=2),
            name="RSI"
        ),
        row=2, col=1
    )
    fig.add_hline(y=70, line_dash="dash", line_color="#ff3b5c", row=2, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="#00ff88", row=2, col=1)
    fig.add_hline(y=50, line_dash="dot", line_color="rgba(255,255,255,0.2)", row=2, col=1)
    
    # === ROW 3: MACD ===
    macd, signal, hist = MACD(df)
    fig.add_trace(
        go.Scatter(
            x=df["Time"],
            y=macd,
            line=dict(color="#00a2ff", width=2),
            name="MACD"
        ),
        row=3, col=1
    )
    fig.add_trace(
        go.Scatter(
            x=df["Time"],
            y=signal,
            line=dict(color="#ff00ff", width=2),
            name="Signal"
        ),
        row=3, col=1
    )
    colors = ["#00ff88" if h >= 0 else "#ff3b5c" for h in hist]
    fig.add_trace(
        go.Bar(
            x=df["Time"],
            y=hist,
            marker_color=colors,
            opacity=0.4,
            name="Histogram"
        ),
        row=3, col=1
    )
    
    # === ROW 4: VOLUME ===
    colors_vol = ["#00ff88" if c >= o else "#ff3b5c" 
                  for c, o in zip(df["Close"], df["Open"])]
    fig.add_trace(
        go.Bar(
            x=df["Time"],
            y=df["Volume"],
            marker_color=colors_vol,
            opacity=0.5,
            name="Volume"
        ),
        row=4, col=1
    )
    fig.add_trace(
        go.Scatter(
            x=df["Time"],
            y=df["Volume"].rolling(20).mean(),
            line=dict(color="rgba(255,255,255,0.3)", width=2),
            name="Volume MA20"
        ),
        row=4, col=1
    )
    
    fig.update_layout(
        template="plotly_dark",
        height=900,
        title=dict(
            text=f"<b>{symbol} - Spot Trading (Daily Timeframe)</b>",
            font=dict(color="#f1f5f9", size=22),
            x=0.5,
            xanchor="center"
        ),
        hovermode="x unified",
        dragmode="pan",
        xaxis_rangeslider_visible=False,
        paper_bgcolor="#0a0a1a",
        plot_bgcolor="#0a0a1a",
        font=dict(color="#94a3b8"),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            font=dict(size=10)
        ),
        margin=dict(l=10, r=10, t=50, b=10)
    )
    
    fig.update_xaxes(gridcolor="rgba(255,255,255,0.03)")
    fig.update_yaxes(gridcolor="rgba(255,255,255,0.03)")
    
    return fig

# =========================================================
# NOTIFICATION FUNCTIONS - SPOT
# =========================================================
def send_spot_signal_alert(result, position_size, total_capital, risk_per_trade):
    """Kirim notifikasi signal spot"""
    if not result or not result.get("entry_signal"):
        return
    
    symbol = result["symbol"]
    entry = result["entry_price"]
    sl = result["stop_loss"]
    tp = result["take_profit"]
    
    # Hitung risk/reward
    if sl and entry:
        if "BUY" in result["entry_signal"]:
            risk_pct = ((sl / entry) - 1) * 100
            reward_pct = ((tp / entry) - 1) * 100
        else:
            risk_pct = (1 - (sl / entry)) * 100
            reward_pct = (1 - (tp / entry)) * 100
        rr_ratio = abs(reward_pct / risk_pct) if risk_pct != 0 else 0
        
        risk_amount = total_capital * (risk_per_trade / 100)
        position_value = position_size * entry
    else:
        risk_pct = reward_pct = rr_ratio = 0
        risk_amount = 0
        position_value = 0
    
    # Status RSI
    rsi_status = "Neutral"
    if result["rsi_daily"] > 70:
        rsi_status = "Overbought ⚠️"
    elif result["rsi_daily"] > 60:
        rsi_status = "Bullish"
    elif result["rsi_daily"] > 40:
        rsi_status = "Neutral"
    elif result["rsi_daily"] > 30:
        rsi_status = "Bearish"
    else:
        rsi_status = "Oversold ⚠️"
    
    # Build message
    message = f"""🐢 SPOT SIGNAL!

Coin : {symbol}
Signal : {result['entry_signal']}
Action : {'BUY NOW' if 'BUY' in result['entry_signal'] else 'SELL NOW'}

📊 Analysis:
• Daily Trend : {result['trend_daily']}
• 4H Trend   : {result['trend_4h']}
• 1H Trend   : {result['trend_1h']}
• RSI Daily  : {result['rsi_daily']:.1f} ({rsi_status})
• Confirm    : {result['confirmations']}/5
• Bullish Days: {result['bullish_days']}/3
• Volume Spike: {'✅' if result['vol_spike'] else '❌'}

🎯 Entry Plan:
• Entry Price : ${entry:,.4f}
• Stop Loss   : ${sl:,.4f} ({risk_pct:+.1f}%)
• Take Profit : ${tp:,.4f} ({reward_pct:+.1f}%)
• RR Ratio    : 1:{rr_ratio:.2f}

💰 Position Sizing:
• Risk per Trade : {risk_per_trade:.1f}%
• Position Size  : {position_size:,.4f} {symbol}
• Position Value : ${position_value:,.2f}
• Max Loss       : ${risk_amount:,.2f}
• Total Capital  : ${total_capital:,.0f}

📅 Hold Duration: 1-2 weeks
📈 Target Profit: ${(position_size * (tp - entry)):,.2f} if BUY else ${(position_size * (entry - tp)):,.2f}

🕐 Time : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

---
💡 Tips:
• Gunakan limit order untuk entry
• Pasang stop loss otomatis
• Ambil profit bertahap (50% di TP1, 50% di TP2)
• Jangan FOMO, tunggu harga retest support/resistance
• Selalu update stop loss ke break even setelah +5%
"""
    
    # Kirim ke Telegram
    if send_telegram_alerts:
        send_telegram(message)

def send_daily_update_spot(active_positions):
    """Kirim update harian semua posisi"""
    if not active_positions:
        return
    
    message = "📊 DAILY SPOT UPDATE\n"
    message += "=" * 35 + "\n\n"
    
    total_pnl = 0
    total_pnl_pct = 0
    
    for symbol, pos in active_positions.items():
        # Get current price
        df = get_data_safe(symbol, "1h", min_candles=5)
        if df is None:
            continue
        
        current_price = df["Close"].iloc[-1]
        entry = pos["entry"]
        sl = pos["sl"]
        tp = pos["tp"]
        size = pos["size"]
        
        pnl_pct = ((current_price / entry) - 1) * 100
        pnl = (current_price - entry) * size
        total_pnl += pnl
        total_pnl_pct += pnl_pct
        
        emoji = "🟢" if pnl > 0 else "🔴" if pnl < 0 else "🟡"
        
        # Risk status
        distance_to_sl = ((current_price - sl) / current_price) * 100 if sl else 0
        distance_to_tp = ((tp - current_price) / current_price) * 100 if tp else 0
        
        message += f"{emoji} {symbol}\n"
        message += f"  Entry: ${entry:,.4f}\n"
        message += f"  Now  : ${current_price:,.4f}\n"
        message += f"  PnL  : {pnl_pct:+.2f}% (${pnl:+,.2f})\n"
        message += f"  SL   : ${sl:,.4f} ({distance_to_sl:.1f}% away)\n"
        message += f"  TP   : ${tp:,.4f} ({distance_to_tp:.1f}% away)\n"
        message += f"  Size : {size:,.4f} {symbol}\n\n"
    
    message += "=" * 35 + "\n"
    message += f"Total PnL : ${total_pnl:+,.2f} ({total_pnl_pct:+.1f}%)\n"
    message += f"Active Positions: {len(active_positions)}"
    
    if send_telegram_alerts:
        send_telegram(message)

def send_tp_hit_alert(symbol, entry, tp, size, duration):
    """Notifikasi ketika TP tercapai"""
    profit = (tp - entry) * size
    profit_pct = ((tp / entry) - 1) * 100
    
    message = f"""🎯 TAKE PROFIT HIT!

Coin : {symbol}
Type : SPOT BUY

📈 Profit Details:
• Entry : ${entry:,.4f}
• TP    : ${tp:,.4f}
• Profit: {profit_pct:+.2f}% (${profit:+,.2f})

📊 Position:
• Size     : {size:,.4f} {symbol}
• Duration : {duration}
• RR Ratio : {abs((tp/entry - 1) / (sl/entry - 1)):.2f}

💡 Next Action:
• Consider taking partial profit
• Move SL to break even
• Watch for re-entry opportunity

🕐 Time : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
    send_telegram(message)

def send_sl_hit_alert(symbol, entry, sl, size, duration):
    """Notifikasi ketika SL tercapai"""
    loss = (sl - entry) * size
    loss_pct = ((sl / entry) - 1) * 100
    
    message = f"""🛑 STOP LOSS HIT!

Coin : {symbol}
Type : SPOT BUY

📉 Loss Details:
• Entry : ${entry:,.4f}
• SL    : ${sl:,.4f}
• Loss  : {loss_pct:+.2f}% (${loss:+,.2f})

📊 Position:
• Size     : {size:,.4f} {symbol}
• Duration : {duration}

📌 Next Action:
• Wait for reversal signal
• Watch RSI divergence
• Consider re-entry at lower support

🕐 Time : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
    send_telegram(message)

# =========================================================
# MAIN UI
# =========================================================

# --- CLEANUP PENDING SIGNALS ---
current_time = datetime.now()
expired_signals = []
for symbol, data in st.session_state.pending_signal.items():
    elapsed = (current_time - data["time"]).seconds / 3600  # hours
    if elapsed > 24:  # 24 hours hold for spot
        expired_signals.append(symbol)

for symbol in expired_signals:
    del st.session_state.pending_signal[symbol]

# --- UPDATE POSITIONS ---
# Check if any position hit TP or SL
for symbol in list(st.session_state.active_positions.keys()):
    pos = st.session_state.active_positions[symbol]
    df = get_data_safe(symbol, "1h", min_candles=5)
    if df is not None:
        current_price = df["Close"].iloc[-1]
        
        # Check TP hit
        if pos["type"] == "BUY" and current_price >= pos["tp"]:
            # TP Hit!
            duration = (datetime.now() - pos["entry_time"]).days
            send_tp_hit_alert(symbol, pos["entry"], pos["tp"], pos["size"], duration)
            st.session_state.performance_stats["wins"] += 1
            st.session_state.performance_stats["total_profit"] += (pos["tp"] - pos["entry"]) * pos["size"]
            del st.session_state.active_positions[symbol]
            st.rerun()
        
        # Check SL hit
        elif pos["type"] == "BUY" and current_price <= pos["sl"]:
            # SL Hit!
            duration = (datetime.now() - pos["entry_time"]).days
            send_sl_hit_alert(symbol, pos["entry"], pos["sl"], pos["size"], duration)
            st.session_state.performance_stats["losses"] += 1
            st.session_state.performance_stats["total_profit"] += (pos["sl"] - pos["entry"]) * pos["size"]
            del st.session_state.active_positions[symbol]
            st.rerun()

# --- DAILY UPDATE ---
if send_daily_update and (datetime.now() - st.session_state.last_daily_update).seconds > 86400:
    if st.session_state.active_positions:
        send_daily_update_spot(st.session_state.active_positions)
    st.session_state.last_daily_update = datetime.now()

# =========================================================
# SIGNAL SUMMARY - SPOT
# =========================================================
st.subheader("📊 Signal Summary (Spot)")

all_signals = []
progress_bar = st.progress(0)
status_text = st.empty()

for idx, symbol in enumerate(st.session_state.watchlist):
    progress_bar.progress((idx + 1) / len(st.session_state.watchlist))
    status_text.text(f"🔄 Scanning {symbol}...")
    
    result = analyze_spot(
        symbol,
        rr_sl=rr_sl,
        rr_tp=rr_tp,
        use_trailing=use_trailing,
        min_confirmations=min_confirmations
    )
    
    if result:
        # Cek apakah ada pending signal
        pending = st.session_state.pending_signal.get(symbol)
        if pending:
            entry_display = pending["signal"]
            is_pending = True
        else:
            entry_display = result["entry_signal"] if result["entry_signal"] else "⏳ WAIT"
            is_pending = False
        
        # Hitung position size jika ada signal
        position_size = 0
        if result["entry_signal"]:
            position_size = calculate_position_size(
                result["entry_price"],
                result["stop_loss"],
                total_capital,
                risk_per_trade
            )
            
            # Simpan signal ke pending jika baru
            if symbol not in st.session_state.pending_signal:
                st.session_state.pending_signal[symbol] = {
                    "signal": result["entry_signal"],
                    "time": datetime.now(),
                    "entry": result["entry_price"],
                    "sl": result["stop_loss"],
                    "tp": result["take_profit"]
                }
                
                # Kirim notifikasi
                send_spot_signal_alert(result, position_size, total_capital, risk_per_trade)
        
        all_signals.append({
            "Coin": symbol,
            "Daily Trend": result["trend_daily"],
            "4H Trend": result["trend_4h"],
            "Signal": "🟡 PENDING" if is_pending else entry_display,
            "RSI Daily": f"{result['rsi_daily']:.1f}",
            "Confirm": f"{result['confirmations']}/5",
            "Support": format_price(result["support"] * currency_rate),
            "Resistance": format_price(result["resistance"] * currency_rate),
            "Entry": format_price(result["entry_price"] * currency_rate) if result["entry_price"] else "-",
            "SL": format_price(result["stop_loss"] * currency_rate) if result["stop_loss"] else "-",
            "TP": format_price(result["take_profit"] * currency_rate) if result["take_profit"] else "-"
        })

progress_bar.empty()
status_text.empty()

if all_signals:
    df_signals = pd.DataFrame(all_signals)
    st.dataframe(df_signals, use_container_width=True, hide_index=True)
else:
    st.info("ℹ️ Tidak ada data")

# =========================================================
# PENDING SIGNALS DISPLAY
# =========================================================
if st.session_state.pending_signal:
    st.divider()
    st.subheader("⏳ Pending Signals (Aktif)")
    st.caption(f"Sinyal bertahan 24 jam | RR {rr_sl}:{rr_tp}")
    
    cols = st.columns(min(len(st.session_state.pending_signal), 4))
    for idx, (symbol, data) in enumerate(st.session_state.pending_signal.items()):
        col_idx = idx % len(cols)
        with cols[col_idx]:
            elapsed = (datetime.now() - data["time"]).seconds / 3600
            remaining = max(0, 24 - elapsed)
            rr = ((data["tp"] / data["entry"] - 1) / (data["sl"] / data["entry"] - 1)) if data["sl"] else 0
            
            # Hitung position size untuk display
            pos_size = calculate_position_size(data["entry"], data["sl"], total_capital, risk_per_trade)
            pos_value = pos_size * data["entry"]
            
            st.markdown(f"""
            <div class="pending-signal">
                <b>{symbol}</b><br>
                {data['signal']}<br>
                Entry: {format_price(data['entry'] * currency_rate)}<br>
                SL: {format_price(data['sl'] * currency_rate)}<br>
                TP: {format_price(data['tp'] * currency_rate)}<br>
                Size: {pos_size:.4f} {symbol}<br>
                Value: ${pos_value:,.2f}<br>
                RR: {rr:.2f}<br>
                ⏱️ {remaining:.1f}h remaining
            </div>
            """, unsafe_allow_html=True)

# =========================================================
# ACTIVE POSITIONS
# =========================================================
if st.session_state.active_positions:
    st.divider()
    st.subheader("📈 Active Positions")
    
    for symbol, pos in st.session_state.active_positions.items():
        # Get current price
        df = get_data_safe(symbol, "1h", min_candles=5)
        if df is None:
            continue
        
        current_price = df["Close"].iloc[-1]
        entry = pos["entry"]
        sl = pos["sl"]
        tp = pos["tp"]
        size = pos["size"]
        
        pnl_pct = ((current_price / entry) - 1) * 100
        pnl = (current_price - entry) * size
        
        col1, col2, col3, col4 = st.columns([2, 2, 2, 1])
        
        with col1:
            st.markdown(f"**{symbol}**")
            st.caption(f"Entry: ${entry:,.4f}")
        
        with col2:
            st.metric("Current Price", f"${current_price:,.4f}", 
                     delta=f"{pnl_pct:+.2f}%")
        
        with col3:
            st.metric("PnL", f"${pnl:+,.2f}",
                     delta_color="normal")
        
        with col4:
            if st.button(f"Close {symbol}", key=f"close_{symbol}"):
                # Close position
                st.session_state.performance_stats["total_signals"] += 1
                if pnl > 0:
                    st.session_state.performance_stats["wins"] += 1
                else:
                    st.session_state.performance_stats["losses"] += 1
                st.session_state.performance_stats["total_profit"] += pnl
                del st.session_state.active_positions[symbol]
                st.rerun()

# =========================================================
# COIN DETAIL - SPOT
# =========================================================
st.divider()
st.subheader("📈 Coin Detail (Spot)")

selected_coin = st.selectbox(
    "Select Coin",
    st.session_state.watchlist,
    index=st.session_state.watchlist.index(st.session_state.selected_coin) 
    if st.session_state.selected_coin in st.session_state.watchlist else 0
)
st.session_state.selected_coin = selected_coin

result = analyze_spot(
    selected_coin,
    rr_sl=rr_sl,
    rr_tp=rr_tp,
    use_trailing=use_trailing,
    min_confirmations=min_confirmations
)

if result:
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    col1.metric("Daily Trend", result["trend_daily"])
    col2.metric("4H Trend", result["trend_4h"])
    col3.metric("RSI Daily", f"{result['rsi_daily']:.1f}")
    col4.metric("Support", format_price(result["support"] * currency_rate))
    col5.metric("Resistance", format_price(result["resistance"] * currency_rate))
    col6.metric("Confirmations", f"{result['confirmations']}/5")
    
    # Additional info
    col_info1, col_info2, col_info3 = st.columns(3)
    col_info1.metric("Bullish Days (3)", f"{result['bullish_days']}/3")
    col_info2.metric("Volume Spike", "✅" if result["vol_spike"] else "❌")
    col_info3.metric("ATR", format_price(result["atr"] * currency_rate))
    
    # Entry signal
    pending = st.session_state.pending_signal.get(selected_coin)
    
    if pending:
        pos_size = calculate_position_size(pending["entry"], pending["sl"], total_capital, risk_per_trade)
        rr = ((pending["tp"] / pending["entry"] - 1) / (pending["sl"] / pending["entry"] - 1)) if pending["sl"] else 0
        st.markdown(f"""
        <div class="pending-signal">
            ⏳ PENDING SIGNAL: {pending['signal']}<br>
            Entry: {format_price(pending['entry'] * currency_rate)} | 
            SL: {format_price(pending['sl'] * currency_rate)} | 
            TP: {format_price(pending['tp'] * currency_rate)}<br>
            Size: {pos_size:.4f} {selected_coin} | Value: ${pos_size * pending['entry']:,.2f}<br>
            RR: {rr:.2f} | ⏱️ {max(0, 24 - (datetime.now() - pending['time']).seconds/3600):.1f}h remaining
        </div>
        """, unsafe_allow_html=True)
        
        if st.button("📊 Open Position", use_container_width=True):
            # Open position
            st.session_state.active_positions[selected_coin] = {
                "entry": pending["entry"],
                "sl": pending["sl"],
                "tp": pending["tp"],
                "size": pos_size,
                "type": "BUY" if "BUY" in pending["signal"] else "SELL",
                "entry_time": pending["time"]
            }
            del st.session_state.pending_signal[selected_coin]
            st.rerun()
            
    elif result["entry_signal"]:
        # Hitung position size
        pos_size = calculate_position_size(result["entry_price"], result["stop_loss"], total_capital, risk_per_trade)
        rr = ((result["take_profit"] / result["entry_price"] - 1) / 
              (result["stop_loss"] / result["entry_price"] - 1)) if result["stop_loss"] else 0
        
        if "BUY" in result["entry_signal"]:
            st.markdown(f'<div class="signal-buy">🚀 {result["entry_signal"]}</div>', unsafe_allow_html=True)
        elif "SELL" in result["entry_signal"]:
            st.markdown(f'<div class="signal-sell">🔻 {result["entry_signal"]}</div>', unsafe_allow_html=True)
        
        col_a, col_b, col_c, col_d, col_e = st.columns(5)
        col_a.metric("Entry Price", format_price(result["entry_price"] * currency_rate))
        col_b.metric("Stop Loss", format_price(result["stop_loss"] * currency_rate),
                    delta=f"{format_percentage((result['stop_loss']/result['entry_price'] - 1)*100)}")
        col_c.metric("Take Profit", format_price(result["take_profit"] * currency_rate),
                    delta=f"{format_percentage((result['take_profit']/result['entry_price'] - 1)*100)}")
        col_d.metric("Risk/Reward", f"1:{rr:.2f}")
        col_e.metric("Position Size", f"{pos_size:.4f} {selected_coin}")
        
        st.info(f"""
        💰 Position Details:
        - Capital: ${total_capital:,.2f}
        - Risk: {risk_per_trade}% (${total_capital * risk_per_trade / 100:,.2f})
        - Position Value: ${pos_size * result['entry_price']:,.2f}
        - Potential Profit: ${(result['take_profit'] - result['entry_price']) * pos_size:,.2f}
        """)
        
    else:
        st.markdown(f'<div class="signal-wait">⏳ WAIT - No Signal</div>', unsafe_allow_html=True)
    
    # Chart
    fig = create_chart_spot(result, selected_coin, currency_rate)
    st.plotly_chart(fig, use_container_width=True)

# =========================================================
# PERFORMANCE STATISTICS
# =========================================================
st.divider()
st.subheader("📊 Performance Statistics")

stats = st.session_state.performance_stats
col1, col2, col3, col4, col5 = st.columns(5)

col1.metric("Total Signals", stats["total_signals"])
col2.metric("Wins", stats["wins"])
col3.metric("Losses", stats["losses"])
col4.metric("Win Rate", f"{(stats['wins'] / max(1, stats['total_signals']) * 100):.1f}%")
col5.metric("Total PnL", f"${stats['total_profit']:,.2f}",
           delta=f"{stats['total_profit']:+,.2f}")

# =========================================================
# FOOTER
# =========================================================
st.divider()
st.caption(f"""
🐢 Crypto Spot Scanner PRO
🔄 Data dari Yahoo Finance | Timeframe: 1D, 4H, 1H
💱 Currency: {currency} | 🔄 Scan Refresh: {refresh} menit
📊 Total Coins: {len(st.session_state.watchlist)}
🎯 RR Strategy: {rr_sl}:{rr_tp} | Risk: {risk_per_trade}% per trade
💰 Capital: ${total_capital:,.0f} | Max Positions: {max_positions}
🛡️ Trailing Stop: {'Active' if use_trailing else 'Inactive'}
📱 Telegram: {'Active' if send_telegram_alerts else 'Inactive'}
""")
