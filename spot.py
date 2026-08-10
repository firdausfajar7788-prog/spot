import streamlit as st
import pandas as pd
import numpy as np
import requests

from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from streamlit_autorefresh import st_autorefresh


# =========================================================
# CONFIG
# =========================================================

st.set_page_config(
    page_title="Momentum Scanner PRO",
    page_icon="⚡",
    layout="wide"
)

BINANCE = "https://api.binance.com"
TIMEOUT = 8

TIMEFRAMES = {
    "15m": "15m",
    "1h": "1h",
    "4h": "4h"
}


# =========================================================
# SESSION STATE
# =========================================================

if "results" not in st.session_state:
    st.session_state.results = pd.DataFrame()

if "last_scan" not in st.session_state:
    st.session_state.last_scan = None


# =========================================================
# BINANCE
# =========================================================

@st.cache_data(ttl=60, show_spinner=False)
def get_symbols():

    try:

        r = requests.get(
            f"{BINANCE}/api/v3/exchangeInfo",
            timeout=TIMEOUT
        )

        data = r.json()

        blacklist = {
            "USDCUSDT",
            "FDUSDUSDT",
            "TUSDUSDT",
            "USDPUSDT",
            "DAIUSDT"
        }

        symbols = []

        for x in data["symbols"]:

            if (
                x["status"] == "TRADING"
                and x["quoteAsset"] == "USDT"
                and x["isSpotTradingAllowed"]
                and x["symbol"] not in blacklist
            ):
                symbols.append(x["symbol"])

        return symbols

    except Exception:

        return []


@st.cache_data(ttl=20, show_spinner=False)
def get_klines(symbol, interval, limit=100):

    try:

        r = requests.get(
            f"{BINANCE}/api/v3/klines",
            params={
                "symbol": symbol,
                "interval": interval,
                "limit": limit
            },
            timeout=TIMEOUT
        )

        raw = r.json()

        if not isinstance(raw, list) or len(raw) < 50:
            return None

        df = pd.DataFrame(
            raw,
            columns=[
                "time",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "close_time",
                "quote_volume",
                "trades",
                "buy_volume",
                "buy_quote",
                "ignore"
            ]
        )

        numeric = [
            "open",
            "high",
            "low",
            "close",
            "volume",
            "quote_volume"
        ]

        for col in numeric:
            df[col] = pd.to_numeric(
                df[col],
                errors="coerce"
            )

        return df

    except Exception:

        return None


@st.cache_data(ttl=20, show_spinner=False)
def get_24h_volume():

    try:

        r = requests.get(
            f"{BINANCE}/api/v3/ticker/24hr",
            timeout=TIMEOUT
        )

        data = r.json()

        return {
            x["symbol"]: float(x["quoteVolume"])
            for x in data
            if x["symbol"].endswith("USDT")
        }

    except Exception:

        return {}


# =========================================================
# INDICATORS
# =========================================================

def EMA(series, period):

    return series.ewm(
        span=period,
        adjust=False
    ).mean()


def RSI(series, period=14):

    delta = series.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1 / period,
        adjust=False
    ).mean()

    avg_loss = loss.ewm(
        alpha=1 / period,
        adjust=False
    ).mean()

    rs = avg_gain / avg_loss.replace(
        0,
        np.nan
    )

    return (
        100 - (100 / (1 + rs))
    ).fillna(50)


def MACD(series):

    fast = EMA(series, 12)
    slow = EMA(series, 26)

    dif = fast - slow

    dea = dif.ewm(
        span=9,
        adjust=False
    ).mean()

    histogram = dif - dea

    return dif, dea, histogram


# =========================================================
# ANALYZE TIMEFRAME
# =========================================================

def analyze_tf(df):

    if df is None or len(df) < 60:
        return None

    close = df["close"]

    ema20 = EMA(close, 20)
    ema50 = EMA(close, 50)

    dif, dea, hist = MACD(close)

    rsi = RSI(close)

    volume_ma = (
        df["volume"]
        .rolling(20)
        .mean()
    )

    price = close.iloc[-1]

    change_5 = (
        price / close.iloc[-6] - 1
    ) * 100

    change_20 = (
        price / close.iloc[-21] - 1
    ) * 100

    volume_ratio = (
        df["volume"].iloc[-1]
        / volume_ma.iloc[-1]
        if volume_ma.iloc[-1] > 0
        else 0
    )

    return {

        "price": price,

        "change_5": change_5,
        "change_20": change_20,

        "ema20": ema20.iloc[-1],
        "ema50": ema50.iloc[-1],

        "bullish":
            price > ema20.iloc[-1]
            and ema20.iloc[-1] > ema50.iloc[-1],

        "bearish":
            price < ema20.iloc[-1]
            and ema20.iloc[-1] < ema50.iloc[-1],

        "dif": dif.iloc[-1],
        "dea": dea.iloc[-1],

        "hist": hist.iloc[-1],
        "hist_prev": hist.iloc[-2],

        "hist_rising":
            hist.iloc[-1] > hist.iloc[-2],

        "rsi": rsi.iloc[-1],

        "volume_ratio": volume_ratio,

        "previous_high":
            df["high"].iloc[-21:-1].max(),

        "previous_low":
            df["low"].iloc[-21:-1].min()
    }


# =========================================================
# MOMENTUM SCANNER
# =========================================================

def analyze_coin(symbol):

    try:

        data = {}

        for tf in TIMEFRAMES:

            df = get_klines(
                symbol,
                TIMEFRAMES[tf],
                100
            )

            result = analyze_tf(df)

            if result is None:
                return None

            data[tf] = result

        m15 = data["15m"]
        h1 = data["1h"]
        h4 = data["4h"]

        price = m15["price"]

        score = 0

        reasons = []

        # =================================================
        # 1. 4H TREND
        # =================================================

        if h4["bullish"]:

            score += 20

            reasons.append(
                "4H bullish"
            )

        elif h4["bearish"]:

            score -= 20

            reasons.append(
                "4H bearish"
            )

        # =================================================
        # 2. 1H TREND
        # =================================================

        if h1["bullish"]:

            score += 15

            reasons.append(
                "1H bullish"
            )

        elif h1["bearish"]:

            score -= 15

            reasons.append(
                "1H bearish"
            )

        # =================================================
        # 3. 15M PRICE MOMENTUM
        # =================================================

        if m15["change_5"] >= 1:

            score += 10

            reasons.append(
                "15M momentum naik"
            )

        elif m15["change_5"] <= -1:

            score -= 10

            reasons.append(
                "15M momentum turun"
            )

        # =================================================
        # 4. MACD MULTI TF
        # =================================================

        bullish_macd = 0
        bearish_macd = 0

        for x in [m15, h1, h4]:

            if x["dif"] > x["dea"]:
                bullish_macd += 1

            elif x["dif"] < x["dea"]:
                bearish_macd += 1

        if bullish_macd >= 2:

            score += 15

            reasons.append(
                "MACD bullish MTF"
            )

        elif bearish_macd >= 2:

            score -= 15

            reasons.append(
                "MACD bearish MTF"
            )

        # =================================================
        # 5. MACD HISTOGRAM
        # =================================================

        if (
            m15["hist"] > 0
            and m15["hist_rising"]
        ):

            score += 10

            reasons.append(
                "Histogram menguat"
            )

        elif (
            m15["hist"] < 0
            and not m15["hist_rising"]
        ):

            score -= 10

            reasons.append(
                "Histogram melemah"
            )

        # =================================================
        # 6. VOLUME
        # =================================================

        vr = m15["volume_ratio"]

        if vr >= 2:

            score += 15

            reasons.append(
                "Volume spike >2x"
            )

        elif vr >= 1.3:

            score += 8

            reasons.append(
                "Volume meningkat"
            )

        elif vr < 0.7:

            score -= 3

        # =================================================
        # 7. RSI
        # =================================================

        rsi = m15["rsi"]

        if 50 <= rsi <= 68:

            score += 8

            reasons.append(
                "RSI sehat"
            )

        elif 68 < rsi <= 75:

            score += 3

            reasons.append(
                "RSI tinggi"
            )

        elif rsi > 80:

            score -= 5

            reasons.append(
                "RSI terlalu panas"
            )

        # =================================================
        # 8. 1H MOMENTUM
        # =================================================

        if h1["change_20"] >= 3:

            score += 7

            reasons.append(
                "1H momentum kuat"
            )

        elif h1["change_20"] <= -3:

            score -= 7

            reasons.append(
                "1H momentum bearish"
            )

        # =================================================
        # 9. BREAKOUT
        # =================================================

        breakout = False

        if (
            price > m15["previous_high"]
            and vr >= 1.3
        ):

            score += 12

            breakout = True

            reasons.append(
                "BREAKOUT + volume"
            )

        elif (
            price < m15["previous_low"]
            and vr >= 1.3
        ):

            score -= 12

            breakout = True

            reasons.append(
                "BREAKDOWN + volume"
            )

        # =================================================
        # 10. MOMENTUM STATE
        # =================================================

        if (
            h1["bullish"]
            and m15["hist"] > 0
            and m15["hist_rising"]
            and vr >= 1.3
        ):

            momentum = (
                "🚀 MOMENTUM BUILDING"
            )

        elif (
            vr >= 2
            and abs(m15["change_5"]) >= 1
        ):

            momentum = (
                "⚡ MOMENTUM ACTIVE"
            )

        elif (
            m15["hist"] > 0
            and m15["hist_rising"]
        ):

            momentum = (
                "🌱 EARLY MOMENTUM"
            )

        elif (
            m15["hist"] < 0
            and not m15["hist_rising"]
        ):

            momentum = (
                "📉 MOMENTUM WEAKENING"
            )

        else:

            momentum = "⏳ WAIT"

        # =================================================
        # SIGNAL
        # =================================================

        score = max(
            -100,
            min(100, score)
        )

        if score >= 60:

            signal = "🔥 STRONG BULLISH"
            direction = "LONG"

        elif score >= 35:

            signal = "🟢 BULLISH"
            direction = "LONG"

        elif score <= -60:

            signal = "🔥 STRONG BEARISH"
            direction = "SHORT"

        elif score <= -35:

            signal = "🔴 BEARISH"
            direction = "SHORT"

        else:

            signal = "⚪ NEUTRAL"
            direction = "WAIT"

        return {

            "Symbol": symbol,

            "Price": price,

            "Score": score,

            "Signal": signal,

            "Direction": direction,

            "Momentum": momentum,

            "15M %": m15["change_5"],

            "1H %": h1["change_20"],

            "4H %": h4["change_20"],

            "Volume x": vr,

            "RSI": rsi,

            "MACD Hist": m15["hist"],

            "Breakout":
                "🔥 YES"
                if breakout
                else "-",

            "Reasons":
                " | ".join(
                    reasons[:8]
                )
        }

    except Exception:

        return None


# =========================================================
# MARKET SCANNER
# =========================================================

def scan_market(symbols, workers=8):

    results = []

    progress = st.progress(0)

    status = st.empty()

    total = len(symbols)

    with ThreadPoolExecutor(
        max_workers=workers
    ) as executor:

        jobs = {
            executor.submit(
                analyze_coin,
                symbol
            ): symbol
            for symbol in symbols
        }

        completed = 0

        for future in as_completed(jobs):

            completed += 1

            symbol = jobs[future]

            status.write(
                f"⚡ Scanning {symbol} "
                f"({completed}/{total})"
            )

            try:

                result = future.result()

                if result:
                    results.append(result)

            except Exception:
                pass

            progress.progress(
                completed / total
            )

    progress.empty()
    status.empty()

    if not results:
        return pd.DataFrame()

    df = pd.DataFrame(results)

    return df.sort_values(
        "Score",
        ascending=False
    ).reset_index(drop=True)


# =========================================================
# UI
# =========================================================

st.title("⚡ Momentum Scanner PRO")

st.caption(
    "Trend + MACD + Volume + RSI + Breakout | "
    "15M / 1H / 4H"
)

with st.sidebar:

    st.header("⚙️ Settings")

    max_coins = st.slider(
        "Coin yang discan",
        20,
        100,
        50,
        10
    )

    workers = st.slider(
        "Concurrent scanner",
        2,
        12,
        8
    )

    auto = st.checkbox(
        "🔄 Auto Refresh",
        False
    )

    refresh = st.slider(
        "Refresh",
        30,
        300,
        60,
        10
    )

    st.divider()

    st.info(
        "Scanner menggunakan rerun Streamlit, "
        "bukan while True."
    )


# =========================================================
# AUTO REFRESH
# =========================================================

if auto:

    st_autorefresh(
        interval=refresh * 1000,
        key="momentum_auto_refresh"
    )


# =========================================================
# SCAN BUTTON
# =========================================================

if st.button(
    "🚀 SCAN MARKET",
    type="primary",
    use_container_width=True
):

    symbols = get_symbols()

    volumes = get_24h_volume()

    # Ambil coin dengan volume 24H terbesar
    symbols = sorted(
        symbols,
        key=lambda x:
            volumes.get(x, 0),
        reverse=True
    )[:max_coins]

    with st.spinner(
        f"Scanning {len(symbols)} coins..."
    ):

        st.session_state.results = (
            scan_market(
                symbols,
                workers
            )
        )

        st.session_state.last_scan = (
            datetime.now()
            .strftime("%H:%M:%S")
        )


# =========================================================
# AUTO SCAN PERTAMA
# =========================================================

if (
    auto
    and st.session_state.last_scan is None
):

    symbols = get_symbols()

    volumes = get_24h_volume()

    symbols = sorted(
        symbols,
        key=lambda x:
            volumes.get(x, 0),
        reverse=True
    )[:max_coins]

    st.session_state.results = (
        scan_market(
            symbols,
            workers
        )
    )

    st.session_state.last_scan = (
        datetime.now()
        .strftime("%H:%M:%S")
    )


# =========================================================
# RESULT
# =========================================================

df = st.session_state.results


if df.empty:

    st.info(
        "Belum ada hasil. "
        "Tekan **SCAN MARKET**."
    )

else:

    st.caption(
        f"Last scan: "
        f"{st.session_state.last_scan}"
    )

    # =====================================================
    # TOP MOMENTUM
    # =====================================================

    st.subheader(
        "🔥 Top Momentum"
    )

    columns = [
        "Symbol",
        "Price",
        "Score",
        "Signal",
        "Momentum",
        "15M %",
        "1H %",
        "4H %",
        "Volume x",
        "RSI",
        "Breakout"
    ]

    st.dataframe(
        df[columns].head(15),
        use_container_width=True,
        hide_index=True
    )

    # =====================================================
    # BULLISH
    # =====================================================

    col1, col2 = st.columns(2)

    with col1:

        st.subheader(
            "🟢 Bullish Momentum"
        )

        bullish = df[
            df["Direction"] == "LONG"
        ].head(10)

        st.dataframe(
            bullish[columns],
            use_container_width=True,
            hide_index=True
        )

    # =====================================================
    # BEARISH
    # =====================================================

    with col2:

        st.subheader(
            "🔴 Bearish Momentum"
        )

        bearish = df[
            df["Direction"] == "SHORT"
        ].sort_values(
            "Score"
        ).head(10)

        st.dataframe(
            bearish[columns],
            use_container_width=True,
            hide_index=True
        )

    # =====================================================
    # MOMENTUM BUILDING
    # =====================================================

    st.divider()

    st.subheader(
        "🚀 Momentum yang Sedang Mulai Terbentuk"
    )

    building = df[
        df["Momentum"].isin([
            "🌱 EARLY MOMENTUM",
            "🚀 MOMENTUM BUILDING"
        ])
    ]

    if not building.empty:

        st.dataframe(
            building[
                columns + ["Reasons"]
            ].head(20),
            use_container_width=True,
            hide_index=True
        )

    else:

        st.info(
            "Belum ditemukan momentum awal."
        )

    # =====================================================
    # DETAIL
    # =====================================================

    st.divider()

    st.subheader(
        "🔎 Detail Coin"
    )

    selected = st.selectbox(
        "Coin",
        df["Symbol"].tolist()
    )

    row = df[
        df["Symbol"] == selected
    ].iloc[0]

    c1, c2, c3, c4, c5 = st.columns(5)

    c1.metric(
        "Score",
        f"{row['Score']:.0f}"
    )

    c2.metric(
        "15M",
        f"{row['15M %']:.2f}%"
    )

    c3.metric(
        "1H",
        f"{row['1H %']:.2f}%"
    )

    c4.metric(
        "Volume",
        f"{row['Volume x']:.2f}x"
    )

    c5.metric(
        "RSI",
        f"{row['RSI']:.1f}"
    )

    st.write(
        f"**Signal:** {row['Signal']}"
    )

    st.write(
        f"**Momentum:** {row['Momentum']}"
    )

    st.write(
        f"**Breakout:** {row['Breakout']}"
    )

    st.write(
        f"**Alasan:** {row['Reasons']}"
    )

    # =====================================================
    # CSV
    # =====================================================

    csv = df.to_csv(
        index=False
    )

    st.download_button(
        "📥 Download hasil",
        csv,
        file_name=(
            f"momentum_"
            f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        ),
        mime="text/csv"
    )


# =========================================================
# FOOTER
# =========================================================

st.divider()

st.caption(
    "Momentum Scanner PRO | Binance Spot API | "
    "No while True | Cache enabled"
)
