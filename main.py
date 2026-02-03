import streamlit as st
import pandas as pd
import numpy as np
import json
from datetime import datetime, timedelta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from yahooquery import Ticker
import warnings

# Suppress unnecessary warnings
warnings.filterwarnings('ignore')

# ---------------------------------------------------------
# 1. PAGE CONFIGURATION
# ---------------------------------------------------------
st.set_page_config(
    page_title="Custom JSON Backtester",
    page_icon="📊",
    layout="wide"
)

# ---------------------------------------------------------
# 2. HELPER FUNCTIONS
# ---------------------------------------------------------

def parse_signal_date(date_str):
    """
    Parses date strings like 'January 19'. 
    Defaults to the current year if year is missing.
    """
    current_year = datetime.now().year
    formats = ["%B %d", "%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y"]
    
    date_str = str(date_str).strip()
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            # If the format didn't include a year, it defaults to 1900. 
            # We fix that to the current year.
            if dt.year == 1900:
                dt = dt.replace(year=current_year)
            return dt
        except ValueError:
            continue
    return None

def fetch_price_data(symbol, start_date, end_date):
    """Fetch and sanitize YahooQuery data."""
    try:
        start_buffer = start_date - timedelta(days=10)
        end_buffer = end_date + timedelta(days=10)
        
        t = Ticker(symbol)
        hist = t.history(start=start_buffer, end=end_buffer, interval='1d')
        
        if hist.empty or isinstance(hist, dict):
            return None, f"No data found for {symbol}."
        
        hist = hist.reset_index()
        hist.columns = [col.lower() for col in hist.columns]
        
        # Timezone stripping
        hist['date'] = pd.to_datetime(hist['date'])
        if hist['date'].dt.tz is not None:
            hist['date'] = hist['date'].dt.tz_localize(None)
            
        return hist.sort_values('date').reset_index(drop=True), None
    except Exception as e:
        return None, f"Data Error: {str(e)}"

def backtest_signals(df_prices, signals):
    """
    Backtests against specific JSON fields: 
    direction, entry, stop_loss, take_profit
    """
    results = []
    
    for sig in signals:
        try:
            # Handle the specific signal structure
            date_raw = sig.get('date')
            sig_date = parse_signal_date(date_raw)
            if not sig_date: continue
            
            direction = str(sig.get('direction', '')).upper()
            target_entry = float(sig.get('entry', 0))
            sl = float(sig.get('stop_loss', 0))
            tp = float(sig.get('take_profit', 0))

            # Find data for this date
            day_data = df_prices[df_prices['date'] >= sig_date]
            if day_data.empty: continue
            
            # Use actual market data for the exit (3 days later)
            entry_idx = day_data.index[0]
            exit_idx = min(entry_idx + 3, len(df_prices) - 1)
            actual_exit_price = df_prices.loc[exit_idx, 'close']
            
            # PnL Calculation based on direction
            if "BUY" in direction:
                pnl = (actual_exit_price - target_entry) / target_entry
            else:
                pnl = (target_entry - actual_exit_price) / target_entry
                
            results.append({
                'Date': sig_date.strftime('%Y-%m-%d'),
                'Direction': direction,
                'Signal Entry': target_entry,
                'Market Exit': round(actual_exit_price, 2),
                'PnL %': round(pnl * 100, 2),
                'SL': sl,
                'TP': tp
            })
        except Exception as e:
            continue
            
    return pd.DataFrame(results)

# ---------------------------------------------------------
# 3. UI LAYOUT
# ---------------------------------------------------------

st.title("🏹 Advanced Signal Backtester")

with st.sidebar:
    st.header("Settings")
    ticker = st.text_input("Ticker (YahooQuery)", value="GC=F")
    
    st.header("JSON Signal Tree")
    # Using your provided structure as default
    default_json = {
        "signals": [
            {"date": "January 19", "direction": "BUY", "entry": 4676.3, "stop_loss": 4582.77, "take_profit": 4933.5},
            {"date": "January 20", "direction": "BUY", "entry": 4732.6, "stop_loss": 4673.44, "take_profit": 4969.23}
        ]
    }
    json_input = st.text_area("Paste Full JSON Structure:", value=json.dumps(default_json, indent=2), height=400)
    
    run_btn = st.button("Run Full Analysis", type="primary", use_container_width=True)

if run_btn:
    try:
        # 🔧 FIX: Access the 'signals' list within the dictionary
        full_data = json.loads(json_input)
        if isinstance(full_data, dict) and "signals" in full_data:
            signal_list = full_data["signals"]
        else:
            signal_list = full_data if isinstance(full_data, list) else []

        if not signal_list:
            st.error("Could not find a list of signals. Check JSON structure.")
            st.stop()

        # Extract dates for range
        parsed_dates = [parse_signal_date(s.get('date')) for s in signal_list]
        parsed_dates = [d for d in parsed_dates if d]
        
        with st.spinner("Fetching market data..."):
            df, err = fetch_price_data(ticker, min(parsed_dates), max(parsed_dates))
            
        if err:
            st.error(err)
        else:
            results_df = backtest_signals(df, signal_list)
            
            if not results_df.empty:
                # Stats
                avg_pnl = results_df['PnL %'].mean()
                st.metric("Total Cumulative PnL", f"{results_df['PnL %'].sum():.2f}%", delta=f"{avg_pnl:.2f}% Avg")
                
                # Table
                st.subheader("Trade Outcome Report")
                st.dataframe(results_df, use_container_width=True)
                
                # Chart
                st.subheader("Visual Analysis")
                fig = make_subplots(rows=1, cols=1)
                fig.add_trace(go.Candlestick(
                    x=df['date'], open=df['open'], high=df['high'], 
                    low=df['low'], close=df['close'], name="Market"
                ))
                
                # Plot Entries
                fig.add_trace(go.Scatter(
                    x=pd.to_datetime(results_df['Date']), 
                    y=results_df['Signal Entry'],
                    mode='markers', marker=dict(color='cyan', size=10, symbol='diamond'),
                    name="Signal Entry"
                ))
                
                fig.update_layout(template="plotly_dark", height=600, xaxis_rangeslider_visible=False)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.warning("No matches found between signals and market data.")

    except json.JSONDecodeError:
        st.error("Invalid JSON. Please check your brackets and commas.")
    except Exception as e:
        st.error(f"Logic Error: {e}")
