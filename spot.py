
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf
import plotly.graph_objects as go

from streamlit_autorefresh import st_autorefresh


# =========================================================
# PAGE CONFIG
# =========================================================
st.set_page_config(
    page_title="Crypto Momentum Scanner PRO - SPOT",
    page_icon="🚀",
    layout="wide",
)

st.title("🚀 Crypto Momentum Scanner PRO - SPOT")
st.caption(
    "Multi Timeframe: 15M | 1H | 4H | "
    "Momentum Score | WATCH Only"
)


# =========================================================
# SESSION STATE
# =========================================================
if "watchlist" not in st.session_state:
    st.session_state.watchlist = [
        "BTC-USD",
        "ETH-USD",
        "SOL-USD",
        "SYN-USD",
        "CYS-USD",
    ]

if "momentum_results" not in st.session_state:
    st.session_state.momentum_results = pd.DataFrame()

if "momentum_details" not in st.session_state:
    st.session_state.momentum_details = {}

if "last_scan" not in st.session_state:
    st.session_state.last_scan = None


# =========================================================
# DATA
# =========================================================
@st.cache_data(ttl=45, show_spinner=False)
def get_data(symbol, interval, period):
    try:
        df = yf.download(
            symbol,
            interval=interval,
            period=period,
            auto_adjust=False,
            progress=False,
            threads=False,
        )

        if df is None or df.empty:
            return None

        # yfinance kadang mengembalikan MultiIndex.
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [
                c[0] if isinstance(c, tuple) else c
                for c in df.columns
            ]

        required = ["Open", "High", "Low", "Close", "Volume"]

        for col in required:
            if col not in df.columns:
                return None

        df = df[required].copy()

        for col in required:
            df[col] = pd.to_numeric(
                df[col],
                errors="coerce"
            )

        df = df.dropna()

        if len(df) < 80:
            return None

        return df

    except Exception as e:
        print(f"get_data error {symbol} {interval}: {e}")
        return None


def get_data_safe(symbol, interval):
    periods = {
        "15m": ["7d", "14d", "30d"],
        "1h": ["30d", "60d", "90d"],
        "4h": ["90d", "180d", "1y"],
    }

    for period in periods.get(interval, ["30d"]):
        df = get_data(symbol, interval, period)

        if df is not None and len(df) >= 80:
            return df

    return None


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

    rs = avg_gain / avg_loss.replace(0, np.nan)

    result = 100 - (100 / (1 + rs))

    return result.fillna(50)


def MACD(series):
    fast = EMA(series, 12)
    slow = EMA(series, 26)

    dif = fast - slow

    dea = dif.ewm(
        span=9,
        adjust=False
    ).mean()

    hist = dif - dea

    return dif, dea, hist


def calculate_tf(df):
    if df is None or len(df) < 80:
        return None

    close = df["Close"]

    ema20 = EMA(close, 20)
    ema50 = EMA(close, 50)
    ema100 = EMA(close, 100)

    dif, dea, hist = MACD(close)
    rsi = RSI(close, 14)

    volume_ma20 = df["Volume"].rolling(20).mean()

    price = float(close.iloc[-1])

    change_5 = (
        price / float(close.iloc[-6]) - 1
    ) * 100

    change_20 = (
        price / float(close.iloc[-21]) - 1
    ) * 100

    volume_ratio = (
        float(df["Volume"].iloc[-1])
        / float(volume_ma20.iloc[-1])
        if volume_ma20.iloc[-1] > 0
        else 0
    )

    hist_now = float(hist.iloc[-1])
    hist_prev = float(hist.iloc[-2])

    return {
        "price": price,

        "ema20": float(ema20.iloc[-1]),
        "ema50": float(ema50.iloc[-1]),
        "ema100": float(ema100.iloc[-1]),

        "price_above_ema20":
            price > float(ema20.iloc[-1]),

        "ema20_above_ema50":
            float(ema20.iloc[-1])
            > float(ema50.iloc[-1]),

        "ema50_above_ema100":
            float(ema50.iloc[-1])
            > float(ema100.iloc[-1]),

        "macd": float(dif.iloc[-1]),
        "signal": float(dea.iloc[-1]),
        "histogram": hist_now,
        "hist_prev": hist_prev,

        "hist_improving":
            hist_now > hist_prev,

        "macd_acceleration":
            (
                hist_now - hist_prev
                >
                hist_prev - float(hist.iloc[-3])
            ),

        "rsi": float(rsi.iloc[-1]),

        "volume_ratio": volume_ratio,

        "change_5": change_5,
        "change_20": change_20,

        "previous_high":
            float(df["High"].iloc[-21:-1].max()),

        "previous_low":
            float(df["Low"].iloc[-21:-1].min()),
    }


# =========================================================
# MOMENTUM ENGINE
# =========================================================
def calculate_momentum(symbol):
    frames = {}

    for tf in ["15m", "1h", "4h"]:
        df = get_data_safe(symbol, tf)

        if df is None:
            return None

        result = calculate_tf(df)

        if result is None:
            return None

        frames[tf] = result

    m15 = frames["15m"]
    h1 = frames["1h"]
    h4 = frames["4h"]

    score = 0
    reasons = []

    # -------------------------
    # 4H trend = highest weight
    # -------------------------
    if (
        h4["price_above_ema20"]
        and h4["ema20_above_ema50"]
        and h4["ema50_above_ema100"]
    ):
        score += 20
        reasons.append("4H trend bullish")

    elif (
        not h4["price_above_ema20"]
        and not h4["ema20_above_ema50"]
        and not h4["ema50_above_ema100"]
    ):
        score -= 20
        reasons.append("4H trend bearish")

    # -------------------------
    # 1H structure
    # -------------------------
    if (
        h1["price_above_ema20"]
        and h1["ema20_above_ema50"]
    ):
        score += 15
        reasons.append("1H structure bullish")

    elif (
        not h1["price_above_ema20"]
        and not h1["ema20_above_ema50"]
    ):
        score -= 15
        reasons.append("1H structure bearish")

    # -------------------------
    # MACD multi timeframe
    # -------------------------
    bullish_macd = sum(
        x["macd"] > x["signal"]
        for x in [m15, h1, h4]
    )

    bearish_macd = sum(
        x["macd"] < x["signal"]
        for x in [m15, h1, h4]
    )

    if bullish_macd >= 2:
        score += 15
        reasons.append("MACD bullish MTF")

    elif bearish_macd >= 2:
        score -= 15
        reasons.append("MACD bearish MTF")

    # -------------------------
    # MACD acceleration
    # -------------------------
    if (
        m15["histogram"] > 0
        and m15["hist_improving"]
    ):
        score += 10
        reasons.append("MACD histogram menguat")

    elif (
        m15["histogram"] < 0
        and not m15["hist_improving"]
    ):
        score -= 10
        reasons.append("MACD histogram melemah")

    # -------------------------
    # Volume
    # -------------------------
    volume_ratio = m15["volume_ratio"]

    if volume_ratio >= 2.0:
        score += 15
        reasons.append(
            f"Volume spike {volume_ratio:.1f}x"
        )

    elif volume_ratio >= 1.3:
        score += 8
        reasons.append(
            f"Volume naik {volume_ratio:.1f}x"
        )

    elif volume_ratio < 0.7:
        score -= 3
        reasons.append("Volume rendah")

    # -------------------------
    # RSI
    # -------------------------
    rsi = m15["rsi"]

    if 50 <= rsi <= 68:
        score += 8
        reasons.append("RSI sehat")

    elif 68 < rsi <= 75:
        score += 3
        reasons.append("RSI tinggi")

    elif rsi > 80:
        score -= 5
        reasons.append("RSI terlalu panas")

    elif rsi < 30:
        reasons.append("RSI oversold")

    # -------------------------
    # Price momentum
    # -------------------------
    if h1["change_20"] >= 3:
        score += 7
        reasons.append("1H momentum kuat")

    elif h1["change_20"] <= -3:
        score -= 7
        reasons.append("1H momentum bearish")

    # -------------------------
    # Breakout
    # -------------------------
    breakout = False
    breakout_type = "-"

    if (
        m15["price"] > m15["previous_high"]
        and volume_ratio >= 1.3
    ):
        score += 12
        breakout = True
        breakout_type = "BREAKOUT"
        reasons.append("Breakout + volume")

    elif (
        m15["price"] < m15["previous_low"]
        and volume_ratio >= 1.3
    ):
        score -= 12
        breakout = True
        breakout_type = "BREAKDOWN"
        reasons.append("Breakdown + volume")

    score = max(-100, min(100, score))

    # -------------------------
    # Direction
    # -------------------------
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

    # -------------------------
    # Momentum phase
    # -------------------------
    if (
        h1["price_above_ema20"]
        and h1["ema20_above_ema50"]
        and m15["histogram"] > 0
        and m15["hist_improving"]
        and volume_ratio >= 1.3
    ):
        momentum_state = "🚀 MOMENTUM BUILDING"

    elif (
        volume_ratio >= 2
        and abs(m15["change_5"]) >= 1
    ):
        momentum_state = "⚡ MOMENTUM ACTIVE"

    elif (
        m15["histogram"] > 0
        and m15["hist_improving"]
    ):
        momentum_state = "🌱 EARLY MOMENTUM"

    elif (
        m15["histogram"] < 0
        and not m15["hist_improving"]
    ):
        momentum_state = "📉 MOMENTUM WEAKENING"

    else:
        momentum_state = "⏳ WAIT"

    return {
        "Symbol": symbol,
        "Price": m15["price"],
        "Score": score,
        "Signal": signal,
        "Direction": direction,
        "Momentum": momentum_state,

        "15M %": m15["change_5"],
        "1H %": h1["change_20"],
        "4H %": h4["change_20"],

        "Volume x": volume_ratio,
        "RSI": rsi,

        "MACD": m15["macd"],
        "MACD Hist": m15["histogram"],
        "MACD Accel":
            m15["macd_acceleration"],

        "Breakout": breakout_type,

        "Reasons":
            " | ".join(reasons[:10]),

        "_frames": frames,
    }


# =========================================================
# SCAN WATCHLIST
# =========================================================
def scan_watchlist(symbols):

    results = []
    details = {}

    progress = st.progress(0)
    status = st.empty()

    total = len(symbols)

    for i, symbol in enumerate(symbols):

        status.write(
            f"🔍 Scanning {symbol} "
            f"({i + 1}/{total})"
        )

        result = calculate_momentum(symbol)

        if result:
            results.append(result)
            details[symbol] = result

        progress.progress(
            (i + 1) / total
        )

    progress.empty()
    status.empty()

    if not results:
        return pd.DataFrame(), {}

    df = pd.DataFrame(results)

    df = df.sort_values(
        "Score",
        ascending=False
    ).reset_index(drop=True)

    return df, details


# =========================================================
# SIDEBAR
# =========================================================
with st.sidebar:

    st.subheader("📊 Scanner Settings")

    auto_refresh = st.toggle(
        "🔄 Auto Refresh",
        value=True,
        help=(
            "Scanner akan rerun secara berkala. "
            "Tidak menggunakan while True."
        )
    )

    refresh = st.slider(
        "Interval Refresh (detik)",
        30,
        300,
        60,
        10,
        disabled=not auto_refresh
    )

    st.divider()

    st.subheader("👀 Watchlist")

    new_coin = st.text_input(
        "Tambah coin",
        placeholder="contoh: SYN atau CYS"
    )

    if st.button(
        "➕ Tambah",
        use_container_width=True
    ):
        if new_coin:

            coin = new_coin.strip().upper()

            if not coin.endswith("-USD"):
                coin += "-USD"

            if coin not in st.session_state.watchlist:
                st.session_state.watchlist.append(
                    coin
                )

    remove_coin = st.selectbox(
        "Hapus coin",
        ["-"] + st.session_state.watchlist
    )

    if st.button(
        "🗑️ Hapus",
        use_container_width=True
    ):
        if (
            remove_coin != "-"
            and remove_coin in st.session_state.watchlist
        ):
            st.session_state.watchlist.remove(
                remove_coin
            )

    st.caption(
        f"Watchlist: "
        f"{len(st.session_state.watchlist)} coin"
    )

    st.divider()

    if st.button(
        "🚀 Scan Sekarang",
        use_container_width=True
    ):
        st.session_state.force_scan = True
    else:
        if "force_scan" not in st.session_state:
            st.session_state.force_scan = False


# =========================================================
# AUTO REFRESH
# =========================================================
if auto_refresh:

    st_autorefresh(
        interval=refresh * 1000,
        key="momentum_auto_refresh"
    )


# =========================================================
# SCAN CONTROL
# =========================================================
# Penting:
# st_autorefresh menyebabkan rerun, tetapi scan hanya dilakukan
# ketika interval benar-benar habis / force scan aktif.
#
# Kita memakai timestamp untuk mencegah scan berulang pada setiap
# UI rerun yang terjadi dalam waktu singkat.

now = datetime.now(timezone.utc)

if "last_scan_dt" not in st.session_state:
    st.session_state.last_scan_dt = None

if st.session_state.last_scan_dt is None:
    should_scan = True

else:
    elapsed = (
        now - st.session_state.last_scan_dt
    ).total_seconds()

    should_scan = (
        auto_refresh
        and elapsed >= refresh
    )

if st.session_state.get(
    "force_scan",
    False
):
    should_scan = True
    st.session_state.force_scan = False


# =========================================================
# RUN SCANNER
# =========================================================
if should_scan:

    with st.spinner(
        "🔍 Scanning momentum..."
    ):

        df, details = scan_watchlist(
            st.session_state.watchlist
        )

    if not df.empty:

        st.session_state.momentum_results = df

        st.session_state.momentum_details = details

        st.session_state.last_scan = (
            datetime.now().strftime(
                "%H:%M:%S"
            )
        )

        st.session_state.last_scan_dt = now


# =========================================================
# TABS
# =========================================================
tab1, tab2, tab3 = st.tabs([
    "🚀 Momentum Scanner",
    "📈 Chart Analysis",
    "📋 Momentum History"
])


# =========================================================
# TAB 1 - SCANNER
# =========================================================
with tab1:

    st.subheader(
        "🚀 Momentum Scanner - SPOT"
    )

    st.caption(
        "Deteksi momentum saja — "
        "bukan auto entry."
    )

    df = st.session_state.momentum_results

    if df.empty:

        st.info(
            "Belum ada data momentum."
        )

    else:

        display_columns = [
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
            "Breakout",
        ]

        st.dataframe(
            df[display_columns],
            use_container_width=True,
            hide_index=True
        )

        st.success(
            f"🏆 Top Momentum: "
            f"{df.iloc[0]['Symbol']} | "
            f"Score {df.iloc[0]['Score']}/100 | "
            f"{df.iloc[0]['Momentum']}"
        )

        st.divider()

        c1, c2 = st.columns(2)

        with c1:

            st.markdown(
                "### 🟢 Bullish Momentum"
            )

            bullish = df[
                df["Direction"] == "LONG"
            ].head(10)

            st.dataframe(
                bullish[display_columns],
                use_container_width=True,
                hide_index=True
            )

        with c2:

            st.markdown(
                "### 🔴 Bearish Momentum"
            )

            bearish = (
                df[
                    df["Direction"] == "SHORT"
                ]
                .sort_values(
                    "Score"
                )
                .head(10)
            )

            st.dataframe(
                bearish[display_columns],
                use_container_width=True,
                hide_index=True
            )

        st.divider()

        st.markdown(
            "### 🌱 Momentum Sedang Mulai Terbentuk"
        )

        building = df[
            df["Momentum"].isin([
                "🌱 EARLY MOMENTUM",
                "🚀 MOMENTUM BUILDING",
                "⚡ MOMENTUM ACTIVE",
            ])
        ]

        if building.empty:

            st.info(
                "Belum ada momentum building."
            )

        else:

            st.dataframe(
                building[
                    display_columns + ["Reasons"]
                ].head(20),
                use_container_width=True,
                hide_index=True
            )

        st.divider()

        selected = st.selectbox(
            "🔎 Detail coin",
            df["Symbol"].tolist()
        )

        row = df[
            df["Symbol"] == selected
        ].iloc[0]

        a, b, c, d, e = st.columns(5)

        a.metric(
            "Score",
            f"{row['Score']}/100"
        )

        b.metric(
            "15M",
            f"{row['15M %']:.2f}%"
        )

        c.metric(
            "1H",
            f"{row['1H %']:.2f}%"
        )

        d.metric(
            "Volume",
            f"{row['Volume x']:.2f}x"
        )

        e.metric(
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
            f"**Reasons:** {row['Reasons']}"
        )


# =========================================================
# TAB 2 - CHART ANALYSIS
# =========================================================
with tab2:

    st.subheader(
        "📈 Chart Analysis"
    )

    df = st.session_state.momentum_results

    if df.empty:

        st.info(
            "Scan terlebih dahulu."
        )

    else:

        selected = st.selectbox(
            "Coin",
            df["Symbol"].tolist(),
            key="chart_symbol"
        )

        timeframe = st.selectbox(
            "Timeframe",
            ["15m", "1h", "4h"],
            index=1
        )

        chart_df = get_data_safe(
            selected,
            timeframe
        )

        if chart_df is not None:

            close = chart_df["Close"]

            ema20 = EMA(close, 20)
            ema50 = EMA(close, 50)
            ema100 = EMA(close, 100)

            dif, dea, hist = MACD(close)

            fig = go.Figure()

            fig.add_trace(
                go.Candlestick(
                    x=chart_df.index,
                    open=chart_df["Open"],
                    high=chart_df["High"],
                    low=chart_df["Low"],
                    close=chart_df["Close"],
                    name="Price"
                )
            )

            fig.add_trace(
                go.Scatter(
                    x=chart_df.index,
                    y=ema20,
                    name="EMA20"
                )
            )

            fig.add_trace(
                go.Scatter(
                    x=chart_df.index,
                    y=ema50,
                    name="EMA50"
                )
            )

            fig.add_trace(
                go.Scatter(
                    x=chart_df.index,
                    y=ema100,
                    name="EMA100"
                )
            )

            fig.update_layout(
                height=650,
                xaxis_rangeslider_visible=False,
                title=(
                    f"{selected} — {timeframe}"
                )
            )

            st.plotly_chart(
                fig,
                use_container_width=True
            )

            st.markdown(
                "### MACD Histogram"
            )

            macd_fig = go.Figure()

            macd_fig.add_trace(
                go.Scatter(
                    x=chart_df.index,
                    y=hist,
                    mode="lines",
                    name="Histogram"
                )
            )

            macd_fig.add_trace(
                go.Scatter(
                    x=chart_df.index,
                    y=dif,
                    mode="lines",
                    name="MACD"
                )
            )

            macd_fig.add_trace(
                go.Scatter(
                    x=chart_df.index,
                    y=dea,
                    mode="lines",
                    name="Signal"
                )
            )

            macd_fig.update_layout(
                height=300
            )

            st.plotly_chart(
                macd_fig,
                use_container_width=True
            )


# =========================================================
# TAB 3 - MOMENTUM HISTORY
# =========================================================
with tab3:

    st.subheader(
        "📋 Momentum History"
    )

    df = st.session_state.momentum_results

    if df.empty:

        st.info(
            "Belum ada history scanner."
        )

    else:

        st.caption(
            "History disimpan di session selama "
            "aplikasi berjalan."
        )

        history = df[
            [
                "Symbol",
                "Score",
                "Momentum",
                "15M %",
                "1H %",
                "4H %",
                "Volume x",
                "RSI",
                "Breakout",
            ]
        ].copy()

        st.dataframe(
            history,
            use_container_width=True,
            hide_index=True
        )

        st.download_button(
            "📥 Download Momentum CSV",
            history.to_csv(index=False),
            file_name=(
                "momentum_history.csv"
            ),
            mime="text/csv"
        )


# =========================================================
# FOOTER
# =========================================================
st.divider()

st.caption(
    "Data source: Yahoo Finance | "
    "Spot scanner | No Binance | "
    "No while True"
)
