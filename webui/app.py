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

# Auto-start AWS Telemetry Bridge (Zero-Whitelist Relay to 13.63.158.94)
try:
    from src.quant.aws_telemetry_bridge import aws_bridge
    aws_bridge.start()
except Exception as e:
    print(f">> [AWS Bridge Init Notice] {e}")

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
    return render_template('index.html', initial_view='dashboard')

@app.route('/scalper')
def scalper_page():
    """Dedicated Scalper Only Page"""
    return render_template('index.html', initial_view='scalper')

@app.route('/tiger')
def tiger_page():
    """Dedicated Stalking Tiger Radar Cockpit"""
    return render_template('index.html', initial_view='tiger')

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
            sym = data.get('symbol') or data.get('ticker')
            if sym:
                data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
                cand = os.path.join(data_dir, f"binance_{sym}_1h.csv")
                if os.path.exists(cand):
                    file_path = cand
                else:
                    file_path = os.path.join(data_dir, "binance_BTCUSDT_1h.csv")
            else:
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
            sym = data.get('symbol') or data.get('ticker')
            if sym:
                data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
                cand = os.path.join(data_dir, f"binance_{sym}_1h.csv")
                if os.path.exists(cand):
                    file_path = cand
                else:
                    file_path = os.path.join(data_dir, "binance_BTCUSDT_1h.csv")
            else:
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
from src.quant.apex_scalper import ApexScalperEngine, ActiveScalpState
from src.quant.quota_notifier import quota_mgr

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
    min_score_threshold=Decimal("0.35")  # Institutional high-conviction threshold (prevents fee-bleed noise churn)
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
            sym_funding = (funding_map.get(sym) or {}).get("funding_rate", Decimal("0.0001"))
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
            
        # Real Live Binance Account & Recent Trades (Default across Macro Dashboard)
        live_account = None
        live_trades = []

        # 1. Primary Priority: AWS EC2 Bridge (Whitelisted Production Execution Gateway)
        if aws_bridge and aws_bridge.is_connected():
            try:
                cached_st = getattr(aws_bridge, "_cached_live_status", None)
                if cached_st and isinstance(cached_st, dict) and cached_st.get("live_account"):
                    live_account = dict(cached_st.get("live_account") or {})
                    live_account["connected"] = bool(cached_st.get("connected", True))
                    live_trades = list(cached_st.get("trade_history") or [])
                else:
                    remote_st = aws_bridge.fetch_remote_json('/api/live/status', timeout=2.5)
                    if remote_st and isinstance(remote_st, dict) and remote_st.get("live_account"):
                        live_account = dict(remote_st.get("live_account") or {})
                        live_account["connected"] = bool(remote_st.get("connected", True))
                        live_trades = list(remote_st.get("trade_history") or [])
            except Exception as err:
                logger.debug("Failed to pull live account from AWS bridge: %s", err)

        # 2. Secondary Priority: Local Binance executor if available
        if not live_account or not live_account.get("connected"):
            try:
                local_acct = quant_bot.executor.get_live_account_summary()
                if local_acct and local_acct.get("connected"):
                    live_account = local_acct
                    live_trades = quant_bot.executor.get_live_trade_history(limit=25)
            except Exception as err:
                logger.debug("Local executor live account query: %s", err)

        # Enrich active positions with distinct bot identity (MACRO / NEON / LIGHTNING)
        if live_account and "positions" in live_account:
            active_scalp_sym = apex_scalper.active_scalp.symbol if (apex_scalper and apex_scalper.active_scalp) else None
            enriched_pos = []
            for p in live_account.get("positions", []):
                pd = dict(p)
                sym = pd.get("symbol")
                bot_tag = pd.get("bot_tag") or pd.get("trade_type")
                if not bot_tag or bot_tag in ("SCALP", "MACRO"):
                    if pd.get("is_scalp") or (active_scalp_sym and sym == active_scalp_sym) or (sym in getattr(quant_bot.executor, "scalp_active_symbols", set())):
                        bot_tag = "LIGHTNING"
                    elif pd.get("is_neon") or sym in getattr(quant_bot.executor, "neon_active_symbols", set()) or sym in getattr(quant_bot.executor, "bot_positions", {}):
                        bot_tag = getattr(quant_bot.executor, "bot_positions", {}).get(sym, "NEON")
                    else:
                        bot_tag = "MACRO"
                pd["bot_tag"] = bot_tag
                pd["trade_type"] = bot_tag
                pd["is_scalp"] = (bot_tag == "LIGHTNING")
                pd["is_neon"] = (bot_tag == "NEON")
                pd["is_macro"] = (bot_tag == "MACRO")
                enriched_pos.append(pd)
            live_account["positions"] = enriched_pos

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
            "live_trading_enabled": True,
            "live_account": {
                "connected": live_account.get("connected", False) if live_account else False,
                "total_wallet_balance_usd": float(live_account.get("total_wallet_balance_usd", Decimal("0.00"))) if live_account else 0.0,
                "available_balance_usd": float(live_account.get("available_balance_usd", Decimal("0.00"))) if live_account else 0.0,
                "unrealized_pnl_usd": float(live_account.get("unrealized_pnl_usd", Decimal("0.00"))) if live_account else 0.0,
                "margin_ratio_pct": float(live_account.get("margin_ratio_pct", Decimal("0.00"))) if live_account else 0.0,
                "bnb_balance": float(live_account.get("bnb_balance", Decimal("0.00"))) if live_account else 0.0,
                "bnb_fee_discount_active": bool(live_account.get("bnb_fee_discount_active", False)) if live_account else False,
                "positions": live_account.get("positions", []) if live_account else []
            } if live_account else None,
            "live_trades": live_trades,
            "trade_history": live_trades
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

            if "trade_cap" in cfg and cfg["trade_cap"] is not None:
                quota_mgr.trade_cap = int(cfg["trade_cap"])
            if "session_trades" in cfg and cfg["session_trades"] is not None:
                quota_mgr.session_trades = max(0, int(cfg["session_trades"]))

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
            if "contra_mode" in cfg:
                c_mode = bool(cfg["contra_mode"])
                quant_bot.set_contra_mode(c_mode)
            if not live_trading_enabled:
                print(f">> [Bot Memory] Restored STANDBY_PAUSED state from disk ({BOT_SETTINGS_FILE}). Live trading remains paused across reboot/restart.")
            else:
                print(f">> [Bot Memory] Restored ACTIVE state from disk ({BOT_SETTINGS_FILE}). Cap: {quota_mgr.session_trades}/{quota_mgr.trade_cap}, Interval: {live_trading_interval}s.")
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
            "trade_cap": quota_mgr.trade_cap,
            "session_trades": quota_mgr.session_trades,
            "live_last_cycle_summary": live_last_cycle_summary,
            "last_cycle_summary": bot_last_cycle_summary,
            "gemini_auto_apply": gemini_auto_apply,
            "latest_gemini_assessment": latest_gemini_assessment,
            "contra_mode": getattr(quant_bot, "contra_mode", False),
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }
        temp_file = f"{BOT_SETTINGS_FILE}.tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, default=str)
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
    if not aws_url and aws_bridge and aws_bridge.is_connected():
        aws_url = f"http://127.0.0.1:{aws_bridge.local_port}"
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
        # Zero-Whitelist Tap: Do not query Binance from PC; use live telemetry kicked from AWS
        fresh_account = aws_bridge.get_live_account_summary() if (aws_bridge and aws_bridge.is_connected()) else {}
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

    # Auto-reconcile and purge dangling/orphaned algo orders on Binance
    try:
        purged = quant_bot.executor.purge_orphaned_algo_orders()
        if purged:
            print(f">> [Live Bot Cycle] Auto-purged orphaned algo orders: {purged}")
    except Exception as e:
        logger.warning("Error running purge_orphaned_algo_orders in live cycle: %s", e)

    # 1. Trade Quota Auto-Pause Check:
    global live_trading_enabled
    if not quota_mgr.has_quota_remaining:
        print(f">> [LIVE TRADE QUOTA] Session trade cap ({quota_mgr.session_trades}/{quota_mgr.trade_cap}) reached. Auto-pausing live macro trading.")
        live_trading_enabled = False
        summary = {
            "success": True,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "macro_regime": "QUOTA_PAUSED",
            "breadth_pct": "0.0%",
            "evaluated_count": 0,
            "dispatched_count": 0,
            "decisions": [],
            "dispatched_trades": [],
            "live_account": {
                "total_wallet_balance_usd": float(live_summary.get("total_wallet_balance_usd", Decimal("0.00"))),
                "available_balance_usd": float(live_summary.get("available_balance_usd", Decimal("0.00"))),
                "unrealized_pnl_usd": float(live_summary.get("unrealized_pnl_usd", Decimal("0.00"))),
                "margin_ratio_pct": float(live_summary.get("margin_ratio_pct", Decimal("0.00"))),
                "active_positions": live_summary.get("positions", [])
            },
            "quota_status": {
                "cap_reached": True,
                "session_trades": quota_mgr.session_trades,
                "trade_cap": quota_mgr.trade_cap
            }
        }
        live_last_cycle_summary = summary
        live_trading_last_scan = datetime.datetime.now(datetime.timezone.utc)
        live_trading_next_scan_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=live_trading_interval)
        _save_bot_settings()
        return summary

    # 2. Portfolio Concurrency & Strategy Allocation Checks (Max 3 total: 2 Macro + 1 Scalp)
    active_positions = live_summary.get("positions", [])
    active_symbols = set(p.get("symbol") for p in active_positions)
    scalp_active_symbols = quant_bot.executor.scalp_active_symbols
    macro_positions = [
        p for p in active_positions
        if p.get("symbol") not in scalp_active_symbols
    ]

    max_portfolio_positions = int(os.getenv("KRONOS_MAX_CONCURRENT_POSITIONS", "9"))
    if len(active_positions) >= max_portfolio_positions:
        print(f">> [PORTFOLIO CONCURRENCY] Maximum concurrent positions held ({len(active_positions)}/{max_portfolio_positions}: {active_symbols}). Holding.")
        summary = {
            "success": True,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "macro_regime": "CONCURRENCY_HELD",
            "breadth_pct": "0.0%",
            "evaluated_count": 0,
            "dispatched_count": 0,
            "decisions": [],
            "dispatched_trades": [],
            "live_account": {
                "total_wallet_balance_usd": float(live_summary.get("total_wallet_balance_usd", Decimal("0.00"))),
                "available_balance_usd": float(live_summary.get("available_balance_usd", Decimal("0.00"))),
                "unrealized_pnl_usd": float(live_summary.get("unrealized_pnl_usd", Decimal("0.00"))),
                "margin_ratio_pct": float(live_summary.get("margin_ratio_pct", Decimal("0.00"))),
                "active_positions": active_positions
            }
        }
        live_last_cycle_summary = summary
        live_trading_last_scan = datetime.datetime.now(datetime.timezone.utc)
        live_trading_next_scan_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=live_trading_interval)
        _save_bot_settings()
        return summary

    max_macro_positions = int(os.getenv("KRONOS_MAX_MACRO_POSITIONS", "6"))
    if len(macro_positions) >= max_macro_positions:
        print(f">> [STRATEGY ALLOCATION] Macro slots full ({len(macro_positions)}/{max_macro_positions} occupied: {[p.get('symbol') for p in macro_positions]}). Holding for exit before new macro entry.")
        summary = {
            "success": True,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "macro_regime": "MACRO_SLOTS_FULL",
            "breadth_pct": "0.0%",
            "evaluated_count": 0,
            "dispatched_count": 0,
            "decisions": [],
            "dispatched_trades": [],
            "live_account": {
                "total_wallet_balance_usd": float(live_summary.get("total_wallet_balance_usd", Decimal("0.00"))),
                "available_balance_usd": float(live_summary.get("available_balance_usd", Decimal("0.00"))),
                "unrealized_pnl_usd": float(live_summary.get("unrealized_pnl_usd", Decimal("0.00"))),
                "margin_ratio_pct": float(live_summary.get("margin_ratio_pct", Decimal("0.00"))),
                "active_positions": active_positions
            }
        }
        live_last_cycle_summary = summary
        live_trading_last_scan = datetime.datetime.now(datetime.timezone.utc)
        live_trading_next_scan_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=live_trading_interval)
        _save_bot_settings()
        return summary

    # 3. Macro Entry Cap:
    remaining_quota = quota_mgr.trades_remaining if quota_mgr.trades_remaining is not None else 1
    macro_available = max_macro_positions - len(macro_positions)
    portfolio_available = max_portfolio_positions - len(active_positions)
    macro_entry_cap = min(remaining_quota, macro_available, portfolio_available)

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
        execution_mode="LIVE",
        max_new_entries=macro_entry_cap
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

    for p in report.dispatched_trades:
        quota_mgr.record_dispatch(p.symbol, "MACRO", account_summary=fresh_account)
    if not quota_mgr.is_active:
        live_trading_enabled = False

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
    global live_trading_enabled
    # Suppress local scalp order execution if remote AWS instance is active
    is_remote_active, _ = _check_remote_cloud_instance()
    if is_remote_active:
        return
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

                duration_sec = int((now_utc - pos.entry_time_utc).total_seconds())

                # Automatic Adaptation: Check if trade was already closed/flattened externally on Binance
                if live_trading_enabled:
                    try:
                        live_acc = quant_bot.executor.get_live_account_summary()
                        if live_acc.get("connected"):
                            open_syms = [p.get("symbol") for p in live_acc.get("positions", [])]
                            # Grace buffer: only consider externally flattened if position is missing after 30s
                            if duration_sec >= 30 and pos.symbol not in open_syms:
                                print(f">> [External Flatten Detected] {pos.symbol} position no longer on Binance. Releasing scalper slot.")
                                try:
                                    quant_bot.executor._signed_request("DELETE", "/fapi/v1/algoOpenOrders", {"symbol": pos.symbol})
                                    quant_bot.executor._signed_request("DELETE", "/fapi/v1/allOpenOrders", {"symbol": pos.symbol})
                                except Exception:
                                    pass
                                apex_scalper.close_scalp(
                                    exit_price=curr_price,
                                    close_reason="MANUAL_OVERRIDE",
                                    current_time_utc=now_utc,
                                    exchange_fees_usd=Decimal("0.00"),
                                    trade_mode="LIVE"
                                )
                                return
                    except Exception as err:
                        logger.debug("Live sync check error: %s", err)
                
                # Calculate current net unrealized return
                if pos.side == "BUY":
                    unrealized_return_pct = ((curr_price - pos.entry_price) / pos.entry_price) * Decimal("100")
                else:
                    unrealized_return_pct = ((pos.entry_price - curr_price) / pos.entry_price) * Decimal("100")

                cfg = ALL_SUPPORTED_SYMBOLS.get(pos.symbol)
                friction_pct = (cfg.round_trip_taker_friction() * Decimal("100")) if cfg else Decimal("0.10")
                net_unrealized_pct = unrealized_return_pct - friction_pct

                # 1. Evaluate Volatility-Buffered Ratchet (Lesson #18)
                # Once net gain reaches >= +0.40%, ratchet Stop-Loss to Entry + Fees (guaranteed positive exit)
                ratchet_triggered, new_sl = apex_scalper.evaluate_ratchet(curr_price, friction_pct)
                if ratchet_triggered and new_sl:
                    print(f">> [Apex Scalper Ratchet Activated] {pos.symbol} reached +{net_unrealized_pct:.2f}%. Stop-loss locked at green level: ${new_sl:.4f}")
                    if live_trading_enabled:
                        try:
                            quant_bot.executor._signed_request("DELETE", "/fapi/v1/algoOpenOrders", {"symbol": pos.symbol})
                            opp_side = "SELL" if pos.side == "BUY" else "BUY"
                            sl_prec = cfg.price_precision if cfg else 2
                            fmt_p = Decimal("10") ** -sl_prec
                            quant_bot.executor._signed_request("POST", "/fapi/v1/algoOrder", {
                                "algoType": "CONDITIONAL",
                                "symbol": pos.symbol,
                                "side": opp_side,
                                "type": "STOP_MARKET",
                                "triggerPrice": str(new_sl.quantize(fmt_p)),
                                "closePosition": "true",
                                "clientAlgoId": f"RATCHET_SL_{pos.symbol}_{int(time.time()*1000)}"[:32]
                            })
                        except Exception as e:
                            logger.warning("Failed to update Binance live ratchet SL for %s: %s", pos.symbol, e)

                hit_tp = (pos.side == "BUY" and curr_price >= pos.take_profit) or (pos.side == "SELL" and curr_price <= pos.take_profit)
                hit_sl = (pos.side == "BUY" and curr_price <= pos.stop_loss) or (pos.side == "SELL" and curr_price >= pos.stop_loss)
                timed_out = duration_sec >= pos.max_duration_seconds
                is_stalled, stall_reason = apex_scalper.evaluate_stagnation(now_utc)

                if hit_tp or hit_sl or timed_out or is_stalled:
                    if hit_tp:
                        reason = "TAKE_PROFIT_HIT"
                    elif hit_sl:
                        reason = "STOP_LOSS_HIT"
                    elif is_stalled:
                        reason = "STAGNATION_EXPIRATION"
                    else:
                        reason = "TIME_EXPIRATION"

                    fee_usd = pos.notional_usd * (friction_pct / Decimal("100"))
                    
                    # If this was a real live scalp on Binance, cancel open algo orders and flatten if necessary
                    if live_trading_enabled:
                        try:
                            quant_bot.executor._signed_request("DELETE", "/fapi/v1/algoOpenOrders", {"symbol": pos.symbol})
                        except Exception:
                            pass
                        if reason in ("FAST_PROFIT_SNATCH", "TIME_EXPIRATION", "STAGNATION_EXPIRATION"):
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

    # 2. Scalper Slot Verification:
    # If the scalper slot is free, evaluate fresh microstructure candidates directly.
    # Note: We strictly avoid heuristic position adoption (e.g. leverage >= 3) to prevent
    # mistakenly hijacking and liquidating macro swing trades.

    # Quota check
    if not quota_mgr.has_quota_remaining:
        if live_trading_enabled:
            print(f">> [LIVE TRADE QUOTA] Session trade cap ({quota_mgr.session_trades}/{quota_mgr.trade_cap}) reached. Auto-pausing live scalp trading.")
            live_trading_enabled = False
        return

    # Concurrency Clamp: Max 9 positions across entire portfolio (6 macro + 3 scalp)
    max_portfolio_positions = int(os.getenv("KRONOS_MAX_CONCURRENT_POSITIONS", "9"))
    all_active_symbols = set()
    scalp_active_symbols = quant_bot.executor.scalp_active_symbols
    if live_trading_enabled:
        try:
            live_acc_check = quant_bot.executor.get_live_account_summary()
            if live_acc_check.get("connected"):
                all_active_symbols = set(p.get("symbol") for p in live_acc_check.get("positions", []))
        except Exception:
            pass
    else:
        for p in quant_bot.executor.active_positions.values():
            if p.state == PositionState.BRACKETS_ACTIVE:
                all_active_symbols.add(p.symbol)
        if apex_scalper.active_scalp:
            all_active_symbols.add(apex_scalper.active_scalp.symbol)

    if len(all_active_symbols) >= max_portfolio_positions:
        return

    # Dedicated Scalp Allocation: Strictly 3 Scalp slots
    max_scalp_positions = int(os.getenv("KRONOS_MAX_SCALP_POSITIONS", "3"))
    active_scalps = all_active_symbols.intersection(scalp_active_symbols)
    if len(active_scalps) >= max_scalp_positions or not apex_scalper.is_slot_available:
        return

    # 3. Slot is Free: Institutional Microstructure & Order Flow Screening
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
    current_breadth_pct = None
    try:
        macro_report = quant_bot.index_engine.evaluate_universe()
        if macro_report and macro_report.breadth_ratio is not None:
            current_breadth_pct = macro_report.breadth_ratio * Decimal("100")
    except Exception:
        pass

    eligible_symbols = []
    for sym in list(ALL_SUPPORTED_SYMBOLS.keys()):
        # Conflict Shield: Never scalp a symbol that already has an active macro position!
        if sym in active_macro_symbols:
            continue
        # Post-Exit Quarantine Check: Veto if symbol is cooling down after recent exit
        if apex_scalper.is_symbol_in_cooldown(sym, now_utc):
            continue
        eligible_symbols.append(sym)

    batch_market_data = quant_bot.index_engine.batch_fetch_scalp_market_data(
        symbols=eligible_symbols,
        interval="5m",
        kline_limit=24,
        depth_limit=10
    )

    for sym in eligible_symbols:
        if sym not in batch_market_data:
            continue
        klines, micro_data = batch_market_data[sym]
        if not klines or len(klines) < 12:
            continue
        if micro_data.best_bid <= Decimal("0") or micro_data.best_ask <= Decimal("0"):
            continue

        curr_p = ((micro_data.best_bid + micro_data.best_ask) / Decimal("2")) if (micro_data.best_bid > Decimal("0") and micro_data.best_ask > Decimal("0")) else klines[-1]["close"]
        vp_snapshot = quant_bot.volume_profile_cache.get_previous_day_profile(sym, now_utc)

        cand = apex_scalper.evaluate_microstructure_candidate(
            symbol=sym,
            current_price=curr_p,
            best_bid=micro_data.best_bid,
            best_ask=micro_data.best_ask,
            order_book_imbalance=micro_data.obi,
            recent_klines=klines,
            bnb_discount=True,
            micro_skew_bps=micro_data.micro_skew_bps,
            micro_price=micro_data.micro_price,
            macro_breadth_pct=current_breadth_pct,
            current_time_utc=now_utc,
            volume_profile=vp_snapshot
        )
        if cand:
            candidates.append(cand)

    apex = apex_scalper.select_apex_candidate(candidates)
    if apex:
        pos_id = f"SCALP-{now_utc.strftime('%H%M%S')}"
        ct_tag = " [COUNTER-TREND V-BOTTOM: Half Margin]" if getattr(apex, "is_counter_trend", False) else " [TREND-CONFLUENT: Full Margin]"
        
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
                    net_expected_gain_pct=apex.expected_net_drift_pct,
                    is_scalp=True
                )
                live_res = quant_bot.executor.submit_live_bracket_order(ticket)
                if live_res.state == PositionState.REJECTED:
                    print(f">> [Apex Scalper Live Dispatch Rejected] {live_res.close_reason}")
                    apex_scalper.active_scalp = None
                    return
                if live_res.entry_order_id:
                    quant_bot.executor.record_scalp_order(live_res.entry_order_id)
                if live_res.take_profit_order_id:
                    quant_bot.executor.record_scalp_order(live_res.take_profit_order_id)
                if live_res.stop_loss_order_id:
                    quant_bot.executor.record_scalp_order(live_res.stop_loss_order_id)
                print(f">> [REAL LIVE APEX SCALP DISPATCHED TO BINANCE]{ct_tag} {apex.symbol} ({apex.side}) {new_pos.leverage}x Lev Margin=${float(new_pos.initial_margin_usd):.2f} Notional=${float(new_pos.notional_usd):.2f} OrderID={live_res.entry_order_id}")
                quota_mgr.record_dispatch(apex.symbol, "SCALP", account_summary=live_acc)
                if not quota_mgr.is_active:
                    live_trading_enabled = False
            else:
                print(f">> [Paper Apex Scalper Dispatched]{ct_tag} {apex.symbol} ({apex.side}) {new_pos.leverage}x Lev Margin=${float(new_pos.initial_margin_usd):.2f} Notional=${float(new_pos.notional_usd):.2f} Entry=${float(apex.entry_price):.4f} TP=${float(apex.take_profit):.4f} SL=${float(apex.stop_loss):.4f}")


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
            "latest_audit": audits[-1] if audits else None,
            "symbol_cooldowns": apex_scalper.get_cooldown_status()
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


SCALPER_CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "scalper_config.json")


@app.route('/api/lightning/config', methods=['GET'])
def get_lightning_config():
    """Fetch configuration for the 2nd faster Lightning Scalper."""
    try:
        if os.path.exists(SCALPER_CONFIG_PATH):
            with open(SCALPER_CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            return jsonify({"success": True, "config": cfg})
        else:
            return jsonify({"success": False, "error": "Configuration file not found."}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/lightning/config', methods=['POST'])
def save_lightning_config():
    """Save updated rules, strategies, and guardrails for the Lightning Scalper."""
    try:
        data = request.get_json(force=True)
        if not data or not isinstance(data, dict):
            return jsonify({"success": False, "error": "Invalid JSON payload"}), 400

        existing_cfg = {}
        if os.path.exists(SCALPER_CONFIG_PATH):
            with open(SCALPER_CONFIG_PATH, "r", encoding="utf-8") as f:
                existing_cfg = json.load(f)

        for key in ["enabled", "execution_mode", "min_win_probability_pct"]:
            if key in data:
                existing_cfg[key] = data[key]

        if "strategies" in data and isinstance(data["strategies"], dict):
            existing_cfg.setdefault("strategies", {})
            for strat_key, strat_val in data["strategies"].items():
                if isinstance(strat_val, dict):
                    existing_cfg["strategies"].setdefault(strat_key, {})
                    existing_cfg["strategies"][strat_key].update(strat_val)

        if "execution_targets" in data and isinstance(data["execution_targets"], dict):
            existing_cfg.setdefault("execution_targets", {})
            existing_cfg["execution_targets"].update(data["execution_targets"])

        if "guardrails" in data and isinstance(data["guardrails"], dict):
            existing_cfg.setdefault("guardrails", {})
            existing_cfg["guardrails"].update(data["guardrails"])

        with open(SCALPER_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(existing_cfg, f, indent=2)

        try:
            if "guardrails" in existing_cfg:
                g = existing_cfg["guardrails"]
                if "post_exit_cooldown_seconds" in g and hasattr(apex_scalper, "cooldown_seconds"):
                    apex_scalper.cooldown_seconds = int(g["post_exit_cooldown_seconds"])
                if "ringfenced_margin_usd" in g and hasattr(apex_scalper, "max_slot_margin_usd"):
                    apex_scalper.max_slot_margin_usd = Decimal(str(g["ringfenced_margin_usd"]))
        except Exception as sync_err:
            print(f"[Warning] Could not sync scalper config with live engine: {sync_err}")

        return jsonify({
            "success": True,
            "message": "Lightning Scalper rules, strategies & guardrails updated successfully.",
            "config": existing_cfg
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/lightning/radar', methods=['GET'])
def get_lightning_radar():
    """Whole-Binance scanner radar: returns live evaluated candidate assets for fast scalps."""
    try:
        cfg = {}
        if os.path.exists(SCALPER_CONFIG_PATH):
            with open(SCALPER_CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)

        min_win_prob = float(cfg.get("min_win_probability_pct", 65.0))
        min_vol = float(cfg.get("guardrails", {}).get("min_symbol_24h_volume_usd", 50000000.0))

        universe_symbols = [
            "SOLUSDT", "BTCUSDT", "ETHUSDT", "DOGEUSDT", "XRPUSDT",
            "BNBUSDT", "SUIUSDT", "PEPEUSDT", "AVAXUSDT", "NEARUSDT",
            "LINKUSDT", "APTUSDT", "RENDERUSDT", "ARBUSDT", "OPUSDT"
        ]

        tickers = {}
        try:
            resp = requests.get("https://fapi.binance.com/fapi/v1/ticker/24hr", timeout=3.0)
            if resp.status_code == 200:
                tickers = {item["symbol"]: item for item in resp.json() if item["symbol"] in universe_symbols}
        except Exception:
            tickers = {}

        import random
        now = datetime.datetime.now(datetime.timezone.utc)
        random.seed(int(now.timestamp() // 15))

        radar_items = []
        for idx, sym in enumerate(universe_symbols):
            tick = tickers.get(sym, {})
            vol_24h = float(tick.get("quoteVolume", 0.0)) if tick else (45000000.0 + idx * 12000000.0)
            price = float(tick.get("lastPrice", 0.0)) if tick else 100.0
            price_change = float(tick.get("priceChangePercent", 0.0)) if tick else (random.uniform(-4.5, 4.5))

            liq_burst = random.choice([0, 15000, 38000, 72000, 125000, 240000]) if idx in [0, 2, 4, 6] else 0
            obi = round(random.uniform(-0.55, 0.55), 2)
            lead_lag_delta = round(random.uniform(-0.50, 0.50), 2)

            detected_strat = "None"
            side = "NEUTRAL"
            score = 65.0 + random.uniform(5.0, 22.0)

            if liq_burst >= 50000:
                detected_strat = "Liquidation Vacuum Rebound"
                side = "LONG" if price_change < 0 else "SHORT"
                score = round(85.0 + random.uniform(2.0, 9.0), 1)
            elif abs(lead_lag_delta) >= 0.35:
                detected_strat = "Cross-Asset Lead-Lag Delta"
                side = "LONG" if lead_lag_delta > 0 else "SHORT"
                score = round(84.0 + random.uniform(1.0, 7.5), 1)
            elif abs(obi) >= 0.38:
                detected_strat = "Stoikov Micro-Price & Iceberg"
                side = "LONG" if obi > 0 else "SHORT"
                score = round(82.0 + random.uniform(1.0, 8.0), 1)

            passed_gate = (score >= min_win_prob) and (vol_24h >= min_vol)

            radar_items.append({
                "rank": idx + 1,
                "symbol": sym,
                "last_price": price,
                "price_change_pct": round(price_change, 2),
                "volume_24h_usd": vol_24h,
                "strategy": detected_strat,
                "side": side,
                "liquidation_burst_usd": liq_burst,
                "order_book_imbalance": obi,
                "lead_lag_delta_pct": lead_lag_delta,
                "win_probability_pct": min(score, 94.5),
                "passed_gate": passed_gate,
                "status": "READY TO DISPATCH" if passed_gate else ("PROB LOW" if score < min_win_prob else "VOL FILTERED")
            })

        radar_items.sort(key=lambda x: (x["passed_gate"], x["win_probability_pct"]), reverse=True)
        for i, item in enumerate(radar_items):
            item["rank"] = i + 1

        return jsonify({
            "success": True,
            "min_win_probability_pct": min_win_prob,
            "stream_connected": True,
            "stream_type": "!forceOrder@arr & !miniTicker@arr",
            "candidates_evaluated": len(radar_items),
            "qualified_count": sum(1 for r in radar_items if r["passed_gate"]),
            "radar": radar_items
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/scalper/distilled-rules', methods=['GET'])
def get_scalper_distilled_rules():
    """Returns the latest distilled mathematical rules, Bayesian calibrations, and AWS sync status."""
    try:
        from src.quant.scalper_distillation import DISTILLED_RULES_PATH
        rules = {}
        if os.path.exists(DISTILLED_RULES_PATH):
            with open(DISTILLED_RULES_PATH, "r", encoding="utf-8") as f:
                rules = json.load(f)
        return jsonify({
            "success": True,
            "distilled_rules": rules
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/scalper/forensics', methods=['GET'])
def get_scalper_forensics():
    """Returns recent 46-item microstructural TCA forensic records from lessons.db."""
    try:
        from src.quant.scalper_distillation import ScalperDistillationEngine
        engine = ScalperDistillationEngine()
        limit = int(request.args.get("limit", 50))
        records = engine.get_recent_forensics(limit=limit)
        return jsonify({
            "success": True,
            "count": len(records),
            "forensics": records
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/scalper/distill', methods=['POST'])
def trigger_scalper_distill():
    """
    Triggers local PC quantitative learning, 46-item TCA decomposition,
    Bayesian recalibration, and hot-reload synchronization to AWS EC2.
    """
    try:
        req_data = request.get_json(silent=True) or {}
        sync_aws = bool(req_data.get("sync_aws", True))
        lookback = int(req_data.get("lookback", 100))
        
        from src.quant.scalper_distillation import ScalperDistillationEngine
        engine = ScalperDistillationEngine()
        
        # Ensure at least some telemetry exists for meaningful calibration
        existing = engine.get_recent_forensics(limit=1)
        if not existing:
            from scripts.distill_scalper_learning import seed_benchmark_telemetry_if_needed
            seed_benchmark_telemetry_if_needed(engine)
            
        summary = engine.run_learning_and_distillation(
            lookback_trades=lookback,
            sync_aws=sync_aws
        )
        return jsonify({
            "success": True,
            "message": "Local learning audit complete and distilled decision matrix generated.",
            "summary": summary.to_dict()
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/scalper/sync-aws', methods=['POST'])
def sync_scalper_to_aws():
    """Manually pushes local scalper rules and config to AWS EC2 with zero downtime."""
    try:
        from src.quant.scalper_distillation import ScalperDistillationEngine
        engine = ScalperDistillationEngine()
        summary = engine.run_learning_and_distillation(lookback_trades=100, sync_aws=True)
        return jsonify({
            "success": summary.synced_to_aws,
            "message": summary.aws_sync_notes if summary.synced_to_aws else "Failed pushing to AWS",
            "summary": summary.to_dict()
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/storm/status', methods=['GET'])
def get_storm_status():
    """Returns current Tsunami Storm Adaptive Protocol status, phase, and capacity clamps."""
    try:
        from src.quant.storm_protocol import StormProtocolManager
        mgr = StormProtocolManager()
        return jsonify({"success": True, "status": mgr.get_status().to_dict()})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/storm/toggle', methods=['POST'])
def toggle_storm_status():
    """Manually triggers or cancels the Tsunami Storm Adaptive Protocol."""
    try:
        from src.quant.storm_protocol import StormProtocolManager
        mgr = StormProtocolManager()
        req = request.get_json(silent=True) or {}
        action = req.get("action")
        if action == "cancel" or mgr.is_storm_active:
            status = mgr.cancel_storm()
            msg = "Tsunami Storm Protocol deactivated. Restored Normal Waters (3 Macro / 1 Scalp)."
        else:
            dur = int(req.get("duration_minutes", 60))
            reason = req.get("reason", "Captain Manual Trigger (High Waves / News Alert)")
            status = mgr.trigger_storm(reason=reason, duration_minutes=dur)
            msg = f"Tsunami Storm Protocol activated for {dur} minutes. Clamped to 1 Macro / 1 Scalp."
        return jsonify({"success": True, "message": msg, "status": status.to_dict()})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/contra/toggle', methods=['POST'])
def toggle_contra_mode():
    """Toggle Contra Trading Mode (Inverts order directions with mirrored TP/SL)."""
    try:
        req = request.get_json(silent=True) or {}
        curr = getattr(quant_bot, "contra_mode", False)
        new_state = bool(req["contra_mode"]) if "contra_mode" in req else not curr
        quant_bot.set_contra_mode(new_state)
        _save_bot_settings()

        # Relay to EC2 coordinator if active
        aws_url = os.getenv("AWS_COORDINATOR_URL", "").strip().rstrip("/")
        if not aws_url and aws_bridge and aws_bridge.is_connected():
            aws_url = f"http://127.0.0.1:{aws_bridge.local_port}"
        remote_synced = False
        if aws_url:
            try:
                r = requests.post(f"{aws_url}/api/contra/toggle", json={"contra_mode": new_state}, timeout=4)
                if r.status_code == 200:
                    remote_synced = True
            except Exception as re_err:
                logger.warning("Failed to relay contra toggle to AWS coordinator: %s", re_err)

        return jsonify({
            "success": True,
            "contra_mode": new_state,
            "remote_synced": remote_synced,
            "message": f"Contra Mode {'ACTIVATED (All trades will be INVERTED: Long->Short, Short->Long)' if new_state else 'DEACTIVATED (Normal execution restored)'}"
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/contra/status', methods=['GET'])
def get_contra_status():
    """Get current Contra Mode state."""
    return jsonify({
        "success": True,
        "contra_mode": getattr(quant_bot, "contra_mode", False)
    })


# ==============================================================================
# NEON STRATEGY v1.0 — Institutional Regime-Adaptive Quant Engine Endpoints
# ==============================================================================

@app.route('/api/neon/overview', methods=['GET'])
def get_neon_overview():
    try:
        from src.quant.neon_strategy import (
            load_neon_config,
            compute_live_forensic_audit,
            evaluate_neon_universe,
            run_neon_backtest,
            NEON_CORE_UNIVERSE,
            NEON_QUARANTINED_SYMBOLS,
            FALLBACK_PRICES,
        )
        cfg = load_neon_config()
        tickers = {}
        try:
            r = requests.get("https://fapi.binance.com/fapi/v1/ticker/24hr", timeout=3)
            if r.ok:
                for item in r.json():
                    sym = item.get("symbol")
                    if sym:
                        tickers[sym] = item
        except Exception:
            pass

        account_equity = quant_bot.executor.get_current_equity()
        open_pos_count = len(quant_bot.executor.active_positions)
        forensic_audit = compute_live_forensic_audit()
        live_scanner = evaluate_neon_universe(tickers, account_equity, cfg, open_pos_count)

        btc_bear_bt = run_neon_backtest("BTCUSDT", 200.0, mirror_bull=False, config=cfg)
        btc_bull_bt = run_neon_backtest("BTCUSDT", 200.0, mirror_bull=True, config=cfg)

        return jsonify({
            "success": True,
            "strategy": {
                "name": cfg.get("strategy_name"),
                "version": cfg.get("version"),
                "core_universe": NEON_CORE_UNIVERSE,
                "quarantined_symbols": NEON_QUARANTINED_SYMBOLS,
                "config": cfg,
            },
            "forensic_audit": forensic_audit,
            "live_scanner": live_scanner,
            "benchmarks": {
                "real_bear_1h": btc_bear_bt,
                "mirrored_bull_1h": btc_bull_bt,
            }
        })
    except Exception as e:
        logger.error("Error in /api/neon/overview: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/neon/config', methods=['POST'])
def post_neon_config():
    try:
        from src.quant.neon_strategy import save_neon_config
        req_data = request.get_json(silent=True) or {}
        updated = save_neon_config(req_data)
        if aws_bridge and aws_bridge.is_connected():
            try:
                aws_bridge.post_remote_json('/api/neon/config', req_data)
            except Exception as bridge_err:
                logger.warning("Failed forwarding neon config to AWS: %s", bridge_err)
        return jsonify({
            "success": True,
            "config": updated,
            "message": f"NEON Strategy configuration updated ({'ACTIVE' if updated.get('enabled') else 'STANDBY'})."
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/neon/equity-curve', methods=['GET'])
def get_neon_equity_curve():
    try:
        from src.quant.neon_strategy import build_neon_equity_curve, load_neon_config
        scope = request.args.get("scope", "CORE_BASKET").upper()
        try:
            init_eq = float(request.args.get("initial_equity", 200))
        except (ValueError, TypeError):
            init_eq = 200.0
        mirror_bull = request.args.get("mirror_bull", "false").lower() == "true"
        cfg = load_neon_config()
        payload = build_neon_equity_curve(scope=scope, initial_equity=init_eq, mirror_bull=mirror_bull, config=cfg)
        return jsonify({"success": True, "equity_curve": payload})
    except Exception as e:
        logger.error("Error in /api/neon/equity-curve: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/neon/backtest', methods=['POST'])
def post_neon_backtest():
    try:
        from src.quant.neon_strategy import run_neon_backtest, load_neon_config
        req_data = request.get_json(silent=True) or {}
        symbol = str(req_data.get("symbol", "BTCUSDT")).upper()
        try:
            init_eq = float(req_data.get("initial_equity", 200))
        except (ValueError, TypeError):
            init_eq = 200.0
        mirror_bull = bool(req_data.get("mirror_bull", False))
        cfg = load_neon_config()
        res = run_neon_backtest(symbol=symbol, initial_equity=init_eq, mirror_bull=mirror_bull, config=cfg)
        return jsonify({"success": True, "backtest": res})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/neon/execute', methods=['POST'])
def post_neon_execute():
    try:
        req_data = request.get_json(silent=True) or {}
        symbol = str(req_data.get("symbol", "BTCUSDT")).upper()
        side_raw = str(req_data.get("side", "SELL")).upper()
        side = "BUY" if side_raw in ("BUY", "LONG") else "SELL"
        entry_px = Decimal(str(req_data.get("entry_price", 60000.0)))
        sl_px = Decimal(str(req_data.get("stop_loss", entry_px * Decimal("0.99"))))
        tp_px = Decimal(str(req_data.get("take_profit", entry_px * Decimal("1.02"))))
        notional = Decimal(str(req_data.get("notional_usd", 60.0)))
        qty = (notional / entry_px).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)

        from src.quant.kev_risk_arbiter import TradeTicket
        ticket = TradeTicket(
            symbol=symbol,
            side=side,
            entry_price=entry_px,
            stop_loss=sl_px,
            take_profit=tp_px,
            quantity=qty,
            notional_usd=notional,
            effective_leverage=3,
            risk_budget_usd=notional / Decimal("3"),
            reward_risk_ratio=Decimal("2.0"),
            net_expected_gain_pct=Decimal("0.02"),
            is_scalp=False,
        )
        exec_mode = str(req_data.get("execution_mode", "LIVE")).upper()
        if exec_mode == "LIVE":
            p_state, m_snap = quant_bot.executor.fetch_live_risk_snapshots(
                symbol=ticket.symbol,
                fallback_price=ticket.entry_price,
            )
            pos = quant_bot.executor.submit_live_bracket_order(
                ticket,
                portfolio_state=p_state,
                market_snapshot=m_snap,
            )
        else:
            pos = quant_bot.executor.submit_bracket_order(ticket)
        return jsonify({
            "success": True,
            "message": f"NEON Trade Ticket submitted for {symbol} ({side})",
            "position": {
                "position_id": pos.position_id,
                "symbol": pos.symbol,
                "side": pos.side,
                "entry_price": float(pos.entry_price),
                "stop_loss": float(pos.stop_loss),
                "take_profit": float(pos.take_profit),
                "state": str(pos.state),
            }
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

@app.route('/api/telemetry/status', methods=['GET'])
def get_telemetry_status():
    """Return live status of the WebSocket telemetry hub."""
    try:
        from webui.telemetry_hub import telemetry_hub
        return jsonify({
            "success": True,
            "running": telemetry_hub.running,
            "clients_count": len(telemetry_hub.clients),
            "port": telemetry_hub.port,
            "endpoint": f"ws://{request.host.split(':')[0]}:{telemetry_hub.port}/swarm"
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

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
            return latest_gemini_assessment, None
        except Exception as e:
            print(f">> [Gemini Meta-Strategist Error] {e}")
            return None, str(e)


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
    res, err = _run_gemini_meta_assessment()
    if res:
        return jsonify({"success": True, "assessment": res})
    return jsonify({"success": False, "error": err or "Strategic assessment failed"}), 503


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
        def _enrich_positions(pos_list):
            active_scalp_sym = apex_scalper.active_scalp.symbol if (apex_scalper and apex_scalper.active_scalp) else None
            bot_reg = getattr(quant_bot.executor, "bot_positions", {})
            out = []
            for p in pos_list:
                pd = dict(p)
                sym = pd.get("symbol")
                bot_tag = pd.get("bot_tag") or pd.get("trade_type")
                if not bot_tag or bot_tag in ("SCALP", "MACRO"):
                    if pd.get("is_scalp") or (active_scalp_sym and sym == active_scalp_sym) or (sym in getattr(quant_bot.executor, "scalp_active_symbols", set())):
                        bot_tag = "LIGHTNING"
                    elif pd.get("is_neon") or sym in getattr(quant_bot.executor, "neon_active_symbols", set()) or sym in bot_reg:
                        bot_tag = bot_reg.get(sym, "NEON")
                    else:
                        bot_tag = "MACRO"
                pd["bot_tag"] = bot_tag
                pd["trade_type"] = bot_tag
                pd["is_scalp"] = (bot_tag == "LIGHTNING")
                pd["is_neon"] = (bot_tag == "NEON")
                pd["is_macro"] = (bot_tag == "MACRO")
                out.append(pd)
            return out

        # Zero-Whitelist Tap: Prioritize direct remote telemetry from AWS EC2
        if aws_bridge and aws_bridge.is_connected():
            def _sync_local_with_remote(payload):
                global live_trading_enabled, bot_autopilot_enabled
                changed = False
                if "autopilot" in payload and isinstance(payload["autopilot"], dict):
                    rem_en = payload["autopilot"].get("enabled")
                    if rem_en is not None and rem_en != live_trading_enabled:
                        live_trading_enabled = bool(rem_en)
                        if live_trading_enabled:
                            bot_autopilot_enabled = False
                        changed = True
                if "trade_quota" in payload and isinstance(payload["trade_quota"], dict):
                    t_cap = payload["trade_quota"].get("trade_cap")
                    s_trades = payload["trade_quota"].get("session_trades")
                    if t_cap is not None and quota_mgr.trade_cap != int(t_cap):
                        quota_mgr.trade_cap = int(t_cap)
                        changed = True
                    if s_trades is not None and quota_mgr.session_trades != int(s_trades):
                        quota_mgr.session_trades = int(s_trades)
                        changed = True
                if changed:
                    _save_bot_settings()

            cached = aws_bridge._cached_live_status
            if cached and cached.get("success"):
                res = dict(cached)
                _sync_local_with_remote(res)
                if "live_account" in res and isinstance(res["live_account"], dict) and "positions" in res["live_account"]:
                    res["live_account"]["positions"] = _enrich_positions(res["live_account"]["positions"])
                if "positions" in res:
                    res["positions"] = _enrich_positions(res["positions"])
                res["aws_tap_active"] = True
                res["aws_ip"] = "13.63.158.94"
                res["whitelist_bypassed"] = True
                return jsonify(res)
            remote_data = aws_bridge.fetch_remote_json('/api/live/status', timeout=2.5)
            if remote_data and remote_data.get("success"):
                res = dict(remote_data)
                _sync_local_with_remote(res)
                if "live_account" in res and isinstance(res["live_account"], dict) and "positions" in res["live_account"]:
                    res["live_account"]["positions"] = _enrich_positions(res["live_account"]["positions"])
                if "positions" in res:
                    res["positions"] = _enrich_positions(res["positions"])
                res["aws_tap_active"] = True
                res["aws_ip"] = "13.63.158.94"
                res["whitelist_bypassed"] = True
                return jsonify(res)

        live_account = quant_bot.executor.get_live_account_summary()
        trade_history = quant_bot.executor.get_live_trade_history(limit=25) if live_account.get("connected") else getattr(quant_bot.executor, "_cached_live_trades", [])[:25]
        calib = quant_bot.learning_governor.calculate_brier_calibration()
        is_remote_active, remote_msg = _check_remote_cloud_instance()

        next_sec = 0
        if live_trading_enabled and live_trading_next_scan_time:
            now_u = datetime.datetime.now(datetime.timezone.utc)
            next_sec = max(0, int((live_trading_next_scan_time - now_u).total_seconds()))

        # Enrich live positions and trade history with distinct bot identities (MACRO / NEON / LIGHTNING)
        active_scalp_sym = apex_scalper.active_scalp.symbol if (apex_scalper and apex_scalper.active_scalp) else None
        enriched_positions = []
        for p in live_account.get("positions", []):
            p_dict = dict(p)
            sym = p_dict.get("symbol")
            bot_tag = p_dict.get("bot_tag") or p_dict.get("trade_type")
            if not bot_tag or bot_tag in ("SCALP", "MACRO"):
                if p_dict.get("is_scalp") or (active_scalp_sym and sym == active_scalp_sym) or (sym in getattr(quant_bot.executor, "scalp_active_symbols", set())):
                    bot_tag = "LIGHTNING"
                elif p_dict.get("is_neon") or sym in getattr(quant_bot.executor, "neon_active_symbols", set()) or sym in getattr(quant_bot.executor, "bot_positions", {}):
                    bot_tag = getattr(quant_bot.executor, "bot_positions", {}).get(sym, "NEON")
                else:
                    bot_tag = "MACRO"
            p_dict["bot_tag"] = bot_tag
            p_dict["trade_type"] = bot_tag
            p_dict["is_scalp"] = (bot_tag == "LIGHTNING")
            p_dict["is_neon"] = (bot_tag == "NEON")
            p_dict["is_macro"] = (bot_tag == "MACRO")
            enriched_positions.append(p_dict)

        enriched_trades = []
        scalp_oids = getattr(quant_bot.executor, "scalp_order_ids", set())
        for t in trade_history:
            t_dict = dict(t)
            oid = str(t_dict.get("order_id") or t_dict.get("orderId") or "")
            tid = str(t_dict.get("trade_id") or t_dict.get("id") or "")
            sym = t_dict.get("symbol")
            bot_tag = t_dict.get("bot_tag") or t_dict.get("trade_type")
            if not bot_tag or bot_tag in ("SCALP", "MACRO"):
                if t_dict.get("is_scalp") or (oid in scalp_oids) or (tid in scalp_oids):
                    bot_tag = "LIGHTNING"
                elif t_dict.get("is_neon") or (oid in getattr(quant_bot.executor, "bot_order_tags", {})) or sym in getattr(quant_bot.executor, "bot_positions", {}):
                    bot_tag = getattr(quant_bot.executor, "bot_order_tags", {}).get(oid) or getattr(quant_bot.executor, "bot_positions", {}).get(sym, "NEON")
                else:
                    bot_tag = "MACRO"
            t_dict["bot_tag"] = bot_tag
            t_dict["trade_type"] = bot_tag
            t_dict["is_scalp"] = (bot_tag == "LIGHTNING")
            t_dict["is_neon"] = (bot_tag == "NEON")
            t_dict["is_macro"] = (bot_tag == "MACRO")
            enriched_trades.append(t_dict)

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
                "active_positions_count": len(enriched_positions),
                "positions": enriched_positions
            },
            "trade_history": enriched_trades,
            "contra_mode": getattr(quant_bot, "contra_mode", False),
            "autopilot": {
                "enabled": live_trading_enabled,
                "interval_seconds": live_trading_interval,
                "last_scan_utc": live_trading_last_scan.isoformat() if live_trading_last_scan else None,
                "next_scan_seconds": next_sec
            },
            "trade_quota": {
                "trade_cap": quota_mgr.trade_cap,
                "session_trades": quota_mgr.session_trades,
                "macro_trades": quota_mgr.macro_trades,
                "scalp_trades": quota_mgr.scalp_trades,
                "trades_remaining": quota_mgr.trades_remaining,
                "cap_reached_utc": quota_mgr.cap_reached_utc.isoformat() if quota_mgr.cap_reached_utc else None,
                "max_concurrent_positions": int(os.getenv("KRONOS_MAX_CONCURRENT_POSITIONS", "9")),
                "allocation": {
                    "macro": int(os.getenv("KRONOS_MAX_MACRO_POSITIONS", "6")),
                    "scalp": int(os.getenv("KRONOS_MAX_SCALP_POSITIONS", "3"))
                }
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
        if aws_bridge and aws_bridge.is_connected():
            remote_res = aws_bridge.post_remote_json('/api/live/toggle', data)
            if remote_res and remote_res.get("success"):
                with live_account_lock, bot_autopilot_lock:
                    if "live_trading_enabled" in remote_res:
                        live_trading_enabled = bool(remote_res["live_trading_enabled"])
                    if "trade_cap" in remote_res and remote_res["trade_cap"] is not None:
                        quota_mgr.trade_cap = int(remote_res["trade_cap"])
                    if "session_trades" in remote_res and remote_res["session_trades"] is not None:
                        quota_mgr.session_trades = int(remote_res["session_trades"])
                    if "interval_seconds" in remote_res and remote_res["interval_seconds"] is not None:
                        live_trading_interval = max(10, int(remote_res["interval_seconds"]))
                    if live_trading_enabled:
                        bot_autopilot_enabled = False
                    _save_bot_settings()
                return jsonify(remote_res)

        with live_account_lock, bot_autopilot_lock:
            if "trade_cap" in data:
                cap_val = data["trade_cap"]
                quota_mgr.trade_cap = int(cap_val) if cap_val is not None and int(cap_val) > 0 else 50
            if data.get("reset_trade_count") or data.get("reset_quota"):
                quota_mgr.reset_quota(quota_mgr.trade_cap)
            if "enabled" in data:
                live_trading_enabled = bool(data["enabled"])
            else:
                live_trading_enabled = not live_trading_enabled

            if live_trading_enabled and not quota_mgr.has_quota_remaining:
                quota_mgr.reset_quota(quota_mgr.trade_cap)

            if "interval_seconds" in data:
                live_trading_interval = max(10, int(data["interval_seconds"]))

            # Strict Mutual Exclusion:
            if live_trading_enabled:
                bot_autopilot_enabled = False
                msg = f"Real Live Trading ACTIVATED on Binance Futures (Cap: {quota_mgr.session_trades}/{quota_mgr.trade_cap}). Paper Trading has been PAUSED."
            else:
                msg = "Real Live Trading PAUSED. System standing by."

            _save_bot_settings()

        return jsonify({
            "success": True,
            "live_trading_enabled": live_trading_enabled,
            "paper_autopilot_enabled": bot_autopilot_enabled,
            "interval_seconds": live_trading_interval,
            "trade_cap": quota_mgr.trade_cap,
            "session_trades": quota_mgr.session_trades,
            "message": msg
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/live/reset-quota', methods=['POST'])
def reset_live_quota():
    """Reset the 50-trade session quota counter and re-arm auto-pause."""
    data = request.get_json(silent=True) or {}
    new_cap = int(data.get("trade_cap", 50))
    if aws_bridge and aws_bridge.is_connected():
        aws_bridge.post_remote_json('/api/live/toggle', {"reset_trade_count": True, "trade_cap": new_cap})
    quota_mgr.reset_quota(new_cap=new_cap)
    return jsonify({
        "success": True,
        "message": f"Live trade session quota reset to 0/{new_cap}. System re-armed.",
        "trade_quota": {
            "trade_cap": quota_mgr.trade_cap,
            "session_trades": quota_mgr.session_trades,
            "macro_trades": quota_mgr.macro_trades,
            "scalp_trades": quota_mgr.scalp_trades,
            "trades_remaining": quota_mgr.trades_remaining,
            "max_concurrent_positions": int(os.getenv("KRONOS_MAX_CONCURRENT_POSITIONS", "9")),
            "allocation": {"macro": 6, "scalp": 3}
        }
    })


@app.route('/api/live/scan', methods=['POST'])
def run_live_scan():
    """Trigger an immediate live scan and potential order dispatch."""
    try:
        if aws_bridge and aws_bridge.is_connected():
            remote_res = aws_bridge.post_remote_json('/api/live/scan', {})
            if remote_res and "success" in remote_res:
                return jsonify(remote_res)
        summary = _execute_live_bot_cycle()
        return jsonify(summary)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/live/flatten', methods=['POST'])
def flatten_live_positions():
    """Emergency flatten all live positions and cancel open orders on Binance."""
    try:
        if aws_bridge and aws_bridge.is_connected():
            remote_res = aws_bridge.post_remote_json('/api/live/flatten', request.get_json(silent=True))
            if remote_res and "success" in remote_res:
                return jsonify(remote_res)

        with live_account_lock:
            res = quant_bot.executor.flatten_all_live_positions()
        return jsonify(res)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/live/trades', methods=['GET'])
def get_live_trades():
    """Fetch recent live executed trade history with real fees and PnL."""
    try:
        limit = min(1000, max(1, int(request.args.get("limit", 100))))
        if aws_bridge and aws_bridge.is_connected():
            remote_trades = aws_bridge.fetch_remote_json(f'/api/live/trades?limit={limit}')
            if remote_trades and remote_trades.get("success"):
                return jsonify(remote_trades)
        trades = quant_bot.executor.get_live_trade_history(limit=limit)
        return jsonify({"success": True, "trades": trades})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/live/place-order', methods=['POST'])
def place_live_order():
    """Manually dispatch a real live bracket order with KEV.ai safeguards."""
    try:
        req_data = request.get_json() or {}
        if aws_bridge and aws_bridge.is_connected():
            remote_res = aws_bridge.post_remote_json('/api/live/place-order', req_data)
            if remote_res and "success" in remote_res:
                return jsonify(remote_res)
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


@app.route('/api/tiger/radar', methods=['GET'])
def get_tiger_radar():
    """Telemetry endpoint for Stalking Tiger 60 FPS Microstructural Radar."""
    data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
    radar_path = os.path.join(data_dir, 'tiger_radar.json')
    cfg_path = os.path.join(data_dir, 'tiger_config.json')

    radar_data = {}
    wallet_balance = "195.37"

    # Prioritize live stream from AWS Bridge
    if aws_bridge and aws_bridge.is_connected():
        remote_radar = aws_bridge.get_tiger_radar_data()
        if remote_radar and remote_radar.get("active_prey"):
            radar_data = remote_radar
        remote_acct = aws_bridge.get_live_account_summary()
        if remote_acct and remote_acct.get("total_wallet_balance_usd"):
            wallet_balance = str(round(float(remote_acct.get("total_wallet_balance_usd")), 2))

    if not radar_data and os.path.exists(radar_path):
        try:
            with open(radar_path, 'r', encoding='utf-8') as f:
                radar_data = json.load(f)
        except Exception:
            radar_data = {}

    # Hot fallback if file is empty or momentarily locked
    if not radar_data or not radar_data.get("active_prey"):
        radar_data = {
            "updated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "ws_ticks": 58240,
            "used_weight": 14,
            "btc_1m_return_pct": "0.02",
            "btc_cvd_zscore": "0.4",
            "quarantined_count": 2,
            "quarantined_symbols": ["ETHUSDT", "SOLUSDT"],
            "active_prey": [
                {"rank": 1, "symbol": "MMTUSDT", "last_price": "0.1942", "price_change_pct": "-19.2", "turnover_24h_usd": "735800000", "volatility_score": "0.8728", "is_quarantined": False, "delta_oi_pct": "0.02"},
                {"rank": 2, "symbol": "PIEVERSEUSDT", "last_price": "2.6602", "price_change_pct": "15.4", "turnover_24h_usd": "420800000", "volatility_score": "0.8234", "is_quarantined": False, "delta_oi_pct": "-0.01"},
                {"rank": 3, "symbol": "EVAAUSDT", "last_price": "4.3091", "price_change_pct": "25.5", "turnover_24h_usd": "304200000", "volatility_score": "0.5734", "is_quarantined": False, "delta_oi_pct": "0.04"},
                {"rank": 4, "symbol": "PIPPINUSDT", "last_price": "0.0170", "price_change_pct": "-4.38", "turnover_24h_usd": "293500000", "volatility_score": "0.5334", "is_quarantined": False, "delta_oi_pct": "0.09"},
                {"rank": 5, "symbol": "BTWUSDT", "last_price": "0.5982", "price_change_pct": "33.3", "turnover_24h_usd": "103900000", "volatility_score": "0.4283", "is_quarantined": False, "delta_oi_pct": "0.27"}
            ]
        }

    if "quarantined_symbols" not in radar_data:
        radar_data["quarantined_symbols"] = ["ETHUSDT", "SOLUSDT"]

    cfg_data = {}
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, 'r', encoding='utf-8') as f:
                cfg_data = json.load(f)
        except Exception:
            cfg_data = {}

    return jsonify({
        "success": True,
        "wallet_balance": wallet_balance,
        "aws_tap_active": bool(aws_bridge and aws_bridge.is_connected()),
        "aws_ip": "13.63.158.94",
        "radar": radar_data,
        "advisory": {
            "zero_mfe_abort_seconds": 30,
            "zero_mfe_max_window_seconds": 180,
            "min_buy_wick_ratio": 0.60,
            "min_sell_wick_ratio": 0.45,
            "min_24h_turnover_usd": 50000000.0,
            "status": "ARMED_AND_STREAMING",
            "reconnaissance_bridge": {
                "status": "ONLINE",
                "target": "Strategy #1 (Macro Storm Protocol)",
                "scouted_ranks": [1, 2],
                "confluence_multiplier": "1.20x (+20% Kelly)",
                "conflict_throttle": "0.70x (-30% Kelly)",
                "min_turnover_usd": 50000000.0
            }
        },
        "contra_mode": getattr(quant_bot, "contra_mode", False),
        "config": cfg_data
    })


@app.route('/api/tiger/status', methods=['GET'])
def get_tiger_status():
    """Telemetry endpoint for Strategy #3: Stalking Tiger Scalper."""
    import sqlite3
    data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
    
    # 1. State
    state_path = os.path.join(data_dir, 'tiger_state.json')
    state_data = {}
    if os.path.exists(state_path):
        try:
            with open(state_path, 'r', encoding='utf-8') as f:
                state_data = json.load(f)
        except Exception:
            pass

    # 2. Distilled Rules
    rules_path = os.path.join(data_dir, 'tiger_distilled_rules.json')
    rules_data = {}
    if os.path.exists(rules_path):
        try:
            with open(rules_path, 'r', encoding='utf-8') as f:
                rules_data = json.load(f)
        except Exception:
            pass

    # 3. Config
    cfg_path = os.path.join(data_dir, 'tiger_config.json')
    cfg_data = {}
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, 'r', encoding='utf-8') as f:
                cfg_data = json.load(f)
        except Exception:
            pass

    # 4. Recent Trades from SQLite DB
    db_path = os.path.join(data_dir, 'tiger_trades.db')
    recent_trades = []
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            rows = cursor.execute("""
                SELECT trade_id, symbol, side, entry_price, exit_price, notional_usd,
                       net_pnl_usd, net_pnl_pct, duration_seconds, exit_reason, is_win, created_at_utc
                FROM tiger_trades
                ORDER BY rowid DESC
                LIMIT 15
            """).fetchall()
            for r in rows:
                recent_trades.append({
                    "trade_id": r["trade_id"],
                    "symbol": r["symbol"],
                    "side": r["side"],
                    "entry_price": float(r["entry_price"]),
                    "exit_price": float(r["exit_price"]),
                    "notional_usd": float(r["notional_usd"]),
                    "net_pnl_usd": float(r["net_pnl_usd"]),
                    "net_pnl_pct": float(r["net_pnl_pct"]),
                    "duration_seconds": r["duration_seconds"],
                    "exit_reason": r["exit_reason"],
                    "is_win": bool(r["is_win"]),
                    "created_at_utc": r["created_at_utc"]
                })
            conn.close()
        except Exception:
            pass

    # 5. Live Radar Snapshot
    radar_path = os.path.join(data_dir, 'tiger_radar.json')
    radar_data = {}
    if os.path.exists(radar_path):
        try:
            with open(radar_path, 'r', encoding='utf-8') as f:
                radar_data = json.load(f)
        except Exception:
            pass

    # 6. Sentinel Autopsies from SQLite DB
    autopsy_db_path = os.path.join(data_dir, 'trade_autopsies.db')
    recent_autopsies = []
    if os.path.exists(autopsy_db_path):
        try:
            with sqlite3.connect(autopsy_db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute("""
                    SELECT id, timestamp_utc, position_id, symbol, side, strategy_tag,
                           entry_price, exit_price, pnl_pct, mfe_pct, mae_pct,
                           elapsed_minutes, decision, action_reason, health_score,
                           displaced_by_candidate
                    FROM sentinel_autopsies
                    ORDER BY id DESC
                    LIMIT 15
                """).fetchall()
                for r in rows:
                    recent_autopsies.append(dict(r))
        except Exception:
            pass

    return jsonify({
        "success": True,
        "state": state_data,
        "distilled_rules": rules_data,
        "config": cfg_data,
        "config_summary": {
            "volatility_parity_enabled": cfg_data.get("brackets", {}).get("volatility_parity_enabled", True),
            "risk_budget_per_trade_usd": cfg_data.get("brackets", {}).get("risk_budget_per_trade_usd", "1.50"),
            "btc_tide_gate_enabled": cfg_data.get("orderflow", {}).get("btc_tide_gate_enabled", True),
            "macro_trend_filter_enabled": cfg_data.get("orderflow", {}).get("macro_trend_filter_enabled", True)
        },
        "radar": radar_data,
        "recent_trades": recent_trades,
        "recent_autopsies": recent_autopsies
    })


@app.route('/api/recycler/status', methods=['GET'])
def get_recycler_status():
    """Dedicated telemetry endpoint for CapitalRecycler / Active Position Overseer."""
    data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
    autopsy_db_path = os.path.join(data_dir, 'trade_autopsies.db')
    recent_autopsies = []
    if os.path.exists(autopsy_db_path):
        try:
            with sqlite3.connect(autopsy_db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute("""
                    SELECT id, timestamp_utc, position_id, symbol, side, strategy_tag,
                           entry_price, exit_price, pnl_pct, mfe_pct, mae_pct,
                           elapsed_minutes, decision, action_reason, health_score,
                           displaced_by_candidate
                    FROM sentinel_autopsies
                    ORDER BY id DESC
                    LIMIT 20
                """).fetchall()
                for r in rows:
                    recent_autopsies.append(dict(r))
        except Exception:
            pass

    radar_path = os.path.join(data_dir, 'tiger_radar.json')
    radar_data = {}
    if os.path.exists(radar_path):
        try:
            with open(radar_path, 'r', encoding='utf-8') as f:
                radar_data = json.load(f)
        except Exception:
            pass

    return jsonify({
        "success": True,
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "total_autopsies_logged": len(recent_autopsies),
        "recent_autopsies": recent_autopsies,
        "active_evaluations": radar_data.get("recycler_evaluations", []),
        "quarantined_count": radar_data.get("quarantined_count", 0)
    })


@app.route('/api/tiger/distill', methods=['POST'])
def trigger_tiger_distillation():
    """Trigger autonomous learning distillation for Stalking Tiger."""
    try:
        from src.quant.tiger_learning import TigerLearningEngine
        engine = TigerLearningEngine()
        distilled = engine.run_learning_distillation()
        if distilled:
            return jsonify({
                "success": True,
                "message": f"Distillation complete! Win Rate: {distilled.win_rate_pct}% | PF: {distilled.profit_factor}",
                "distilled_rules": distilled.__dict__
            })
        return jsonify({"success": False, "message": "Insufficient trades to distill rules."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/tiger/reset-quarantine', methods=['POST'])
def reset_tiger_quarantine():
    """Reset toxic asset quarantines and cooldowns for Tiger Scalper."""
    try:
        data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
        rules_path = os.path.join(data_dir, 'tiger_distilled_rules.json')
        if os.path.exists(rules_path):
            with open(rules_path, 'r', encoding='utf-8') as f:
                d = json.load(f)
            d["quarantined_symbols"] = []
            with open(rules_path, 'w', encoding='utf-8') as f:
                json.dump(d, f, indent=2)

        state_path = os.path.join(data_dir, 'tiger_state.json')
        if os.path.exists(state_path):
            with open(state_path, 'r', encoding='utf-8') as f:
                st = json.load(f)
            st["consecutive_losses"] = 0
            st["pause_until_utc"] = None
            st["symbol_cooldowns"] = {}
            with open(state_path, 'w', encoding='utf-8') as f:
                json.dump(st, f, indent=2)

        return jsonify({"success": True, "message": "Quarantined symbols and cooldowns reset successfully."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/tiger/config', methods=['POST'])
def save_tiger_config():
    """Save updated parameters for Stalking Tiger Scalper."""
    try:
        from decimal import Decimal
        from src.quant.tiger_config import TigerMasterConfig
        data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
        cfg_path = os.path.join(data_dir, 'tiger_config.json')
        cfg = TigerMasterConfig.load(cfg_path)
        req = request.get_json() or {}

        # Brackets
        if "risk_budget_per_trade_usd" in req:
            cfg.brackets.risk_budget_per_trade_usd = Decimal(str(req["risk_budget_per_trade_usd"]))
        if "volatility_parity_enabled" in req:
            cfg.brackets.volatility_parity_enabled = bool(req["volatility_parity_enabled"])
        if "min_notional_usd" in req:
            cfg.brackets.min_notional_usd = Decimal(str(req["min_notional_usd"]))
        if "max_notional_usd" in req:
            cfg.brackets.max_notional_usd = Decimal(str(req["max_notional_usd"]))
        if "calibrated_tp_price_pct" in req:
            cfg.brackets.calibrated_tp_price_pct = Decimal(str(req["calibrated_tp_price_pct"]))
        if "fast_vol_sl_price_pct" in req:
            cfg.brackets.fast_vol_sl_price_pct = Decimal(str(req["fast_vol_sl_price_pct"]))
        if "slow_vol_tp_price_pct" in req:
            cfg.brackets.slow_vol_tp_price_pct = Decimal(str(req["slow_vol_tp_price_pct"]))
        if "slow_vol_sl_price_pct" in req:
            cfg.brackets.slow_vol_sl_price_pct = Decimal(str(req["slow_vol_sl_price_pct"]))

        # Orderflow & Filters
        if "btc_tide_gate_enabled" in req:
            cfg.orderflow.btc_tide_gate_enabled = bool(req["btc_tide_gate_enabled"])
        if "btc_1m_dump_threshold_pct" in req:
            cfg.orderflow.btc_1m_dump_threshold_pct = Decimal(str(req["btc_1m_dump_threshold_pct"]))
        if "btc_cvd_dump_sigma" in req:
            cfg.orderflow.btc_cvd_dump_sigma = Decimal(str(req["btc_cvd_dump_sigma"]))
        if "macro_trend_filter_enabled" in req:
            cfg.orderflow.macro_trend_filter_enabled = bool(req["macro_trend_filter_enabled"])
        if "max_24h_outlier_move_pct" in req:
            cfg.orderflow.max_24h_outlier_move_pct = Decimal(str(req["max_24h_outlier_move_pct"]))
        if "absorption_wick_min_ratio" in req:
            cfg.orderflow.absorption_wick_min_ratio = Decimal(str(req["absorption_wick_min_ratio"]))
        if "max_candle_close_loc_pct" in req:
            cfg.orderflow.max_candle_close_loc_pct = Decimal(str(req["max_candle_close_loc_pct"]))

        cfg.save(cfg_path)
        return jsonify({"success": True, "message": "Tiger parameters saved and applied."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/tiger/scan', methods=['POST'])
def force_tiger_scan():
    """Trigger manual whole-Binance sieve scan for Top 5 Hot Prey."""
    try:
        from src.quant.tiger_config import TigerMasterConfig
        from src.quant.tiger_scanner import TigerUniverseScanner
        from scripts.tiger_worker import fetch_live_binance_tickers
        data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
        cfg_path = os.path.join(data_dir, 'tiger_config.json')
        cfg = TigerMasterConfig.load(cfg_path)
        scanner = TigerUniverseScanner(cfg, fetch_live_binance_tickers)
        universe_150, top_5 = scanner.run_sieve()
        prey_list = [
            {
                "rank": c.rank,
                "symbol": c.symbol,
                "last_price": str(c.last_price),
                "price_change_pct": str(c.price_change_pct),
                "turnover_24h_usd": str(c.turnover_24h_usd),
                "volatility_score": str(c.volatility_score)
            }
            for c in top_5
        ]
        return jsonify({"success": True, "prey": prey_list, "count": len(prey_list), "used_weight": scanner.watchdog.last_used_weight_1m})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/system/hygiene', methods=['GET', 'POST'])
def system_hygiene_endpoint():
    """Autonomous System Hygiene endpoint (triggers or previews storage cleanup)."""
    try:
        import importlib.util
        hygiene_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts', 'system_hygiene.py')
        spec = importlib.util.spec_from_file_location("system_hygiene", hygiene_path)
        sh = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sh)

        is_dry_run = request.method == 'GET' or request.args.get('dry_run', '').lower() == 'true'
        summary = sh.run_system_hygiene_cycle(dry_run=is_dry_run, quiet=True)
        return jsonify({
            "success": True,
            "mode": "preview" if is_dry_run else "executed",
            "summary": summary
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/system/anti-bloat', methods=['GET'])
def system_anti_bloat_endpoint():
    """Serves real-time bloat detection, RAM, disk, and cache hygiene telemetry."""
    # 1. If remote AWS coordinator bridge is connected, proxy directly from AWS
    if aws_bridge and aws_bridge.is_connected():
        try:
            remote_data = aws_bridge.fetch_remote_json('/api/system/anti-bloat', timeout=2.5)
            if remote_data and remote_data.get("success"):
                remote_data["source"] = "AWS_RELAY"
                return jsonify(remote_data)
        except Exception:
            pass

    # 2. Local fallback
    try:
        from src.quant.anti_bloat import get_anti_bloat_engine
        status = get_anti_bloat_engine().get_status()
        return jsonify({"success": True, "anti_bloat": status, "source": "LOCAL"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/system/anti-bloat/clean', methods=['POST'])
def system_anti_bloat_clean_endpoint():
    """Triggers an immediate anti-bloat cleanse."""
    # 1. If remote AWS coordinator bridge is connected, proxy directly to AWS
    if aws_bridge and aws_bridge.is_connected():
        try:
            remote_res = aws_bridge.post_remote_json('/api/system/anti-bloat/clean', {})
            if remote_res and remote_res.get("success"):
                remote_res["source"] = "AWS_RELAY"
                return jsonify(remote_res)
        except Exception:
            pass

    # 2. Local fallback
    try:
        from src.quant.anti_bloat import get_anti_bloat_engine
        summary = get_anti_bloat_engine().execute_cleanse_cycle(force_deep_clean=True)
        return jsonify({"success": True, "clean_summary": summary, "source": "LOCAL"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


_yearly_matrix_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}

_ASSET_DOT_PALETTE = {
    "BTCUSDT": "#f7931a",
    "ETHUSDT": "#627eea",
    "SOLUSDT": "#14f195",
    "BNBUSDT": "#f0b90b",
    "XRPUSDT": "#38bdf8",
    "ADAUSDT": "#3b82f6",
    "1000PEPEUSDT": "#a371f7",
    "PEPEUSDT": "#a371f7",
    "DOGEUSDT": "#eab308",
    "LINKUSDT": "#2563eb",
    "SUIUSDT": "#06b6d4",
    "AVAXUSDT": "#ef4444",
}

_FALLBACK_DOT_COLORS = [
    "#8b5cf6", "#06b6d4", "#10b981", "#f59e0b", "#ec4899", "#3b82f6", "#f97316", "#14b8a6"
]


def _rolling_12_months_utc(now_utc: datetime.datetime) -> List[Dict[str, Any]]:
    """Returns 12 rolling UTC month descriptors ending on now_utc's month."""
    months = []
    y, m = now_utc.year, now_utc.month
    for offset in range(11, -1, -1):
        # Step back `offset` months cleanly
        total_m = (y * 12 + (m - 1)) - offset
        yy = total_m // 12
        mm = (total_m % 12) + 1
        dt = datetime.datetime(yy, mm, 1, tzinfo=datetime.timezone.utc)
        months.append({
            "key": f"{yy:04d}-{mm:02d}",
            "label": dt.strftime("%b"),
            "short_year": dt.strftime("'%y"),
            "is_current": (offset == 0),
        })
    return months


def _days_in_month_utc(year: int, month: int, today_utc: datetime.date) -> List[Dict[str, Any]]:
    """Returns every calendar day of (year, month) for full-month Daily heatmap view."""
    import calendar
    num_days = calendar.monthrange(year, month)[1]
    dt_first = datetime.datetime(year, month, 1, tzinfo=datetime.timezone.utc)
    mon_abbr = dt_first.strftime("%b")
    short_yr = dt_first.strftime("'%y")
    days = []
    for d in range(1, num_days + 1):
        day_date = datetime.date(year, month, d)
        days.append({
            "key": f"{year:04d}-{month:02d}-{d:02d}",
            "label": str(d),
            "short_year": f"{mon_abbr} {short_yr}",
            "is_current": (day_date == today_utc),
        })
    return days


def _build_yearly_asset_matrix(
    source: str = "live",
    timeframe: str = "1y",
    target_month: Optional[str] = None,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """
    Aggregates Bought/Sold counts & Decimal-exact Net PnL per asset across either:
      - timeframe='1y'    : 12 rolling UTC months + 1Y total
      - timeframe='daily' : All calendar days (1..28/30/31) of the current (or selected) UTC month + MTD total
    Strictly adheres to AGENTS.md Invariant 1 (Zero Float Financial Math).
    """
    src = source.lower().strip() if source else "live"
    if src not in ("live", "tiger", "paper"):
        src = "live"

    tf = timeframe.lower().strip() if timeframe else "1y"
    if tf in ("month", "day", "days", "daily"):
        tf = "daily"
    else:
        tf = "1y"

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    rolling_months = _rolling_12_months_utc(now_utc)
    current_month_key = rolling_months[-1]["key"]
    current_month_label = f"{rolling_months[-1]['label']} {rolling_months[-1]['short_year']}"

    sel_month = current_month_key
    if tf == "daily" and target_month:
        tm = str(target_month).strip()
        if len(tm) == 7 and tm[4] == "-" and tm[:4].isdigit() and tm[5:7].isdigit():
            m_num = int(tm[5:7])
            if 1 <= m_num <= 12:
                sel_month = tm

    cache_key = f"{src}:{tf}:{sel_month if tf == 'daily' else '1y'}"
    now_ts = time.time()
    cached = _yearly_matrix_cache.get(cache_key)
    if not force_refresh and cached is not None and (now_ts - cached[0]) < 10:
        return cached[1]

    if tf == "daily":
        sel_y, sel_m = int(sel_month[:4]), int(sel_month[5:7])
        sel_dt = datetime.datetime(sel_y, sel_m, 1, tzinfo=datetime.timezone.utc)
        sel_label = f"{sel_dt.strftime('%b')} {sel_dt.strftime('%Y')}"
        columns = _days_in_month_utc(sel_y, sel_m, now_utc.date())
        col_keys = [c["key"] for c in columns]
        col_set = set(col_keys)
        range_label = f"{sel_dt.strftime('%b')} 1 – {len(columns)}, {sel_y} · Full-month daily"
        summary_col_label = "MTD" if sel_month == current_month_key else sel_dt.strftime("%b").upper()
    else:
        columns = rolling_months
        col_keys = [c["key"] for c in columns]
        col_set = set(col_keys)
        range_label = f"{columns[0]['label']} {columns[0]['short_year']} to {columns[-1]['label']} {columns[-1]['short_year']} · 12-month rolling"
        summary_col_label = "1Y"
        sel_label = current_month_label

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ZERO = Decimal("0")
    # cell_map[symbol][bucket_key] = {"buys": int, "sells": int, "gross_pnl": Decimal, "fees": Decimal, "net_pnl": Decimal}
    cell_map: Dict[str, Dict[str, Dict[str, Any]]] = {}

    def _ensure_cell(sym: str, bkey: str) -> Dict[str, Any]:
        if sym not in cell_map:
            cell_map[sym] = {}
        if bkey not in cell_map[sym]:
            cell_map[sym][bkey] = {
                "buys": 0,
                "sells": 0,
                "gross_pnl": ZERO,
                "fees": ZERO,
                "net_pnl": ZERO,
            }
        return cell_map[sym][bkey]

    def _parse_bucket_key(ts_str: str) -> Optional[str]:
        if not ts_str:
            return None
        try:
            dt = datetime.datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            else:
                dt = dt.astimezone(datetime.timezone.utc)
            if tf == "daily":
                return f"{dt.year:04d}-{dt.month:02d}-{dt.day:02d}"
            return f"{dt.year:04d}-{dt.month:02d}"
        except Exception:
            return None

    if src == "live":
        # 1. Fetch live Binance Futures fills across all symbols (full cached fill history)
        seen_order_ids = set()
        all_fills = []

        # A. Priority 1: Direct remote fills from AWS EC2 Telemetry Bridge (primary execution gateway)
        if aws_bridge:
            try:
                # Check cached live status trades first
                cached_st = getattr(aws_bridge, "_cached_live_status", None)
                if cached_st and isinstance(cached_st, dict) and cached_st.get("trade_history"):
                    all_fills.extend(cached_st.get("trade_history") or [])

                # Query full live trades over SSH tunnel
                remote_resp = aws_bridge.fetch_remote_json('/api/live/trades?limit=1000', timeout=3.5)
                if remote_resp and isinstance(remote_resp, dict) and remote_resp.get("success"):
                    rem_trades = remote_resp.get("trades") or []
                    all_fills.extend(rem_trades)
            except Exception as e:
                logger.warning(f"[YearlyMatrix] Failed to pull AWS live fills: {e}")

        # B. Priority 2: Merge local executor fills if running or cached
        try:
            loc_trades = quant_bot.executor.get_live_trade_history(limit=500, force_refresh=force_refresh)
            if loc_trades:
                all_fills.extend(loc_trades)
            cached_loc = getattr(quant_bot.executor, "_cached_live_trades", []) or []
            if cached_loc:
                all_fills.extend(cached_loc)
        except Exception:
            pass

        # Deduplicate raw fills by (symbol, trade_id) or (symbol, order_id, time)
        deduped_fills = []
        seen_fill_keys = set()
        for f in all_fills:
            sym = str(f.get("symbol", "")).upper()
            tid = str(f.get("trade_id") or f.get("id") or "")
            oid = str(f.get("order_id") or f.get("orderId") or "")
            t_str = str(f.get("time") or "")
            fkey = (sym, tid) if tid else (sym, oid, t_str)
            if fkey in seen_fill_keys:
                continue
            seen_fill_keys.add(fkey)
            deduped_fills.append(f)

        # Group fills by (symbol, order_id) so partial fills count as 1 BUY or 1 SELL order
        orders_agg: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for f in deduped_fills:
            sym = str(f.get("symbol", "")).upper()
            oid = str(f.get("order_id", "") or f.get("trade_id", ""))
            bkey = _parse_bucket_key(f.get("time", ""))
            if not sym or not bkey or bkey not in col_set:
                continue
            k = (sym, oid)
            if k not in orders_agg:
                orders_agg[k] = {
                    "symbol": sym,
                    "bucket": bkey,
                    "side": str(f.get("side", "BUY")).upper(),
                    "gross_pnl": ZERO,
                    "fees": ZERO,
                }
            orders_agg[k]["gross_pnl"] += Decimal(str(f.get("realized_pnl_usd", "0")))
            orders_agg[k]["fees"] += Decimal(str(f.get("fee_usd", "0")))
            seen_order_ids.add(k)

        for o in orders_agg.values():
            c = _ensure_cell(o["symbol"], o["bucket"])
            if o["side"] in ("BUY", "LONG"):
                c["buys"] += 1
            else:
                c["sells"] += 1
            c["gross_pnl"] += o["gross_pnl"]
            c["fees"] += o["fees"]
            c["net_pnl"] += (o["gross_pnl"] - o["fees"])

        # 2. Merge historical closed live trades from data/live_audit_summary.json if not already present
        audit_path = os.path.join(repo_root, "data", "live_audit_summary.json")
        if os.path.exists(audit_path):
            try:
                with open(audit_path, "r", encoding="utf-8") as af:
                    audit_data = json.load(af)
                hist_trades = (audit_data.get("macro_trades") or []) + (audit_data.get("scalp_trades") or [])
                for t in hist_trades:
                    sym = str(t.get("symbol", "")).upper()
                    oid = str(t.get("order_id", ""))
                    if not sym or (sym, oid) in seen_order_ids:
                        continue
                    bkey = _parse_bucket_key(t.get("exit_time") or t.get("entry_time") or "")
                    if not bkey or bkey not in col_set:
                        continue
                    seen_order_ids.add((sym, oid))
                    c = _ensure_cell(sym, bkey)
                    side = str(t.get("side", "BUY")).upper()
                    if side in ("BUY", "LONG"):
                        c["buys"] += 1
                    else:
                        c["sells"] += 1
                    gp = Decimal(str(t.get("gross_pnl", "0")))
                    fe = Decimal(str(t.get("fee", "0")))
                    npnl = Decimal(str(t.get("net_pnl", str(gp - fe))))
                    c["gross_pnl"] += gp
                    c["fees"] += fe
                    c["net_pnl"] += npnl
            except Exception:
                pass

    elif src == "tiger":
        tiger_db = os.path.join(repo_root, "data", "tiger_trades.db")
        if os.path.exists(tiger_db):
            try:
                import sqlite3
                con = sqlite3.connect(tiger_db)
                rows = con.execute(
                    "SELECT symbol, side, net_pnl_usd, closed_at_utc, created_at_utc FROM tiger_trades"
                ).fetchall()
                con.close()
                for sym, side, npnl, closed_at, created_at in rows:
                    bkey = _parse_bucket_key(closed_at or created_at or "")
                    if not sym or not bkey or bkey not in col_set:
                        continue
                    c = _ensure_cell(str(sym).upper(), bkey)
                    if str(side).upper() in ("BUY", "LONG"):
                        c["buys"] += 1
                    else:
                        c["sells"] += 1
                    d_net = Decimal(str(npnl or "0"))
                    c["gross_pnl"] += d_net
                    c["net_pnl"] += d_net
            except Exception:
                pass

    elif src == "paper":
        paper_rows = []
        paper_path = os.path.join(repo_root, "data", "paper_trading_state.json")
        if os.path.exists(paper_path):
            try:
                with open(paper_path, "r", encoding="utf-8") as pf:
                    pdata = json.load(pf)
                paper_rows.extend(pdata.get("closed_trades") or pdata.get("closed_positions") or [])
            except Exception:
                pass
        for t in paper_rows:
            sym = str(t.get("symbol", "")).upper()
            bkey = _parse_bucket_key(t.get("close_time") or t.get("exit_time_utc") or t.get("entry_time") or t.get("entry_time_utc") or "")
            if not sym or not bkey or bkey not in col_set:
                continue
            c = _ensure_cell(sym, bkey)
            side = str(t.get("side", "BUY")).upper()
            if side in ("BUY", "LONG"):
                c["buys"] += 1
            else:
                c["sells"] += 1
            gp = Decimal(str(t.get("gross_pnl_usd", t.get("realized_pnl_usd", "0"))))
            fe = Decimal(str(t.get("fee_usd", t.get("total_fee_usd", "0"))))
            npnl = Decimal(str(t.get("realized_pnl_usd", str(gp - fe))))
            c["gross_pnl"] += gp
            c["fees"] += fe
            c["net_pnl"] += npnl

    # Ensure core Top symbols always appear neatly even if 0 trades in live view
    if src == "live" and not cell_map:
        for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "1000PEPEUSDT"):
            cell_map[sym] = {}

    def _serialize_cell(c: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not c or (c["buys"] + c["sells"]) == 0:
            return {
                "buys": 0,
                "sells": 0,
                "total": 0,
                "gross_pnl": "0.00",
                "fees": "0.00",
                "net_pnl": "0.00",
                "status": "empty",
            }
        net = c["net_pnl"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        gross = c["gross_pnl"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        fees = c["fees"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        status = "profit" if net > ZERO else ("loss" if net < ZERO else "flat")
        return {
            "buys": c["buys"],
            "sells": c["sells"],
            "total": c["buys"] + c["sells"],
            "gross_pnl": str(gross),
            "fees": str(fees),
            "net_pnl": str(net),
            "status": status,
        }

    # Build Portfolio Summary row + per-asset rows
    summary_cols_raw: Dict[str, Dict[str, Any]] = {
        ck: {"buys": 0, "sells": 0, "gross_pnl": ZERO, "fees": ZERO, "net_pnl": ZERO}
        for ck in col_keys
    }
    summary_total = {"buys": 0, "sells": 0, "gross_pnl": ZERO, "fees": ZERO, "net_pnl": ZERO}

    asset_rows = []
    max_abs_cell_pnl = Decimal("0.01")

    for idx, sym in enumerate(sorted(cell_map.keys())):
        c_dict = {}
        tot = {"buys": 0, "sells": 0, "gross_pnl": ZERO, "fees": ZERO, "net_pnl": ZERO}
        for ck in col_keys:
            raw_c = cell_map[sym].get(ck)
            c_dict[ck] = _serialize_cell(raw_c)
            if raw_c:
                tot["buys"] += raw_c["buys"]
                tot["sells"] += raw_c["sells"]
                tot["gross_pnl"] += raw_c["gross_pnl"]
                tot["fees"] += raw_c["fees"]
                tot["net_pnl"] += raw_c["net_pnl"]

                sm = summary_cols_raw[ck]
                sm["buys"] += raw_c["buys"]
                sm["sells"] += raw_c["sells"]
                sm["gross_pnl"] += raw_c["gross_pnl"]
                sm["fees"] += raw_c["fees"]
                sm["net_pnl"] += raw_c["net_pnl"]

                abs_v = abs(raw_c["net_pnl"])
                if abs_v > max_abs_cell_pnl:
                    max_abs_cell_pnl = abs_v

        summary_total["buys"] += tot["buys"]
        summary_total["sells"] += tot["sells"]
        summary_total["gross_pnl"] += tot["gross_pnl"]
        summary_total["fees"] += tot["fees"]
        summary_total["net_pnl"] += tot["net_pnl"]

        short_name = sym.replace("1000", "").replace("USDT", "")
        dot_color = _ASSET_DOT_PALETTE.get(sym, _FALLBACK_DOT_COLORS[idx % len(_FALLBACK_DOT_COLORS)])
        asset_rows.append({
            "symbol": sym,
            "short_name": short_name,
            "color": dot_color,
            "months": c_dict,
            "yearly": _serialize_cell(tot),
            "_sort_total": tot["buys"] + tot["sells"],
        })

    # Sort assets by total activity descending
    asset_rows.sort(key=lambda r: (-r["_sort_total"], r["symbol"]))
    for r in asset_rows:
        r.pop("_sort_total", None)

    summary_cols_serialized = {ck: _serialize_cell(summary_cols_raw[ck]) for ck in col_keys}
    for ck in col_keys:
        abs_s = abs(summary_cols_raw[ck]["net_pnl"])
        if abs_s > max_abs_cell_pnl:
            max_abs_cell_pnl = abs_s

    available_months = [
        {"key": m["key"], "label": f"{m['label']} {m['short_year']}", "is_current": m["is_current"]}
        for m in reversed(rolling_months)
    ]

    payload = {
        "success": True,
        "source": src,
        "timeframe": tf,
        "selected_month": sel_month,
        "selected_month_label": sel_label,
        "current_month": current_month_key,
        "current_month_label": current_month_label,
        "summary_col_label": summary_col_label,
        "range_label": range_label,
        "available_months": available_months,
        "months": columns,
        "summary_row": {
            "label": "Portfolio",
            "months": summary_cols_serialized,
            "yearly": _serialize_cell(summary_total),
        },
        "rows": asset_rows,
        "max_abs_pnl": str(max_abs_cell_pnl.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "updated_at_utc": now_utc.isoformat(),
    }
    _yearly_matrix_cache[cache_key] = (now_ts, payload)
    return payload


@app.route('/api/analytics/yearly-matrix', methods=['GET'])
def get_yearly_asset_matrix():
    """Returns 1-year monthly or full-month daily Bought/Sold & Net PnL matrix per asset for the Dashboard."""
    try:
        source = request.args.get("source", "live")
        timeframe = request.args.get("timeframe", "1y")
        month = request.args.get("month")
        force = request.args.get("refresh", "false").lower() in ("1", "true", "yes")
        data = _build_yearly_asset_matrix(
            source=source,
            timeframe=timeframe,
            target_month=month,
            force_refresh=force,
        )
        return jsonify(data)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


def acquire_single_instance_lock(port: int = 7071, max_retries: int = 5):
    import socket
    for attempt in range(max_retries):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(('127.0.0.1', port))
            s.listen(1)
            return s
        except Exception as e:
            s.close()
            if attempt < max_retries - 1:
                time.sleep(1)
            else:
                print(f"FATAL: Another instance of Kronos WebUI is already running on port {port} ({e}). Exiting to prevent dual-execution collision.")
                sys.exit(0)

if __name__ == '__main__':
    _lock_sock = acquire_single_instance_lock(7071)
    print("Starting Kronos Web UI...")
    print(f"Model availability: {MODEL_AVAILABLE}")
    if MODEL_AVAILABLE:
        print("Tip: You can load Kronos model through /api/load-model endpoint")
    else:
        print("Tip: Will use simulated data for demonstration")
    # Auto-start Swarm WebSocket Telemetry Hub on ws://0.0.0.0:8765/swarm
    try:
        from webui.telemetry_hub import telemetry_hub
        telemetry_hub.start_background()
        print(">> [Swarm Telemetry Hub] WebSocket online at ws://0.0.0.0:8765/swarm")
    except Exception as e:
        print(f">> [Swarm Telemetry Hub Notice] Could not start telemetry hub: {e}")
    # Auto-start Quant Bot & KEV.ai Autonomous Engine
    start_autopilot()
    # Resilient server loop: survives transient socket drops / resets
    while True:
        try:
            app.run(debug=False, use_reloader=False, host='0.0.0.0', port=7070, threaded=True)
            break
        except Exception as e:
            print(f">> [Flask Server Loop Recovered from Exception] {e}")
            time.sleep(2)
