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
    page_title="Pro Signal Backtester",
    page_icon="🎯",
    layout="wide"
)

# ---------------------------------------------------------
# 2. HELPER FUNCTIONS
# ---------------------------------------------------------

def parse_signal_date(date_str):
    """Parses date strings into timezone-naive datetime objects."""
    formats = ["%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y", "%Y/%m/%d", "%d/%m/%Y"]
    for fmt in formats:
        try:
            # We ensure the result is naive (no tz) immediately
            dt = datetime.strptime(str(date_str).strip(), fmt)
            return dt
        except ValueError:
            continue
    return None

def fetch_price_data(symbol, start_date, end_date):
    """
    Fetch historical price data using yahooquery and sanitize for backtesting.
    """
    try:
        # Buffer dates to catch the first/last signal candles
        start_buffer = start_date - timedelta(days=10)
        end_buffer = end_date + timedelta(days=10)
        
        t = Ticker(symbol)
        # Fetch daily history
        hist = t.history(start=start_buffer, end=end_buffer, interval='1d')
        
        if hist.empty or isinstance(hist, dict):
            return None, f"No data found for {symbol}. Check if the ticker is correct."
        
        # 🔧 FIX 1: Handle MultiIndex
        # Yahooquery returns (symbol, date) as index. Resetting makes them columns.
        hist = hist.reset_index()
        
        # 🔧 FIX 2: Standardize Column Names
        hist.columns = [col.lower() for col in hist.columns]
        
        # 🔧 FIX 3: CRITICAL TIMEZONE STRIPPING
        # Convert to datetime and remove timezone info to prevent comparison errors
        hist['date'] = pd.to_datetime(hist['date'])
        if hist['date'].dt.tz is not None:
            hist['date'] = hist['date'].dt.tz_localize(None)
            
        # Ensure we only have the columns we need
        required = ['date', 'open', 'high', 'low', 'close', 'volume']
        hist = hist[[col for col in required if col in hist.columns]]
        
        return hist.sort_values('date').reset_index(drop=True), None
        
    except Exception as e:
        return None, f"YahooQuery Error: {str(e)}"

def backtest_signals(df_prices, signals):
    """
    Simple backtest engine: 
    Enters at 'Open' of the signal day.
    Exits at 'Close' of the day (intraday) or after 5 days if held.
    """
    results = []
    
    for sig in signals:
        try:
            sig_date = parse_signal_date(sig.get('date'))
            if not sig_date: continue
            
            action = str(sig.get('action', '')).upper()
            
            # Find the first available trading day on or after the signal date
            valid_days = df_prices[df_prices['date'] >= sig_date]
            if valid_days.empty: continue
            
            entry_row = valid_days.iloc[0]
            entry_price = entry_row['open']
            
            # Simulated Exit: 3 trading days later (or last available day)
            current_idx = valid_days.index[0]
            exit_idx = min(current_idx + 3, len(df_prices) - 1)
            exit_row = df_prices.loc[exit_idx]
            exit_price = exit_row['close']
            
            # Calc PnL
            if action in ['BUY', 'LONG']:
                pnl = (exit_price - entry_price) / entry_price
            elif action in ['SELL', 'SHORT']:
                pnl = (entry_price - exit_price) / entry_price
            else:
                continue
                
            results.append({
                'Date': entry_row['date'].strftime('%Y-%m-%d'),
                'Action': action,
                'Entry': round(entry_price, 2),
                'Exit': round(exit_price, 2),
                'PnL %': round(pnl * 100, 2)
            })
        except:
            continue
            
    return pd.DataFrame(results)

# ---------------------------------------------------------
# 3. USER INTERFACE
# ---------------------------------------------------------

st.title("📈 Multi-Asset Signal Backtester")
st.markdown("---")

# Layout: Sidebar for inputs
with st.sidebar:
    st.header("1. Configuration")
    ticker_input = st.text_input("Yahoo Finance Ticker", value="GC=F", help="Gold=GC=F, Bitcoin=BTC-USD, Apple=AAPL")
    
    st.header("2. Input Signals")
    example_json = [
        {"date": "2024-12-05", "action": "BUY"},
        {"date": "2025-01-15", "action": "SELL"},
        {"date": "2025-01-28", "action": "BUY"}
    ]
    json_data = st.text_area("Paste JSON here:", value=json.dumps(example_json, indent=2), height=300)
    
    run_btn = st.button("🚀 Run Backtest", use_container_width=True)

# Main Dashboard Logic
if run_btn:
    try:
        # Step 1: Parse JSON
        parsed_signals = json.loads(json_data)
        signal_dates = [parse_signal_date(s.get('date')) for s in parsed_signals if parse_signal_date(s.get('date'))]
        
        if not signal_dates:
            st.error("No valid dates found in your JSON.")
            st.stop()

        # Step 2: Fetch Data
        with st.spinner(f"Downloading data for {ticker_input}..."):
            df_price, error = fetch_price_data(ticker_input, min(signal_dates), max(signal_dates))
            
        if error:
            st.error(error)
        else:
            # Step 3: Run Backtest
            report_df = backtest_signals(df_price, parsed_signals)
            
            if report_df.empty:
                st.warning("Could not match signals to trading days. Check your date range.")
            else:
                # Step 4: Display Results
                total_pnl = report_df['PnL %'].sum()
                win_rate = (len(report_df[report_df['PnL %'] > 0]) / len(report_df)) * 100
                
                col1, col2, col3 = st.columns(3)
                col1.metric("Total Trades", len(report_df))
                col2.metric("Cumulative PnL", f"{total_pnl:.2f}%")
                col3.metric("Win Rate", f"{win_rate:.1f}%")
                
                st.subheader("Detailed Trade Log")
                st.dataframe(report_df, use_container_width=True)
                
                # Step 5: Visual Chart
                st.subheader("Price Action & Entries")
                fig = make_subplots(rows=1, cols=1)
                
                # Candlesticks
                fig.add_trace(go.Candlestick(
                    x=df_price['date'],
                    open=df_price['open'], high=df_price['high'],
                    low=df_price['low'], close=df_price['close'],
                    name='Price'
                ))
                
                # Add Green Arrows for Buys
                buys = report_df[report_df['Action'].isin(['BUY', 'LONG'])]
                fig.add_trace(go.Scatter(
                    x=pd.to_datetime(buys['Date']), y=buys['Entry'],
                    mode='markers', marker=dict(symbol='triangle-up', size=12, color='#00ff00'),
                    name='Buy Entry'
                ))
                
                fig.update_layout(
                    template="plotly_dark",
                    xaxis_rangeslider_visible=False,
                    height=600,
                    margin=dict(l=20, r=20, t=20, b=20)
                )
                st.plotly_chart(fig, use_container_width=True)

    except json.JSONDecodeError:
        st.error("❌ Invalid JSON format. Please check your commas and brackets.")
    except Exception as e:
        st.error(f"❌ An error occurred: {e}")

else:
    st.info("👈 Enter your signals in the sidebar and click 'Run Backtest' to see results.")
