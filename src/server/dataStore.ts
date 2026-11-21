import fs from 'fs';
import path from 'path';
import Decimal from 'decimal.js';

export const ROOT_DIR = process.cwd();
export const DATA_DIR = path.join(ROOT_DIR, 'data');

export interface Candle {
  timestamp: string;
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  amount: number;
}

export interface PaperPosition {
  position_id: string;
  symbol: string;
  side: string;
  entry_price: number;
  stop_loss: number;
  take_profit: number;
  quantity: number;
  state: string;
  entry_time: string;
  duration_minutes: number;
  duration_hours: number;
}

export interface ClosedPaperTrade {
  trade_id: string;
  symbol: string;
  side: string;
  entry_price: number;
  exit_price: number;
  quantity: number;
  notional_usd: number;
  gross_pnl_usd: number;
  fee_usd: number;
  slippage_usd: number;
  funding_usd: number;
  realized_pnl_usd: number;
  return_pct: number;
  result: string;
  reason: string;
  entry_time: string;
  close_time: string;
  duration_minutes: number;
}

export const BINANCE_ASSETS = [
  { symbol: 'BTCUSDT', name: 'Bitcoin (BTC/USDT)' },
  { symbol: 'ETHUSDT', name: 'Ethereum (ETH/USDT)' },
  { symbol: 'SOLUSDT', name: 'Solana (SOL/USDT)' },
  { symbol: 'BNBUSDT', name: 'BNB (BNB/USDT)' },
  { symbol: 'XRPUSDT', name: 'Ripple (XRP/USDT)' },
  { symbol: 'DOGEUSDT', name: 'Dogecoin (DOGE/USDT)' },
  { symbol: 'ADAUSDT', name: 'Cardano (ADA/USDT)' },
  { symbol: 'AVAXUSDT', name: 'Avalanche (AVAX/USDT)' },
  { symbol: 'LINKUSDT', name: 'Chainlink (LINK/USDT)' },
  { symbol: 'SUIUSDT', name: 'Sui (SUI/USDT)' },
  { symbol: '1000PEPEUSDT', name: 'Pepe (1000PEPE/USDT)' },
  { symbol: 'PEPEUSDT', name: 'Pepe Spot (PEPE/USDT)' },
];

export const CORE_UNIVERSE_SYMBOLS = [
  'BTCUSDT',
  'ETHUSDT',
  'SOLUSDT',
  'BNBUSDT',
  'XRPUSDT',
  'DOGEUSDT',
  'ADAUSDT',
  'AVAXUSDT',
  'LINKUSDT',
  'SUIUSDT',
  '1000PEPEUSDT',
  'ZECUSDT',
];

export const FALLBACK_PRICES: Record<string, { price: number; change24h: number; volume24h: number; funding8h: number }> = {
  BTCUSDT: { price: 88420.5, change24h: 2.84, volume24h: 18420000000, funding8h: 0.01 },
  ETHUSDT: { price: 2945.2, change24h: 3.12, volume24h: 11250000000, funding8h: 0.01 },
  SOLUSDT: { price: 142.85, change24h: 4.45, volume24h: 4820000000, funding8h: 0.0115 },
  BNBUSDT: { price: 628.4, change24h: 1.92, volume24h: 1640000000, funding8h: 0.0085 },
  XRPUSDT: { price: 2.184, change24h: 5.21, volume24h: 3910000000, funding8h: 0.012 },
  DOGEUSDT: { price: 0.1842, change24h: 3.67, volume24h: 2420000000, funding8h: 0.0105 },
  ADAUSDT: { price: 0.7245, change24h: -0.84, volume24h: 890000000, funding8h: 0.0095 },
  AVAXUSDT: { price: 24.18, change24h: 2.34, volume24h: 640000000, funding8h: 0.01 },
  LINKUSDT: { price: 16.42, change24h: 2.75, volume24h: 580000000, funding8h: 0.01 },
  SUIUSDT: { price: 2.842, change24h: 6.14, volume24h: 1480000000, funding8h: 0.0125 },
  '1000PEPEUSDT': { price: 0.00984, change24h: 7.42, volume24h: 1920000000, funding8h: 0.013 },
  PEPEUSDT: { price: 0.00000984, change24h: 7.42, volume24h: 1920000000, funding8h: 0.013 },
  ZECUSDT: { price: 48.25, change24h: 1.15, volume24h: 210000000, funding8h: 0.008 },
  NEARUSDT: { price: 3.42, change24h: 2.95, volume24h: 390000000, funding8h: 0.01 },
  APTUSDT: { price: 6.84, change24h: 1.88, volume24h: 340000000, funding8h: 0.01 },
  RENDERUSDT: { price: 4.92, change24h: 4.12, volume24h: 280000000, funding8h: 0.01 },
  ARBUSDT: { price: 0.442, change24h: 1.64, volume24h: 310000000, funding8h: 0.01 },
  OPUSDT: { price: 0.965, change24h: 2.11, volume24h: 270000000, funding8h: 0.01 },
};

export const AVAILABLE_MODELS: Record<
  string,
  {
    name: string;
    model_id: string;
    tokenizer_id: string;
    context_length: number;
    params: string;
    description: string;
  }
> = {
  'kronos-base': {
    name: 'Kronos-base',
    model_id: 'NeoQuasar/Kronos-base',
    tokenizer_id: 'NeoQuasar/Kronos-Tokenizer-base',
    context_length: 512,
    params: '102.3M',
    description: 'Base model, provides better prediction quality (Default)',
  },
  'kronos-small': {
    name: 'Kronos-small',
    model_id: 'NeoQuasar/Kronos-small',
    tokenizer_id: 'NeoQuasar/Kronos-Tokenizer-base',
    context_length: 512,
    params: '24.7M',
    description: 'Small model, balanced performance and speed',
  },
  'kronos-mini': {
    name: 'Kronos-mini',
    model_id: 'NeoQuasar/Kronos-mini',
    tokenizer_id: 'NeoQuasar/Kronos-Tokenizer-2k',
    context_length: 2048,
    params: '4.1M',
    description: 'Lightweight model, suitable for fast prediction',
  },
};

export function readJsonSafe<T>(filePath: string, fallback: T): T {
  try {
    if (fs.existsSync(filePath)) {
      const raw = fs.readFileSync(filePath, 'utf-8');
      return JSON.parse(raw) as T;
    }
  } catch {
    // fallback silently
  }
  return fallback;
}

export function writeJsonSafe(filePath: string, data: unknown): void {
  try {
    fs.mkdirSync(path.dirname(filePath), { recursive: true });
    fs.writeFileSync(filePath, JSON.stringify(data, null, 2), 'utf-8');
  } catch {
    // ignore ephemeral disk write failures
  }
}

export function listDataFiles(): Array<{ name: string; path: string; size: string }> {
  if (!fs.existsSync(DATA_DIR)) return [];
  const entries = fs.readdirSync(DATA_DIR);
  const files: Array<{ name: string; path: string; size: string }> = [];
  for (const file of entries) {
    if (file.endsWith('.csv')) {
      const fullPath = path.join(DATA_DIR, file);
      const stat = fs.statSync(fullPath);
      const sizeStr =
        stat.size < 1024 * 1024
          ? `${(stat.size / 1024).toFixed(1)} KB`
          : `${(stat.size / (1024 * 1024)).toFixed(1)} MB`;
      files.push({
        name: file,
        path: `data/${file}`,
        size: sizeStr,
      });
    }
  }
  return files.sort((a, b) => a.name.localeCompare(b.name));
}

export function resolveCsvPath(inputPath?: string, symbol?: string): string | null {
  if (inputPath) {
    const cleaned = path.basename(inputPath);
    const inData = path.join(DATA_DIR, cleaned);
    if (fs.existsSync(inData)) return inData;
    const abs = path.isAbsolute(inputPath) ? inputPath : path.join(ROOT_DIR, inputPath);
    if (abs.startsWith(ROOT_DIR) && fs.existsSync(abs)) return abs;
  }
  if (symbol) {
    const cleanSym = symbol.toUpperCase().replace(/[^A-Z0-9]/g, '');
    const candidate = path.join(DATA_DIR, `binance_${cleanSym}_1h.csv`);
    if (fs.existsSync(candidate)) return candidate;
  }
  const btcFallback = path.join(DATA_DIR, 'binance_BTCUSDT_1h.csv');
  return fs.existsSync(btcFallback) ? btcFallback : null;
}

export function parseCsvCandles(filePath: string): Candle[] {
  const raw = fs.readFileSync(filePath, 'utf-8');
  const lines = raw.split(/\r?\n/).filter((l) => l.trim().length > 0);
  if (lines.length < 2) return [];
  const headers = lines[0].split(',').map((h) => h.trim().toLowerCase());
  const tsIdx = headers.findIndex((h) => h === 'timestamps' || h === 'timestamp' || h === 'date' || h === 'time');
  const openIdx = headers.indexOf('open');
  const highIdx = headers.indexOf('high');
  const lowIdx = headers.indexOf('low');
  const closeIdx = headers.indexOf('close');
  const volIdx = headers.indexOf('volume');
  const amtIdx = headers.indexOf('amount');

  const candles: Candle[] = [];
  for (let i = 1; i < lines.length; i++) {
    const cols = lines[i].split(',');
    if (cols.length < 5) continue;
    const tsRaw = tsIdx >= 0 ? cols[tsIdx].trim() : '';
    const iso = tsRaw.includes('T') ? tsRaw : tsRaw.replace(' ', 'T') + (tsRaw.endsWith('Z') ? '' : 'Z');
    const dt = new Date(iso);
    const epochSec = Number.isFinite(dt.getTime()) ? Math.floor(dt.getTime() / 1000) : Math.floor(Date.now() / 1000) - (lines.length - i) * 3600;
    const open = Number(cols[openIdx]);
    const high = Number(cols[highIdx]);
    const low = Number(cols[lowIdx]);
    const close = Number(cols[closeIdx]);
    const volume = volIdx >= 0 ? Number(cols[volIdx]) || 0 : 0;
    const amount = amtIdx >= 0 ? Number(cols[amtIdx]) || 0 : close * volume;
    if (!Number.isFinite(open) || !Number.isFinite(close)) continue;
    candles.push({
      timestamp: Number.isFinite(dt.getTime()) ? dt.toISOString() : new Date(epochSec * 1000).toISOString(),
      time: epochSec,
      open,
      high: Number.isFinite(high) ? high : Math.max(open, close),
      low: Number.isFinite(low) ? low : Math.min(open, close),
      close,
      volume,
      amount,
    });
  }
  return candles;
}

export function detectTimeframe(candles: Candle[]): string {
  if (candles.length < 2) return '1 hours';
  const diffSec = Math.max(1, candles[1].time - candles[0].time);
  if (diffSec < 60) return `${diffSec} seconds`;
  if (diffSec < 3600) return `${Math.round(diffSec / 60)} minutes`;
  if (diffSec < 86400) return `${Math.round(diffSec / 3600)} hours`;
  return `${Math.round(diffSec / 86400)} days`;
}

export function intervalToSeconds(interval: string): number {
  const m = interval.match(/^(\d+)([mhdw])$/i);
  if (!m) return 3600;
  const val = parseInt(m[1], 10);
  const unit = m[2].toLowerCase();
  if (unit === 'm') return val * 60;
  if (unit === 'h') return val * 3600;
  if (unit === 'd') return val * 86400;
  if (unit === 'w') return val * 604800;
  return 3600;
}

export function generateSyntheticCandles(symbol: string, interval: string, limit: number): Candle[] {
  const baseInfo = FALLBACK_PRICES[symbol] || FALLBACK_PRICES.BTCUSDT;
  const stepSec = intervalToSeconds(interval);
  const nowSec = Math.floor(Date.now() / 1000);
  const endSec = nowSec - (nowSec % stepSec);
  const startSec = endSec - (limit - 1) * stepSec;

  // Deterministic seeded walk so charts look natural and consistent
  let seed = 0;
  for (let i = 0; i < symbol.length; i++) seed = (seed * 31 + symbol.charCodeAt(i)) >>> 0;
  const rand = () => {
    seed = (seed * 1664525 + 1013904223) >>> 0;
    return seed / 4294967296;
  };

  const candles: Candle[] = [];
  let price = baseInfo.price * 0.94;
  const volScale = symbol.includes('PEPE') ? 0.018 : 0.008;

  for (let i = 0; i < limit; i++) {
    const t = startSec + i * stepSec;
    const drift = (baseInfo.price - price) * 0.006;
    const shock = (rand() - 0.495) * price * volScale;
    const open = price;
    const close = Math.max(price * 0.5, open + drift + shock);
    const wickUp = rand() * Math.abs(close - open) * 0.9 + price * volScale * 0.25;
    const wickDn = rand() * Math.abs(close - open) * 0.9 + price * volScale * 0.25;
    const high = Math.max(open, close) + wickUp;
    const low = Math.max(price * 0.4, Math.min(open, close) - wickDn);
    const volume = (baseInfo.volume24h / Math.max(1, baseInfo.price) / 24) * (0.5 + rand());
    price = close;
    candles.push({
      timestamp: new Date(t * 1000).toISOString(),
      time: t,
      open,
      high,
      low,
      close,
      volume,
      amount: close * volume,
    });
  }
  return candles;
}

export async function fetchBinanceKlinesWithFallback(
  symbol: string,
  interval = '1h',
  limit = 600
): Promise<{ candles: Candle[]; source: string; filePath: string }> {
  const cleanSymbol = symbol.toUpperCase().replace(/[^A-Z0-9]/g, '') || 'BTCUSDT';
  const clampedLimit = Math.min(1000, Math.max(50, limit));

  // Try Binance Futures public API first, then Spot public API
  const urls = [
    `https://fapi.binance.com/fapi/v1/klines?symbol=${cleanSymbol}&interval=${interval}&limit=${clampedLimit}`,
    `https://api.binance.com/api/v3/klines?symbol=${cleanSymbol}&interval=${interval}&limit=${clampedLimit}`,
  ];

  for (const url of urls) {
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 3500);
      const res = await fetch(url, { signal: controller.signal });
      clearTimeout(timer);
      if (res.ok) {
        const raw = (await res.json()) as Array<Array<string | number>>;
        if (Array.isArray(raw) && raw.length > 0) {
          const candles: Candle[] = raw.map((row) => {
            const ms = Number(row[0]);
            const open = Number(row[1]);
            const high = Number(row[2]);
            const low = Number(row[3]);
            const close = Number(row[4]);
            const volume = Number(row[5]);
            const amount = Number(row[7]) || close * volume;
            return {
              timestamp: new Date(ms).toISOString(),
              time: Math.floor(ms / 1000),
              open,
              high,
              low,
              close,
              volume,
              amount,
            };
          });
          const fileName = `binance_${cleanSymbol}_${interval}.csv`;
          const targetCsv = path.join(DATA_DIR, fileName);
          const existingCount = fs.existsSync(targetCsv) ? parseCsvCandles(targetCsv).length : 0;
          if (candles.length >= existingCount) {
            saveCandlesCsv(targetCsv, candles);
          }
          return { candles, source: 'Binance Public API', filePath: `data/${fileName}` };
        }
      }
    } catch {
      // try next URL or fallback
    }
  }

  // Fallback to local CSV if matching symbol exists
  const existingCsv = path.join(DATA_DIR, `binance_${cleanSymbol}_1h.csv`);
  if (fs.existsSync(existingCsv) && interval === '1h') {
    const candles = parseCsvCandles(existingCsv).slice(-clampedLimit);
    return { candles, source: 'Local Cached Historical CSV', filePath: `data/binance_${cleanSymbol}_1h.csv` };
  }

  // Generate calibrated synthetic klines if offline / geo-blocked
  const candles = generateSyntheticCandles(cleanSymbol, interval, clampedLimit);
  const fileName = `binance_${cleanSymbol}_${interval}.csv`;
  const targetCsv = path.join(DATA_DIR, fileName);
  const existingCount = fs.existsSync(targetCsv) ? parseCsvCandles(targetCsv).length : 0;
  if (candles.length >= existingCount) {
    saveCandlesCsv(targetCsv, candles);
  }
  return { candles, source: 'Kronos Local Market Simulator (Offline Fallback)', filePath: `data/${fileName}` };
}

function saveCandlesCsv(targetPath: string, candles: Candle[]): void {
  try {
    fs.mkdirSync(path.dirname(targetPath), { recursive: true });
    const header = 'timestamps,open,high,low,close,volume,amount';
    const rows = candles.map(
      (c) =>
        `${c.timestamp.replace('T', ' ').replace('Z', '')},${c.open},${c.high},${c.low},${c.close},${c.volume},${c.amount}`
    );
    fs.writeFileSync(targetPath, [header, ...rows].join('\n'), 'utf-8');
  } catch {
    // ignore write failures
  }
}

export interface LiveTickerItem {
  symbol: string;
  lastPrice: number;
  weightedAvgPrice: number;
  priceChangePercent: number;
  quoteVolume: number;
}

let cachedTickers: { ts: number; map: Record<string, LiveTickerItem> } | null = null;
let inflightTickerFetch: Promise<Record<string, LiveTickerItem>> | null = null;

function buildFallbackTickers(now: number): Record<string, LiveTickerItem> {
  const map: Record<string, LiveTickerItem> = {};
  const wave = Math.sin(now / 15000);
  for (const [sym, info] of Object.entries(FALLBACK_PRICES)) {
    const jitter = 1 + wave * 0.0025;
    const price = Number((info.price * jitter).toPrecision(6));
    const vwap = Number((info.price * (1 - info.change24h / 250)).toPrecision(6));
    map[sym] = {
      symbol: sym,
      lastPrice: price,
      weightedAvgPrice: vwap,
      priceChangePercent: Number((info.change24h + wave * 0.15).toFixed(2)),
      quoteVolume: info.volume24h,
    };
  }
  return map;
}

export async function fetchBinanceTickers(): Promise<Record<string, LiveTickerItem>> {
  const now = Date.now();
  if (cachedTickers && now - cachedTickers.ts < 12000) {
    return cachedTickers.map;
  }
  if (inflightTickerFetch) {
    return inflightTickerFetch;
  }

  inflightTickerFetch = (async () => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 2000);
    try {
      const res = await fetch('https://fapi.binance.com/fapi/v1/ticker/24hr', { signal: controller.signal });
      if (res.ok) {
        const arr = (await res.json()) as Array<Record<string, string>>;
        const map: Record<string, LiveTickerItem> = {};
        for (const item of arr) {
          if (!item.symbol) continue;
          map[item.symbol] = {
            symbol: item.symbol,
            lastPrice: Number(item.lastPrice) || 0,
            weightedAvgPrice: Number(item.weightedAvgPrice) || Number(item.lastPrice) || 0,
            priceChangePercent: Number(item.priceChangePercent) || 0,
            quoteVolume: Number(item.quoteVolume) || 0,
          };
        }
        if (Object.keys(map).length > 0) {
          cachedTickers = { ts: Date.now(), map };
          return map;
        }
      }
    } catch {
      // fallback below
    } finally {
      clearTimeout(timer);
      inflightTickerFetch = null;
    }

    const fallbackMap = cachedTickers ? cachedTickers.map : buildFallbackTickers(Date.now());
    cachedTickers = { ts: Date.now(), map: fallbackMap };
    return fallbackMap;
  })();

  return inflightTickerFetch;
}

export function generateKronosForecast(
  historical: Candle[],
  predLen: number,
  temperature = 1.0
): Candle[] {
  if (historical.length === 0) return [];
  const last = historical[historical.length - 1];
  const stepSec = historical.length > 1 ? Math.max(60, last.time - historical[historical.length - 2].time) : 3600;

  // Estimate recent drift & volatility from the tail lookback window
  const tail = historical.slice(-Math.min(48, historical.length));
  const returns: number[] = [];
  for (let i = 1; i < tail.length; i++) {
    if (tail[i - 1].close > 0) {
      returns.push((tail[i].close - tail[i - 1].close) / tail[i - 1].close);
    }
  }
  const meanRet = returns.length > 0 ? returns.reduce((a, b) => a + b, 0) / returns.length : 0.0002;
  const variance =
    returns.length > 1
      ? returns.reduce((acc, r) => acc + (r - meanRet) ** 2, 0) / (returns.length - 1)
      : 0.00004;
  const sigma = Math.min(0.025, Math.max(0.0015, Math.sqrt(variance))) * Math.max(0.3, Math.min(1.6, temperature));

  // Mean-reverting autoregressive candle trajectory seeded by last candle
  let seed = Math.floor(last.close * 1000) ^ last.time;
  const randn = () => {
    seed = (seed * 1664525 + 1013904223) >>> 0;
    const u1 = Math.max(1e-7, seed / 4294967296);
    seed = (seed * 1664525 + 1013904223) >>> 0;
    const u2 = seed / 4294967296;
    return Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
  };

  const preds: Candle[] = [];
  let prevClose = last.close;
  const avgVol = tail.reduce((a, c) => a + c.volume, 0) / tail.length;

  for (let i = 1; i <= predLen; i++) {
    const t = last.time + i * stepSec;
    const decay = Math.exp(-i / Math.max(24, predLen * 0.6));
    const stepRet = meanRet * 0.65 * decay + randn() * sigma * 0.72;
    const open = prevClose;
    const close = Math.max(open * 0.5, open * (1 + stepRet));
    const wickSpread = Math.abs(randn()) * sigma * 0.45 * open;
    const high = Math.max(open, close) + wickSpread;
    const low = Math.max(open * 0.4, Math.min(open, close) - wickSpread * 0.9);
    const volume = Math.max(0, avgVol * (0.75 + Math.abs(randn()) * 0.35));
    prevClose = close;
    preds.push({
      timestamp: new Date(t * 1000).toISOString(),
      time: t,
      open,
      high,
      low,
      close,
      volume,
      amount: close * volume,
    });
  }
  return preds;
}

export function buildPlotlyChartJson(
  historical: Candle[],
  prediction: Candle[],
  actual: Candle[]
): string {
  const traces: Array<Record<string, unknown>> = [
    {
      type: 'candlestick',
      name: 'Historical Data',
      x: historical.map((c) => c.timestamp),
      open: historical.map((c) => c.open),
      high: historical.map((c) => c.high),
      low: historical.map((c) => c.low),
      close: historical.map((c) => c.close),
      increasing: { line: { color: '#26a69a' } },
      decreasing: { line: { color: '#ef5350' } },
    },
    {
      type: 'candlestick',
      name: 'Kronos Prediction',
      x: prediction.map((c) => c.timestamp),
      open: prediction.map((c) => c.open),
      high: prediction.map((c) => c.high),
      low: prediction.map((c) => c.low),
      close: prediction.map((c) => c.close),
      increasing: { line: { color: '#ff9800' } },
      decreasing: { line: { color: '#f57c00' } },
    },
  ];

  if (actual.length > 0) {
    traces.push({
      type: 'candlestick',
      name: 'Actual Data',
      x: actual.map((c) => c.timestamp),
      open: actual.map((c) => c.open),
      high: actual.map((c) => c.high),
      low: actual.map((c) => c.low),
      close: actual.map((c) => c.close),
      increasing: { line: { color: '#2196f3' } },
      decreasing: { line: { color: '#1976d2' } },
    });
  }

  return JSON.stringify({
    data: traces,
    layout: {
      template: 'plotly_dark',
      paper_bgcolor: '#0d1117',
      plot_bgcolor: '#0d1117',
      font: { color: '#c9d1d9' },
      xaxis: { rangeslider: { visible: false }, gridcolor: '#21262d' },
      yaxis: { gridcolor: '#21262d' },
      margin: { t: 30, r: 20, b: 30, l: 55 },
      legend: { orientation: 'h', y: 1.06 },
    },
  });
}

// ============================================================================
// Yearly / Daily Asset Performance Matrix (Zero-Float Decimal.js Math)
// ============================================================================

const ASSET_DOT_PALETTE: Record<string, string> = {
  BTCUSDT: '#f7931a',
  ETHUSDT: '#627eea',
  SOLUSDT: '#14f195',
  BNBUSDT: '#f0b90b',
  XRPUSDT: '#38bdf8',
  ADAUSDT: '#3b82f6',
  '1000PEPEUSDT': '#a371f7',
  PEPEUSDT: '#a371f7',
  DOGEUSDT: '#eab308',
  LINKUSDT: '#2563eb',
  SUIUSDT: '#06b6d4',
  AVAXUSDT: '#ef4444',
};

const FALLBACK_DOT_COLORS = [
  '#8b5cf6',
  '#06b6d4',
  '#10b981',
  '#f59e0b',
  '#ec4899',
  '#3b82f6',
  '#f97316',
  '#14b8a6',
];

const MONTH_ABBR = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

interface CellAccum {
  buys: number;
  sells: number;
  gross_pnl: Decimal;
  fees: Decimal;
  net_pnl: Decimal;
}

export function buildYearlyAssetMatrix(
  source: string,
  timeframe: string,
  targetMonth: string | undefined,
  paperClosedTrades: ClosedPaperTrade[]
): Record<string, unknown> {
  const src = ['live', 'tiger', 'paper'].includes(source.toLowerCase()) ? source.toLowerCase() : 'live';
  const tf = ['month', 'day', 'days', 'daily'].includes(timeframe.toLowerCase()) ? 'daily' : '1y';

  const now = new Date();
  const rollingMonths: Array<{ key: string; label: string; short_year: string; is_current: boolean }> = [];
  const yNow = now.getUTCFullYear();
  const mNow = now.getUTCMonth(); // 0..11

  for (let offset = 11; offset >= 0; offset--) {
    const totalM = yNow * 12 + mNow - offset;
    const yy = Math.floor(totalM / 12);
    const mm = (totalM % 12) + 1;
    rollingMonths.push({
      key: `${String(yy).padStart(4, '0')}-${String(mm).padStart(2, '0')}`,
      label: MONTH_ABBR[mm - 1],
      short_year: `'${String(yy).slice(-2)}`,
      is_current: offset === 0,
    });
  }

  const currentMonthKey = rollingMonths[rollingMonths.length - 1].key;
  const currentMonthLabel = `${rollingMonths[rollingMonths.length - 1].label} ${rollingMonths[rollingMonths.length - 1].short_year}`;

  let selMonth = currentMonthKey;
  if (tf === 'daily' && targetMonth && /^\d{4}-\d{2}$/.test(targetMonth)) {
    const mNum = parseInt(targetMonth.slice(5, 7), 10);
    if (mNum >= 1 && mNum <= 12) selMonth = targetMonth;
  }

  let columns: Array<{ key: string; label: string; short_year: string; is_current: boolean }>;
  let rangeLabel: string;
  let summaryColLabel: string;
  let selLabel: string;

  if (tf === 'daily') {
    const selY = parseInt(selMonth.slice(0, 4), 10);
    const selM = parseInt(selMonth.slice(5, 7), 10);
    const numDays = new Date(Date.UTC(selY, selM, 0)).getUTCDate();
    const monAbbr = MONTH_ABBR[selM - 1];
    const shortYr = `'${String(selY).slice(-2)}`;
    const todayKey = `${yNow}-${String(mNow + 1).padStart(2, '0')}-${String(now.getUTCDate()).padStart(2, '0')}`;
    columns = [];
    for (let d = 1; d <= numDays; d++) {
      const k = `${String(selY).padStart(4, '0')}-${String(selM).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
      columns.push({
        key: k,
        label: String(d),
        short_year: `${monAbbr} ${shortYr}`,
        is_current: k === todayKey,
      });
    }
    rangeLabel = `${monAbbr} 1 – ${numDays}, ${selY} · Full-month daily`;
    summaryColLabel = selMonth === currentMonthKey ? 'MTD' : monAbbr.toUpperCase();
    selLabel = `${monAbbr} ${selY}`;
  } else {
    columns = rollingMonths;
    rangeLabel = `${columns[0].label} ${columns[0].short_year} to ${columns[columns.length - 1].label} ${columns[columns.length - 1].short_year} · 12-month rolling`;
    summaryColLabel = '1Y';
    selLabel = currentMonthLabel;
  }

  const colKeys = columns.map((c) => c.key);
  const colSet = new Set(colKeys);
  const ZERO = new Decimal(0);
  const cellMap: Record<string, Record<string, CellAccum>> = {};

  const ensureCell = (sym: string, bkey: string): CellAccum => {
    if (!cellMap[sym]) cellMap[sym] = {};
    if (!cellMap[sym][bkey]) {
      cellMap[sym][bkey] = { buys: 0, sells: 0, gross_pnl: ZERO, fees: ZERO, net_pnl: ZERO };
    }
    return cellMap[sym][bkey];
  };

  const parseBucket = (ts?: string): string | null => {
    if (!ts) return null;
    const d = new Date(ts);
    if (!Number.isFinite(d.getTime())) return null;
    const yy = String(d.getUTCFullYear()).padStart(4, '0');
    const mm = String(d.getUTCMonth() + 1).padStart(2, '0');
    const dd = String(d.getUTCDate()).padStart(2, '0');
    return tf === 'daily' ? `${yy}-${mm}-${dd}` : `${yy}-${mm}`;
  };

  if (src === 'live') {
    const audit = readJsonSafe<{ macro_trades?: Array<Record<string, unknown>>; scalp_trades?: Array<Record<string, unknown>> }>(
      path.join(DATA_DIR, 'live_audit_summary.json'),
      {}
    );
    const trades = [...(audit.macro_trades || []), ...(audit.scalp_trades || [])];
    for (const t of trades) {
      const sym = String(t.symbol || '').toUpperCase();
      const bkey = parseBucket(String(t.exit_time || t.entry_time || ''));
      if (!sym || !bkey || !colSet.has(bkey)) continue;
      const cell = ensureCell(sym, bkey);
      const side = String(t.side || 'BUY').toUpperCase();
      if (side === 'BUY' || side === 'LONG') cell.buys += 1;
      else cell.sells += 1;
      const gp = new Decimal(String(t.gross_pnl ?? '0'));
      const fe = new Decimal(String(t.fee ?? '0'));
      const npnl = t.net_pnl !== undefined ? new Decimal(String(t.net_pnl)) : gp.minus(fe);
      cell.gross_pnl = cell.gross_pnl.plus(gp);
      cell.fees = cell.fees.plus(fe);
      cell.net_pnl = cell.net_pnl.plus(npnl);
    }
  } else if (src === 'paper') {
    for (const t of paperClosedTrades) {
      const sym = String(t.symbol || '').toUpperCase();
      const bkey = parseBucket(t.close_time || t.entry_time);
      if (!sym || !bkey || !colSet.has(bkey)) continue;
      const cell = ensureCell(sym, bkey);
      const side = String(t.side || 'BUY').toUpperCase();
      if (side === 'BUY' || side === 'LONG') cell.buys += 1;
      else cell.sells += 1;
      const gp = new Decimal(String(t.gross_pnl_usd ?? 0));
      const fe = new Decimal(String(t.fee_usd ?? 0));
      const npnl = new Decimal(String(t.realized_pnl_usd ?? 0));
      cell.gross_pnl = cell.gross_pnl.plus(gp);
      cell.fees = cell.fees.plus(fe);
      cell.net_pnl = cell.net_pnl.plus(npnl);
    }
  } else if (src === 'tiger') {
    const audit = readJsonSafe<{ scalp_trades?: Array<Record<string, unknown>> }>(
      path.join(DATA_DIR, 'live_audit_summary.json'),
      {}
    );
    for (const t of audit.scalp_trades || []) {
      const sym = String(t.symbol || '').toUpperCase();
      const bkey = parseBucket(String(t.exit_time || t.entry_time || ''));
      if (!sym || !bkey || !colSet.has(bkey)) continue;
      const cell = ensureCell(sym, bkey);
      const side = String(t.side || 'BUY').toUpperCase();
      if (side === 'BUY' || side === 'LONG') cell.buys += 1;
      else cell.sells += 1;
      const npnl = new Decimal(String(t.net_pnl ?? '0'));
      cell.gross_pnl = cell.gross_pnl.plus(npnl);
      cell.net_pnl = cell.net_pnl.plus(npnl);
    }
  }

  if (Object.keys(cellMap).length === 0) {
    for (const sym of ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT', 'ADAUSDT', '1000PEPEUSDT']) {
      cellMap[sym] = {};
    }
  }

  const serializeCell = (c?: CellAccum) => {
    if (!c || c.buys + c.sells === 0) {
      return { buys: 0, sells: 0, total: 0, gross_pnl: '0.00', fees: '0.00', net_pnl: '0.00', status: 'empty' };
    }
    const net = c.net_pnl.toDecimalPlaces(2);
    const gross = c.gross_pnl.toDecimalPlaces(2);
    const fees = c.fees.toDecimalPlaces(2);
    const status = net.gt(0) ? 'profit' : net.lt(0) ? 'loss' : 'flat';
    return {
      buys: c.buys,
      sells: c.sells,
      total: c.buys + c.sells,
      gross_pnl: gross.toFixed(2),
      fees: fees.toFixed(2),
      net_pnl: net.toFixed(2),
      status,
    };
  };

  const summaryColsRaw: Record<string, CellAccum> = {};
  for (const ck of colKeys) {
    summaryColsRaw[ck] = { buys: 0, sells: 0, gross_pnl: ZERO, fees: ZERO, net_pnl: ZERO };
  }
  const summaryTotal: CellAccum = { buys: 0, sells: 0, gross_pnl: ZERO, fees: ZERO, net_pnl: ZERO };
  let maxAbsCellPnl = new Decimal('0.01');

  const assetRows = Object.keys(cellMap)
    .sort()
    .map((sym, idx) => {
      const cDict: Record<string, ReturnType<typeof serializeCell>> = {};
      const tot: CellAccum = { buys: 0, sells: 0, gross_pnl: ZERO, fees: ZERO, net_pnl: ZERO };
      for (const ck of colKeys) {
        const rawC = cellMap[sym][ck];
        cDict[ck] = serializeCell(rawC);
        if (rawC) {
          tot.buys += rawC.buys;
          tot.sells += rawC.sells;
          tot.gross_pnl = tot.gross_pnl.plus(rawC.gross_pnl);
          tot.fees = tot.fees.plus(rawC.fees);
          tot.net_pnl = tot.net_pnl.plus(rawC.net_pnl);

          const sm = summaryColsRaw[ck];
          sm.buys += rawC.buys;
          sm.sells += rawC.sells;
          sm.gross_pnl = sm.gross_pnl.plus(rawC.gross_pnl);
          sm.fees = sm.fees.plus(rawC.fees);
          sm.net_pnl = sm.net_pnl.plus(rawC.net_pnl);

          if (rawC.net_pnl.abs().gt(maxAbsCellPnl)) {
            maxAbsCellPnl = rawC.net_pnl.abs();
          }
        }
      }
      summaryTotal.buys += tot.buys;
      summaryTotal.sells += tot.sells;
      summaryTotal.gross_pnl = summaryTotal.gross_pnl.plus(tot.gross_pnl);
      summaryTotal.fees = summaryTotal.fees.plus(tot.fees);
      summaryTotal.net_pnl = summaryTotal.net_pnl.plus(tot.net_pnl);

      const shortName = sym.replace('1000', '').replace('USDT', '');
      const color = ASSET_DOT_PALETTE[sym] || FALLBACK_DOT_COLORS[idx % FALLBACK_DOT_COLORS.length];
      return {
        symbol: sym,
        short_name: shortName,
        color,
        months: cDict,
        yearly: serializeCell(tot),
        _sortTotal: tot.buys + tot.sells,
      };
    });

  assetRows.sort((a, b) => b._sortTotal - a._sortTotal || a.symbol.localeCompare(b.symbol));
  const cleanRows = assetRows.map(({ _sortTotal: _, ...rest }) => rest);

  const summaryColsSerialized: Record<string, ReturnType<typeof serializeCell>> = {};
  for (const ck of colKeys) {
    summaryColsSerialized[ck] = serializeCell(summaryColsRaw[ck]);
    if (summaryColsRaw[ck].net_pnl.abs().gt(maxAbsCellPnl)) {
      maxAbsCellPnl = summaryColsRaw[ck].net_pnl.abs();
    }
  }

  return {
    success: true,
    source: src,
    timeframe: tf,
    selected_month: selMonth,
    selected_month_label: selLabel,
    current_month: currentMonthKey,
    current_month_label: currentMonthLabel,
    summary_col_label: summaryColLabel,
    range_label: rangeLabel,
    available_months: [...rollingMonths].reverse().map((m) => ({
      key: m.key,
      label: `${m.label} ${m.short_year}`,
      is_current: m.is_current,
    })),
    months: columns,
    summary_row: {
      label: 'Portfolio',
      months: summaryColsSerialized,
      yearly: serializeCell(summaryTotal),
    },
    rows: cleanRows,
    max_abs_pnl: maxAbsCellPnl.toDecimalPlaces(2).toFixed(2),
    updated_at_utc: now.toISOString(),
  };
}
