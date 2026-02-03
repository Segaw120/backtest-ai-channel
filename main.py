import streamlit as st
import pandas as pd
import numpy as np
import json
from datetime import datetime, timedelta
import plotly.graph_objects as go
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
**All times are assumed to be GMT+3 (Middle East Time).**
""")

# Initialize session state
if 'signals_data' not in st.session_state:
    st.session_state.signals_data = None
if 'backtest_results' not in st.session_state:
    st.session_state.backtest_results = None
if 'price_data' not in st.session_state:
    st.session_state.price_data = None
if 'signals_df' not in st.session_state:
    st.session_state.signals_df = None
if 'backtest_config' not in st.session_state:
    st.session_state.backtest_config = {}

# Function to parse date strings with GMT+3 timezone
def parse_signal_date(date_str, time_str=None, year=None):
    """Parse date string with GMT+3 timezone assumption"""
    try:
        # Use provided year or current year if not specified
        if year is None:
            current_year = datetime.now().year
        else:
            current_year = year
        
        # Clean date string
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
        
        # Parse date part
        for fmt in date_formats:
            try:
                date_part = datetime.strptime(date_str_clean, fmt)
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
            
            # Combine date and time
            parsed_date = datetime.combine(date_part.date(), time_part)
        else:
            # No time specified, use end of day (23:59) as default
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
        hist = ticker.history(start=start_date, end=end_date)
        
        if hist.empty:
            st.error("No data returned from Yahoo Finance")
            return None
        
        # Reset index to get Date as column
        if isinstance(hist.index, pd.MultiIndex):
            hist = hist.reset_index()
        
        # Convert date to datetime
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

# Sidebar for file upload
st.sidebar.header("📁 Data Upload")
uploaded_file = st.sidebar.file_uploader("Upload JSON signals file", type=['json'])

if uploaded_file is not None:
    try:
        signals_data = json.load(uploaded_file)
        st.session_state.signals_data = signals_data
        # Clear previous results when new file is uploaded
        st.session_state.backtest_results = None
        st.session_state.price_data = None
        st.session_state.backtest_config = {}
        st.sidebar.success(f"✅ Loaded {len(signals_data.get('signals', []))} signals")
    except Exception as e:
        st.sidebar.error(f"Error loading file: {e}")

# Main content
if st.session_state.signals_data:
    signals = st.session_state.signals_data.get('signals', [])
    
    if signals:
        # Convert to DataFrame
        signals_df = pd.DataFrame(signals)
        st.session_state.signals_df = signals_df
        
        # Display signals
        st.header("📋 Trading Signals")
        st.dataframe(signals_df[['date', 'time', 'direction', 'entry', 'stop_loss', 
                                'take_profit', 'size_lots', 'risk_percent']])
        
        # Combined Date Parsing and Backtest Configuration
        st.header("⚙️ Backtest Configuration")
        
        # Check for missing times
        missing_times = signals_df[signals_df['time'].isna() | (signals_df['time'] == '') | (signals_df['time'].isnull())]
        if not missing_times.empty:
            st.warning(f"⚠️ {len(missing_times)} signals have missing time information.")
            st.info("For signals with missing times, 11:59 PM GMT+3 will be used as default.")
        
        # Configuration in columns
        col1, col2, col3 = st.columns(3)
        
        with col1:
            # Year selection
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
            symbol = st.selectbox(
                "Ticker Symbol",
                ["GC=F", "XAUUSD=X", "GLD"],
                help="Gold futures (GC=F), Gold spot (XAUUSD=X), or GLD ETF"
            )
            
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
        
        # Main backtest button
        st.markdown("---")
        st.subheader("🚀 Run Backtest")
        
        if st.button("🚀 **Parse Dates & Run Backtest**", type="primary", use_container_width=True):
            with st.spinner("Parsing dates and running backtest..."):
                # Step 1: Parse dates
                parsed_dates = []
                errors = []
                
                for idx, row in signals_df.iterrows():
                    # Use actual time if available, otherwise use default
                    time_to_use = row['time'] if pd.notna(row['time']) and row['time'] != '' else "11:59 PM"
                    parsed_date, error = parse_signal_date(row['date'], time_to_use, signal_year)
                    
                    if error:
                        errors.append(f"Signal {idx}: {error}")
                    
                    parsed_dates.append(parsed_date)
                
                if errors:
                    st.error("Failed to parse some dates:")
                    for error in errors:
                        st.error(error)
                else:
                    # Add parsed dates to dataframe
                    signals_df['parsed_date'] = parsed_dates
                    st.session_state.signals_df = signals_df
                    
                    # Step 2: Calculate date range and fetch price data
                    start_date = signals_df['parsed_date'].min().date() - timedelta(days=30)
                    
                    # Display parsed dates
                    st.success("✅ Dates parsed successfully!")
                    parsed_display = signals_df.copy()
                    parsed_display['parsed_date_display'] = parsed_display['parsed_date'].dt.strftime('%Y-%m-%d %H:%M GMT+3')
                    st.dataframe(parsed_display[['date', 'time', 'parsed_date_display', 'entry']], height=200)
                    
                    # Fetch price data
                    price_data = fetch_price_data(
                        symbol, 
                        start_date.strftime('%Y-%m-%d'), 
                        end_date.strftime('%Y-%m-%d')
                    )
                    
                    if price_data is not None:
                        st.session_state.price_data = price_data
                        
                        # Step 3: Run backtest
                        results_df, unevaluated = backtest_signals(signals_df, price_data, max_days_held)
                        st.session_state.backtest_results = results_df
                        
                        # Store configuration
                        st.session_state.backtest_config = {
                            'symbol': symbol,
                            'start_date': start_date,
                            'end_date': end_date,
                            'max_days_held': max_days_held,
                            'signal_year': signal_year
                        }
                        
                        st.success(f"✅ Backtest completed! {len(results_df)} signals evaluated")
        
        # Display backtest results if available
        if st.session_state.backtest_results is not None:
            st.header("📊 Backtest Results")
            
            results_df = st.session_state.backtest_results
            
            if not results_df.empty:
                total_signals = len(signals_df)
                evaluated_signals = len(results_df)
                
                # Count different result types
                result_counts = results_df['result'].value_counts()
                winning_trades = result_counts.get('TAKE_PROFIT', 0)
                losing_trades = result_counts.get('STOP_LOSS', 0)
                max_days_trades = result_counts.get('MAX_DAYS', 0)
                incomplete_trades = result_counts.get('INCOMPLETE', 0)
                
                # Calculate win rate
                closed_trades = results_df[results_df['result'].isin(['TAKE_PROFIT', 'STOP_LOSS'])]
                if len(closed_trades) > 0:
                    win_rate = (len(closed_trades[closed_trades['result'] == 'TAKE_PROFIT']) / len(closed_trades)) * 100
                else:
                    win_rate = 0
                
                # Calculate P&L
                total_pnl = results_df['pnl_abs'].sum()
                avg_pnl = results_df['pnl_abs'].mean() if len(results_df) > 0 else 0
                
                # Calculate average days held
                if not closed_trades.empty:
                    avg_days_held = closed_trades['days_held'].mean()
                else:
                    avg_days_held = 0
                
                # Display metrics
                st.subheader("Performance Summary")
                
                # Create metrics grid
                col1, col2, col3, col4 = st.columns(4)
                col5, col6, col7, col8 = st.columns(4)
                
                with col1:
                    st.metric("Total Signals", total_signals)
                with col2:
                    st.metric("Evaluated Signals", evaluated_signals)
                with col3:
                    st.metric("Winning Trades", winning_trades)
                with col4:
                    st.metric("Losing Trades", losing_trades)
                with col5:
                    st.metric("Win Rate", f"{win_rate:.1f}%")
                with col6:
                    st.metric("Total P&L", f"${total_pnl:,.2f}")
                with col7:
                    st.metric("Avg P&L per Trade", f"${avg_pnl:,.2f}")
                with col8:
                    st.metric("Avg Days Held", f"{avg_days_held:.1f}")
                
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
                
                st.dataframe(results_display)
                
                # Visualizations
                st.subheader("📈 Visualization")
                
                # Create tabs for different charts
                tab1, tab2, tab3 = st.tabs(["P&L Distribution", "Cumulative P&L", "Trade Duration"])
                
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
                
                # Download results
                csv = results_df.to_csv(index=False)
                st.download_button(
                    label="📥 Download Results as CSV",
                    data=csv,
                    file_name="backtest_results.csv",
                    mime="text/csv"
                )
                
                # Button to run another backtest
                st.markdown("---")
                if st.button("🔄 Run Another Backtest"):
                    st.session_state.backtest_results = None
                    st.session_state.price_data = None
                    st.rerun()
            else:
                st.warning("No signals were evaluated in the backtest period.")
    else:
        st.info("No signals found in the uploaded data.")
else:
    # Show instructions when no data is loaded
    st.info("👈 Please upload a JSON file with trading signals in the sidebar to begin backtesting.")

# Footer
st.markdown("---")
st.markdown("""
**Note:** 
1. All times are assumed to be GMT+3 (Middle East Time)
2. Signals without time specified default to 11:59 PM GMT+3
3. Positions close when: Stop Loss/Take Profit hit, Max Days Held reached, or end of data
4. No slippage, commissions, or other trading costs are included
""")

# Add reset button in sidebar
st.sidebar.markdown("---")
if st.sidebar.button("🔄 Reset All Data"):
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()
