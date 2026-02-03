import streamlit as st
import pandas as pd
import numpy as np
import json
from datetime import datetime, timedelta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from yahooquery import Ticker
import warnings
warnings.filterwarnings('ignore')

# Page configuration
st.set_page_config(
    page_title="RayBot Signal Backtester",
    page_icon="📈",
    layout="wide"
)

# Title and description
st.title("📈 RayBot Trading Signal Backtester")
st.markdown("""
This tool backtests the RayBot Gold/XAUUSD trading signals using historical data from Yahoo Finance.
Upload your JSON signal file or use the sample data to analyze performance.
**All times are assumed to be GMT+3 (Middle East Time).**
""")

# Initialize session state
if 'signals_df' not in st.session_state:
    st.session_state.signals_df = None
if 'dates_parsed' not in st.session_state:
    st.session_state.dates_parsed = False
if 'backtest_results' not in st.session_state:
    st.session_state.backtest_results = None
if 'price_data' not in st.session_state:
    st.session_state.price_data = None

# Function to parse date strings with GMT+3 timezone
def parse_signal_date(date_str, time_str=None, year=None):
    """Parse date string with GMT+3 timezone assumption"""
    try:
        if year is None:
            year = datetime.now().year
        
        # Clean the date string
        date_str_clean = date_str.strip()
        
        # Try different date formats
        date_formats = [
            '%B %d',  # January 19
            '%b %d',   # Jan 19
            '%d %B',   # 19 January
            '%d %b'    # 19 Jan
        ]
        
        date_part = None
        
        # Parse date part
        for fmt in date_formats:
            try:
                date_part = datetime.strptime(date_str_clean, fmt)
                date_part = date_part.replace(year=year)
                break
            except ValueError:
                continue
        
        if date_part is None:
            # Try with year in string
            for fmt in ['%B %d %Y', '%b %d %Y', '%d %B %Y', '%d %b %Y']:
                try:
                    date_part = datetime.strptime(date_str_clean, fmt)
                    break
                except ValueError:
                    continue
        
        if date_part is None:
            # Last resort: extract month and day
            import re
            month_names = {
                'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5, 'june': 6,
                'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12,
                'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
                'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
            }
            
            date_str_lower = date_str_clean.lower()
            for month_name, month_num in month_names.items():
                if month_name in date_str_lower:
                    day_match = re.search(r'(\d{1,2})', date_str_lower)
                    if day_match:
                        day = int(day_match.group(1))
                        date_part = datetime(year, month_num, day)
                        break
        
        if date_part is None:
            return None, f"Could not parse date: {date_str}"
        
        # Parse time part
        if time_str and isinstance(time_str, str) and time_str.strip():
            time_str_clean = time_str.strip().upper()
            
            # Handle PM/AM format
            if 'PM' in time_str_clean or 'AM' in time_str_clean:
                try:
                    time_str_clean = time_str_clean.replace(' ', '')
                    time_part = datetime.strptime(time_str_clean, '%I:%M%p').time()
                except:
                    try:
                        time_part = datetime.strptime(time_str_clean, '%I%p').time()
                    except:
                        return None, f"Could not parse time: {time_str}"
            else:
                # 24-hour format
                try:
                    time_part = datetime.strptime(time_str_clean, '%H:%M').time()
                except:
                    try:
                        time_part = datetime.strptime(time_str_clean, '%H').time()
                    except:
                        return None, f"Could not parse time: {time_str}"
            
            parsed_date = datetime.combine(date_part.date(), time_part)
        else:
            # Default to 11:59 PM if no time specified
            parsed_date = datetime.combine(date_part.date(), datetime.strptime('23:59', '%H:%M').time())
        
        # Convert from GMT+3 to UTC (subtract 3 hours)
        # Note: For backtesting, we'll use the GMT+3 time as-is for matching with data
        # parsed_date = parsed_date - timedelta(hours=3)
        
        return parsed_date, None
    except Exception as e:
        return None, f"Error parsing date: {date_str} {time_str} - {str(e)}"

# Function to fetch price data
def fetch_price_data(symbol, start_date, end_date):
    """Fetch historical price data using yahooquery"""
    try:
        ticker = Ticker(symbol)
        hist = ticker.history(start=start_date, end=end_date, interval='1d')
        
        if hist is None or (isinstance(hist, pd.DataFrame) and hist.empty):
            return None, "No data returned from Yahoo Finance"
        
        # Reset index to get date as column
        if isinstance(hist.index, pd.MultiIndex):
            hist = hist.reset_index()
        else:
            hist = hist.reset_index()
        
        # Ensure we have required columns
        required_cols = ['open', 'high', 'low', 'close']
        available_cols = [col.lower() for col in hist.columns]
        
        # Standardize column names
        hist.columns = [col.lower() if isinstance(col, str) else col for col in hist.columns]
        
        missing_cols = [col for col in required_cols if col not in hist.columns]
        if missing_cols:
            return None, f"Missing required columns: {missing_cols}"
        
        # Handle date column
        if 'date' in hist.columns:
            hist['date'] = pd.to_datetime(hist['date'])
        else:
            return None, "No date column found in data"
        
        # Sort by date
        hist = hist.sort_values('date').reset_index(drop=True)
        
        return hist, None
    except Exception as e:
        return None, f"Error fetching price data: {str(e)}"

# Function to backtest signals
def backtest_signals(signals_df, price_data, max_days_held=30):
    """Backtest trading signals against price data"""
    results = []
    
    for idx, signal in signals_df.iterrows():
        signal_date = signal['parsed_date']
        
        if pd.isna(signal_date):
            continue
        
        # Find price data starting from signal date
        future_prices = price_data[price_data['date'] >= signal_date].copy()
        
        if future_prices.empty or len(future_prices) <= 1:
            continue
        
        # Get signal parameters
        entry_price = float(signal['entry'])
        stop_loss = float(signal['stop_loss'])
        take_profit = float(signal['take_profit'])
        direction = str(signal['direction']).upper()
        size_lots = float(signal.get('size_lots', 1.0))
        
        exit_triggered = False
        min_low = float('inf')
        max_high = float('-inf')
        
        # For BUY signals
        if direction == 'BUY':
            for price_idx, price_row in future_prices.iterrows():
                current_low = float(price_row['low'])
                current_high = float(price_row['high'])
                current_close = float(price_row['close'])
                current_date = price_row['date']
                
                min_low = min(min_low, current_low)
                max_high = max(max_high, current_high)
                
                days_held = (current_date - signal_date).days
                
                # Check for stop loss hit (check this first as it's the lower price)
                if current_low <= stop_loss:
                    result = {
                        'signal_index': idx,
                        'signal_date': signal_date,
                        'exit_date': current_date,
                        'entry_price': entry_price,
                        'exit_price': stop_loss,
                        'stop_loss': stop_loss,
                        'take_profit': take_profit,
                        'direction': direction,
                        'size_lots': size_lots,
                        'result': 'STOP_LOSS',
                        'pnl_percent': ((stop_loss - entry_price) / entry_price) * 100,
                        'pnl_abs': (stop_loss - entry_price) * size_lots,
                        'days_held': days_held,
                        'exit_reason': 'Stop Loss Hit',
                        'max_adverse_excursion': ((min_low - entry_price) / entry_price) * 100,
                        'max_favorable_excursion': ((max_high - entry_price) / entry_price) * 100
                    }
                    results.append(result)
                    exit_triggered = True
                    break
                
                # Check for take profit hit
                elif current_high >= take_profit:
                    result = {
                        'signal_index': idx,
                        'signal_date': signal_date,
                        'exit_date': current_date,
                        'entry_price': entry_price,
                        'exit_price': take_profit,
                        'stop_loss': stop_loss,
                        'take_profit': take_profit,
                        'direction': direction,
                        'size_lots': size_lots,
                        'result': 'TAKE_PROFIT',
                        'pnl_percent': ((take_profit - entry_price) / entry_price) * 100,
                        'pnl_abs': (take_profit - entry_price) * size_lots,
                        'days_held': days_held,
                        'exit_reason': 'Take Profit Hit',
                        'max_adverse_excursion': ((min_low - entry_price) / entry_price) * 100,
                        'max_favorable_excursion': ((max_high - entry_price) / entry_price) * 100
                    }
                    results.append(result)
                    exit_triggered = True
                    break
                
                # Check for max days held
                elif days_held >= max_days_held:
                    exit_price = current_close
                    result = {
                        'signal_index': idx,
                        'signal_date': signal_date,
                        'exit_date': current_date,
                        'entry_price': entry_price,
                        'exit_price': exit_price,
                        'stop_loss': stop_loss,
                        'take_profit': take_profit,
                        'direction': direction,
                        'size_lots': size_lots,
                        'result': 'MAX_DAYS',
                        'pnl_percent': ((exit_price - entry_price) / entry_price) * 100,
                        'pnl_abs': (exit_price - entry_price) * size_lots,
                        'days_held': days_held,
                        'exit_reason': f'Max Days Held ({max_days_held})',
                        'max_adverse_excursion': ((min_low - entry_price) / entry_price) * 100,
                        'max_favorable_excursion': ((max_high - entry_price) / entry_price) * 100
                    }
                    results.append(result)
                    exit_triggered = True
                    break
        
        # If no exit triggered, mark as incomplete
        if not exit_triggered and not future_prices.empty:
            last_price_row = future_prices.iloc[-1]
            last_close = float(last_price_row['close'])
            days_held = (last_price_row['date'] - signal_date).days
            
            final_min_low = float(future_prices['low'].min())
            final_max_high = float(future_prices['high'].max())
            
            result = {
                'signal_index': idx,
                'signal_date': signal_date,
                'exit_date': last_price_row['date'],
                'entry_price': entry_price,
                'exit_price': last_close,
                'stop_loss': stop_loss,
                'take_profit': take_profit,
                'direction': direction,
                'size_lots': size_lots,
                'result': 'INCOMPLETE',
                'pnl_percent': ((last_close - entry_price) / entry_price) * 100,
                'pnl_abs': (last_close - entry_price) * size_lots,
                'days_held': days_held,
                'exit_reason': 'End of Data',
                'max_adverse_excursion': ((final_min_low - entry_price) / entry_price) * 100,
                'max_favorable_excursion': ((final_max_high - entry_price) / entry_price) * 100
            }
            results.append(result)
    
    return pd.DataFrame(results)

# ========================================
# SIDEBAR - FILE UPLOAD
# ========================================
st.sidebar.header("📁 Data Upload")

uploaded_file = st.sidebar.file_uploader("Upload JSON signals file", type=['json'])

sample_data = {
    "signals": [
        {
            "date": "January 19",
            "time": "8:39 PM",
            "direction": "BUY",
            "level": "L2",
            "entry": 2676.3,
            "stop_loss": 2582.77,
            "take_profit": 2933.5,
            "size_lots": 2.45,
            "risk_percent": 2.3
        },
        {
            "date": "January 20",
            "time": "3:44 PM",
            "direction": "BUY",
            "level": "L3",
            "entry": 2732.6,
            "stop_loss": 2673.44,
            "take_profit": 2969.23,
            "size_lots": 3.72,
            "risk_percent": 2.21
        },
        {
            "date": "January 25",
            "time": "",
            "direction": "BUY",
            "level": "L1",
            "entry": 2780.5,
            "stop_loss": 2710.0,
            "take_profit": 3000.0,
            "size_lots": 1.0,
            "risk_percent": 2.0
        }
    ]
}

if uploaded_file is not None:
    try:
        signals_data = json.load(uploaded_file)
        signals_list = signals_data.get('signals', [])
        
        if signals_list:
            signals_df = pd.DataFrame(signals_list)
            st.session_state.signals_df = signals_df
            st.session_state.dates_parsed = False
            st.session_state.backtest_results = None
            st.sidebar.success(f"✅ Loaded {len(signals_list)} signals")
        else:
            st.sidebar.error("No signals found in the JSON file")
    except Exception as e:
        st.sidebar.error(f"Error loading file: {str(e)}")

if st.sidebar.button("📋 Load Sample Data"):
    signals_df = pd.DataFrame(sample_data['signals'])
    st.session_state.signals_df = signals_df
    st.session_state.dates_parsed = False
    st.session_state.backtest_results = None
    st.sidebar.success(f"✅ Loaded {len(signals_df)} sample signals")
    st.rerun()

# Reset button
st.sidebar.markdown("---")
if st.sidebar.button("🔄 Reset All"):
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()

# ========================================
# MAIN CONTENT
# ========================================

# STEP 1: Display uploaded signals
if st.session_state.signals_df is not None:
    signals_df = st.session_state.signals_df
    
    st.header("📋 Step 1: Review Your Signals")
    st.dataframe(
        signals_df[['date', 'time', 'direction', 'entry', 'stop_loss', 'take_profit', 'size_lots']],
        use_container_width=True
    )
    
    # Check for missing times
    missing_times = signals_df[signals_df['time'].isna() | (signals_df['time'] == '')]
    if not missing_times.empty:
        st.warning(f"⚠️ {len(missing_times)} signals have missing times. Default time 11:59 PM GMT+3 will be used.")
    
    st.markdown("---")
    
    # STEP 2: Parse Dates
    st.header("📅 Step 2: Parse Dates")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        year_option = st.radio(
            "Select year for signals:",
            ["Use Current Year (2026)", "Specify Custom Year"],
            horizontal=True
        )
        
        if year_option == "Specify Custom Year":
            signal_year = st.number_input(
                "Enter year:",
                min_value=2000,
                max_value=datetime.now().year,
                value=2025
            )
        else:
            signal_year = datetime.now().year
    
    with col2:
        st.markdown("### ")
        st.markdown("### ")
        if st.button("🔍 Parse All Dates", type="primary", use_container_width=True):
            with st.spinner("Parsing dates with GMT+3 timezone..."):
                parsed_dates = []
                errors = []
                
                for idx, row in signals_df.iterrows():
                    time_val = row.get('time', '')
                    if pd.isna(time_val) or time_val == '':
                        time_val = "11:59 PM"
                    
                    parsed_date, error = parse_signal_date(row['date'], time_val, signal_year)
                    
                    if error:
                        errors.append(f"Signal {idx + 1}: {error}")
                    
                    parsed_dates.append(parsed_date)
                
                signals_df['parsed_date'] = parsed_dates
                st.session_state.signals_df = signals_df
                
                if errors:
                    st.error("❌ Some dates could not be parsed:")
                    for error in errors:
                        st.text(error)
                    st.session_state.dates_parsed = False
                else:
                    st.session_state.dates_parsed = True
                    st.success("✅ All dates parsed successfully!")
                    st.rerun()
    
    # Show parsed dates if available
    if st.session_state.dates_parsed and 'parsed_date' in signals_df.columns:
        st.subheader("✅ Parsed Dates (GMT+3)")
        
        display_df = signals_df.copy()
        display_df['Parsed DateTime (GMT+3)'] = display_df['parsed_date'].dt.strftime('%Y-%m-%d %I:%M %p')
        
        st.dataframe(
            display_df[['date', 'time', 'Parsed DateTime (GMT+3)', 'entry', 'direction']],
            use_container_width=True
        )
        
        st.markdown("---")
        
        # STEP 3: Configure Backtest
        st.header("⚙️ Step 3: Configure Backtest")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            symbol = st.selectbox(
                "Ticker Symbol",
                ["GC=F", "XAUUSD=X", "GLD"],
                help="GC=F: Gold Futures, XAUUSD=X: Gold Spot, GLD: Gold ETF"
            )
        
        with col2:
            end_date = st.date_input(
                "End Date",
                datetime.now().date(),
                help="End date for backtesting period"
            )
        
        with col3:
            max_days_held = st.number_input(
                "Max Days Held",
                min_value=1,
                max_value=365,
                value=30,
                help="Maximum days to hold a position"
            )
        
        # Calculate start date
        min_signal_date = signals_df['parsed_date'].min()
        start_date = (min_signal_date - timedelta(days=5)).date()
        
        st.info(f"📊 Data will be fetched from {start_date} to {end_date}")
        
        st.markdown("---")
        
        # STEP 4: Run Backtest
        st.header("🚀 Step 4: Run Backtest")
        
        col1, col2, col3 = st.columns([1, 1, 1])
        
        with col2:
            if st.button("▶️ **RUN BACKTEST**", type="primary", use_container_width=True):
                # Fetch price data
                with st.spinner(f"Fetching {symbol} data from Yahoo Finance..."):
                    price_data, error = fetch_price_data(
                        symbol,
                        start_date.strftime('%Y-%m-%d'),
                        end_date.strftime('%Y-%m-%d')
                    )
                    
                    if error:
                        st.error(f"❌ {error}")
                        st.stop()
                    
                    st.session_state.price_data = price_data
                    st.success(f"✅ Fetched {len(price_data)} days of price data")
                
                # Run backtest
                with st.spinner("Running backtest analysis..."):
                    results_df = backtest_signals(signals_df, price_data, max_days_held)
                    st.session_state.backtest_results = results_df
                    st.success(f"✅ Analyzed {len(results_df)} signals")
                    st.rerun()
    
    # STEP 5: Display Results
    if st.session_state.backtest_results is not None and not st.session_state.backtest_results.empty:
        st.markdown("---")
        st.header("📊 Step 5: Backtest Results")
        
        results_df = st.session_state.backtest_results
        
        # Performance metrics
        total_trades = len(results_df)
        winning_trades = len(results_df[results_df['result'] == 'TAKE_PROFIT'])
        losing_trades = len(results_df[results_df['result'] == 'STOP_LOSS'])
        
        closed_trades = results_df[results_df['result'].isin(['TAKE_PROFIT', 'STOP_LOSS'])]
        win_rate = (winning_trades / len(closed_trades) * 100) if len(closed_trades) > 0 else 0
        
        total_pnl = results_df['pnl_abs'].sum()
        avg_pnl = results_df['pnl_abs'].mean()
        avg_days = closed_trades['days_held'].mean() if not closed_trades.empty else 0
        
        # Display metrics
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total Trades", total_trades)
        with col2:
            st.metric("Win Rate", f"{win_rate:.1f}%")
        with col3:
            st.metric("Total P&L", f"${total_pnl:,.2f}", delta=f"Avg: ${avg_pnl:.2f}")
        with col4:
            st.metric("Avg Days Held", f"{avg_days:.1f}")
        
        # Breakdown
        st.subheader("Trade Breakdown")
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("🎯 Take Profit", winning_trades, delta_color="normal")
        with col2:
            st.metric("🛑 Stop Loss", losing_trades, delta_color="inverse")
        with col3:
            max_days_count = len(results_df[results_df['result'] == 'MAX_DAYS'])
            st.metric("⏱️ Max Days", max_days_count)
        with col4:
            incomplete_count = len(results_df[results_df['result'] == 'INCOMPLETE'])
            st.metric("📍 Incomplete", incomplete_count)
        
        # Detailed results table
        st.subheader("Detailed Results")
        
        display_results = results_df.copy()
        display_results['signal_date'] = display_results['signal_date'].dt.strftime('%Y-%m-%d %H:%M')
        display_results['exit_date'] = display_results['exit_date'].dt.strftime('%Y-%m-%d %H:%M')
        display_results['pnl_percent'] = display_results['pnl_percent'].round(2)
        display_results['pnl_abs'] = display_results['pnl_abs'].round(2)
        
        st.dataframe(
            display_results[[
                'signal_index', 'signal_date', 'exit_date', 'entry_price', 'exit_price',
                'result', 'pnl_percent', 'pnl_abs', 'days_held', 'exit_reason'
            ]],
            use_container_width=True,
            height=400
        )
        
        # Visualizations
        st.subheader("📈 Performance Visualizations")
        
        tab1, tab2, tab3 = st.tabs(["P&L Distribution", "Cumulative P&L", "Days Held"])
        
        with tab1:
            fig1 = go.Figure()
            
            colors = results_df['result'].map({
                'TAKE_PROFIT': 'green',
                'STOP_LOSS': 'red',
                'MAX_DAYS': 'orange',
                'INCOMPLETE': 'gray'
            })
            
            fig1.add_trace(go.Bar(
                x=results_df.index,
                y=results_df['pnl_abs'],
                marker_color=colors,
                text=results_df['pnl_abs'].round(0),
                textposition='outside',
                hovertemplate='<b>Trade %{x}</b><br>P&L: $%{y:.2f}<extra></extra>'
            ))
            
            fig1.update_layout(
                title='P&L per Trade',
                xaxis_title='Trade Index',
                yaxis_title='P&L ($)',
                height=400,
                showlegend=False
            )
            
            st.plotly_chart(fig1, use_container_width=True)
        
        with tab2:
            fig2 = go.Figure()
            
            cumulative_pnl = results_df['pnl_abs'].cumsum()
            
            fig2.add_trace(go.Scatter(
                x=results_df.index,
                y=cumulative_pnl,
                mode='lines+markers',
                line=dict(color='blue', width=2),
                marker=dict(size=6),
                hovertemplate='<b>Trade %{x}</b><br>Cumulative: $%{y:.2f}<extra></extra>'
            ))
            
            fig2.add_hline(y=0, line_dash="dash", line_color="gray", annotation_text="Break Even")
            
            fig2.update_layout(
                title='Cumulative P&L Over Time',
                xaxis_title='Trade Index',
                yaxis_title='Cumulative P&L ($)',
                height=400
            )
            
            st.plotly_chart(fig2, use_container_width=True)
        
        with tab3:
            fig3 = go.Figure()
            
            fig3.add_trace(go.Bar(
                x=results_df.index,
                y=results_df['days_held'],
                marker_color='purple',
                text=results_df['days_held'],
                textposition='outside',
                hovertemplate='<b>Trade %{x}</b><br>Days: %{y}<extra></extra>'
            ))
            
            if avg_days > 0:
                fig3.add_hline(
                    y=avg_days,
                    line_dash="dash",
                    line_color="red",
                    annotation_text=f"Average: {avg_days:.1f} days"
                )
            
            fig3.update_layout(
                title='Days Held per Trade',
                xaxis_title='Trade Index',
                yaxis_title='Days',
                height=400,
                showlegend=False
            )
            
            st.plotly_chart(fig3, use_container_width=True)
        
        # Download button
        st.markdown("---")
        csv = results_df.to_csv(index=False)
        st.download_button(
            label="📥 Download Results as CSV",
            data=csv,
            file_name=f"backtest_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            use_container_width=True
        )

else:
    # Instructions
    st.info("👈 **Get Started:** Upload your JSON signals file or load sample data from the sidebar.")
    
    st.markdown("### 📖 How to Use")
    st.markdown("""
    1. **Upload Data**: Upload your JSON file with trading signals or use sample data
    2. **Parse Dates**: Convert signal dates to GMT+3 timezone
    3. **Configure**: Set ticker symbol, date range, and parameters
    4. **Run Backtest**: Fetch price data and analyze performance
    5. **Analyze Results**: Review metrics, charts, and download detailed results
    """)
    
    st.markdown("### 📋 JSON Format Example")
    st.code(json.dumps(sample_data, indent=2), language='json')

# Footer
st.markdown("---")
st.markdown("""
**Important Notes:**
- All times are GMT+3 (Middle East Time)
- Missing times default to 11:59 PM GMT+3
- Positions close on: Stop Loss/Take Profit hit, Max Days, or end of data
- Results do not include slippage, commissions, or spreads
- Past performance does not guarantee future results
""")

# Custom CSS
st.markdown("""
<style>
    div[data-testid="stMetric"] {
        background-color: #f0f2f6;
        padding: 15px;
        border-radius: 10px;
        border: 1px solid #e0e0e0;
    }
    
    div[data-testid="stMetric"] label {
        font-size: 14px !important;
        font-weight: 600 !important;
    }
    
    .stButton > button {
        font-weight: 600;
    }
    
    h1 {
        padding-bottom: 10px;
    }
    
    h2 {
        padding-top: 20px;
        padding-bottom: 10px;
    }
</style>
""", unsafe_allow_html=True)
