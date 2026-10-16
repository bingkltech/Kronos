import os
import pandas as pd
import numpy as np
import json
import plotly.graph_objects as go
import plotly.utils
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import sys
import warnings
import datetime
warnings.filterwarnings('ignore')

# Add project root directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from model import Kronos, KronosTokenizer, KronosPredictor
    MODEL_AVAILABLE = True
except ImportError:
    MODEL_AVAILABLE = False
    print("Warning: Kronos model cannot be imported, will use simulated data for demonstration")

app = Flask(__name__)
CORS(app)

# Global variables to store models
tokenizer = None
model = None
predictor = None

# Available model configurations
AVAILABLE_MODELS = {
    'kronos-base': {
        'name': 'Kronos-base',
        'model_id': 'NeoQuasar/Kronos-base',
        'tokenizer_id': 'NeoQuasar/Kronos-Tokenizer-base',
        'context_length': 512,
        'params': '102.3M',
        'description': 'Base model, provides better prediction quality (Default)'
    },
    'kronos-small': {
        'name': 'Kronos-small',
        'model_id': 'NeoQuasar/Kronos-small',
        'tokenizer_id': 'NeoQuasar/Kronos-Tokenizer-base',
        'context_length': 512,
        'params': '24.7M',
        'description': 'Small model, balanced performance and speed'
    },
    'kronos-mini': {
        'name': 'Kronos-mini',
        'model_id': 'NeoQuasar/Kronos-mini',
        'tokenizer_id': 'NeoQuasar/Kronos-Tokenizer-2k',
        'context_length': 2048,
        'params': '4.1M',
        'description': 'Lightweight model, suitable for fast prediction'
    }
}

def load_data_files():
    """Scan data directory and return available data files"""
    data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
    data_files = []
    
    if os.path.exists(data_dir):
        for file in os.listdir(data_dir):
            if file.endswith(('.csv', '.feather')):
                file_path = os.path.join(data_dir, file)
                file_size = os.path.getsize(file_path)
                data_files.append({
                    'name': file,
                    'path': file_path,
                    'size': f"{file_size / 1024:.1f} KB" if file_size < 1024*1024 else f"{file_size / (1024*1024):.1f} MB"
                })
    
    return data_files

def load_data_file(file_path):
    """Load data file with flexible path resolution"""
    try:
        if not os.path.isabs(file_path):
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            cand1 = os.path.join(base_dir, file_path)
            cand2 = os.path.join(base_dir, 'data', os.path.basename(file_path))
            if os.path.exists(cand1):
                file_path = cand1
            elif os.path.exists(cand2):
                file_path = cand2

        if file_path.endswith('.csv'):
            df = pd.read_csv(file_path)
        elif file_path.endswith('.feather'):
            df = pd.read_feather(file_path)
        else:
            return None, "Unsupported file format"
        
        # Check required columns
        required_cols = ['open', 'high', 'low', 'close']
        if not all(col in df.columns for col in required_cols):
            return None, f"Missing required columns: {required_cols}"
        
        # Process timestamp column
        if 'timestamps' in df.columns:
            df['timestamps'] = pd.to_datetime(df['timestamps'])
        elif 'timestamp' in df.columns:
            df['timestamps'] = pd.to_datetime(df['timestamp'])
        elif 'date' in df.columns:
            # If column name is 'date', rename it to 'timestamps'
            df['timestamps'] = pd.to_datetime(df['date'])
        else:
            # If no timestamp column exists, create one
            df['timestamps'] = pd.date_range(start='2024-01-01', periods=len(df), freq='1H')
        
        # Ensure numeric columns are numeric type
        for col in ['open', 'high', 'low', 'close']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # Process volume column (optional)
        if 'volume' in df.columns:
            df['volume'] = pd.to_numeric(df['volume'], errors='coerce')
        
        # Process amount column (optional, but not used for prediction)
        if 'amount' in df.columns:
            df['amount'] = pd.to_numeric(df['amount'], errors='coerce')
        
        # Remove rows containing NaN values
        df = df.dropna()
        
        return df, None
        
    except Exception as e:
        return None, f"Failed to load file: {str(e)}"

def save_prediction_results(file_path, prediction_type, prediction_results, actual_data, input_data, prediction_params):
    """Save prediction results to file"""
    try:
        # Create prediction results directory
        results_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'prediction_results')
        os.makedirs(results_dir, exist_ok=True)
        
        # Generate filename
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'prediction_{timestamp}.json'
        filepath = os.path.join(results_dir, filename)
        
        # Prepare data for saving
        save_data = {
            'timestamp': datetime.datetime.now().isoformat(),
            'file_path': file_path,
            'prediction_type': prediction_type,
            'prediction_params': prediction_params,
            'input_data_summary': {
                'rows': len(input_data),
                'columns': list(input_data.columns),
                'price_range': {
                    'open': {'min': float(input_data['open'].min()), 'max': float(input_data['open'].max())},
                    'high': {'min': float(input_data['high'].min()), 'max': float(input_data['high'].max())},
                    'low': {'min': float(input_data['low'].min()), 'max': float(input_data['low'].max())},
                    'close': {'min': float(input_data['close'].min()), 'max': float(input_data['close'].max())}
                },
                'last_values': {
                    'open': float(input_data['open'].iloc[-1]),
                    'high': float(input_data['high'].iloc[-1]),
                    'low': float(input_data['low'].iloc[-1]),
                    'close': float(input_data['close'].iloc[-1])
                }
            },
            'prediction_results': prediction_results,
            'actual_data': actual_data,
            'analysis': {}
        }
        
        # If actual data exists, perform comparison analysis
        if actual_data and len(actual_data) > 0:
            # Calculate continuity analysis
            if len(prediction_results) > 0 and len(actual_data) > 0:
                last_pred = prediction_results[0]  # First prediction point
            first_actual = actual_data[0]      # First actual point
                
            save_data['analysis']['continuity'] = {
                    'last_prediction': {
                        'open': last_pred['open'],
                        'high': last_pred['high'],
                        'low': last_pred['low'],
                        'close': last_pred['close']
                    },
                    'first_actual': {
                        'open': first_actual['open'],
                        'high': first_actual['high'],
                        'low': first_actual['low'],
                        'close': first_actual['close']
                    },
                    'gaps': {
                        'open_gap': abs(last_pred['open'] - first_actual['open']),
                        'high_gap': abs(last_pred['high'] - first_actual['high']),
                        'low_gap': abs(last_pred['low'] - first_actual['low']),
                        'close_gap': abs(last_pred['close'] - first_actual['close'])
                    },
                    'gap_percentages': {
                        'open_gap_pct': (abs(last_pred['open'] - first_actual['open']) / first_actual['open']) * 100,
                        'high_gap_pct': (abs(last_pred['high'] - first_actual['high']) / first_actual['high']) * 100,
                        'low_gap_pct': (abs(last_pred['low'] - first_actual['low']) / first_actual['low']) * 100,
                        'close_gap_pct': (abs(last_pred['close'] - first_actual['close']) / first_actual['close']) * 100
                    }
                }
        
        # Save to file
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(save_data, f, indent=2, ensure_ascii=False)
        
        print(f"Prediction results saved to: {filepath}")
        return filepath
        
    except Exception as e:
        print(f"Failed to save prediction results: {e}")
        return None

def create_prediction_chart(df, pred_df, lookback, pred_len, actual_df=None, historical_start_idx=0):
    """Create prediction chart with crystal-clear visibility, pure JSON arrays, and ergonomic zoom."""
    # Slicing lookback historical points
    if historical_start_idx + lookback <= len(df):
        historical_df = df.iloc[historical_start_idx:historical_start_idx+lookback]
    else:
        available_lookback = min(lookback, len(df))
        historical_df = df.iloc[-available_lookback:]
    
    # 1. Format timestamps as ISO string lists (pure string arrays for browser Plotly.js)
    if 'timestamps' in historical_df.columns:
        hist_x = [pd.to_datetime(t).strftime('%Y-%m-%d %H:%M:%S') for t in historical_df['timestamps']]
        time_diff = historical_df['timestamps'].iloc[1] - historical_df['timestamps'].iloc[0] if len(historical_df) > 1 else pd.Timedelta(hours=1)
        last_hist_dt = pd.to_datetime(historical_df['timestamps'].iloc[-1])
        split_dt_str = last_hist_dt.strftime('%Y-%m-%d %H:%M:%S')
    else:
        hist_x = [f"T{i}" for i in range(len(historical_df))]
        split_dt_str = hist_x[-1] if hist_x else "T0"
        time_diff = pd.Timedelta(hours=1)
        last_hist_dt = pd.to_datetime('2026-01-01')

    # Convert numeric Series to native Python float lists (PREVENTS binary bdata / dtype serialization bug!)
    hist_open = [float(x) for x in historical_df['open']]
    hist_high = [float(x) for x in historical_df['high']]
    hist_low = [float(x) for x in historical_df['low']]
    hist_close = [float(x) for x in historical_df['close']]

    fig = go.Figure()

    # Trace 0: Historical Candlesticks
    fig.add_trace(go.Candlestick(
        x=hist_x,
        open=hist_open,
        high=hist_high,
        low=hist_low,
        close=hist_close,
        name='Historical Lookback (400)',
        increasing_line_color='#26A69A',
        decreasing_line_color='#EF5350',
        increasing_fillcolor='rgba(38, 166, 154, 0.7)',
        decreasing_fillcolor='rgba(239, 83, 80, 0.7)',
        opacity=0.9
    ))

    pred_x = []
    if pred_df is not None and len(pred_df) > 0:
        if 'timestamps' in df.columns and len(historical_df) > 0:
            pred_dt_range = pd.date_range(
                start=last_hist_dt + time_diff,
                periods=len(pred_df),
                freq=time_diff
            )
            pred_x = [dt.strftime('%Y-%m-%d %H:%M:%S') for dt in pred_dt_range]
        else:
            pred_x = [f"P{i}" for i in range(len(pred_df))]

        pred_open = [float(x) for x in pred_df['open']]
        pred_high = [float(x) for x in pred_df['high']]
        pred_low = [float(x) for x in pred_df['low']]
        pred_close = [float(x) for x in pred_df['close']]

        # Trace 1: Predicted Candlesticks (Vivid Neon Indigo / Cyan / Coral for clear contrast)
        fig.add_trace(go.Candlestick(
            x=pred_x,
            open=pred_open,
            high=pred_high,
            low=pred_low,
            close=pred_close,
            name='Kronos Forecast Candles (120)',
            increasing_line_color='#00E676',
            decreasing_line_color='#FF5252',
            increasing_fillcolor='rgba(0, 230, 118, 0.85)',
            decreasing_fillcolor='rgba(255, 82, 82, 0.85)',
        ))

        # Trace 2: Predicted Close Price Line (Easy-to-see trajectory path)
        fig.add_trace(go.Scatter(
            x=pred_x,
            y=pred_close,
            mode='lines',
            line=dict(color='#00E676', width=2, dash='dot'),
            name='Forecast Trajectory (Close)'
        ))

    # Trace 3 & 4: Actual Ground-Truth Data (if available for comparison)
    if actual_df is not None and len(actual_df) > 0:
        if pred_x and len(pred_x) == len(actual_df):
            actual_x = pred_x
        elif 'timestamps' in actual_df.columns:
            actual_x = [pd.to_datetime(t).strftime('%Y-%m-%d %H:%M:%S') for t in actual_df['timestamps']]
        else:
            actual_x = pred_x

        actual_open = [float(x) for x in actual_df['open']]
        actual_high = [float(x) for x in actual_df['high']]
        actual_low = [float(x) for x in actual_df['low']]
        actual_close = [float(x) for x in actual_df['close']]

        # Actual Data Candlesticks (toggleable via legend to avoid visual collision)
        fig.add_trace(go.Candlestick(
            x=actual_x,
            open=actual_open,
            high=actual_high,
            low=actual_low,
            close=actual_close,
            name='Actual Ground Truth Candles (120)',
            increasing_line_color='#3B82F6',
            decreasing_line_color='#F59E0B',
            increasing_fillcolor='rgba(59, 130, 246, 0.4)',
            decreasing_fillcolor='rgba(245, 158, 11, 0.4)',
            opacity=0.65,
            visible='legendonly'
        ))

        # Actual Close Price Line (Amber solid line with markers for direct path comparison)
        fig.add_trace(go.Scatter(
            x=actual_x,
            y=actual_close,
            mode='lines+markers',
            marker=dict(size=4, color='#F59E0B'),
            line=dict(color='#F59E0B', width=2),
            name='Actual Ground Truth (Close)'
        ))

    # Add Vertical Separation Line marking Forecast Start
    if split_dt_str:
        fig.add_shape(
            type="line",
            x0=split_dt_str,
            x1=split_dt_str,
            y0=0,
            y1=1,
            yref="paper",
            line=dict(color="#E53E3E", width=2, dash="dash")
        )
        fig.add_annotation(
            x=split_dt_str,
            y=0.98,
            yref="paper",
            text="Forecast Start (Kronos AI)",
            showarrow=False,
            xanchor="right",
            yanchor="top",
            font=dict(size=12, color="#E53E3E", family="Segoe UI, sans-serif"),
            bgcolor="rgba(255, 255, 255, 0.9)",
            bordercolor="#E53E3E",
            borderwidth=1,
            borderpad=4
        )

    # Focus on the transition: last 80 historical candles + 120 prediction candles
    if hist_x and pred_x:
        zoom_start = hist_x[-80] if len(hist_x) >= 80 else hist_x[0]
        zoom_end = pred_x[-1]
    elif hist_x:
        zoom_start = hist_x[0]
        zoom_end = hist_x[-1]
    else:
        zoom_start, zoom_end = None, None

    # Update layout with professional quant styling and range slider
    fig.update_layout(
        title={
            'text': 'Kronos Quant Forecast — Historical Lookback vs Prediction Horizon',
            'y': 0.96,
            'x': 0.05,
            'xanchor': 'left',
            'yanchor': 'top',
            'font': dict(size=18, color='#1A202C')
        },
        xaxis=dict(
            title='Time',
            gridcolor='#EDF2F7',
            showgrid=True,
            range=[zoom_start, zoom_end] if zoom_start and zoom_end else None,
            rangeslider=dict(visible=True, thickness=0.08),
            type='date' if 'timestamps' in historical_df.columns else None
        ),
        yaxis=dict(
            title='Price (USDT / Asset Currency)',
            gridcolor='#EDF2F7',
            showgrid=True,
            autorange=True,
            fixedrange=False
        ),
        template='plotly_white',
        height=720,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            bgcolor='rgba(255, 255, 255, 0.85)',
            bordercolor='#CBD5E0',
            borderwidth=1
        ),
        hovermode='x unified',
        margin=dict(l=50, r=50, t=90, b=50)
    )

    return json.dumps(fig.to_dict())


import urllib.request

BINANCE_ASSETS = [
    {"symbol": "BTCUSDT", "name": "Bitcoin (BTC/USDT)"},
    {"symbol": "ETHUSDT", "name": "Ethereum (ETH/USDT)"},
    {"symbol": "SOLUSDT", "name": "Solana (SOL/USDT)"},
    {"symbol": "BNBUSDT", "name": "BNB (BNB/USDT)"},
    {"symbol": "DOGEUSDT", "name": "Dogecoin (DOGE/USDT)"},
    {"symbol": "XRPUSDT", "name": "Ripple (XRP/USDT)"},
    {"symbol": "ADAUSDT", "name": "Cardano (ADA/USDT)"},
    {"symbol": "AVAXUSDT", "name": "Avalanche (AVAX/USDT)"},
    {"symbol": "LINKUSDT", "name": "Chainlink (LINK/USDT)"},
    {"symbol": "NEARUSDT", "name": "NEAR Protocol (NEAR/USDT)"},
    {"symbol": "SUIUSDT", "name": "Sui Network (SUI/USDT)"},
    {"symbol": "PEPEUSDT", "name": "Pepe (PEPE/USDT)"}
]

import requests
import certifi

def fetch_binance_klines(symbol="BTCUSDT", interval="1h", limit=600):
    """Fetch live candlestick data from Binance Free Public API (no API key required)."""
    symbol = symbol.upper().strip()
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=15, verify=certifi.where())
    except requests.exceptions.SSLError:
        resp = requests.get(url, params=params, headers=headers, timeout=15, verify=False)
        
    resp.raise_for_status()
    raw_data = resp.json()
    
    if not raw_data or not isinstance(raw_data, list):
        raise ValueError(f"Empty or invalid response from Binance API for {symbol}")
        
    df = pd.DataFrame(raw_data, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "amount", "trades", "taker_base", "taker_quote", "ignore"
    ])
    
    df["timestamps"] = pd.to_datetime(df["open_time"], unit="ms")
    for col in ["open", "high", "low", "close", "volume", "amount"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
        
    clean_df = df[["timestamps", "open", "high", "low", "close", "volume", "amount"]].dropna().reset_index(drop=True)
    
    data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
    os.makedirs(data_dir, exist_ok=True)
    filename = f"binance_{symbol}_{interval}.csv"
    file_path = os.path.join(data_dir, filename)
    clean_df.to_csv(file_path, index=False)
    
    return clean_df, file_path

@app.route('/')
def index():
    """Home page"""
    return render_template('index.html')

@app.route('/api/binance/symbols', methods=['GET'])
def get_binance_symbols():
    """Return available Binance popular crypto assets and intervals"""
    return jsonify({
        "success": True,
        "symbols": BINANCE_ASSETS,
        "intervals": ["1m", "5m", "15m", "1h", "4h", "1d"]
    })

@app.route('/api/binance/fetch-klines', methods=['POST'])
def binance_fetch():
    """Fetch live market data from Binance free public API and load it"""
    try:
        req_data = request.get_json() or {}
        symbol = req_data.get('symbol', 'BTCUSDT')
        interval = req_data.get('interval', '1h')
        limit = int(req_data.get('limit', 600))
        
        df, file_path = fetch_binance_klines(symbol=symbol, interval=interval, limit=limit)
        
        def detect_timeframe(df):
            if len(df) < 2:
                return "Unknown"
            diff = df['timestamps'].iloc[1] - df['timestamps'].iloc[0]
            if diff < pd.Timedelta(minutes=1):
                return f"{diff.total_seconds():.0f} seconds"
            elif diff < pd.Timedelta(hours=1):
                return f"{diff.total_seconds() / 60:.0f} minutes"
            elif diff < pd.Timedelta(days=1):
                return f"{diff.total_seconds() / 3600:.0f} hours"
            else:
                return f"{diff.days} days"

        data_info = {
            'rows': len(df),
            'columns': list(df.columns),
            'start_date': df['timestamps'].min().isoformat(),
            'end_date': df['timestamps'].max().isoformat(),
            'price_range': {
                'min': float(df[['open', 'high', 'low', 'close']].min().min()),
                'max': float(df[['open', 'high', 'low', 'close']].max().max())
            },
            'prediction_columns': ['open', 'high', 'low', 'close', 'volume'],
            'timeframe': detect_timeframe(df),
            'symbol': symbol,
            'interval': interval,
            'source': 'Binance Public API'
        }
        
        # Include lightweight candle array for immediate TradingView rendering
        data_info['candles'] = [
            {
                'time': int(pd.to_datetime(row['timestamps']).timestamp()) if 'timestamps' in row else 0,
                'open': float(row['open']),
                'high': float(row['high']),
                'low': float(row['low']),
                'close': float(row['close']),
                'volume': float(row['volume']) if 'volume' in row else 0
            }
            for _, row in df.iterrows()
        ]
        
        return jsonify({
            'success': True,
            'file_path': file_path,
            'data_info': data_info,
            'message': f'Successfully fetched {len(df)} live {symbol} ({interval}) candles from Binance!'
        })
    except Exception as e:
        return jsonify({'error': f'Failed to fetch Binance data: {str(e)}'}), 500

@app.route('/api/data-files')
def get_data_files():
    """Get available data file list"""
    data_files = load_data_files()
    return jsonify(data_files)

@app.route('/api/load-data', methods=['POST'])
def load_data():
    """Load data file"""
    try:
        data = request.get_json()
        file_path = data.get('file_path')
        
        if not file_path:
            return jsonify({'error': 'File path cannot be empty'}), 400
        
        df, error = load_data_file(file_path)
        if error:
            return jsonify({'error': error}), 400
        
        # Detect data time frequency
        def detect_timeframe(df):
            if len(df) < 2:
                return "Unknown"
            
            time_diffs = []
            for i in range(1, min(10, len(df))):  # Check first 10 time differences
                diff = df['timestamps'].iloc[i] - df['timestamps'].iloc[i-1]
                time_diffs.append(diff)
            
            if not time_diffs:
                return "Unknown"
            
            avg_diff = sum(time_diffs, pd.Timedelta(0)) / len(time_diffs)
            
            if avg_diff < pd.Timedelta(minutes=1):
                return f"{avg_diff.total_seconds():.0f} seconds"
            elif avg_diff < pd.Timedelta(hours=1):
                return f"{avg_diff.total_seconds() / 60:.0f} minutes"
            elif avg_diff < pd.Timedelta(days=1):
                return f"{avg_diff.total_seconds() / 3600:.0f} hours"
            else:
                return f"{avg_diff.days} days"
        
        # Return data information
        data_info = {
            'rows': len(df),
            'columns': list(df.columns),
            'start_date': df['timestamps'].min().isoformat() if 'timestamps' in df.columns else 'N/A',
            'end_date': df['timestamps'].max().isoformat() if 'timestamps' in df.columns else 'N/A',
            'price_range': {
                'min': float(df[['open', 'high', 'low', 'close']].min().min()),
                'max': float(df[['open', 'high', 'low', 'close']].max().max())
            },
            'prediction_columns': ['open', 'high', 'low', 'close'] + (['volume'] if 'volume' in df.columns else []),
            'timeframe': detect_timeframe(df)
        }
        
        # Include lightweight candle array for TradingView rendering
        data_info['candles'] = [
            {
                'time': int(pd.to_datetime(row['timestamps']).timestamp()) if 'timestamps' in row else 0,
                'open': float(row['open']),
                'high': float(row['high']),
                'low': float(row['low']),
                'close': float(row['close']),
                'volume': float(row['volume']) if 'volume' in row else 0
            }
            for _, row in df.iterrows()
        ]
        
        return jsonify({
            'success': True,
            'data_info': data_info,
            'message': f'Successfully loaded data, total {len(df)} rows'
        })
        
    except Exception as e:
        return jsonify({'error': f'Failed to load data: {str(e)}'}), 500

@app.route('/api/predict', methods=['POST'])
def predict():
    """Perform prediction"""
    try:
        data = request.get_json()
        file_path = data.get('file_path')
        lookback = int(data.get('lookback', 400))
        pred_len = int(data.get('pred_len', 120))
        
        # Get prediction quality parameters
        temperature = float(data.get('temperature', 1.0))
        top_p = float(data.get('top_p', 0.9))
        sample_count = int(data.get('sample_count', 1))
        
        if not file_path:
            return jsonify({'error': 'File path cannot be empty'}), 400
        
        # Load data
        df, error = load_data_file(file_path)
        if error:
            return jsonify({'error': error}), 400
        
        if len(df) < lookback:
            return jsonify({'error': f'Insufficient data length, need at least {lookback} rows'}), 400
        
        # Perform prediction
        if MODEL_AVAILABLE and predictor is not None:
            try:
                # Use real Kronos model
                # Only use necessary columns: OHLCV, excluding amount
                required_cols = ['open', 'high', 'low', 'close']
                if 'volume' in df.columns:
                    required_cols.append('volume')
                
                # Process time period selection
                start_date = data.get('start_date')
                
                if start_date:
                    # Custom time period - fix logic: use data within selected window
                    start_dt = pd.to_datetime(start_date)
                    
                    # Find data after start time
                    mask = df['timestamps'] >= start_dt
                    time_range_df = df[mask]
                    
                    # Ensure sufficient data: lookback + pred_len
                    if len(time_range_df) < lookback + pred_len:
                        return jsonify({'error': f'Insufficient data from start time {start_dt.strftime("%Y-%m-%d %H:%M")}, need at least {lookback + pred_len} data points, currently only {len(time_range_df)} available'}), 400
                    
                    # Use first lookback data points within selected window for prediction
                    x_df = time_range_df.iloc[:lookback][required_cols]
                    x_timestamp = time_range_df.iloc[:lookback]['timestamps']
                    
                    # Use last pred_len data points within selected window as actual values
                    y_timestamp = time_range_df.iloc[lookback:lookback+pred_len]['timestamps']
                    
                    # Calculate actual time period length
                    start_timestamp = time_range_df['timestamps'].iloc[0]
                    end_timestamp = time_range_df['timestamps'].iloc[lookback+pred_len-1]
                    time_span = end_timestamp - start_timestamp
                    
                    prediction_type = f"Kronos model prediction (within selected window: first {lookback} data points for prediction, last {pred_len} data points for comparison, time span: {time_span})"
                else:
                    # Use latest data or tail data
                    use_tail = data.get('use_tail', False) or (len(df) - lookback < pred_len)
                    if use_tail:
                        x_df = df.iloc[-lookback:][required_cols]
                        x_timestamp = df.iloc[-lookback:]['timestamps']
                        if len(x_timestamp) > 1:
                            time_diff = x_timestamp.iloc[-1] - x_timestamp.iloc[-2]
                        else:
                            time_diff = pd.Timedelta(hours=1)
                        future_ts = pd.date_range(start=x_timestamp.iloc[-1] + time_diff, periods=pred_len, freq=time_diff)
                        y_timestamp = pd.Series(future_ts, name='timestamps')
                        prediction_type = f"Kronos model live forward prediction (latest {lookback} lookback bars)"
                    else:
                        x_df = df.iloc[:lookback][required_cols]
                        x_timestamp = df.iloc[:lookback]['timestamps']
                        y_timestamp = df.iloc[lookback:lookback+pred_len]['timestamps']
                        if len(y_timestamp) < pred_len:
                            if len(x_timestamp) > 1:
                                time_diff = x_timestamp.iloc[-1] - x_timestamp.iloc[-2]
                            else:
                                time_diff = pd.Timedelta(hours=1)
                            future_ts = pd.date_range(start=x_timestamp.iloc[-1] + time_diff, periods=pred_len, freq=time_diff)
                            y_timestamp = pd.Series(future_ts, name='timestamps')
                        prediction_type = "Kronos model prediction (latest data)"
                
                # Ensure timestamps are Series format, not DatetimeIndex, to avoid .dt attribute error in Kronos model
                if isinstance(x_timestamp, pd.DatetimeIndex):
                    x_timestamp = pd.Series(x_timestamp, name='timestamps')
                if isinstance(y_timestamp, pd.DatetimeIndex):
                    y_timestamp = pd.Series(y_timestamp, name='timestamps')
                
                pred_df = predictor.predict(
                    df=x_df,
                    x_timestamp=x_timestamp,
                    y_timestamp=y_timestamp,
                    pred_len=pred_len,
                    T=temperature,
                    top_p=top_p,
                    sample_count=sample_count
                )
                
            except Exception as e:
                return jsonify({'error': f'Kronos model prediction failed: {str(e)}'}), 500
        else:
            return jsonify({'error': 'Kronos model not loaded, please load model first'}), 400
        
        # Prepare actual data for comparison (if exists)
        actual_data = []
        actual_df = None
        
        if start_date:  # Custom time period
            # Fix logic: use data within selected window
            # Prediction uses first 400 data points within selected window
            # Actual data should be last 120 data points within selected window
            start_dt = pd.to_datetime(start_date)
            
            # Find data starting from start_date
            mask = df['timestamps'] >= start_dt
            time_range_df = df[mask]
            
            if len(time_range_df) >= lookback + pred_len:
                # Get last 120 data points within selected window as actual values
                actual_df = time_range_df.iloc[lookback:lookback+pred_len]
                
                for i, (_, row) in enumerate(actual_df.iterrows()):
                    ts = pd.to_datetime(row['timestamps']) if 'timestamps' in row else None
                    actual_data.append({
                        'timestamp': ts.isoformat() if ts is not None else '',
                        'time': int(ts.timestamp()) if ts is not None else 0,
                        'open': float(row['open']),
                        'high': float(row['high']),
                        'low': float(row['low']),
                        'close': float(row['close']),
                        'volume': float(row['volume']) if 'volume' in row else 0,
                        'amount': float(row['amount']) if 'amount' in row else 0
                    })
        else:  # Latest / tail data
            use_tail = data.get('use_tail', False) or (len(df) - lookback < pred_len)
            if not use_tail and len(df) >= lookback + pred_len:
                actual_df = df.iloc[lookback:lookback+pred_len]
                for i, (_, row) in enumerate(actual_df.iterrows()):
                    ts = pd.to_datetime(row['timestamps']) if 'timestamps' in row else None
                    actual_data.append({
                        'timestamp': ts.isoformat() if ts is not None else '',
                        'time': int(ts.timestamp()) if ts is not None else 0,
                        'open': float(row['open']),
                        'high': float(row['high']),
                        'low': float(row['low']),
                        'close': float(row['close']),
                        'volume': float(row['volume']) if 'volume' in row else 0,
                        'amount': float(row['amount']) if 'amount' in row else 0
                    })
            else:
                actual_df = None
                actual_data = []
        
        # Create chart - pass historical data start position
        if start_date:
            # Custom time period: find starting position of historical data in original df
            start_dt = pd.to_datetime(start_date)
            mask = df['timestamps'] >= start_dt
            historical_start_idx = df[mask].index[0] if len(df[mask]) > 0 else 0
        else:
            use_tail = data.get('use_tail', False) or (len(df) - lookback < pred_len)
            historical_start_idx = max(0, len(df) - lookback) if use_tail else 0
        
        chart_json = create_prediction_chart(df, pred_df, lookback, pred_len, actual_df, historical_start_idx)
        
        # Prepare historical data for TradingView chart
        historical_data = []
        if historical_start_idx + lookback <= len(df):
            hist_subset = df.iloc[historical_start_idx:historical_start_idx+lookback]
        else:
            available_lookback = min(lookback, len(df))
            hist_subset = df.iloc[-available_lookback:]
            
        for _, row in hist_subset.iterrows():
            ts = pd.to_datetime(row['timestamps']) if 'timestamps' in row else None
            historical_data.append({
                'timestamp': ts.isoformat() if ts is not None else '',
                'time': int(ts.timestamp()) if ts is not None else 0,
                'open': float(row['open']),
                'high': float(row['high']),
                'low': float(row['low']),
                'close': float(row['close']),
                'volume': float(row['volume']) if 'volume' in row else 0
            })

        # Prepare prediction result data - ensure perfect continuity with historical lookback
        if 'timestamps' in df.columns and len(hist_subset) > 0:
            last_timestamp = hist_subset['timestamps'].iloc[-1]
            time_diff = df['timestamps'].iloc[1] - df['timestamps'].iloc[0] if len(df) > 1 else pd.Timedelta(hours=1)
            future_timestamps = pd.date_range(
                start=last_timestamp + time_diff,
                periods=pred_len,
                freq=time_diff
            )
        else:
            future_timestamps = range(len(df), len(df) + pred_len)
        
        prediction_results = []
        for i, (_, row) in enumerate(pred_df.iterrows()):
            ts = future_timestamps[i] if i < len(future_timestamps) else None
            prediction_results.append({
                'timestamp': ts.isoformat() if ts is not None and hasattr(ts, 'isoformat') else f"T{i}",
                'time': int(pd.to_datetime(ts).timestamp()) if ts is not None and hasattr(ts, 'timestamp') else 0,
                'open': float(row['open']),
                'high': float(row['high']),
                'low': float(row['low']),
                'close': float(row['close']),
                'volume': float(row['volume']) if 'volume' in row else 0,
                'amount': float(row['amount']) if 'amount' in row else 0
            })
        
        # Save prediction results to file
        try:
            save_prediction_results(
                file_path=file_path,
                prediction_type=prediction_type,
                prediction_results=prediction_results,
                actual_data=actual_data,
                input_data=x_df,
                prediction_params={
                    'lookback': lookback,
                    'pred_len': pred_len,
                    'temperature': temperature,
                    'top_p': top_p,
                    'sample_count': sample_count,
                    'start_date': start_date if start_date else 'latest'
                }
            )
        except Exception as e:
            print(f"Failed to save prediction results: {e}")
        
        return jsonify({
            'success': True,
            'prediction_type': prediction_type,
            'chart': chart_json,
            'historical_data': historical_data,
            'prediction_results': prediction_results,
            'actual_data': actual_data,
            'has_comparison': len(actual_data) > 0,
            'message': f'Prediction completed, generated {pred_len} prediction points' + (f', including {len(actual_data)} actual data points for comparison' if len(actual_data) > 0 else '')
        })
        
    except Exception as e:
        return jsonify({'error': f'Prediction failed: {str(e)}'}), 500

@app.route('/api/load-model', methods=['POST'])
def load_model():
    """Load Kronos model"""
    global tokenizer, model, predictor
    
    try:
        if not MODEL_AVAILABLE:
            return jsonify({'error': 'Kronos model library not available'}), 400
        
        data = request.get_json() or {}
        model_key = data.get('model_key', 'kronos-base')
        device = data.get('device', 'cpu')
        
        if model_key not in AVAILABLE_MODELS:
            return jsonify({'error': f'Unsupported model: {model_key}'}), 400
        
        model_config = AVAILABLE_MODELS[model_key]
        
        # Load tokenizer and model
        tokenizer = KronosTokenizer.from_pretrained(model_config['tokenizer_id'])
        model = Kronos.from_pretrained(model_config['model_id'])
        
        # Create predictor
        predictor = KronosPredictor(model, tokenizer, device=device, max_context=model_config['context_length'])
        
        return jsonify({
            'success': True,
            'message': f'Model loaded successfully: {model_config["name"]} ({model_config["params"]}) on {device}',
            'model_info': {
                'name': model_config['name'],
                'params': model_config['params'],
                'context_length': model_config['context_length'],
                'description': model_config['description']
            }
        })
        
    except Exception as e:
        return jsonify({'error': f'Model loading failed: {str(e)}'}), 500

@app.route('/api/available-models')
def get_available_models():
    """Get available model list"""
    return jsonify({
        'models': AVAILABLE_MODELS,
        'model_available': MODEL_AVAILABLE
    })

@app.route('/api/model-status')
def get_model_status():
    """Get model status"""
    if MODEL_AVAILABLE:
        if predictor is not None:
            return jsonify({
                'available': True,
                'loaded': True,
                'message': 'Kronos model loaded and available',
                'current_model': {
                    'name': predictor.model.__class__.__name__,
                    'device': str(next(predictor.model.parameters()).device)
                }
            })
        else:
            return jsonify({
                'available': True,
                'loaded': False,
                'message': 'Kronos model available but not loaded'
            })
    else:
        return jsonify({
            'available': False,
            'loaded': False,
            'message': 'Kronos model library not available, please install related dependencies'
        })

if __name__ == '__main__':
    print("Starting Kronos Web UI...")
    print(f"Model availability: {MODEL_AVAILABLE}")
    if MODEL_AVAILABLE:
        print("Tip: You can load Kronos model through /api/load-model endpoint")
    else:
        print("Tip: Will use simulated data for demonstration")
    
    app.run(debug=True, host='0.0.0.0', port=7070)
