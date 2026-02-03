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
""")

# Initialize session state for data
if 'signals_data' not in st.session_state:
    st.session_state.signals_data = None
if 'backtest_results' not in st.session_state:
    st.session_state.backtest_results = None
if 'price_data' not in st.session_state:
    st.session_state.price_data = None

# Function to load sample data
def load_sample_data():
    """Load the sample signals data"""
    sample_data = {
        "signals": [
            {
                "date": "January 19",
                "time": "9:39 PM",
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
                "time": "9:34 PM",
                "direction": "BUY",
                "level": "L3",
                "entry": 4732.6,
                "stop_loss": 4673.44,
                "take_profit": 4969.23,
                "size_lots": 3.72,
                "risk_percent": 2.21
            },
            # Add more sample signals as needed
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

# Function to parse date strings
def parse_signal_date(date_str, time_str=None):
    """Parse date string with current year assumption"""
    try:
        # Add current year if not present
        current_year = datetime.now().year
        full_date_str = f"{date_str} {current_year}"
        
        # Parse date
        if time_str:
            # Try multiple time formats
            time_formats = ['%I:%M %p', '%H:%M']
            parsed_date = None
            for fmt in ['%B %d %Y']:
                try:
                    date_part = datetime.strptime(full_date_str, fmt)
                    
                    # Parse time
                    for time_fmt in time_formats:
                        try:
                            time_part = datetime.strptime(time_str, time_fmt).time()
                            parsed_date = datetime.combine(date_part.date(), time_part)
                            break
                        except:
                            continue
                    
                    if parsed_date:
                        break
                except:
                    continue
            
            if parsed_date:
                return parsed_date
        
        # Fallback to date only
        for fmt in ['%B %d %Y', '%b %d %Y', '%d %B %Y']:
            try:
                return datetime.strptime(full_date_str, fmt)
            except:
                continue
        
        return None
    except Exception as e:
        st.warning(f"Could not parse date: {date_str} {time_str} - {e}")
        return None

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
def backtest_signals(signals_df, price_data):
    """Backtest trading signals against price data"""
    results = []
    unevaluated_signals = []
    
    for idx, signal in signals_df.iterrows():
        signal_date = signal['parsed_date']
        
        if pd.isna(signal_date):
            unevaluated_signals.append({
                'signal_index': idx,
                'reason': 'Invalid date',
                'signal': signal
            })
            continue
        
        # Find price data starting from signal date
        future_prices = price_data[price_data['date'] >= signal_date].copy()
        
        if future_prices.empty:
            unevaluated_signals.append({
                'signal_index': idx,
                'reason': 'No price data after signal date',
                'signal_date': signal_date,
                'signal': signal
            })
            continue
        
        # Check if we have enough data to evaluate (at least 1 day after signal)
        if len(future_prices) <= 1:
            unevaluated_signals.append({
                'signal_index': idx,
                'reason': 'Insufficient price data',
                'signal_date': signal_date,
                'signal': signal
            })
            continue
        
        # Get entry price from signal
        entry_price = signal['entry']
        stop_loss = signal['stop_loss']
        take_profit = signal['take_profit']
        direction = signal['direction']
        size_lots = signal['size_lots']
        
        exit_triggered = False
        
        # For BUY signals
        if direction.upper() == 'BUY':
            # Check for stop loss or take profit hit
            for price_idx, price_row in future_prices.iterrows():
                current_low = price_row['low']
                current_high = price_row['high']
                
                # Check if stop loss was hit
                if current_low <= stop_loss:
                    result = {
                        'signal_index': idx,
                        'signal_date': signal_date,
                        'exit_date': price_row['date'],
                        'entry_price': entry_price,
                        'exit_price': stop_loss,
                        'stop_loss': stop_loss,
                        'take_profit': take_profit,
                        'direction': direction,
                        'size_lots': size_lots,
                        'result': 'STOP_LOSS',
                        'pnl_percent': ((stop_loss - entry_price) / entry_price) * 100,
                        'pnl_abs': (stop_loss - entry_price) * size_lots,
                        'days_held': (price_row['date'] - signal_date).days,
                        'exit_reason': 'Stop Loss',
                        'max_adverse_excursion': ((current_low - entry_price) / entry_price) * 100,
                        'max_favorable_excursion': ((current_high - entry_price) / entry_price) * 100
                    }
                    results.append(result)
                    exit_triggered = True
                    break
                
                # Check if take profit was hit
                elif current_high >= take_profit:
                    result = {
                        'signal_index': idx,
                        'signal_date': signal_date,
                        'exit_date': price_row['date'],
                        'entry_price': entry_price,
                        'exit_price': take_profit,
                        'stop_loss': stop_loss,
                        'take_profit': take_profit,
                        'direction': direction,
                        'size_lots': size_lots,
                        'result': 'TAKE_PROFIT',
                        'pnl_percent': ((take_profit - entry_price) / entry_price) * 100,
                        'pnl_abs': (take_profit - entry_price) * size_lots,
                        'days_held': (price_row['date'] - signal_date).days,
                        'exit_reason': 'Take Profit',
                        'max_adverse_excursion': ((current_low - entry_price) / entry_price) * 100,
                        'max_favorable_excursion': ((current_high - entry_price) / entry_price) * 100
                    }
                    results.append(result)
                    exit_triggered = True
                    break
        
        # If no exit was triggered by the end of available data
        if not exit_triggered:
            last_price_row = future_prices.iloc[-1]
            last_close = last_price_row['close']
            
            # Calculate P&L based on last available close
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
                'result': 'OPEN',
                'pnl_percent': ((last_close - entry_price) / entry_price) * 100,
                'pnl_abs': (last_close - entry_price) * size_lots,
                'days_held': (last_price_row['date'] - signal_date).days,
                'exit_reason': 'Still Open',
                'max_adverse_excursion': ((future_prices['low'].min() - entry_price) / entry_price) * 100,
                'max_favorable_excursion': ((future_prices['high'].max() - entry_price) / entry_price) * 100
            }
            results.append(result)
    
    return pd.DataFrame(results), unevaluated_signals

# Main content area
if st.session_state.signals_data:
    signals = st.session_state.signals_data.get('signals', [])
    
    if signals:
        # Convert to DataFrame
        signals_df = pd.DataFrame(signals)
        
        # Parse dates
        signals_df['parsed_date'] = signals_df.apply(
            lambda x: parse_signal_date(x['date'], x['time']), axis=1
        )
        
        # Display signals
        st.header("📋 Trading Signals")
        st.dataframe(signals_df[['date', 'time', 'direction', 'entry', 'stop_loss', 
                                'take_profit', 'size_lots', 'risk_percent']], 
                    use_container_width=True)
        
        # Backtest configuration
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
        if not signals_df['parsed_date'].isna().all():
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
                            results_df, unevaluated = backtest_signals(signals_df, price_data)
                            st.session_state.backtest_results = results_df
                            
                            st.success(f"✅ Backtest completed! {len(results_df)} signals evaluated")
                            
                            # Display results
                            st.header("📊 Backtest Results")
                            
                            # Summary statistics
                            if not results_df.empty:
                                total_signals = len(signals_df)
                                evaluated_signals = len(results_df)
                                winning_trades = len(results_df[results_df['result'] == 'TAKE_PROFIT'])
                                losing_trades = len(results_df[results_df['result'] == 'STOP_LOSS'])
                                open_trades = len(results_df[results_df['result'] == 'OPEN'])
                                
                                win_rate = (winning_trades / (winning_trades + losing_trades) * 100) if (winning_trades + losing_trades) > 0 else 0
                                
                                # Calculate P&L for closed trades only
                                closed_trades = results_df[results_df['result'] != 'OPEN']
                                if not closed_trades.empty:
                                    total_pnl = closed_trades['pnl_abs'].sum()
                                    avg_pnl = closed_trades['pnl_abs'].mean()
                                    avg_days_held = closed_trades['days_held'].mean()
                                else:
                                    total_pnl = 0
                                    avg_pnl = 0
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
                                    st.metric("Open Trades", open_trades)
                                
                                with row2_col2:
                                    st.metric("Win Rate", f"{win_rate:.1f}%")
                                
                                with row2_col3:
                                    st.metric("Total P&L", f"${total_pnl:,.2f}")
                                
                                with row2_col4:
                                    st.metric("Avg P&L per Trade", f"${avg_pnl:,.2f}")
                                
                                # Show unevaluated signals if any
                                if unevaluated:
                                    with st.expander(f"⚠️ {len(unevaluated)} Unevaluated Signals"):
                                        for uneval in unevaluated:
                                            st.write(f"Signal {uneval['signal_index']}: {uneval['reason']}")
                                
                                # Results table
                                st.subheader("Detailed Results")
                                results_display = results_df[[
                                    'signal_index', 'signal_date', 'exit_date', 
                                    'entry_price', 'exit_price', 'result', 'exit_reason',
                                    'pnl_percent', 'pnl_abs', 'days_held'
                                ]].copy()
                                
                                results_display['pnl_percent'] = results_display['pnl_percent'].round(2)
                                results_display['pnl_abs'] = results_display['pnl_abs'].round(2)
                                
                                st.dataframe(results_display, use_container_width=True)
                                
                                # Visualizations
                                st.subheader("📈 Visualization")
                                
                                # Create tabs for different charts
                                tab1, tab2, tab3, tab4 = st.tabs(["P&L Distribution", "Cumulative P&L", "Trade Duration", "Win/Loss Analysis"])
                                
                                with tab1:
                                    fig1 = go.Figure()
                                    colors = []
                                    for result in results_df['result']:
                                        if result == 'TAKE_PROFIT':
                                            colors.append('green')
                                        elif result == 'STOP_LOSS':
                                            colors.append('red')
                                        else:
                                            colors.append('gray')
                                    
                                    fig1.add_trace(go.Bar(
                                        x=results_df['signal_index'],
                                        y=results_df['pnl_abs'],
                                        marker_color=colors,
                                        text=results_df['pnl_abs'].round(2),
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
                                    win_loss_counts = results_df['result'].value_counts()
                                    
                                    fig4 = go.Figure(data=[go.Pie(
                                        labels=win_loss_counts.index,
                                        values=win_loss_counts.values,
                                        hole=.3,
                                        marker_colors=['green', 'red', 'gray']
                                    )])
                                    
                                    fig4.update_layout(
                                        title='Trade Outcome Distribution',
                                        height=400
                                    )
                                    st.plotly_chart(fig4, use_container_width=True)
                                
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
            st.warning("Could not parse dates from signals. Please check the date format.")
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
      "time": "9:39 PM",
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
      "time": "9:34 PM",
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
**Note:** This backtester assumes:
1. All signals are executed at the specified entry price
2. Stop loss and take profit are executed at exact price levels
3. No slippage, commissions, or other trading costs are included
4. Positions close when either stop loss or take profit is hit, or after max holding period
""")

# Add some CSS for better styling
st.markdown("""
<style>
    .stDataFrame {
        font-size: 14px;
    }
    .metric-container {
        background-color: #f0f2f6;
        padding: 15px;
        border-radius: 10px;
        margin: 5px;
    }
    div[data-testid="stMetric"] {
        background-color: #f0f2f6;
        padding: 15px;
        border-radius: 10px;
        margin: 5px;
    }
</style>
""", unsafe_allow_html=True)
