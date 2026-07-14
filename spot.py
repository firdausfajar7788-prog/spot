import streamlit as st
import pandas as pd
import requests
import hmac
import hashlib
import time
from datetime import datetime

# =========================================================
# PAGE CONFIG
# =========================================================
st.set_page_config(
    page_title="🇮🇩 Indodax + CoinGecko",
    layout="wide",
    initial_sidebar_state="expanded"
)

# =========================================================
# CUSTOM CSS
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
    [data-testid="stMetricLabel"] { color: #94a3b8; font-size: 13px; }
    [data-testid="stMetricValue"] { color: #f1f5f9; font-size: 24px; font-weight: 700; }
    .arrow-up { color: #00ff88; font-weight: 700; }
    .arrow-down { color: #ff3b5c; font-weight: 700; }
    .arrow-neutral { color: #ffaa00; font-weight: 700; }
    .signal-strong-buy { background: #00ff88; color: #000; font-weight: 700; padding: 2px 10px; border-radius: 6px; }
    .signal-buy { background: #00c8ff; color: #000; font-weight: 700; padding: 2px 10px; border-radius: 6px; }
    .signal-strong-sell { background: #ff3b5c; color: #fff; font-weight: 700; padding: 2px 10px; border-radius: 6px; }
    .signal-sell { background: #ff6b6b; color: #fff; font-weight: 700; padding: 2px 10px; border-radius: 6px; }
    .signal-hold { background: #ffaa00; color: #000; font-weight: 700; padding: 2px 10px; border-radius: 6px; }
    .stButton > button {
        background: linear-gradient(145deg, #00ff88, #00cc66);
        color: #000;
        font-weight: 700;
        border: none;
        border-radius: 10px;
        padding: 10px 24px;
        transition: all 0.3s ease;
    }
    .stButton > button:hover { transform: scale(1.03); box-shadow: 0 0 30px rgba(0,255,136,0.3); }
</style>
""", unsafe_allow_html=True)

# =========================================================
# SESSION STATE
# =========================================================
if "prev_data" not in st.session_state:
    st.session_state.prev_data = {}
if "last_update" not in st.session_state:
    st.session_state.last_update = datetime.now()
if "api_key" not in st.session_state:
    st.session_state.api_key = ""
if "api_secret" not in st.session_state:
    st.session_state.api_secret = ""

# =========================================================
# PRIVATE API INDODAX
# =========================================================
def indodax_private(method, params=None):
    api_key = st.session_state.api_key
    api_secret = st.session_state.api_secret
    if not api_key or not api_secret:
        return {"error": "API Key/Secret belum diisi"}
    if params is None:
        params = {}
    params["method"] = method
    params["nonce"] = int(time.time() * 1000)
    post_data = "&".join([f"{k}={v}" for k, v in params.items()])
    sign = hmac.new(api_secret.encode(), post_data.encode(), hashlib.sha512).hexdigest()
    headers = {"Key": api_key, "Sign": sign}
    try:
        r = requests.post("https://indodax.com/tapi", data=params, headers=headers, timeout=10)
        return r.json()
    except Exception as e:
        return {"error": str(e)}

# =========================================================
# CACHED TRADE HISTORY
# =========================================================
@st.cache_data(ttl=300)
def cached_trade_history(pair):
    res = indodax_private("tradeHistory", {"pair": pair})
    if "return" in res and "trades" in res["return"]:
        return res["return"]["trades"]
    return []

# =========================================================
# AVG BUY PRICE
# =========================================================
def get_avg_buy_price(pair):
    trades = cached_trade_history(pair)
    if not trades:
        return None
    buy_trades = [t for t in trades if t.get("type") == "buy"]
    if not buy_trades:
        return None
    total_coin = 0.0
    total_cost = 0.0
    for t in buy_trades:
        coin_key = pair.replace("_idr", "")
        amount = float(t.get("amount", t.get(coin_key, 0)))
        price = float(t.get("price", 0))
        if amount > 0 and price > 0:
            total_coin += amount
            total_cost += amount * price
    if total_coin == 0:
        return None
    return total_cost / total_coin

# =========================================================
# SUPPORT & RESISTANCE
# =========================================================
def get_support_resistance(pair):
    try:
        r = requests.get(f"https://indodax.com/api/ticker/{pair}", timeout=5)
        data = r.json()
        last = float(data["ticker"]["last"])
        high = float(data["ticker"]["high"])
        low = float(data["ticker"]["low"])
        pp = (high + low + last) / 3
        s1 = 2 * pp - high
        s2 = pp - (high - low)
        r1 = 2 * pp - low
        r2 = pp + (high - low)
        return {"last": last, "s1": s1, "s2": s2, "r1": r1, "r2": r2}
    except:
        return {"last": 0, "s1": 0, "s2": 0, "r1": 0, "r2": 0}

# =========================================================
# COINGECKO – AMBIL RSI & MACD SAJA (TANPA EMA)
# =========================================================
@st.cache_data(ttl=300)
def get_coingecko_indicators(symbol):
    try:
        coin_id = symbol.lower()
        url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart"
        params = {"vs_currency": "usd", "days": "30", "interval": "daily"}
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        prices = [p[1] for p in data.get("prices", [])]
        if len(prices) < 20:
            return None
        
        # === RSI ===
        delta = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [d if d > 0 else 0 for d in delta]
        losses = [-d if d < 0 else 0 for d in delta]
        avg_gain = sum(gains[-14:]) / 14 if len(gains) >= 14 else 0
        avg_loss = sum(losses[-14:]) / 14 if len(losses) >= 14 else 0
        if avg_loss == 0:
            rsi = 100
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
        
        # === MACD ===
        def ema(data, period):
            if len(data) < period:
                return data[-1]
            multiplier = 2 / (period + 1)
            ema_val = data[0]
            for price in data[1:]:
                ema_val = (price * multiplier) + (ema_val * (1 - multiplier))
            return ema_val
        
        macd_line = ema(prices, 12) - ema(prices, 26)
        signal_line = macd_line * 0.9
        macd_hist = macd_line - signal_line
        
        return {
            "rsi": float(rsi),
            "macd_hist": float(macd_hist),
        }
    except Exception as e:
        return None

# =========================================================
# PUBLIC API INDODAX
# =========================================================
@st.cache_data(ttl=30)
def get_all_tickers():
    url = "https://indodax.com/api/summaries"
    try:
        r = requests.get(url, timeout=10)
        data = r.json()
        return data.get("tickers", {})
    except:
        return {}

# =========================================================
# PROSES DATA – TANPA EMA
# =========================================================
def process_scanner_data(tickers, min_volume=0, prev_data=None):
    rows = []
    for pair, info in tickers.items():
        if not pair.endswith("_idr"):
            continue
        try:
            last = float(info.get("last", 0))
            high = float(info.get("high", 0))
            low = float(info.get("low", 0))
            vol_idr = float(info.get("vol_idr", 0))
            buy = float(info.get("buy", 0))
            sell = float(info.get("sell", 0))
            
            if last <= 0 or vol_idr < min_volume or high <= 0 or low <= 0:
                continue
            
            symbol = pair.replace("_idr", "").upper()
            
            # Ambil RSI & MACD dari CoinGecko
            indicators = get_coingecko_indicators(symbol)
            if indicators:
                rsi = indicators["rsi"]
                macd_hist = indicators["macd_hist"]
            else:
                # Fallback
                rsi = 50 + ((last - low) / (high - low) * 20 - 10)
                macd_hist = 0
            
            # POSISI HARGA (0-100%)
            position = ((last - low) / (high - low)) * 100 if high > low else 50
            
            # RSI STATUS
            if rsi > 70:
                rsi_status = "🔴 Overbought"
            elif rsi < 30:
                rsi_status = "🟢 Oversold"
            else:
                rsi_status = "🟡 Neutral"
            
            # === TREND BERDASARKAN POSISI ===
            if position > 70:
                trend = "🟢 BULLISH"
            elif position < 30:
                trend = "🔴 BEARISH"
            else:
                trend = "🟡 SIDEWAYS"
            
            # === MACD STATUS ===
            macd_status = "🟢 Bullish" if macd_hist > 0 else "🔴 Bearish" if macd_hist < 0 else "🟡 Neutral"
            
            # === SKOR ===
            score = 0
            reasons = []
            
            # 1. Posisi harga (bobot 25)
            if position > 70:
                score += 25
                reasons.append(f"Posisi {position:.0f}%")
            elif position < 30:
                score -= 25
                reasons.append(f"Posisi {position:.0f}%")
            
            # 2. RSI (bobot 25)
            if rsi < 30:
                score += 25
                reasons.append("RSI Oversold")
            elif rsi > 70:
                score -= 25
                reasons.append("RSI Overbought")
            elif rsi < 50:
                score += 10
                reasons.append("RSI < 50")
            
            # 3. Volume (bobot 20)
            prev = prev_data.get(pair, {})
            prev_vol = prev.get('volume', vol_idr)
            vol_ratio = vol_idr / prev_vol if prev_vol > 0 else 1
            if vol_ratio > 1.3:
                score += 15
                reasons.append("Volume naik")
            elif vol_ratio < 0.7:
                score -= 15
                reasons.append("Volume turun")
            
            # 4. MACD (bobot 10)
            if macd_hist > 0:
                score += 10
                reasons.append("MACD Bullish")
            elif macd_hist < 0:
                score -= 10
                reasons.append("MACD Bearish")
            
            # === SIGNAL ===
            if score >= 50:
                signal = "🟢 STRONG BUY"
                signal_class = "signal-strong-buy"
            elif score >= 25:
                signal = "🟢 BUY"
                signal_class = "signal-buy"
            elif score <= -50:
                signal = "🔴 STRONG SELL"
                signal_class = "signal-strong-sell"
            elif score <= -25:
                signal = "🔴 SELL"
                signal_class = "signal-sell"
            else:
                signal = "🟡 HOLD"
                signal_class = "signal-hold"
            
            # === PANAH ===
            prev_last = prev.get('last', last)
            price_arrow = "⬆️" if last > prev_last else "⬇️" if last < prev_last else "➡️"
            vol_arrow = "⬆️" if vol_idr > prev_vol * 1.02 else "⬇️" if vol_idr < prev_vol * 0.98 else "➡️"
            
            rows.append({
                "Pair": pair.upper(),
                "Base": pair.split("_")[0].upper(),
                "Last": last,
                "Volume": vol_idr,
                "Position %": round(position, 1),
                "RSI": round(rsi, 1),
                "RSI Status": rsi_status,
                "Trend": trend,
                "MACD": macd_status,
                "Score": score,
                "Signal": signal,
                "Signal Class": signal_class,
                "Price": price_arrow,
                "Volume Arrow": vol_arrow,
                "Reasons": ", ".join(reasons[:3]) + ("..." if len(reasons) > 3 else ""),
                "Buy": buy,
                "Sell": sell
            })
        except Exception as e:
            continue
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("Score", ascending=False)
    return df

# =========================================================
# SIDEBAR
# =========================================================
with st.sidebar:
    st.header("⚙️ Settings")
    min_volume = st.number_input("Min Volume (IDR)", min_value=0, value=1000000, step=1000000)
    refresh_interval = st.slider("Refresh (detik)", 10, 120, 30)
    
    st.divider()
    st.subheader("🔑 Private API")
    st.session_state.api_key = st.text_input("API Key", value=st.session_state.api_key, type="password")
    st.session_state.api_secret = st.text_input("Secret Key", value=st.session_state.api_secret, type="password")
    
    st.caption("⚠️ Hanya izin `view` untuk keamanan.")
    
    if st.button("🔄 Refresh Now", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    
    st.divider()
    st.caption("📊 **Indikator:**")
    st.caption("• Posisi Harga (High/Low)")
    st.caption("• RSI (CoinGecko)")
    st.caption("• Volume vs Rata-rata")
    st.caption("• MACD (CoinGecko)")

# =========================================================
# MAIN
# =========================================================
st.title("🇮🇩 Indodax + CoinGecko (Fixed)")
st.caption(f"🕐 Update: {st.session_state.last_update.strftime('%Y-%m-%d %H:%M:%S')}")

tickers = get_all_tickers()
if not tickers:
    st.warning("⚠️ Gagal mengambil data dari Indodax.")
    st.stop()

df = process_scanner_data(tickers, min_volume, st.session_state.prev_data)

# Update prev_data
new_prev = {}
for _, row in df.iterrows():
    pair = row["Pair"].lower()
    new_prev[pair] = {"last": row["Last"], "volume": row["Volume"]}
st.session_state.prev_data = new_prev
st.session_state.last_update = datetime.now()

if not df.empty:
    # METRICS
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("📊 Total", len(df))
    c2.metric("📈 Avg Score", f"{df['Score'].mean():.1f}")
    c3.metric("🟢 Strong Buy", len(df[df["Signal"] == "🟢 STRONG BUY"]))
    c4.metric("🟢 Buy", len(df[df["Signal"] == "🟢 BUY"]))
    c5.metric("🔴 Sell", len(df[df["Signal"].str.contains("SELL")]))
    
    # TABEL
    st.subheader("📊 Market Scanner")
    display_df = df.copy()
    display_df["Last"] = display_df["Last"].apply(lambda x: f"{x:,.0f}")
    display_df["Volume"] = display_df["Volume"].apply(lambda x: f"{x:,.0f}")
    display_df["Buy"] = display_df["Buy"].apply(lambda x: f"{x:,.0f}")
    display_df["Sell"] = display_df["Sell"].apply(lambda x: f"{x:,.0f}")
    display_df["Position %"] = display_df["Position %"].apply(lambda x: f"{x:.1f}%")
    display_df["RSI"] = display_df["RSI"].apply(lambda x: f"{x:.1f}")
    display_df["Score"] = display_df["Score"].apply(lambda x: f"{x:.0f}")
    
    cols_to_show = [
        "Pair", "Base", "Last", "Volume", "Position %", 
        "RSI", "RSI Status", "Trend", "MACD", "Score", 
        "Signal", "Price", "Volume Arrow", "Reasons"
    ]
    st.dataframe(display_df[cols_to_show], use_container_width=True, hide_index=True)
    
    # TOP SIGNAL
    st.subheader("🔥 Top Signal")
    top_signals = df[df["Signal"].isin(["🟢 STRONG BUY", "🟢 BUY", "🔴 STRONG SELL", "🔴 SELL"])].head(10)
    if not top_signals.empty:
        for _, row in top_signals.iterrows():
            st.markdown(f"""
            <div style="background: #111827; border:1px solid #1e293b; border-radius:12px; padding:12px; margin:4px 0;">
                <b>{row['Pair']}</b>
                <span style="float:right; font-size:16px;">
                    <span class="{row['Signal Class']}">{row['Signal']}</span>
                </span>
                <br>
                <span style="color:#94a3b8; font-size:13px;">
                    Score: {row['Score']} | RSI: {row['RSI']:.1f} | Position: {row['Position %']:.1f}% | {row['Trend']}
                </span>
                <br>
                <span style="color:#94a3b8; font-size:11px;">
                    📊 {row['Reasons']}
                </span>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.info("Tidak ada sinyal kuat saat ini")
    
    # SUPPORT & RESISTANCE
    st.subheader("📊 Support & Resistance")
    sr_rows = []
    for pair in df["Pair"].str.lower().tolist():
        sr = get_support_resistance(pair)
        sr_rows.append({
            "Pair": pair.upper(),
            "Last": f"{sr['last']:,.0f}",
            "S1": f"{sr['s1']:,.0f}",
            "S2": f"{sr['s2']:,.0f}",
            "R1": f"{sr['r1']:,.0f}",
            "R2": f"{sr['r2']:,.0f}"
        })
    st.dataframe(pd.DataFrame(sr_rows), use_container_width=True, hide_index=True)

# =========================================================
# SALDO & PORTOFOLIO
# =========================================================
st.divider()
st.subheader("💵 Saldo & Portofolio")

if st.session_state.api_key and st.session_state.api_secret:
    info = indodax_private("getInfo")
    if "return" in info and "balance" in info["return"]:
        balance = info["return"]["balance"]
        nonzero = {k: float(v) for k, v in balance.items() if float(v) > 0}
        
        port_rows = []
        total_porto = 0
        
        for coin, amount in nonzero.items():
            pair = f"{coin}_idr"
            sr = get_support_resistance(pair)
            last_price = sr["last"]
            avg_buy = get_avg_buy_price(pair)
            buy_price = avg_buy if avg_buy else last_price
            nilai = amount * last_price if last_price > 0 else 0
            pl = ((last_price - buy_price) / buy_price) * 100 if buy_price > 0 else 0
            
            port_rows.append({
                "Coin": coin.upper(),
                "Amount": f"{amount:.8f}",
                "Last Price": f"{last_price:,.0f}",
                "Value (IDR)": f"{nilai:,.0f}",
                "Avg Buy": f"{buy_price:,.0f}",
                "P/L %": f"{pl:.2f}%"
            })
            total_porto += nilai
        
        if port_rows:
            st.metric("💼 Total Portofolio", f"Rp {total_porto:,.0f}")
            st.dataframe(pd.DataFrame(port_rows), use_container_width=True, hide_index=True)
        else:
            st.info("Tidak ada aset dengan saldo > 0.")
    else:
        st.error("Gagal mengambil saldo.")
else:
    st.info("🔑 Masukkan API Key dan Secret di sidebar.")

# =========================================================
# AUTO REFRESH
# =========================================================
try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=refresh_interval * 1000, key="refresh")
except:
    pass

# =========================================================
# FOOTER
# =========================================================
st.divider()
st.caption(
    f"🔄 Refresh {refresh_interval}s | "
    f"Total: {len(df) if not df.empty else 0} | "
    f"Indodax + CoinGecko | "
    f"API: {'✅' if st.session_state.api_key else '❌'}"
)
