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

# Initialize session state for data
if 'signals_data' not in st.session_state:
    st.session_state.signals_data = None
if 'backtest_results' not in st.session_state:
    st.session_state.backtest_results = None
if 'price_data' not in st.session_state:
    st.session_state.price_data = None
if 'signals_df' not in st.session_state:
    st.session_state.signals_df = None
if 'filled_times' not in st.session_state:
    st.session_state.filled_times = {}

# Function to load sample data
def load_sample_data():
    """Load the sample signals data"""
    sample_data = {
        "signals": [
            {
                "date": "January 19",
                "time": "8:39 PM",
                "direction": "BUY",
                "level": "L2",
                "entry": 4676.3,
                "stop_loss": 4582.77,
                "take_profit": 4933.5,
                "size_lots": 2.45,
                "risk_percent": 2.3
            },
            {
                "date": "January 20",
                "time": "3:44 PM",
                "direction": "BUY",
                "level": "L3",
                "entry": 4732.6,
                "stop_loss": 4673.44,
                "take_profit": 4969.23,
                "size_lots": 3.72,
                "risk_percent": 2.21
            }
        ]
    }
    return sample_data

# File uploader
st.sidebar.header("📁 Data Upload")
uploaded_file = st.sidebar.file_uploader("Upload JSON signals file", type=['json'])

if uploaded_file is not None:
    try:
        signals_data = json.load(uploaded_file)
        st.session_state.signals_data = signals_data
        st.sidebar.success(f"✅ Loaded {len(signals_data.get('signals', []))} signals")
    except Exception as e:
        st.sidebar.error(f"Error loading file: {e}")
else:
    if st.sidebar.button("Load Sample Data"):
        st.session_state.signals_data = load_sample_data()
        st.sidebar.success(f"✅ Loaded {len(st.session_state.signals_data.get('signals', []))} sample signals")

# Function to parse date strings with GMT+3 timezone
def parse_signal_date(date_str, time_str=None, year=None):
    """Parse date string with GMT+3 timezone assumption"""
    try:
        # Use provided year or current year if not specified
        if year is None:
            current_year = datetime.now().year
        else:
            current_year = year
        
        # For debugging
        # st.write(f"Parsing: date_str='{date_str}', time_str='{time_str}', year={current_year}")
        
        # Remove any emojis or special characters from date string
        date_str_clean = date_str.strip()
        
        # Try different date formats
        date_formats = [
            '%B %d',  # January 19
            '%b %d',   # Jan 19
            '%d %B',   # 19 January
            '%d %b'    # 19 Jan
        ]
        
        parsed_date = None
        date_part = None
        
        # First, parse the date part
        for fmt in date_formats:
            try:
                # Parse without year first
                date_part = datetime.strptime(date_str_clean, fmt)
                # Add the year
                date_part = date_part.replace(year=current_year)
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
            # Last resort: try to extract month and day
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
                    # Try to extract day
                    day_match = re.search(r'(\d{1,2})', date_str_lower)
                    if day_match:
                        day = int(day_match.group(1))
                        date_part = datetime(current_year, month_num, day)
                        break
        
        if date_part is None:
            return None, f"Could not parse date: {date_str}"
        
        # Now parse the time part
        if time_str and isinstance(time_str, str) and time_str.strip():
            time_str_clean = time_str.strip().upper()
            
            # Handle PM/AM format
            if 'PM' in time_str_clean or 'AM' in time_str_clean:
                try:
                    # Remove any spaces and convert to proper format
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
            
            # Combine date and time
            parsed_date = datetime.combine(date_part.date(), time_part)
        else:
            # No time specified, use end of day (23:59) as default for GMT+3
            parsed_date = datetime.combine(date_part.date(), datetime.strptime('23:59', '%H:%M').time())
        
        # Apply GMT+3 offset (add 3 hours)
        parsed_date = parsed_date + timedelta(hours=3)
        
        return parsed_date, None
    except Exception as e:
        return None, f"Error parsing date: {date_str} {time_str} - {str(e)}"

# Function to fetch price data
def fetch_price_data(symbol, start_date, end_date):
    """Fetch historical price data using yahooquery"""
    try:
        ticker = Ticker(symbol)
        
        # Fetch historical data
        hist = ticker.history(start=start_date, end=end_date)
        
        if hist.empty:
            st.error("No data returned from Yahoo Finance")
            return None
        
        # Reset index to get Date as column
        if isinstance(hist.index, pd.MultiIndex):
            hist = hist.reset_index()
        
        # Ensure we have the right columns
        required_cols = ['open', 'high', 'low', 'close', 'volume']
        available_cols = [col for col in required_cols if col in hist.columns]
        
        if not available_cols:
            st.error("No price data columns found")
            return None
        
        # Convert date to datetime if it's not already
        if 'date' in hist.columns:
            hist['date'] = pd.to_datetime(hist['date'])
        elif hist.index.name == 'date':
            hist = hist.reset_index()
            hist['date'] = pd.to_datetime(hist['date'])
        
        # Sort by date
        hist = hist.sort_values('date').reset_index(drop=True)
        
        return hist
    except Exception as e:
        st.error(f"Error fetching price data: {e}")
        return None

# Function to backtest signals
def backtest_signals(signals_df, price_data, max_days_held=30):
    """Backtest trading signals against price data"""
    results = []
    unevaluated_signals = []
    
    for idx, signal in signals_df.iterrows():
        signal_date = signal['parsed_date']
        
        if pd.isna(signal_date):
            unevaluated_signals.append({
                'signal_index': idx,
                'reason': 'Invalid date',
                'signal': signal.to_dict()
            })
            continue
        
        # Find price data starting from signal date
        future_prices = price_data[price_data['date'] >= signal_date].copy()
        
        if future_prices.empty:
            unevaluated_signals.append({
                'signal_index': idx,
                'reason': 'No price data after signal date',
                'signal_date': signal_date,
                'signal': signal.to_dict()
            })
            continue
        
        # Check if we have enough data to evaluate
        if len(future_prices) <= 1:
            unevaluated_signals.append({
                'signal_index': idx,
                'reason': 'Insufficient price data',
                'signal_date': signal_date,
                'signal': signal.to_dict()
            })
            continue
        
        # Get signal parameters
        entry_price = signal['entry']
        stop_loss = signal['stop_loss']
        take_profit = signal['take_profit']
        direction = signal['direction']
        size_lots = signal['size_lots']
        
        exit_triggered = False
        
        # For BUY signals
        if direction.upper() == 'BUY':
            # Track price movements
            max_high = float('-inf')
            min_low = float('inf')
            
            for price_idx, price_row in future_prices.iterrows():
                current_low = price_row['low']
                current_high = price_row['high']
                current_date = price_row['date']
                
                # Update min/max
                min_low = min(min_low, current_low)
                max_high = max(max_high, current_high)
                
                # Calculate days held
                days_held = (current_date - signal_date).days
                
                # Check for stop loss hit
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
                    # Use the close price on the max day
                    exit_price = price_row['close']
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
        
        # If no exit was triggered by the end of available data
        if not exit_triggered:
            last_price_row = future_prices.iloc[-1]
            last_close = last_price_row['close']
            days_held = (last_price_row['date'] - signal_date).days
            
            # Calculate final min/max
            final_min_low = future_prices['low'].min()
            final_max_high = future_prices['high'].max()
            
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
    
    return pd.DataFrame(results), unevaluated_signals

# Main content area
if st.session_state.signals_data:
    signals = st.session_state.signals_data.get('signals', [])
    
    if signals:
        # Convert to DataFrame
        signals_df = pd.DataFrame(signals)
        st.session_state.signals_df = signals_df
        
        # Check for missing times
        missing_times = signals_df[signals_df['time'].isna() | (signals_df['time'] == '')]
        
        # Display signals
        st.header("📋 Trading Signals")
        
        # Show warning for missing times
        if not missing_times.empty:
            st.warning(f"⚠️ {len(missing_times)} signals have missing time information.")
            
            st.subheader("⏰ Fill Missing Times for Specific Signals")
            st.markdown("""
            Please enter the time for each signal below (GMT+3 timezone).
            Format examples: `8:39 PM`, `14:30`, `3:44 PM`
            """)
            
            # Create a form for time input
            with st.form("time_input_form"):
                st.markdown("### Enter Times for Signals with Missing Time")
                
                # Create columns for better layout
                col1, col2, col3 = st.columns(3)
                
                time_inputs = {}
                for idx, row in missing_times.iterrows():
                    signal_info = f"**Signal {idx}** - {row['date']} - Entry: {row['entry']}"
                    
                    # Distribute across columns
                    if idx % 3 == 0:
                        with col1:
                            time_inputs[idx] = st.text_input(
                                signal_info,
                                value=st.session_state.filled_times.get(idx, ""),
                                key=f"time_{idx}",
                                placeholder="e.g., 8:39 PM"
                            )
                    elif idx % 3 == 1:
                        with col2:
                            time_inputs[idx] = st.text_input(
                                signal_info,
                                value=st.session_state.filled_times.get(idx, ""),
                                key=f"time_{idx}",
                                placeholder="e.g., 8:39 PM"
                            )
                    else:
                        with col3:
                            time_inputs[idx] = st.text_input(
                                signal_info,
                                value=st.session_state.filled_times.get(idx, ""),
                                key=f"time_{idx}",
                                placeholder="e.g., 8:39 PM"
                            )
                
                # Submit button for time inputs
                col1, col2, col3 = st.columns([1, 2, 1])
                with col2:
                    submit_times = st.form_submit_button("✅ Save All Times")
                
                if submit_times:
                    # Validate and save times
                    valid_times = True
                    for idx, time_input in time_inputs.items():
                        if not time_input:
                            st.error(f"Time for Signal {idx} is empty! Please enter a time.")
                            valid_times = False
                            break
                        
                        # Validate time format
                        try:
                            # Test if time can be parsed
                            test_time = time_input.upper()
                            if 'PM' in test_time or 'AM' in test_time:
                                # Try 12-hour format
                                test_time = test_time.replace(' ', '')
                                datetime.strptime(test_time, '%I:%M%p').time()
                            else:
                                # Try 24-hour format
                                datetime.strptime(test_time, '%H:%M').time()
                            
                            # Save to session state
                            st.session_state.filled_times[idx] = time_input
                        except ValueError:
                            st.error(f"Invalid time format for Signal {idx}: '{time_input}'. Use format like '8:39 PM' or '14:30'")
                            valid_times = False
                    
                    if valid_times:
                        st.success("✅ All times saved successfully!")
                        
                        # Update the signals DataFrame with filled times
                        for idx, time_value in st.session_state.filled_times.items():
                            if idx < len(signals_df):
                                signals_df.at[idx, 'time'] = time_value
                        
                        st.session_state.signals_df = signals_df
                        st.rerun()
            
            # Show current status
            with st.expander("📊 Current Time Filling Status"):
                st.write(f"**Total signals:** {len(signals_df)}")
                st.write(f"**Signals with time:** {len(signals_df) - len(missing_times)}")
                st.write(f"**Signals missing time:** {len(missing_times)}")
                st.write(f"**Times filled:** {len(st.session_state.filled_times)}")
                
                if st.session_state.filled_times:
                    st.write("**Filled times:**")
                    for idx, time_val in st.session_state.filled_times.items():
                        st.write(f"  - Signal {idx}: {time_val}")
        
        # Display signals table
        st.subheader("Signal Overview")
        
        display_df = signals_df.copy()
        if 'time' in display_df.columns:
            # Mark which times were filled
            display_df['time_source'] = display_df.apply(
                lambda x: "✅ Original" if pd.notna(x['time']) and x.name not in st.session_state.filled_times 
                else "✅ Filled" if x.name in st.session_state.filled_times 
                else "❌ Missing", 
                axis=1
            )
        
        st.dataframe(display_df[['date', 'time', 'time_source', 'direction', 'entry', 
                                'stop_loss', 'take_profit', 'size_lots', 'risk_percent']], 
                    use_container_width=True)
        
        # Only proceed with date parsing if all times are filled or we have original times
        if missing_times.empty or len(st.session_state.filled_times) == len(missing_times):
            st.header("📅 Date Parsing Configuration")
            
            col1, col2 = st.columns(2)
            
            with col1:
                # Let user specify the year if needed
                year_option = st.radio("Year for signals:", 
                                      ["Current Year", "Specify Year"])
                
                if year_option == "Specify Year":
                    signal_year = st.number_input("Year for all signals", 
                                                min_value=2000, 
                                                max_value=datetime.now().year, 
                                                value=datetime.now().year)
                else:
                    signal_year = datetime.now().year
            
            with col2:
                # Parse dates button
                parse_dates = st.button("🔍 Parse Dates with GMT+3")
            
            if parse_dates:
                with st.spinner("Parsing dates with GMT+3 timezone..."):
                    parsed_dates = []
                    errors = []
                    
                    for idx, row in signals_df.iterrows():
                        parsed_date, error = parse_signal_date(row['date'], row['time'], signal_year)
                        
                        if error:
                            errors.append(f"Signal {idx}: {error}")
                        
                        parsed_dates.append(parsed_date)
                    
                    signals_df['parsed_date'] = parsed_dates
                    st.session_state.signals_df = signals_df
                    
                    if errors:
                        with st.expander("❌ Date Parsing Errors"):
                            for error in errors:
                                st.error(error)
                    else:
                        st.success("✅ All dates parsed successfully!")
                        st.rerun()
        else:
            st.info("👆 Please fill all missing times above before proceeding to date parsing.")
        
        # If dates are parsed, show backtest configuration
        if 'parsed_date' in signals_df.columns and not signals_df['parsed_date'].isna().all():
            st.header("⚙️ Backtest Configuration")
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                symbol = st.selectbox(
                    "Ticker Symbol",
                    ["GC=F", "XAUUSD=X", "GLD"],
                    help="Gold futures (GC=F), Gold spot (XAUUSD=X), or GLD ETF"
                )
            
            with col2:
                end_date = st.date_input(
                    "End Date for Analysis",
                    datetime.now().date()
                )
            
            with col3:
                max_days_held = st.number_input(
                    "Max Days to Hold Position",
                    min_value=1,
                    max_value=365,
                    value=30,
                    help="Close position after this many days if no exit triggered"
                )
            
            # Calculate date range for data fetching
            start_date = signals_df['parsed_date'].min().date() - timedelta(days=30)
            
            # Fetch price data button
            if st.button("🚀 Fetch Price Data and Run Backtest"):
                with st.spinner("Fetching historical data..."):
                    # Fetch price data
                    price_data = fetch_price_data(
                        symbol, 
                        start_date.strftime('%Y-%m-%d'), 
                        end_date.strftime('%Y-%m-%d')
                    )
                    
                    if price_data is not None:
                        st.session_state.price_data = price_data
                        
                        # Run backtest
                        with st.spinner("Running backtest..."):
                            results_df, unevaluated = backtest_signals(signals_df, price_data, max_days_held)
                            st.session_state.backtest_results = results_df
                            
                            st.success(f"✅ Backtest completed! {len(results_df)} signals evaluated")
                            
                            # Display results
                            st.header("📊 Backtest Results")
                            
                            # Summary statistics
                            if not results_df.empty:
                                total_signals = len(signals_df)
                                evaluated_signals = len(results_df)
                                
                                # Count different result types
                                result_counts = results_df['result'].value_counts()
                                winning_trades = result_counts.get('TAKE_PROFIT', 0)
                                losing_trades = result_counts.get('STOP_LOSS', 0)
                                max_days_trades = result_counts.get('MAX_DAYS', 0)
                                incomplete_trades = result_counts.get('INCOMPLETE', 0)
                                
                                # Calculate win rate (only for closed trades with clear outcome)
                                closed_trades = results_df[results_df['result'].isin(['TAKE_PROFIT', 'STOP_LOSS'])]
                                if len(closed_trades) > 0:
                                    win_rate = (len(closed_trades[closed_trades['result'] == 'TAKE_PROFIT']) / len(closed_trades)) * 100
                                else:
                                    win_rate = 0
                                
                                # Calculate P&L for all trades
                                total_pnl = results_df['pnl_abs'].sum()
                                avg_pnl = results_df['pnl_abs'].mean() if len(results_df) > 0 else 0
                                
                                # Calculate average days held for closed trades
                                if not closed_trades.empty:
                                    avg_days_held = closed_trades['days_held'].mean()
                                else:
                                    avg_days_held = 0
                                
                                # Display metrics in a grid
                                st.subheader("Performance Summary")
                                
                                # Create 2 rows of metrics
                                row1_col1, row1_col2, row1_col3, row1_col4 = st.columns(4)
                                row2_col1, row2_col2, row2_col3, row2_col4 = st.columns(4)
                                
                                with row1_col1:
                                    st.metric("Total Signals", total_signals)
                                
                                with row1_col2:
                                    st.metric("Evaluated Signals", evaluated_signals)
                                
                                with row1_col3:
                                    st.metric("Winning Trades", winning_trades)
                                
                                with row1_col4:
                                    st.metric("Losing Trades", losing_trades)
                                
                                with row2_col1:
                                    st.metric("Win Rate", f"{win_rate:.1f}%")
                                
                                with row2_col2:
                                    st.metric("Total P&L", f"${total_pnl:,.2f}")
                                
                                with row2_col3:
                                    st.metric("Avg P&L per Trade", f"${avg_pnl:,.2f}")
                                
                                with row2_col4:
                                    st.metric("Avg Days Held", f"{avg_days_held:.1f}")
                                
                                # Show additional stats
                                with st.expander("📈 Detailed Statistics"):
                                    col1, col2 = st.columns(2)
                                    
                                    with col1:
                                        st.write("**Trade Outcomes:**")
                                        for result_type, count in result_counts.items():
                                            st.write(f"- {result_type}: {count}")
                                    
                                    with col2:
                                        if not results_df.empty:
                                            st.write("**Risk/Reward Stats:**")
                                            # Calculate average risk/reward
                                            results_df['risk'] = abs(results_df['entry_price'] - results_df['stop_loss'])
                                            results_df['reward'] = abs(results_df['take_profit'] - results_df['entry_price'])
                                            results_df['rr_ratio'] = results_df['reward'] / results_df['risk']
                                            
                                            avg_rr = results_df['rr_ratio'].mean()
                                            st.write(f"- Avg Risk/Reward Ratio: {avg_rr:.2f}")
                                            
                                            total_risk = results_df['risk'].sum() * results_df['size_lots'].mean()
                                            st.write(f"- Total Risk: ${total_risk:,.2f}")
                                
                                # Show unevaluated signals if any
                                if unevaluated:
                                    with st.expander(f"⚠️ {len(unevaluated)} Unevaluated Signals"):
                                        for uneval in unevaluated[:10]:  # Show first 10
                                            st.write(f"**Signal {uneval['signal_index']}**: {uneval['reason']}")
                                        if len(unevaluated) > 10:
                                            st.write(f"... and {len(unevaluated) - 10} more")
                                
                                # Results table
                                st.subheader("Detailed Results")
                                results_display = results_df[[
                                    'signal_index', 'signal_date', 'exit_date', 
                                    'entry_price', 'exit_price', 'result', 'exit_reason',
                                    'pnl_percent', 'pnl_abs', 'days_held'
                                ]].copy()
                                
                                # Format dates for display
                                results_display['signal_date'] = results_display['signal_date'].dt.strftime('%Y-%m-%d %H:%M')
                                results_display['exit_date'] = results_display['exit_date'].dt.strftime('%Y-%m-%d %H:%M')
                                
                                results_display['pnl_percent'] = results_display['pnl_percent'].round(2)
                                results_display['pnl_abs'] = results_display['pnl_abs'].round(2)
                                
                                st.dataframe(results_display, use_container_width=True)
                                
                                # Visualizations
                                st.subheader("📈 Visualization")
                                
                                # Create tabs for different charts
                                tab1, tab2, tab3, tab4, tab5 = st.tabs(["P&L Distribution", "Cumulative P&L", 
                                                                       "Trade Duration", "Win/Loss Analysis", "Risk/Reward"])
                                
                                with tab1:
                                    fig1 = go.Figure()
                                    colors = []
                                    for result in results_df['result']:
                                        if result == 'TAKE_PROFIT':
                                            colors.append('green')
                                        elif result == 'STOP_LOSS':
                                            colors.append('red')
                                        elif result == 'MAX_DAYS':
                                            colors.append('orange')
                                        else:
                                            colors.append('gray')
                                    
                                    fig1.add_trace(go.Bar(
                                        x=results_df['signal_index'],
                                        y=results_df['pnl_abs'],
                                        marker_color=colors,
                                        text=results_df['pnl_abs'].round(0),
                                        textposition='outside',
                                        name='P&L per Trade'
                                    ))
                                    
                                    fig1.update_layout(
                                        title='P&L Distribution per Trade',
                                        xaxis_title='Trade Index',
                                        yaxis_title='P&L ($)',
                                        showlegend=False,
                                        height=400
                                    )
                                    st.plotly_chart(fig1, use_container_width=True)
                                
                                with tab2:
                                    fig2 = go.Figure()
                                    cumulative_pnl = results_df['pnl_abs'].cumsum()
                                    
                                    fig2.add_trace(go.Scatter(
                                        x=results_df['signal_index'],
                                        y=cumulative_pnl,
                                        mode='lines+markers',
                                        name='Cumulative P&L',
                                        line=dict(color='blue', width=2)
                                    ))
                                    
                                    fig2.add_hline(y=0, line_dash="dash", line_color="gray")
                                    
                                    fig2.update_layout(
                                        title='Cumulative P&L',
                                        xaxis_title='Trade Index',
                                        yaxis_title='Cumulative P&L ($)',
                                        height=400
                                    )
                                    st.plotly_chart(fig2, use_container_width=True)
                                
                                with tab3:
                                    fig3 = go.Figure()
                                    
                                    fig3.add_trace(go.Bar(
                                        x=results_df['signal_index'],
                                        y=results_df['days_held'],
                                        marker_color='purple',
                                        text=results_df['days_held'],
                                        textposition='outside',
                                        name='Days Held'
                                    ))
                                    
                                    fig3.add_hline(y=avg_days_held, line_dash="dash", 
                                                 line_color="red", annotation_text=f"Avg: {avg_days_held:.1f} days")
                                    
                                    fig3.update_layout(
                                        title='Trade Duration (Days Held)',
                                        xaxis_title='Trade Index',
                                        yaxis_title='Days',
                                        showlegend=False,
                                        height=400
                                    )
                                    st.plotly_chart(fig3, use_container_width=True)
                                
                                with tab4:
                                    # Win/Loss analysis
                                    closed_results = results_df[results_df['result'].isin(['TAKE_PROFIT', 'STOP_LOSS'])]
                                    if not closed_results.empty:
                                        win_loss_counts = closed_results['result'].value_counts()
                                        
                                        fig4 = go.Figure(data=[go.Pie(
                                            labels=win_loss_counts.index,
                                            values=win_loss_counts.values,
                                            hole=.3,
                                            marker_colors=['green', 'red']
                                        )])
                                        
                                        fig4.update_layout(
                                            title='Closed Trade Outcomes',
                                            height=400
                                        )
                                        st.plotly_chart(fig4, use_container_width=True)
                                    else:
                                        st.info("No closed trades to analyze")
                                
                                with tab5:
                                    if 'rr_ratio' in results_df.columns:
                                        fig5 = go.Figure()
                                        
                                        fig5.add_trace(go.Scatter(
                                            x=results_df['signal_index'],
                                            y=results_df['rr_ratio'],
                                            mode='markers',
                                            marker=dict(
                                                size=10,
                                                color=results_df['pnl_abs'],
                                                colorscale='RdYlGn',
                                                showscale=True,
                                                colorbar=dict(title="P&L ($)")
                                            ),
                                            text=[f"Signal {i}" for i in results_df['signal_index']],
                                            name='Risk/Reward Ratio'
                                        ))
                                        
                                        fig5.add_hline(y=1, line_dash="dash", line_color="gray", 
                                                     annotation_text="1:1 R:R")
                                        fig5.add_hline(y=avg_rr, line_dash="dash", line_color="blue", 
                                                     annotation_text=f"Avg: {avg_rr:.2f}")
                                        
                                        fig5.update_layout(
                                            title='Risk/Reward Ratio per Trade',
                                            xaxis_title='Trade Index',
                                            yaxis_title='Risk/Reward Ratio',
                                            height=400
                                        )
                                        st.plotly_chart(fig5, use_container_width=True)
                                    else:
                                        st.info("Risk/Reward data not available")
                                
                                # Download results
                                csv = results_df.to_csv(index=False)
                                st.download_button(
                                    label="📥 Download Results as CSV",
                                    data=csv,
                                    file_name="backtest_results.csv",
                                    mime="text/csv"
                                )
                            else:
                                st.warning("No signals were evaluated in the backtest period.")
                    else:
                        st.error("Failed to fetch price data. Please try again.")
    else:
        st.info("No signals found in the uploaded data.")

else:
    # Show instructions when no data is loaded
    st.info("👈 Please upload a JSON file with trading signals or load sample data to begin backtesting.")
    
    # Show sample JSON structure
    with st.expander("📋 Expected JSON Structure"):
        st.code("""
{
  "signals": [
    {
      "date": "January 19",
      "time": "8:39 PM",
      "direction": "BUY",
      "level": "L2",
      "entry": 4676.3,
      "stop_loss": 4582.77,
      "take_profit": 4933.5,
      "size_lots": 2.45,
      "risk_percent": 2.3
    },
    {
      "date": "January 20",
      "time": "3:44 PM",
      "direction": "BUY",
      "level": "L3",
      "entry": 4732.6,
      "stop_loss": 4673.44,
      "take_profit": 4969.23,
      "size_lots": 3.72,
      "risk_percent": 2.21
    }
  ]
}
""", language="json")

# Footer
st.markdown("---")
st.markdown("""
**Note:** 
1. All times are assumed to be GMT+3 (Middle East Time)
2. Signals without time specified must be filled manually before proceeding
3. Positions close when: Stop Loss/Take Profit hit, Max Days Held reached, or end of data
4. No slippage, commissions, or other trading costs are included
""")

# Add reset button in sidebar
st.sidebar.markdown("---")
if st.sidebar.button("🔄 Reset All Data"):
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()

# Add some CSS for better styling
st.markdown("""
<style>
    .stDataFrame {
        font-size: 14px;
    }
    div[data-testid="stMetric"] {
        background-color: #f0f2f6;
        padding: 15px;
        border-radius: 10px;
        margin: 5px;
    }
    .warning-box {
        background-color: #fff3cd;
        border: 1px solid #ffeaa7;
        padding: 15px;
        border-radius: 5px;
        margin: 10px 0;
    }
</style>
""", unsafe_allow_html=True)
