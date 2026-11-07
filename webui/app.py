import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass
import pandas as pd
import numpy as np
import json
import plotly.graph_objects as go
import plotly.utils
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import sys
import time
import threading
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
app.config['TEMPLATES_AUTO_RELOAD'] = True
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
            fixedrange=False,
            tickformat='.8f' if (hist_close and hist_close[-1] < 0.0001) else ('.6f' if (hist_close and hist_close[-1] < 0.01) else ('.4f' if (hist_close and hist_close[-1] < 1.0) else ('.3f' if (hist_close and hist_close[-1] < 100.0) else ',.2f'))),
            hoverformat='.8f' if (hist_close and hist_close[-1] < 0.0001) else ('.6f' if (hist_close and hist_close[-1] < 0.01) else ('.4f' if (hist_close and hist_close[-1] < 1.0) else ('.3f' if (hist_close and hist_close[-1] < 100.0) else ',.2f')))
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
    {"symbol": "1000PEPEUSDT", "name": "1000PEPE Futures (1000PEPE/USDT)"},
    {"symbol": "PEPEUSDT", "name": "Pepe Spot (PEPE/USDT)"}
]

import requests
import certifi

def fetch_binance_klines(symbol="BTCUSDT", interval="1h", limit=600):
    """Fetch live candlestick data from Binance Free Public API (Spot or Futures)."""
    symbol = symbol.upper().strip()
    is_futures = symbol.startswith("1000")
    url = "https://fapi.binance.com/fapi/v1/klines" if is_futures else "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=15, verify=certifi.where())
    except requests.exceptions.SSLError:
        resp = requests.get(url, params=params, headers=headers, timeout=15, verify=False)
    
    if not resp.ok and not is_futures:
        # Fallback to Binance Futures endpoint if Spot returns 400 (e.g. futures-only symbols)
        url = "https://fapi.binance.com/fapi/v1/klines"
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
        
        data = request.get_json(silent=True) or {}
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

# ==============================================================================
# Quantitative Terminal & Multi-Agent Bot APIs
# ==============================================================================

from decimal import Decimal, ROUND_HALF_UP
from src.quant.orchestrator import QuantBotOrchestrator
from src.quant.config import ALL_SUPPORTED_SYMBOLS, DEFAULT_RISK_CONFIG
from src.quant.binance_execution import BinanceAtomicExecutor, PositionState
from src.quant.kev_risk_arbiter import TradeTicket
from src.quant.gemini_strategy_arbiter import GeminiStrategyArbiter
from src.quant.apex_scalper import ApexScalperEngine

# Global singleton quant orchestrator
quant_bot = QuantBotOrchestrator(
    symbols_config=ALL_SUPPORTED_SYMBOLS,
    risk_config=DEFAULT_RISK_CONFIG,
    executor=BinanceAtomicExecutor(dry_run=True, realistic_friction=True, symbols_config=ALL_SUPPORTED_SYMBOLS)
)

# Global singleton apex scalper engine (Single-slot N=1 sequential scalper)
apex_scalper = ApexScalperEngine(
    symbols_config=ALL_SUPPORTED_SYMBOLS,
    risk_config=DEFAULT_RISK_CONFIG,
    min_score_threshold=Decimal("0.10")  # Scalper activation threshold for real-time responsiveness
)

@app.route('/api/macro/overview', methods=['GET'])
def get_macro_overview():
    """Return live Top-10 composite breadth, funding rates, and news blackout status."""
    try:
        # 1. Systemic Market Breadth
        macro_verdict = quant_bot.index_engine.evaluate_universe()
        
        # 2. Funding Rates & Carry Economics
        funding_map = quant_bot.carry_specialist.fetch_funding_rates()
        
        # 3. Macro News Blackout Status
        news_verdict = quant_bot.news_specialist.evaluate_blackout()
        
        # Format symbols data
        symbols_data = []
        for sym, stats in macro_verdict.symbol_stats.items():
            sym_funding = funding_map.get(sym, {}).get("funding_rate", Decimal("0.0001"))
            annualized = sym_funding * Decimal("3") * Decimal("365") * Decimal("100")
            carry = quant_bot.carry_specialist.evaluate_carry(sym, "LONG", sym_funding)
            
            symbols_data.append({
                "symbol": sym,
                "current_price": float(stats.current_price),
                "vwap_24h": float(stats.vwap_24h),
                "above_vwap": stats.above_vwap,
                "price_change_24h_pct": float(stats.price_change_24h_pct),
                "volume_24h_usdt": float(stats.volume_24h_usdt),
                "funding_rate_8h_pct": float(sym_funding * Decimal("100")),
                "annualized_funding_pct": float(annualized),
                "carry_verdict": carry.verdict
            })
            
        return jsonify({
            "success": True,
            "macro_regime": macro_verdict.macro_regime,
            "breadth_ratio": float(macro_verdict.breadth_ratio),
            "breadth_pct": f"{float(macro_verdict.breadth_ratio) * 100:.1f}%",
            "coins_above_vwap": macro_verdict.coins_above_vwap_count,
            "total_coins": macro_verdict.total_coins_evaluated,
            "news_blackout": {
                "is_blackout": news_verdict.is_blackout,
                "event_name": news_verdict.event_name,
                "minutes_to_event": news_verdict.minutes_to_event,
                "reason": news_verdict.reason
            },
            "symbols": symbols_data,
            "paper_report": quant_bot.executor.get_paper_summary()
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# ==============================================================================
# Autonomous Quant Bot & KEV.ai Auto-Pilot Daemon
# ==============================================================================

bot_autopilot_enabled = False  # Paper trading paused by default; Live is persistent system default per user directive
bot_autopilot_interval = 60    # Default: 60s autonomous scan interval
bot_autopilot_last_scan = None
bot_autopilot_next_scan_time = None
bot_last_cycle_summary = None
bot_autopilot_lock = threading.Lock()

# Live Real Capital Trading Configuration & Mutual Exclusion
live_trading_enabled = True           # True by default per user directive
live_trading_interval = 60           # 60s autonomous live scan interval
live_trading_last_scan = None
live_trading_next_scan_time = None
live_last_cycle_summary = None
live_account_lock = threading.Lock()

# Gemini Meta-Strategy Arbiter (Google Gemini Free Tier)
gemini_arbiter = GeminiStrategyArbiter()
gemini_auto_apply = True
latest_gemini_assessment = None
last_assessed_trade_count = 0
last_assessed_timestamp = None
gemini_assessment_lock = threading.Lock()


BOT_SETTINGS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "bot_settings.json")

def _load_bot_settings():
    """Restore autopilot settings and last cycle state across server restarts."""
    global bot_autopilot_enabled, bot_autopilot_interval, bot_last_cycle_summary
    global live_trading_enabled, live_trading_interval, live_last_cycle_summary
    if not os.path.exists(BOT_SETTINGS_FILE):
        return
    try:
        with open(BOT_SETTINGS_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            if "live_trading_enabled" in cfg:
                live_trading_enabled = bool(cfg["live_trading_enabled"])
            else:
                live_trading_enabled = True

            if "enabled" in cfg:
                bot_autopilot_enabled = bool(cfg["enabled"])
            else:
                bot_autopilot_enabled = False

            # Strict mutual exclusion enforcement on startup:
            if live_trading_enabled:
                bot_autopilot_enabled = False

            if "interval_seconds" in cfg:
                bot_autopilot_interval = max(10, int(cfg["interval_seconds"]))
            if "last_cycle_summary" in cfg and cfg["last_cycle_summary"]:
                bot_last_cycle_summary = cfg["last_cycle_summary"]
            if "live_trading_interval" in cfg:
                live_trading_interval = max(10, int(cfg["live_trading_interval"]))
            if "live_last_cycle_summary" in cfg and cfg["live_last_cycle_summary"]:
                live_last_cycle_summary = cfg["live_last_cycle_summary"]
            if "gemini_auto_apply" in cfg:
                gemini_auto_apply = bool(cfg["gemini_auto_apply"])
            if "latest_gemini_assessment" in cfg and cfg["latest_gemini_assessment"]:
                latest_gemini_assessment = cfg["latest_gemini_assessment"]
                if gemini_auto_apply and "sweetspot_rr_ratio" in latest_gemini_assessment:
                    try:
                        quant_bot.kev_arbiter.update_sweetspot(
                            min_rr_ratio=Decimal(str(latest_gemini_assessment["sweetspot_rr_ratio"])),
                            min_net_fee_hurdle=Decimal(str(latest_gemini_assessment["sweetspot_fee_hurdle_pct"])) / Decimal("100"),
                            base_risk_budget_ratio=Decimal(str(latest_gemini_assessment["sweetspot_risk_budget_pct"])) / Decimal("100")
                        )
                        print(f">> [Gemini Memory] Restored sweetspot: R:R={latest_gemini_assessment['sweetspot_rr_ratio']:.2f}, Fee Hurdle={latest_gemini_assessment['sweetspot_fee_hurdle_pct']:.2f}%")
                    except Exception as err:
                        print(f">> [Gemini Memory] Could not apply restored sweetspot: {err}")
    except Exception as e:
        print(f">> [Bot Memory] Warning loading settings: {e}")

def _save_bot_settings():
    """Persist autopilot settings and last cycle summary to disk for memory across reloads."""
    try:
        os.makedirs(os.path.dirname(BOT_SETTINGS_FILE), exist_ok=True)
        payload = {
            "enabled": bot_autopilot_enabled,
            "interval_seconds": bot_autopilot_interval,
            "live_trading_enabled": live_trading_enabled,
            "live_trading_interval": live_trading_interval,
            "live_last_cycle_summary": live_last_cycle_summary,
            "last_cycle_summary": bot_last_cycle_summary,
            "gemini_auto_apply": gemini_auto_apply,
            "latest_gemini_assessment": latest_gemini_assessment,
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }
        temp_file = f"{BOT_SETTINGS_FILE}.tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        if os.path.exists(BOT_SETTINGS_FILE):
            os.replace(temp_file, BOT_SETTINGS_FILE)
        else:
            os.rename(temp_file, BOT_SETTINGS_FILE)
    except Exception as e:
        print(f">> [Bot Memory] Warning saving settings: {e}")

# Initial load of persistent settings on startup
_load_bot_settings()

def _execute_quant_bot_cycle(account_equity: Optional[Decimal] = None):
    """Executes a single end-to-end multi-agent scan cycle across the full universe."""
    global bot_autopilot_last_scan, bot_autopilot_next_scan_time, bot_last_cycle_summary
    if account_equity is None:
        account_equity = quant_bot.executor.get_current_equity()

    data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
    lookbacks = {}
    # Fetch live lookback candles directly from Binance API to ensure real-time forward execution
    for sym in list(ALL_SUPPORTED_SYMBOLS.keys())[:5]:
        try:
            live_df = quant_bot.index_engine.fetch_lookback_dataframe(sym, limit=100)
            if live_df is not None and len(live_df) >= 20:
                lookbacks[sym] = live_df
                # Sync fresh candles to disk so UI chart stays synchronized with reality
                live_df.to_csv(os.path.join(data_dir, f"binance_{sym}_1h.csv"), index=False)
        except Exception as e:
            logger.warning("Live lookback fetch error for %s: %s", sym, e)

    report = quant_bot.run_scan_cycle(
        account_equity=account_equity,
        lookback_data_map=lookbacks if lookbacks else None
    )
    bot_autopilot_last_scan = report.timestamp_utc
    bot_autopilot_next_scan_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=bot_autopilot_interval)

    decisions_summary = []
    for sym, dec in report.decisions.items():
        decisions_summary.append({
            "symbol": sym,
            "side": dec.side,
            "approved": dec.approved,
            "veto_gate": dec.veto_gate_failed,
            "reason": dec.veto_reason,
            "adversarial_notes": dec.adversarial_notes,
            "ticket": {
                "entry_price": float(dec.ticket.entry_price),
                "stop_loss": float(dec.ticket.stop_loss),
                "take_profit": float(dec.ticket.take_profit),
                "quantity": float(dec.ticket.quantity),
                "notional_usd": float(dec.ticket.notional_usd),
                "effective_leverage": dec.ticket.effective_leverage,
                "rr_ratio": float(dec.ticket.reward_risk_ratio),
                "net_gain_pct": float(dec.ticket.net_expected_gain_pct)
            } if dec.ticket else None
        })

    dispatched = [
        {
            "position_id": p.position_id,
            "symbol": p.symbol,
            "side": p.side,
            "entry_price": float(p.entry_price),
            "stop_loss": float(p.stop_loss),
            "take_profit": float(p.take_profit),
            "quantity": float(p.quantity)
        }
        for p in report.dispatched_trades
    ]

    summary = {
        "success": True,
        "timestamp": report.timestamp_utc.isoformat(),
        "macro_regime": report.macro_verdict.macro_regime,
        "breadth_pct": f"{float(report.macro_verdict.breadth_ratio)*100:.1f}%",
        "evaluated_count": len(decisions_summary),
        "dispatched_count": len(dispatched),
        "decisions": decisions_summary,
        "dispatched_trades": dispatched,
        "paper_report": quant_bot.executor.get_paper_summary()
    }

    # Autonomous Scalper Micro-Cycle (Single-Slot N=1 Sequential Scalper)
    try:
        _execute_apex_scalp_step(account_equity=account_equity)
    except Exception as e:
        print(f">> [Apex Scalper Step Error] {e}")

    bot_last_cycle_summary = summary
    _save_bot_settings()
    return summary

def _check_remote_cloud_instance() -> Tuple[bool, str]:
    """
    Checks if a remote AWS cloud instance is active and designated as PRIMARY.
    If online and active, local PC live trading is suppressed to prevent double-entry / order collision.
    Configured via AWS_COORDINATOR_URL in .env (e.g. AWS_COORDINATOR_URL=http://<aws_ip>:7070).
    """
    aws_url = os.getenv("AWS_COORDINATOR_URL", "").strip().rstrip("/")
    if not aws_url:
        return False, ""
    try:
        r = requests.get(f"{aws_url}/api/live/status", timeout=2)
        if r.status_code == 200:
            data = r.json()
            is_active = (data.get("bot_state") == "ACTIVE" and 
                         data.get("mutual_exclusion", {}).get("live_trading_active", False))
            if is_active:
                return True, f"Remote AWS Cloud instance at {aws_url} is ONLINE & ACTIVE."
    except Exception:
        pass
    return False, ""

def _execute_live_bot_cycle():
    """Executes a single autonomous live scan cycle with real Binance execution and mutual exclusion."""
    global live_trading_last_scan, live_trading_next_scan_time, live_last_cycle_summary

    # Distributed Multi-Instance Mutual Exclusion Guard:
    is_remote_active, remote_msg = _check_remote_cloud_instance()
    if is_remote_active:
        print(f">> [Distributed Multi-Instance Guard] {remote_msg}")
        print(">> [Distributed Multi-Instance Guard] Local PC in PASSIVE OBSERVER mode — order dispatch suppressed.")
        fresh_account = quant_bot.executor.get_live_account_summary()
        summary = {
            "success": True,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "macro_regime": "STANDBY_OBSERVER",
            "breadth_pct": "0.0%",
            "evaluated_count": 0,
            "dispatched_count": 0,
            "decisions": [],
            "dispatched_trades": [],
            "live_account": {
                "total_wallet_balance_usd": float(fresh_account.get("total_wallet_balance_usd", Decimal("0.00"))),
                "available_balance_usd": float(fresh_account.get("available_balance_usd", Decimal("0.00"))),
                "unrealized_pnl_usd": float(fresh_account.get("unrealized_pnl_usd", Decimal("0.00"))),
                "margin_ratio_pct": float(fresh_account.get("margin_ratio_pct", Decimal("0.00"))),
                "active_positions": fresh_account.get("positions", [])
            },
            "distributed_guard": {
                "cloud_active": True,
                "message": remote_msg,
                "mode": "PASSIVE_OBSERVER"
            }
        }
        live_last_cycle_summary = summary
        live_trading_last_scan = datetime.datetime.now(datetime.timezone.utc)
        live_trading_next_scan_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=live_trading_interval)
        _save_bot_settings()
        return summary

    live_summary = quant_bot.executor.get_live_account_summary()
    if not live_summary.get("connected"):
        summary = {
            "success": False,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "error": live_summary.get("error", "Binance API credentials missing or invalid."),
            "live_account": live_summary
        }
        live_last_cycle_summary = summary
        _save_bot_settings()
        return summary

    account_equity = live_summary.get("total_wallet_balance_usd", Decimal("0.00"))
    if account_equity <= Decimal("0"):
        account_equity = quant_bot.risk_config.small_account_threshold

    data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
    lookbacks = {}
    for sym in list(ALL_SUPPORTED_SYMBOLS.keys())[:5]:
        try:
            live_df = quant_bot.index_engine.fetch_lookback_dataframe(sym, limit=100)
            if live_df is not None and len(live_df) >= 20:
                lookbacks[sym] = live_df
        except Exception as e:
            logger.warning("Live lookback fetch error for %s: %s", sym, e)

    report = quant_bot.run_scan_cycle(
        account_equity=account_equity,
        lookback_data_map=lookbacks if lookbacks else None,
        execution_mode="LIVE"
    )
    live_trading_last_scan = report.timestamp_utc
    live_trading_next_scan_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=live_trading_interval)

    decisions_summary = []
    for sym, dec in report.decisions.items():
        decisions_summary.append({
            "symbol": sym,
            "side": dec.side,
            "approved": dec.approved,
            "veto_gate": dec.veto_gate_failed,
            "reason": dec.veto_reason,
            "adversarial_notes": dec.adversarial_notes,
            "ticket": {
                "entry_price": float(dec.ticket.entry_price),
                "stop_loss": float(dec.ticket.stop_loss),
                "take_profit": float(dec.ticket.take_profit),
                "quantity": float(dec.ticket.quantity),
                "notional_usd": float(dec.ticket.notional_usd),
                "effective_leverage": dec.ticket.effective_leverage,
                "rr_ratio": float(dec.ticket.reward_risk_ratio),
                "net_gain_pct": float(dec.ticket.net_expected_gain_pct)
            } if dec.ticket else None
        })

    dispatched = [
        {
            "position_id": p.position_id,
            "symbol": p.symbol,
            "side": p.side,
            "entry_price": float(p.entry_price),
            "stop_loss": float(p.stop_loss),
            "take_profit": float(p.take_profit),
            "quantity": float(p.quantity)
        }
        for p in report.dispatched_trades
    ]

    fresh_account = quant_bot.executor.get_live_account_summary()

    summary = {
        "success": True,
        "timestamp": report.timestamp_utc.isoformat(),
        "macro_regime": report.macro_verdict.macro_regime,
        "breadth_pct": f"{float(report.macro_verdict.breadth_ratio)*100:.1f}%",
        "evaluated_count": len(decisions_summary),
        "dispatched_count": len(dispatched),
        "decisions": decisions_summary,
        "dispatched_trades": dispatched,
        "live_account": {
            "total_wallet_balance_usd": float(fresh_account.get("total_wallet_balance_usd", Decimal("0.00"))),
            "available_balance_usd": float(fresh_account.get("available_balance_usd", Decimal("0.00"))),
            "unrealized_pnl_usd": float(fresh_account.get("unrealized_pnl_usd", Decimal("0.00"))),
            "margin_ratio_pct": float(fresh_account.get("margin_ratio_pct", Decimal("0.00"))),
            "active_positions": fresh_account.get("positions", [])
        }
    }
    live_last_cycle_summary = summary
    _save_bot_settings()
    return summary

def _autopilot_daemon_loop():
    """Background thread running autonomous scans with strict mutual exclusion."""
    print(">> [Quant Bot & KEV.ai] Autonomous Background Daemon Worker Initialized.")
    # Brief pause to let web server bind to socket
    time.sleep(2)
    # Immediate initial scan
    try:
        if live_trading_enabled:
            _execute_live_bot_cycle()
            print(">> [Quant Bot & KEV.ai] Initial LIVE market scan completed successfully.")
        elif bot_autopilot_enabled:
            _execute_quant_bot_cycle()
            print(">> [Quant Bot & KEV.ai] Initial universe market scan completed successfully.")
    except Exception as e:
        print(f">> [Quant Bot & KEV.ai] Initial scan deferred: {e}")

    while True:
        with live_account_lock:
            live_active = live_trading_enabled
            live_int = live_trading_interval
        with bot_autopilot_lock:
            paper_active = bot_autopilot_enabled
            paper_int = bot_autopilot_interval

        # Strict Mutual Exclusion: If LIVE trading is enabled, PAPER is forced paused!
        if live_active:
            for _ in range(int(live_int)):
                if not live_trading_enabled:
                    break
                time.sleep(1)

            if live_trading_enabled:
                try:
                    _execute_live_bot_cycle()
                    _execute_apex_scalp_step()
                except Exception as e:
                    print(f">> [Live Trading Autopilot Error] {e}")

        elif paper_active:
            for _ in range(int(paper_int)):
                if not bot_autopilot_enabled or live_trading_enabled:
                    break
                time.sleep(1)

            if bot_autopilot_enabled and not live_trading_enabled:
                try:
                    _execute_quant_bot_cycle()
                    _execute_apex_scalp_step()
                except Exception as e:
                    print(f">> [Quant Bot Autopilot Error] {e}")
        else:
            time.sleep(2)

_autopilot_thread = None

def start_autopilot():
    global _autopilot_thread
    with bot_autopilot_lock:
        if _autopilot_thread is None or not _autopilot_thread.is_alive():
            _autopilot_thread = threading.Thread(target=_autopilot_daemon_loop, daemon=True)
            _autopilot_thread.start()


@app.route('/api/bot/status', methods=['GET'])
def get_bot_status():
    """Return quant bot operational status, active positions, and risk metrics."""
    try:
        calib = quant_bot.learning_governor.calculate_brier_calibration()
        positions = []
        for pos_id, pos in quant_bot.executor.active_positions.items():
            if pos.state == PositionState.BRACKETS_ACTIVE:
                duration_min = 0
                if pos.entry_fill_time_utc:
                    duration_min = int((datetime.datetime.now(datetime.timezone.utc) - pos.entry_fill_time_utc).total_seconds() / 60)
                positions.append({
                    "position_id": pos.position_id,
                    "symbol": pos.symbol,
                    "side": pos.side,
                    "entry_price": float(pos.entry_price),
                    "stop_loss": float(pos.stop_loss),
                    "take_profit": float(pos.take_profit),
                    "quantity": float(pos.quantity),
                    "duration_minutes": duration_min,
                    "duration_hours": round(duration_min / 60.0, 1),
                    "state": pos.state.value,
                    "entry_time": pos.entry_fill_time_utc.isoformat() if pos.entry_fill_time_utc else None
                })

        next_sec = 0
        if bot_autopilot_enabled and bot_autopilot_next_scan_time:
            now_u = datetime.datetime.now(datetime.timezone.utc)
            next_sec = max(0, int((bot_autopilot_next_scan_time - now_u).total_seconds()))

        paper_summary = quant_bot.executor.get_paper_summary()
        current_eq = float(quant_bot.executor.get_current_equity())

        return jsonify({
            "success": True,
            "bot_state": "ACTIVE" if bot_autopilot_enabled else "STANDBY_PAUSED",
            "execution_mode": "DRY_RUN (SIMULATED)",
            "account_equity": current_eq,
            "paper_report": paper_summary,
            "last_paper_trade": paper_summary.get("last_paper_trade"),
            "memory_status": {
                "active": True,
                "open_positions_persisted": len(quant_bot.executor.active_positions),
                "closed_trades_persisted": len(quant_bot.executor.closed_trades)
            },
            "micro_trading_active": True,
            "base_risk_budget_pct": "1.5%",
            "max_leverage": 5,
            "confidence_multiplier": float(calib.confidence_multiplier),
            "calibration_status": calib.status,
            "active_positions_count": len(positions),
            "active_positions": positions,
            "autopilot": {
                "enabled": bot_autopilot_enabled,
                "interval_seconds": bot_autopilot_interval,
                "last_scan_utc": bot_autopilot_last_scan.isoformat() if bot_autopilot_last_scan else None,
                "next_scan_seconds": next_sec
            },
            "last_cycle": bot_last_cycle_summary
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

def _execute_apex_scalp_step(account_equity: Optional[Decimal] = None):
    """
    Executes a single autonomous step for the Apex Sequential Scalper:
    1. If slot occupied: fetches current price, updates MAE/MFE, checks TP/SL or 45m timeout.
    2. If slot free: scores Top-10 coins, picks #1 apex candidate, and opens bracket.
    """
    if account_equity is None:
        account_equity = quant_bot.executor.get_current_equity()

    now_utc = datetime.datetime.now(datetime.timezone.utc)

    # 1. Active Scalp In-Trade Management
    if not apex_scalper.is_slot_available and apex_scalper.active_scalp:
        pos = apex_scalper.active_scalp
        # Fetch fresh tick/current price
        try:
            klines = quant_bot.index_engine.fetch_recent_klines(pos.symbol, limit=2)
            if klines:
                curr_price = klines[-1]["close"]
                apex_scalper.update_in_trade_path(curr_price)
                
                # Check TP / SL hit or Fast Profit Snatch
                duration_sec = int((now_utc - pos.entry_time_utc).total_seconds())
                
                # Calculate current net unrealized return
                if pos.side == "BUY":
                    unrealized_return_pct = ((curr_price - pos.entry_price) / pos.entry_price) * Decimal("100")
                else:
                    unrealized_return_pct = ((pos.entry_price - curr_price) / pos.entry_price) * Decimal("100")

                cfg = ALL_SUPPORTED_SYMBOLS.get(pos.symbol)
                friction_pct = (cfg.round_trip_taker_friction() * Decimal("100")) if cfg else Decimal("0.10")
                net_unrealized_pct = unrealized_return_pct - friction_pct

                hit_tp = (pos.side == "BUY" and curr_price >= pos.take_profit) or (pos.side == "SELL" and curr_price <= pos.take_profit)
                hit_sl = (pos.side == "BUY" and curr_price <= pos.stop_loss) or (pos.side == "SELL" and curr_price >= pos.stop_loss)
                # Fast Green Exit: Sell immediately once green (+0.25% net profit achieved)
                fast_profit_snatch = net_unrealized_pct >= Decimal("0.25")
                timed_out = duration_sec >= pos.max_duration_seconds

                if hit_tp or hit_sl or fast_profit_snatch or timed_out:
                    if hit_tp:
                        reason = "TAKE_PROFIT_HIT"
                    elif fast_profit_snatch:
                        reason = "FAST_PROFIT_SNATCH"
                    elif hit_sl:
                        reason = "STOP_LOSS_HIT"
                    else:
                        reason = "TIME_EXPIRATION"

                    fee_usd = pos.notional_usd * (friction_pct / Decimal("100"))
                    
                    # If this was a real live scalp on Binance, cancel open algo orders and flatten if necessary
                    if live_trading_enabled:
                        try:
                            quant_bot.executor._signed_request("DELETE", "/fapi/v1/algoOpenOrders", {"symbol": pos.symbol})
                        except Exception:
                            pass
                        if reason in ("FAST_PROFIT_SNATCH", "TIME_EXPIRATION"):
                            try:
                                flat_side = "SELL" if pos.side == "BUY" else "BUY"
                                quant_bot.executor._signed_request("POST", "/fapi/v1/order", {
                                    "symbol": pos.symbol,
                                    "side": flat_side,
                                    "type": "MARKET",
                                    "quantity": str(pos.quantity),
                                    "reduceOnly": "true"
                                })
                            except Exception as e:
                                print(f">> [Live Scalp Flatten Error] {e}")

                    telemetry = apex_scalper.close_scalp(
                        exit_price=curr_price,
                        close_reason=reason,
                        current_time_utc=now_utc,
                        exchange_fees_usd=fee_usd,
                        trade_mode="LIVE" if live_trading_enabled else "PAPER"
                    )
                    print(f">> [Fast Apex Scalp Closed] {pos.symbol} ({reason}) Return: {float(net_unrealized_pct):.2f}% PnL: ${float(telemetry.net_pnl_usd):.2f} | Diagnosis: {telemetry.root_cause_diagnosis}")
        except Exception as err:
            print(f">> [Apex Scalper Position Monitor Error] {err}")
        return

    # 2. Slot is Free: Institutional Microstructure & Order Flow Screening
    candidates = []
    
    # Symbol Mutual Exclusion: Get all symbols currently held in macro/swing positions
    active_macro_symbols = set()
    for p in quant_bot.executor.active_positions.values():
        if p.state == PositionState.BRACKETS_ACTIVE:
            active_macro_symbols.add(p.symbol)
    if live_trading_enabled:
        try:
            live_acc = quant_bot.executor.get_live_account_summary()
            for lp in live_acc.get("positions", []):
                active_macro_symbols.add(lp.get("symbol"))
        except Exception:
            pass

    # Evaluate full supported universe using live order book depth and volume surge detection
    for sym in list(ALL_SUPPORTED_SYMBOLS.keys()):
        # Conflict Shield: Never scalp a symbol that already has an active macro position!
        if sym in active_macro_symbols:
            continue

        try:
            klines = quant_bot.index_engine.fetch_recent_klines(sym, interval="5m", limit=24)
            if not klines or len(klines) < 12:
                continue
            curr_p = klines[-1]["close"]
            
            # Fetch real-time Top-5 Order Book Imbalance (OBI) and Best Bid/Ask
            obi, best_bid, best_ask = quant_bot.index_engine.fetch_order_book_imbalance(sym, depth_limit=5)

            cand = apex_scalper.evaluate_microstructure_candidate(
                symbol=sym,
                current_price=curr_p,
                best_bid=best_bid,
                best_ask=best_ask,
                order_book_imbalance=obi,
                recent_klines=klines,
                bnb_discount=True
            )
            if cand:
                candidates.append(cand)
        except Exception as e:
            continue

    apex = apex_scalper.select_apex_candidate(candidates)
    if apex:
        pos_id = f"SCALP-{now_utc.strftime('%H%M%S')}"
        
        # Query free cash if in live mode to prevent margin overdraft
        available_cash = None
        if live_trading_enabled:
            # Distributed Multi-Instance Mutual Exclusion Guard:
            is_remote_active, _ = _check_remote_cloud_instance()
            if is_remote_active:
                return

            try:
                live_acc = quant_bot.executor.get_live_account_summary()
                available_cash = Decimal(str(live_acc.get("available_balance_usd", "0.00")))
                if available_cash < Decimal("10.00"):
                    print(f">> [Apex Live Scalp Skipped] Available margin ${available_cash:.2f} below $10.00 safety buffer.")
                    return
            except Exception:
                available_cash = Decimal("19.00")

        new_pos = apex_scalper.open_scalp(
            apex,
            account_equity=account_equity,
            position_id=pos_id,
            current_time_utc=now_utc,
            available_balance_usd=available_cash
        )
        if new_pos:
            if live_trading_enabled:
                ticket = TradeTicket(
                    symbol=apex.symbol,
                    side="BUY" if apex.side in ("BUY", "LONG") else "SELL",
                    entry_price=apex.entry_price,
                    stop_loss=apex.stop_loss,
                    take_profit=apex.take_profit,
                    quantity=new_pos.quantity,
                    notional_usd=new_pos.notional_usd,
                    effective_leverage=new_pos.leverage,
                    risk_budget_usd=new_pos.initial_margin_usd,
                    reward_risk_ratio=apex.reward_risk_ratio,
                    net_expected_gain_pct=apex.predicted_drift_pct
                )
                live_res = quant_bot.executor.submit_live_bracket_order(ticket)
                if live_res.state == PositionState.REJECTED:
                    print(f">> [Apex Scalper Live Dispatch Rejected] {live_res.close_reason}")
                    apex_scalper.active_scalp = None
                    return
                print(f">> [REAL LIVE APEX SCALP DISPATCHED TO BINANCE] {apex.symbol} ({apex.side}) {new_pos.leverage}x Lev Margin=${float(new_pos.initial_margin_usd):.2f} Notional=${float(new_pos.notional_usd):.2f} OrderID={live_res.entry_order_id}")
            else:
                print(f">> [Paper Apex Scalper Dispatched] {apex.symbol} ({apex.side}) {new_pos.leverage}x Lev Margin=${float(new_pos.initial_margin_usd):.2f} Notional=${float(new_pos.notional_usd):.2f} Entry=${float(apex.entry_price):.4f} TP=${float(apex.take_profit):.4f} SL=${float(apex.stop_loss):.4f}")


@app.route('/api/scalper/reset-slot', methods=['POST'])
def reset_scalper_slot():
    """Reset the scalper slot so it can immediately evaluate and dispatch a fresh live trade."""
    apex_scalper.active_scalp = None
    return jsonify({"success": True, "message": "Apex scalper slot reset successfully."})


@app.route('/api/scalper/status', methods=['GET'])
def get_scalper_status():
    """Return live status of the Apex Sequential Scalper and batch learning audits."""
    try:
        active = None
        if apex_scalper.active_scalp:
            pos = apex_scalper.active_scalp
            now_u = datetime.datetime.now(datetime.timezone.utc)
            duration_min = int((now_u - pos.entry_time_utc).total_seconds() / 60)
            active = {
                "position_id": pos.position_id,
                "symbol": pos.symbol,
                "side": pos.side,
                "entry_price": float(pos.entry_price),
                "take_profit": float(pos.take_profit),
                "stop_loss": float(pos.stop_loss),
                "quantity": float(pos.quantity),
                "notional_usd": float(pos.notional_usd),
                "leverage": pos.leverage,
                "initial_margin_usd": float(pos.initial_margin_usd),
                "duration_minutes": duration_min,
                "max_duration_minutes": int(pos.max_duration_seconds / 60),
                "highest_price": float(pos.highest_favorable_price) if pos.highest_favorable_price else None,
                "lowest_price": float(pos.lowest_adverse_price) if pos.lowest_adverse_price else None
            }

        recent_telemetry = [
            {
                "trade_id": r.trade_id,
                "symbol": r.symbol,
                "direction": r.direction,
                "net_pnl_usd": float(r.net_pnl_usd),
                "return_pct": float(r.return_pct),
                "mfe_pct": float(r.mfe_pct),
                "mae_pct": float(r.mae_pct),
                "root_cause": r.root_cause_diagnosis,
                "remedy": r.actionable_remedy
            }
            for r in apex_scalper.closed_scalp_records[-10:]
        ]

        audits = [
            {
                "batch_size": a.batch_size,
                "win_rate_pct": float(a.win_rate_pct),
                "total_pnl_usd": float(a.total_realized_pnl_usd),
                "dominant_root_cause": a.dominant_root_cause,
                "recommended_remedy": a.recommended_remedy,
                "recalibrated_atr_mult": float(a.recalibrated_atr_mult),
                "recalibrated_fee_hurdle_pct": float(a.recalibrated_fee_hurdle_pct)
            }
            for a in apex_scalper.learning_audits
        ]

        return jsonify({
            "success": True,
            "is_slot_available": apex_scalper.is_slot_available,
            "active_scalp": active,
            "total_closed_scalps": len(apex_scalper.closed_scalp_records),
            "recent_trades": recent_telemetry,
            "learning_audits_count": len(audits),
            "latest_audit": audits[-1] if audits else None
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/bot/paper-report', methods=['GET'])
def get_paper_report():
    """Return comprehensive paper trading performance audit and win/loss records."""
    try:
        report = quant_bot.executor.get_paper_summary()
        return jsonify({"success": True, "paper_report": report})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/bot/paper-reset', methods=['POST'])
def reset_paper_report():
    """Reset paper trading balance and trade ledger back to initial USDT equity."""
    try:
        req_data = request.get_json() or {}
        equity = Decimal(str(req_data.get("equity", 200.00)))
        summary = quant_bot.executor.reset_paper_trading(initial_equity=equity)
        return jsonify({
            "success": True,
            "message": f"Paper trading account successfully reset to ${float(equity):.2f} USDT.",
            "paper_report": summary
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/bot/autopilot/toggle', methods=['POST'])
def toggle_bot_autopilot():
    """Toggle or update autonomous auto-pilot settings."""
    global bot_autopilot_enabled, bot_autopilot_interval, live_trading_enabled
    try:
        data = request.get_json(silent=True) or {}
        with bot_autopilot_lock, live_account_lock:
            if "enabled" in data:
                bot_autopilot_enabled = bool(data["enabled"])
            else:
                bot_autopilot_enabled = not bot_autopilot_enabled

            if "interval_seconds" in data:
                bot_autopilot_interval = max(10, int(data["interval_seconds"]))

            # Strict Mutual Exclusion: If Paper is turned ON, Live Trading MUST be turned OFF
            if bot_autopilot_enabled and live_trading_enabled:
                live_trading_enabled = False

            _save_bot_settings()

        return jsonify({
            "success": True,
            "autopilot_enabled": bot_autopilot_enabled,
            "live_trading_enabled": live_trading_enabled,
            "interval_seconds": bot_autopilot_interval,
            "message": f"Quant Bot Auto-Pilot {'ENABLED' if bot_autopilot_enabled else 'PAUSED'}."
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/bot/scan', methods=['POST'])
def run_bot_scan():
    """Trigger an immediate scan cycle across the universe."""
    try:
        req_data = request.get_json() or {}
        equity_val = req_data.get("account_equity")
        equity = Decimal(str(equity_val)) if equity_val is not None else quant_bot.executor.get_current_equity()
        summary = _execute_quant_bot_cycle(account_equity=equity)
        return jsonify(summary)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/bot/place-order', methods=['POST'])
def place_bot_order():
    """Manually dispatch a realistic paper order for the current asset."""
    try:
        req_data = request.get_json() or {}
        symbol = req_data.get("symbol", "BTCUSDT")
        side = req_data.get("side", "SELL").upper()
        if side not in ("BUY", "SELL"):
            side = "SELL"
            
        sym_cfg = quant_bot.executor.symbols_config.get(symbol)
        price_prec = sym_cfg.price_precision if sym_cfg else 2
        qty_prec = sym_cfg.quantity_precision if sym_cfg else 4
        price_fmt = Decimal("10") ** -price_prec
        qty_fmt = Decimal("10") ** -qty_prec
        
        # Determine entry price
        price_val = req_data.get("price")
        if price_val:
            entry_price = Decimal(str(price_val)).quantize(price_fmt, rounding=ROUND_HALF_UP)
        else:
            try:
                klines = quant_bot.index_engine.fetch_24h_klines(symbol)
                if klines:
                    entry_price = klines[-1]["close"].quantize(price_fmt)
                else:
                    entry_price = Decimal("77859.00").quantize(price_fmt)
            except Exception:
                entry_price = Decimal("77859.00").quantize(price_fmt)

        # Micro notional budget $15 USDT
        notional_usd = Decimal(str(req_data.get("notional", "15.00")))
        quantity = (notional_usd / entry_price).quantize(qty_fmt, rounding=ROUND_HALF_UP)
        if sym_cfg and quantity < sym_cfg.min_quantity:
            quantity = sym_cfg.min_quantity
        elif quantity <= Decimal("0"):
            quantity = qty_fmt
        notional_usd = (entry_price * quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        
        sl_pct = Decimal("0.0125")
        tp_pct = Decimal("0.0250")
        if side == "SELL":
            stop_loss = (entry_price * (Decimal("1") + sl_pct)).quantize(price_fmt, rounding=ROUND_HALF_UP)
            take_profit = (entry_price * (Decimal("1") - tp_pct)).quantize(price_fmt, rounding=ROUND_HALF_UP)
        else:
            stop_loss = (entry_price * (Decimal("1") - sl_pct)).quantize(price_fmt, rounding=ROUND_HALF_UP)
            take_profit = (entry_price * (Decimal("1") + tp_pct)).quantize(price_fmt, rounding=ROUND_HALF_UP)
            
        ticket = TradeTicket(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            quantity=quantity,
            notional_usd=notional_usd,
            effective_leverage=3,
            risk_budget_usd=Decimal("3.00"),
            reward_risk_ratio=Decimal("2.00"),
            net_expected_gain_pct=Decimal("0.025")
        )
        
        pos = quant_bot.executor.submit_bracket_order(ticket)
        return jsonify({
            "success": True,
            "message": f"Successfully placed paper order: {side} {float(quantity)} {symbol} @ ${float(entry_price):,.2f}",
            "position": {
                "position_id": pos.position_id,
                "symbol": pos.symbol,
                "side": pos.side,
                "entry_price": float(pos.entry_price),
                "quantity": float(pos.quantity),
                "stop_loss": float(pos.stop_loss),
                "take_profit": float(pos.take_profit),
                "state": pos.state.value
            }
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/bot/close-position', methods=['POST'])
def close_bot_position():
    """Manually flatten an active bracket position."""
    try:
        req_data = request.get_json() or {}
        pos_id = req_data.get("position_id")
        if not pos_id:
            return jsonify({"error": "Missing position_id"}), 400
            
        pos = quant_bot.executor.active_positions.get(pos_id)
        if not pos:
            return jsonify({"error": f"Position {pos_id} not found"}), 404
            
        exit_price = Decimal(str(req_data.get("exit_price", pos.entry_price)))
        closed = quant_bot.executor.close_position_manual(pos_id, reason="MANUAL_CLOSE", exit_price=exit_price)
        
        # Record outcome to LearningGovernor SQLite database for online adaptation
        try:
            quant_bot.learning_governor.record_outcome(TradeOutcome(
                trade_id=closed.position_id,
                symbol=closed.symbol,
                side=closed.side,
                forecast_confidence=Decimal("0.70"),
                realized_hit=1 if closed.realized_pnl_usd > Decimal("0") else 0,
                realized_pnl_usd=closed.realized_pnl_usd,
                exit_reason="MANUAL_CLOSE",
                timestamp_utc=closed.close_time_utc or datetime.datetime.now(datetime.timezone.utc)
            ))
        except Exception:
            pass

        return jsonify({
            "success": True,
            "position_id": closed.position_id,
            "symbol": closed.symbol,
            "state": closed.state.value,
            "realized_pnl_usd": float(closed.realized_pnl_usd),
            "reason": closed.close_reason
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/learning/stats', methods=['GET'])
def get_learning_stats():
    """Return model Brier calibration report and SQLite lessons DB logs."""
    try:
        calib = quant_bot.learning_governor.calculate_brier_calibration()
        outcomes = quant_bot.learning_governor._load_recent_outcomes(limit=15)
        
        formatted_outcomes = [
            {
                "trade_id": o.trade_id,
                "symbol": o.symbol,
                "side": o.side,
                "confidence": float(o.forecast_confidence),
                "hit": o.realized_hit,
                "pnl_usd": float(o.realized_pnl_usd),
                "exit_reason": o.exit_reason,
                "timestamp": o.timestamp_utc.isoformat()
            }
            for o in outcomes
        ]
        
        return jsonify({
            "success": True,
            "brier_score": float(calib.brier_score),
            "confidence_multiplier": float(calib.confidence_multiplier),
            "status": calib.status,
            "reason": calib.reason,
            "total_evaluations": calib.total_evaluations,
            "recent_outcomes": formatted_outcomes
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


def _run_gemini_meta_assessment():
    """Execute background strategic meta-assessment via Gemini Free Tier."""
    global latest_gemini_assessment, last_assessed_trade_count, last_assessed_timestamp
    with gemini_assessment_lock:
        try:
            macro_verdict = quant_bot.index_engine.evaluate_universe()
            macro_summary = {
                "macro_regime": macro_verdict.macro_regime,
                "breadth_pct": f"{float(macro_verdict.breadth_ratio)*100:.1f}%",
                "coins_above_vwap": macro_verdict.coins_above_vwap_count,
                "total_coins": macro_verdict.total_coins_evaluated,
                "news_blackout": {"is_blackout": quant_bot.news_specialist.is_blackout_active()}
            }
            paper_summary = quant_bot.executor.get_paper_summary()
            lessons_calib = quant_bot.learning_governor.calculate_brier_calibration()
            lessons_summary = {
                "brier_score": float(lessons_calib.brier_score),
                "confidence_multiplier": float(lessons_calib.confidence_multiplier),
                "total_lessons": lessons_calib.total_evaluations
            }
            current_settings = {
                "rr_hurdle_ratio": float(quant_bot.kev_arbiter.risk_config.min_rr_ratio),
                "fee_hurdle_pct": float(quant_bot.kev_arbiter.risk_config.min_net_fee_hurdle * Decimal("100")),
                "risk_budget_pct": float(quant_bot.kev_arbiter.risk_config.base_risk_budget_ratio * Decimal("100")),
                "param_sweep_fast_ema": 17,
                "param_sweep_slow_ema": 65
            }
            
            assessment = gemini_arbiter.evaluate_strategy(macro_summary, paper_summary, lessons_summary, current_settings)
            latest_gemini_assessment = assessment.to_dict()
            last_assessed_trade_count = len(quant_bot.executor.closed_trades)
            last_assessed_timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

            if gemini_auto_apply:
                quant_bot.kev_arbiter.update_sweetspot(
                    min_rr_ratio=Decimal(str(assessment.sweetspot_rr_ratio)),
                    min_net_fee_hurdle=Decimal(str(assessment.sweetspot_fee_hurdle_pct)) / Decimal("100"),
                    base_risk_budget_ratio=Decimal(str(assessment.sweetspot_risk_budget_pct)) / Decimal("100")
                )
                print(f">> [Gemini Meta-Strategist] Applied new sweetspot: R:R={assessment.sweetspot_rr_ratio:.2f}, Fee Hurdle={assessment.sweetspot_fee_hurdle_pct:.2f}%, Risk={assessment.sweetspot_risk_budget_pct:.2f}%")

            _save_bot_settings()
            return latest_gemini_assessment
        except Exception as e:
            print(f">> [Gemini Meta-Strategist Error] {e}")
            return None


@app.route('/api/gemini/assessment', methods=['GET'])
def get_gemini_assessment_endpoint():
    """Return latest Gemini strategic assessment and active sweetspot configuration."""
    return jsonify({
        "success": True,
        "available": gemini_arbiter.is_available(),
        "model": gemini_arbiter.model_name,
        "auto_apply": gemini_auto_apply,
        "assessment": latest_gemini_assessment,
        "active_sweetspot": {
            "rr_hurdle_ratio": float(quant_bot.kev_arbiter.risk_config.min_rr_ratio),
            "fee_hurdle_pct": float(quant_bot.kev_arbiter.risk_config.min_net_fee_hurdle * Decimal("100")),
            "risk_budget_pct": float(quant_bot.kev_arbiter.risk_config.base_risk_budget_ratio * Decimal("100")),
            "max_account_leverage": quant_bot.kev_arbiter.risk_config.max_account_leverage
        }
    })


@app.route('/api/gemini/assess', methods=['POST'])
def trigger_gemini_assessment_endpoint():
    """Trigger an immediate strategic meta-assessment via Gemini Free Tier."""
    res = _run_gemini_meta_assessment()
    if res:
        return jsonify({"success": True, "assessment": res})
    return jsonify({"success": False, "error": "Strategic assessment failed"}), 500


@app.route('/api/gemini/apply-sweetspot', methods=['POST'])
def apply_gemini_sweetspot_endpoint():
    """Manually apply the recommended sweetspot parameters to live KEV.ai gates."""
    global latest_gemini_assessment
    if not latest_gemini_assessment:
        return jsonify({"success": False, "error": "No assessment available to apply"}), 400

    try:
        rr = Decimal(str(latest_gemini_assessment.get("sweetspot_rr_ratio", 1.60)))
        fee = Decimal(str(latest_gemini_assessment.get("sweetspot_fee_hurdle_pct", 0.50))) / Decimal("100")
        risk = Decimal(str(latest_gemini_assessment.get("sweetspot_risk_budget_pct", 1.50))) / Decimal("100")

        quant_bot.kev_arbiter.update_sweetspot(
            min_rr_ratio=rr,
            min_net_fee_hurdle=fee,
            base_risk_budget_ratio=risk
        )
        _save_bot_settings()
        return jsonify({
            "success": True,
            "message": f"Sweetspot parameters applied: R:R={float(rr):.2f}, Fee Hurdle={float(fee*Decimal('100')):.2f}%, Risk={float(risk*Decimal('100')):.2f}%"
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/gemini/toggle-auto-apply', methods=['POST'])
def toggle_gemini_auto_apply_endpoint():
    """Toggle automatic sweetspot parameter adoption."""
    global gemini_auto_apply
    data = request.get_json(silent=True) or {}
    if "auto_apply" in data:
        gemini_auto_apply = bool(data["auto_apply"])
    else:
        gemini_auto_apply = not gemini_auto_apply
    _save_bot_settings()
    return jsonify({"success": True, "auto_apply": gemini_auto_apply})


# ==============================================================================
# Real Live Trading Endpoints & Real-Time Futures API
# ==============================================================================

@app.route('/api/health', methods=['GET'])
def health_check():
    """Lightweight 1ms ping for cloud coordinator health checks."""
    return jsonify({
        "status": "ok",
        "instance_tag": os.getenv("KRONOS_INSTANCE_TAG", "PC").strip().upper(),
        "live_trading_enabled": live_trading_enabled,
        "bot_state": "ACTIVE" if live_trading_enabled else "STANDBY_PAUSED",
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()
    })

@app.route('/api/live/status', methods=['GET'])
def get_live_status():
    """Return real Binance Futures account summary, positions, and live autopilot state."""
    try:
        live_account = quant_bot.executor.get_live_account_summary()
        trade_history = quant_bot.executor.get_live_trade_history(limit=25) if live_account.get("connected") else getattr(quant_bot.executor, "_cached_live_trades", [])[:25]
        calib = quant_bot.learning_governor.calculate_brier_calibration()
        is_remote_active, remote_msg = _check_remote_cloud_instance()

        next_sec = 0
        if live_trading_enabled and live_trading_next_scan_time:
            now_u = datetime.datetime.now(datetime.timezone.utc)
            next_sec = max(0, int((live_trading_next_scan_time - now_u).total_seconds()))

        return jsonify({
            "success": True,
            "connected": live_account.get("connected", False),
            "error": live_account.get("error"),
            "bot_state": "ACTIVE" if live_trading_enabled else "STANDBY_PAUSED",
            "execution_mode": "REAL LIVE TRADING (BINANCE FUTURES)",
            "distributed_guard": {
                "instance_tag": os.getenv("KRONOS_INSTANCE_TAG", "PC").strip().upper(),
                "coordinator_url": os.getenv("AWS_COORDINATOR_URL", "").strip(),
                "remote_cloud_active": is_remote_active,
                "role": "PASSIVE_OBSERVER" if is_remote_active else "ACTIVE_PRIMARY",
                "message": remote_msg if is_remote_active else ("Active Primary Instance" if not os.getenv("AWS_COORDINATOR_URL") else "AWS instance unreachable; Local instance is ACTIVE")
            },
            "mutual_exclusion": {
                "live_trading_active": live_trading_enabled and not is_remote_active,
                "paper_trading_paused": live_trading_enabled or not bot_autopilot_enabled,
                "passive_observer": is_remote_active
            },
            "live_account": {
                "total_wallet_balance_usd": float(live_account.get("total_wallet_balance_usd", Decimal("0.00"))),
                "available_balance_usd": float(live_account.get("available_balance_usd", Decimal("0.00"))),
                "unrealized_pnl_usd": float(live_account.get("unrealized_pnl_usd", Decimal("0.00"))),
                "margin_ratio_pct": float(live_account.get("margin_ratio_pct", Decimal("0.00"))),
                "bnb_balance": float(live_account.get("bnb_balance", Decimal("0.00"))),
                "bnb_fee_discount_active": bool(live_account.get("bnb_fee_discount_active", False)),
                "active_positions_count": len(live_account.get("positions", [])),
                "positions": live_account.get("positions", [])
            },
            "trade_history": trade_history,
            "autopilot": {
                "enabled": live_trading_enabled,
                "interval_seconds": live_trading_interval,
                "last_scan_utc": live_trading_last_scan.isoformat() if live_trading_last_scan else None,
                "next_scan_seconds": next_sec
            },
            "confidence_multiplier": float(calib.confidence_multiplier),
            "last_cycle": live_last_cycle_summary
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/live/toggle', methods=['POST'])
def toggle_live_trading():
    """Toggle real live trading. Automatically pauses paper trading when enabled."""
    global live_trading_enabled, live_trading_interval, bot_autopilot_enabled
    try:
        data = request.get_json(silent=True) or {}
        with live_account_lock, bot_autopilot_lock:
            if "enabled" in data:
                live_trading_enabled = bool(data["enabled"])
            else:
                live_trading_enabled = not live_trading_enabled

            if "interval_seconds" in data:
                live_trading_interval = max(10, int(data["interval_seconds"]))

            # Strict Mutual Exclusion:
            if live_trading_enabled:
                bot_autopilot_enabled = False
                msg = "Real Live Trading ACTIVATED on Binance Futures. Paper Trading has been PAUSED."
            else:
                msg = "Real Live Trading PAUSED. System standing by."

            _save_bot_settings()

        return jsonify({
            "success": True,
            "live_trading_enabled": live_trading_enabled,
            "paper_autopilot_enabled": bot_autopilot_enabled,
            "interval_seconds": live_trading_interval,
            "message": msg
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/live/scan', methods=['POST'])
def run_live_scan():
    """Trigger an immediate live scan and potential order dispatch."""
    try:
        summary = _execute_live_bot_cycle()
        return jsonify(summary)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/live/flatten', methods=['POST'])
def flatten_live_positions():
    """Emergency flatten all live positions and cancel open orders on Binance."""
    try:
        with live_account_lock:
            res = quant_bot.executor.flatten_all_live_positions()
        return jsonify(res)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/live/trades', methods=['GET'])
def get_live_trades():
    """Fetch recent live executed trade history with real fees and PnL."""
    try:
        limit = min(100, int(request.args.get("limit", 50)))
        trades = quant_bot.executor.get_live_trade_history(limit=limit)
        return jsonify({"success": True, "trades": trades})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/live/place-order', methods=['POST'])
def place_live_order():
    """Manually dispatch a real live bracket order with KEV.ai safeguards."""
    try:
        req_data = request.get_json() or {}
        symbol = req_data.get("symbol", "BTCUSDT")
        side = req_data.get("side", "SELL").upper()
        if side not in ("BUY", "SELL"):
            side = "SELL"

        sym_cfg = quant_bot.executor.symbols_config.get(symbol)
        price_prec = sym_cfg.price_precision if sym_cfg else 2
        qty_prec = sym_cfg.quantity_precision if sym_cfg else 4
        price_fmt = Decimal("10") ** -price_prec
        qty_fmt = Decimal("10") ** -qty_prec

        # Fetch current price from live Binance API
        try:
            klines = quant_bot.index_engine.fetch_24h_klines(symbol)
            if klines:
                entry_price = klines[-1]["close"].quantize(price_fmt)
            else:
                entry_price = Decimal(str(req_data.get("price", "77859.00"))).quantize(price_fmt)
        except Exception:
            entry_price = Decimal(str(req_data.get("price", "77859.00"))).quantize(price_fmt)

        # Micro notional budget $15 - $50 max
        raw_notional = Decimal(str(req_data.get("notional", "15.00")))
        notional_usd = min(quant_bot.risk_config.small_account_micro_lot_max_usd, max(Decimal("10.00"), raw_notional))
        quantity = (notional_usd / entry_price).quantize(qty_fmt, rounding=ROUND_HALF_UP)
        if sym_cfg and quantity < sym_cfg.min_quantity:
            quantity = sym_cfg.min_quantity
        elif quantity <= Decimal("0"):
            quantity = qty_fmt
        notional_usd = (entry_price * quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        sl_pct = Decimal("0.0125")
        tp_pct = Decimal("0.0250")
        if side == "SELL":
            stop_loss = (entry_price * (Decimal("1") + sl_pct)).quantize(price_fmt, rounding=ROUND_HALF_UP)
            take_profit = (entry_price * (Decimal("1") - tp_pct)).quantize(price_fmt, rounding=ROUND_HALF_UP)
        else:
            stop_loss = (entry_price * (Decimal("1") - sl_pct)).quantize(price_fmt, rounding=ROUND_HALF_UP)
            take_profit = (entry_price * (Decimal("1") + tp_pct)).quantize(price_fmt, rounding=ROUND_HALF_UP)

        ticket = TradeTicket(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            quantity=quantity,
            notional_usd=notional_usd,
            effective_leverage=min(3, quant_bot.risk_config.max_account_leverage),
            risk_budget_usd=Decimal("3.00"),
            reward_risk_ratio=Decimal("2.00"),
            net_expected_gain_pct=Decimal("0.025")
        )

        pos = quant_bot.executor.submit_live_bracket_order(ticket)
        return jsonify({
            "success": True,
            "message": f"Successfully executed live bracket order: {side} {float(quantity)} {symbol} @ ${float(entry_price):,.2f}",
            "position": {
                "position_id": pos.position_id,
                "symbol": pos.symbol,
                "side": pos.side,
                "entry_price": float(pos.entry_price),
                "quantity": float(pos.quantity),
                "stop_loss": float(pos.stop_loss),
                "take_profit": float(pos.take_profit),
                "state": pos.state.value
            }
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == '__main__':
    print("Starting Kronos Web UI...")
    print(f"Model availability: {MODEL_AVAILABLE}")
    if MODEL_AVAILABLE:
        print("Tip: You can load Kronos model through /api/load-model endpoint")
    else:
        print("Tip: Will use simulated data for demonstration")
    # Auto-start Quant Bot & KEV.ai Autonomous Engine
    start_autopilot()
    # Use use_reloader=False to avoid Windows watchdog socket race conditions
    app.run(debug=False, use_reloader=False, host='0.0.0.0', port=7070)
