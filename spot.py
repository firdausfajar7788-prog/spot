
import os
import requests
import numpy as np
import pandas as pd
import streamlit as st

from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from streamlit_autorefresh import st_autorefresh
from supabase import create_client, Client


# ============================================================
# CONFIG
# ============================================================

st.set_page_config(
    page_title="Momentum Scanner PRO",
    page_icon="⚡",
    layout="wide"
)

BINANCE_BASE = "https://api.binance.com"
REQUEST_TIMEOUT = 8

TIMEFRAMES = {
    "15m": "15m",
    "1h": "1h",
    "4h": "4h",
}


# ============================================================
# SECRETS / SUPABASE
# ============================================================

def get_supabase() -> Client | None:
    """
    Mendukung:
      1. Streamlit secrets:
         [supabase]
         url = "..."
         key = "..."
      2. Environment variables:
         SUPABASE_URL
         SUPABASE_KEY
    """
    try:
        if "supabase" in st.secrets:
            url = st.secrets["supabase"]["url"]
            key = st.secrets["supabase"]["key"]
        else:
            url = os.getenv("SUPABASE_URL")
            key = os.getenv("SUPABASE_KEY")

        if not url or not key:
            return None

        return create_client(url, key)

    except Exception as e:
        print(f"Supabase init error: {e}")
        return None


# ============================================================
# SESSION STATE
# ============================================================

if "results" not in st.session_state:
    st.session_state.results = pd.DataFrame()

if "last_scan" not in st.session_state:
    st.session_state.last_scan = None

if "db_status" not in st.session_state:
    st.session_state.db_status = "UNKNOWN"


# ============================================================
# BINANCE DATA
# ============================================================

@st.cache_data(ttl=60, show_spinner=False)
def get_symbols():

    try:
        r = requests.get(
            f"{BINANCE_BASE}/api/v3/exchangeInfo",
            timeout=REQUEST_TIMEOUT
        )
        r.raise_for_status()
        data = r.json()

        blacklist = {
            "USDCUSDT",
            "FDUSDUSDT",
            "TUSDUSDT",
            "USDPUSDT",
            "DAIUSDT",
            "EURUSDT",
        }

        symbols = []

        for x in data.get("symbols", []):
            if (
                x.get("status") == "TRADING"
                and x.get("quoteAsset") == "USDT"
                and x.get("isSpotTradingAllowed", False)
                and x.get("symbol") not in blacklist
            ):
                symbols.append(x["symbol"])

        return symbols

    except Exception as e:
        print(f"Symbol error: {e}")
        return []


@st.cache_data(ttl=20, show_spinner=False)
def get_24h_volume():

    try:
        r = requests.get(
            f"{BINANCE_BASE}/api/v3/ticker/24hr",
            timeout=REQUEST_TIMEOUT
        )
        r.raise_for_status()

        return {
            x["symbol"]: float(x.get("quoteVolume", 0))
            for x in r.json()
            if x.get("symbol", "").endswith("USDT")
        }

    except Exception as e:
        print(f"24h volume error: {e}")
        return {}


@st.cache_data(ttl=20, show_spinner=False)
def get_klines(symbol, interval, limit=100):

    try:
        r = requests.get(
            f"{BINANCE_BASE}/api/v3/klines",
            params={
                "symbol": symbol,
                "interval": interval,
                "limit": limit,
            },
            timeout=REQUEST_TIMEOUT,
        )
        r.raise_for_status()

        raw = r.json()

        if not isinstance(raw, list) or len(raw) < 60:
            return None

        df = pd.DataFrame(
            raw,
            columns=[
                "open_time",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "close_time",
                "quote_volume",
                "trades",
                "taker_base",
                "taker_quote",
                "ignore",
            ],
        )

        for col in [
            "open",
            "high",
            "low",
            "close",
            "volume",
            "quote_volume",
        ]:
            df[col] = pd.to_numeric(
                df[col],
                errors="coerce"
            )

        df["open_time"] = pd.to_datetime(
            df["open_time"],
            unit="ms",
            utc=True
        )

        return df

    except Exception as e:
        print(f"Kline error {symbol} {interval}: {e}")
        return None


# ============================================================
# INDICATORS
# ============================================================

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

    hist = dif - dea

    return dif, dea, hist


# ============================================================
# TIMEFRAME ANALYSIS
# ============================================================

def analyze_tf(df):

    if df is None or len(df) < 60:
        return None

    close = df["close"]

    ema20 = EMA(close, 20)
    ema50 = EMA(close, 50)

    dif, dea, hist = MACD(close)

    rsi = RSI(close)

    volume_ma = df["volume"].rolling(20).mean()

    price = float(close.iloc[-1])

    change_5 = (
        price / float(close.iloc[-6]) - 1
    ) * 100

    change_20 = (
        price / float(close.iloc[-21]) - 1
    ) * 100

    volume_ratio = (
        float(df["volume"].iloc[-1])
        / float(volume_ma.iloc[-1])
        if volume_ma.iloc[-1] > 0
        else 0
    )

    return {
        "price": price,
        "change_5": change_5,
        "change_20": change_20,

        "ema20": float(ema20.iloc[-1]),
        "ema50": float(ema50.iloc[-1]),

        "bullish":
            price > float(ema20.iloc[-1])
            and float(ema20.iloc[-1])
            > float(ema50.iloc[-1]),

        "bearish":
            price < float(ema20.iloc[-1])
            and float(ema20.iloc[-1])
            < float(ema50.iloc[-1]),

        "dif": float(dif.iloc[-1]),
        "dea": float(dea.iloc[-1]),
        "hist": float(hist.iloc[-1]),
        "hist_prev": float(hist.iloc[-2]),
        "hist_rising":
            float(hist.iloc[-1])
            > float(hist.iloc[-2]),

        "rsi": float(rsi.iloc[-1]),
        "rsi_prev": float(rsi.iloc[-2]),

        "volume_ratio": volume_ratio,

        "previous_high":
            float(df["high"].iloc[-21:-1].max()),

        "previous_low":
            float(df["low"].iloc[-21:-1].min()),
    }


# ============================================================
# MOMENTUM ENGINE
# ============================================================

def analyze_coin(symbol):

    try:

        data = {}

        for tf, interval in TIMEFRAMES.items():

            df = get_klines(
                symbol,
                interval,
                100
            )

            result = analyze_tf(df)

            if result is None:
                return None

            data[tf] = result

        m15 = data["15m"]
        h1 = data["1h"]
        h4 = data["4h"]

        score = 0
        reasons = []

        # ----------------------------------------------------
        # 4H TREND
        # ----------------------------------------------------

        if h4["bullish"]:
            score += 20
            reasons.append("4H bullish")

        elif h4["bearish"]:
            score -= 20
            reasons.append("4H bearish")

        # ----------------------------------------------------
        # 1H TREND
        # ----------------------------------------------------

        if h1["bullish"]:
            score += 15
            reasons.append("1H bullish")

        elif h1["bearish"]:
            score -= 15
            reasons.append("1H bearish")

        # ----------------------------------------------------
        # PRICE MOMENTUM
        # ----------------------------------------------------

        if m15["change_5"] >= 1:
            score += 10
            reasons.append("15M momentum naik")

        elif m15["change_5"] <= -1:
            score -= 10
            reasons.append("15M momentum turun")

        # ----------------------------------------------------
        # MACD MTF
        # ----------------------------------------------------

        bullish_macd = sum(
            x["dif"] > x["dea"]
            for x in [m15, h1, h4]
        )

        bearish_macd = sum(
            x["dif"] < x["dea"]
            for x in [m15, h1, h4]
        )

        if bullish_macd >= 2:
            score += 15
            reasons.append("MACD bullish MTF")

        elif bearish_macd >= 2:
            score -= 15
            reasons.append("MACD bearish MTF")

        # ----------------------------------------------------
        # MACD ACCELERATION
        # ----------------------------------------------------

        if (
            m15["hist"] > 0
            and m15["hist_rising"]
        ):
            score += 10
            reasons.append("MACD histogram menguat")

        elif (
            m15["hist"] < 0
            and not m15["hist_rising"]
        ):
            score -= 10
            reasons.append("MACD histogram melemah")

        # ----------------------------------------------------
        # VOLUME
        # ----------------------------------------------------

        vr = m15["volume_ratio"]

        if vr >= 2:
            score += 15
            reasons.append("Volume spike >= 2x")

        elif vr >= 1.3:
            score += 8
            reasons.append("Volume meningkat")

        elif vr < 0.7:
            score -= 3
            reasons.append("Volume rendah")

        # ----------------------------------------------------
        # RSI
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # 1H MOMENTUM
        # ----------------------------------------------------

        if h1["change_20"] >= 3:
            score += 7
            reasons.append("1H momentum kuat")

        elif h1["change_20"] <= -3:
            score -= 7
            reasons.append("1H momentum bearish")

        # ----------------------------------------------------
        # BREAKOUT / BREAKDOWN
        # ----------------------------------------------------

        breakout = False
        breakout_type = "-"

        if (
            m15["price"] > m15["previous_high"]
            and vr >= 1.3
        ):
            score += 12
            breakout = True
            breakout_type = "BREAKOUT"
            reasons.append("Breakout + volume")

        elif (
            m15["price"] < m15["previous_low"]
            and vr >= 1.3
        ):
            score -= 12
            breakout = True
            breakout_type = "BREAKDOWN"
            reasons.append("Breakdown + volume")

        # ----------------------------------------------------
        # MOMENTUM STATE
        # ----------------------------------------------------

        if (
            h1["bullish"]
            and m15["hist"] > 0
            and m15["hist_rising"]
            and vr >= 1.3
        ):
            momentum = "🚀 MOMENTUM BUILDING"

        elif (
            vr >= 2
            and abs(m15["change_5"]) >= 1
        ):
            momentum = "⚡ MOMENTUM ACTIVE"

        elif (
            m15["hist"] > 0
            and m15["hist_rising"]
        ):
            momentum = "🌱 EARLY MOMENTUM"

        elif (
            m15["hist"] < 0
            and not m15["hist_rising"]
        ):
            momentum = "📉 MOMENTUM WEAKENING"

        else:
            momentum = "⏳ WAIT"

        # ----------------------------------------------------
        # FINAL SIGNAL
        # ----------------------------------------------------

        score = max(-100, min(100, score))

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
            "symbol": symbol,
            "price": float(m15["price"]),
            "score": int(score),
            "signal": signal,
            "direction": direction,
            "momentum": momentum,

            "change_15m": float(m15["change_5"]),
            "change_1h": float(h1["change_20"]),
            "change_4h": float(h4["change_20"]),

            "volume_ratio": float(vr),
            "rsi": float(rsi),

            "macd": float(m15["dif"]),
            "macd_signal": float(m15["dea"]),
            "macd_histogram": float(m15["hist"]),
            "macd_acceleration":
                bool(m15["hist_rising"]),

            "score_4h":
                20 if h4["bullish"]
                else -20 if h4["bearish"]
                else 0,

            "score_1h":
                15 if h1["bullish"]
                else -15 if h1["bearish"]
                else 0,

            "breakout": breakout,
            "breakout_type": breakout_type,

            "reasons": " | ".join(
                reasons[:10]
            ),
        }

    except Exception as e:

        print(
            f"Analyze {symbol} error: {e}"
        )

        return None


# ============================================================
# DATABASE
# ============================================================

def save_momentum_to_db(result):

    supabase = get_supabase()

    if supabase is None:
        return False, "Supabase belum dikonfigurasi."

    try:

        now = datetime.now(timezone.utc)

        # Satu bucket per menit.
        time_bucket = now.replace(
            second=0,
            microsecond=0
        )

        payload = {
            "symbol":
                result["symbol"],

            "scan_time":
                now.isoformat(),

            "time_bucket":
                time_bucket.isoformat(),

            "score":
                result["score"],

            "status":
                result["momentum"],

            "score_4h":
                result["score_4h"],

            "score_1h":
                result["score_1h"],

            "score_15m":
                result["score"],

            "rsi_1h":
                result["rsi"],

            "volume_ratio_1h":
                result["volume_ratio"],

            "breakout_1h":
                result["breakout"],

            "macd_1h":
                result["macd"],

            "macd_signal_1h":
                result["macd_signal"],

            "macd_histogram_1h":
                result["macd_histogram"],

            "macd_acceleration_1h":
                result["macd_acceleration"],

            "price_1h":
                result["price"],
        }

        supabase.table(
            "momentum_history"
        ).upsert(
            payload,
            on_conflict="symbol,time_bucket"
        ).execute()

        return True, "OK"

    except Exception as e:

        return False, str(e)


def save_all_momentum(results):

    supabase = get_supabase()

    if supabase is None:
        return 0, "Supabase belum dikonfigurasi."

    if not results:
        return 0, "Tidak ada hasil."

    now = datetime.now(timezone.utc)

    bucket = now.replace(
        second=0,
        microsecond=0
    )

    rows = []

    for result in results:

        rows.append({
            "symbol": result["symbol"],
            "scan_time": now.isoformat(),
            "time_bucket": bucket.isoformat(),

            "score": result["score"],
            "status": result["momentum"],

            "score_4h": result["score_4h"],
            "score_1h": result["score_1h"],
            "score_15m": result["score"],

            "rsi_1h": result["rsi"],
            "volume_ratio_1h":
                result["volume_ratio"],

            "breakout_1h":
                result["breakout"],

            "macd_1h":
                result["macd"],

            "macd_signal_1h":
                result["macd_signal"],

            "macd_histogram_1h":
                result["macd_histogram"],

            "macd_acceleration_1h":
                result["macd_acceleration"],

            "price_1h":
                result["price"],
        })

    try:

        # Satu request untuk seluruh hasil scanner.
        supabase.table(
            "momentum_history"
        ).upsert(
            rows,
            on_conflict="symbol,time_bucket"
        ).execute()

        return len(rows), "OK"

    except Exception as e:

        return 0, str(e)


def get_momentum_history(
    symbol=None,
    limit=300
):

    supabase = get_supabase()

    if supabase is None:
        return pd.DataFrame()

    try:

        query = (
            supabase
            .table("momentum_history")
            .select("*")
            .order(
                "scan_time",
                desc=True
            )
            .limit(limit)
        )

        if symbol:
            query = query.eq(
                "symbol",
                symbol
            )

        response = query.execute()

        if not response.data:
            return pd.DataFrame()

        return pd.DataFrame(
            response.data
        )

    except Exception as e:

        print(
            f"History error: {e}"
        )

        return pd.DataFrame()


# ============================================================
# MARKET SCAN
# ============================================================

def scan_market(
    symbols,
    workers=8
):

    results = []

    progress = st.progress(0)

    status = st.empty()

    total = len(symbols)

    with ThreadPoolExecutor(
        max_workers=workers
    ) as executor:

        futures = {
            executor.submit(
                analyze_coin,
                symbol
            ): symbol
            for symbol in symbols
        }

        completed = 0

        for future in as_completed(
            futures
        ):

            completed += 1

            symbol = futures[future]

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

    return results


# ============================================================
# UI
# ============================================================

st.title(
    "⚡ Momentum Scanner PRO"
)

st.caption(
    "Binance Spot | 15M + 1H + 4H | "
    "Trend + MACD + Volume + RSI + Breakout"
)

with st.sidebar:

    st.header(
        "⚙️ Scanner Settings"
    )

    max_coins = st.slider(
        "Coin yang discan",
        10,
        100,
        30,
        10
    )

    workers = st.slider(
        "Concurrent request",
        2,
        12,
        8
    )

    auto_refresh = st.checkbox(
        "🔄 Auto Refresh",
        value=False
    )

    refresh_seconds = st.slider(
        "Interval",
        30,
        300,
        60,
        10,
        disabled=not auto_refresh
    )

    st.divider()

    supabase = get_supabase()

    if supabase is None:
        st.warning(
            "⚠️ Supabase belum terhubung."
        )
    else:
        st.success(
            "🟢 Supabase connected"
        )


# ============================================================
# AUTO REFRESH
# ============================================================

if auto_refresh:

    st_autorefresh(
        interval=refresh_seconds * 1000,
        key="momentum_auto_refresh"
    )


# ============================================================
# SCAN
# ============================================================

scan_now = st.button(
    "🚀 SCAN MARKET",
    type="primary",
    use_container_width=True
)

should_auto_scan = (
    auto_refresh
    and st.session_state.last_scan is None
)

if scan_now or should_auto_scan:

    symbols = get_symbols()

    volumes = get_24h_volume()

    symbols = sorted(
        symbols,
        key=lambda x:
            volumes.get(x, 0),
        reverse=True
    )[:max_coins]

    if not symbols:

        st.error(
            "Tidak bisa mengambil market Binance."
        )

    else:

        with st.spinner(
            f"Scanning {len(symbols)} coin..."
        ):

            raw_results = scan_market(
                symbols,
                workers
            )

        if raw_results:

            df = pd.DataFrame(
                raw_results
            )

            df = df.sort_values(
                "score",
                ascending=False
            ).reset_index(
                drop=True
            )

            st.session_state.results = df

            st.session_state.last_scan = (
                datetime.now().strftime(
                    "%H:%M:%S"
                )
            )

            # SAVE TO SUPABASE
            saved, db_message = (
                save_all_momentum(
                    raw_results
                )
            )

            if saved:

                st.success(
                    f"✅ {saved} momentum snapshot "
                    f"disimpan ke Supabase."
                )

                st.session_state.db_status = (
                    f"SAVED {saved}"
                )

            else:

                st.warning(
                    "⚠️ Hasil scanner tampil, "
                    f"tetapi database gagal: "
                    f"{db_message}"
                )

                st.session_state.db_status = (
                    "ERROR"
                )

        else:

            st.warning(
                "Tidak ada hasil scanner."
            )


# ============================================================
# CURRENT RESULTS
# ============================================================

df = st.session_state.results

if df.empty:

    st.info(
        "Klik **SCAN MARKET** untuk mulai."
    )

else:

    st.caption(
        f"Last scan: "
        f"{st.session_state.last_scan} | "
        f"DB: {st.session_state.db_status}"
    )

    display_columns = [
        "symbol",
        "price",
        "score",
        "signal",
        "momentum",
        "change_15m",
        "change_1h",
        "change_4h",
        "volume_ratio",
        "rsi",
        "breakout_type",
    ]

    st.subheader(
        "🔥 Top Momentum"
    )

    st.dataframe(
        df[display_columns].head(15),
        use_container_width=True,
        hide_index=True
    )

    # ========================================================
    # BULLISH / BEARISH
    # ========================================================

    c1, c2 = st.columns(2)

    with c1:

        st.subheader(
            "🟢 Bullish"
        )

        bullish = df[
            df["direction"] == "LONG"
        ].head(10)

        st.dataframe(
            bullish[display_columns],
            use_container_width=True,
            hide_index=True
        )

    with c2:

        st.subheader(
            "🔴 Bearish"
        )

        bearish = (
            df[
                df["direction"] == "SHORT"
            ]
            .sort_values(
                "score"
            )
            .head(10)
        )

        st.dataframe(
            bearish[display_columns],
            use_container_width=True,
            hide_index=True
        )

    # ========================================================
    # MOMENTUM BUILDING
    # ========================================================

    st.divider()

    st.subheader(
        "🚀 Momentum Sedang Terbentuk"
    )

    building = df[
        df["momentum"].isin([
            "🌱 EARLY MOMENTUM",
            "🚀 MOMENTUM BUILDING",
            "⚡ MOMENTUM ACTIVE",
        ])
    ].copy()

    if not building.empty:

        st.dataframe(
            building[
                display_columns + [
                    "reasons"
                ]
            ].head(20),
            use_container_width=True,
            hide_index=True
        )

    else:

        st.info(
            "Belum ada momentum building."
        )

    # ========================================================
    # DETAIL + HISTORY
    # ========================================================

    st.divider()

    st.subheader(
        "🔎 Momentum Detail & History"
    )

    selected = st.selectbox(
        "Pilih coin",
        df["symbol"].tolist()
    )

    row = df[
        df["symbol"] == selected
    ].iloc[0]

    a, b, c, d, e = st.columns(5)

    a.metric(
        "Score",
        row["score"]
    )

    b.metric(
        "15M",
        f"{row['change_15m']:.2f}%"
    )

    c.metric(
        "1H",
        f"{row['change_1h']:.2f}%"
    )

    d.metric(
        "Volume",
        f"{row['volume_ratio']:.2f}x"
    )

    e.metric(
        "RSI",
        f"{row['rsi']:.1f}"
    )

    st.write(
        f"**Signal:** {row['signal']}"
    )

    st.write(
        f"**Momentum:** {row['momentum']}"
    )

    st.write(
        f"**Breakout:** {row['breakout_type']}"
    )

    st.write(
        f"**Reasons:** {row['reasons']}"
    )

    # --------------------------------------------------------
    # HISTORY FROM SUPABASE
    # --------------------------------------------------------

    history = get_momentum_history(
        symbol=selected,
        limit=300
    )

    if not history.empty:

        st.markdown(
            f"### 📈 {selected} Momentum History"
        )

        history["scan_time"] = pd.to_datetime(
            history["scan_time"],
            errors="coerce"
        )

        history = history.sort_values(
            "scan_time"
        )

        chart_df = history[
            [
                "scan_time",
                "score"
            ]
        ].dropna()

        if not chart_df.empty:

            st.line_chart(
                chart_df.set_index(
                    "scan_time"
                )["score"],
                height=350
            )

        st.dataframe(
            history[
                [
                    "scan_time",
                    "symbol",
                    "score",
                    "status",
                    "score_4h",
                    "score_1h",
                    "score_15m",
                    "rsi_1h",
                    "volume_ratio_1h",
                    "breakout_1h",
                    "macd_acceleration_1h",
                    "price_1h",
                ]
            ].tail(100).sort_values(
                "scan_time",
                ascending=False
            ),
            use_container_width=True,
            hide_index=True
        )

    else:

        st.info(
            "Belum ada history di database "
            f"untuk {selected}."
        )


# ============================================================
# FOOTER
# ============================================================

st.divider()

st.caption(
    "Momentum Scanner PRO | "
    "Binance Spot Public API | "
    "Supabase Momentum History | "
    "No while True"
)
