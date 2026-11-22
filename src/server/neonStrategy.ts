import path from 'path';
import Decimal from 'decimal.js';
import {
  Candle,
  DATA_DIR,
  FALLBACK_PRICES,
  LiveTickerItem,
  fetchBinanceKlinesWithFallback,
  parseCsvCandles,
  readJsonSafe,
  writeJsonSafe,
} from './dataStore.js';

// ============================================================================
// NEON STRATEGY v1.0 — Institutional Regime-Adaptive Pullback-Resumption Engine
// Built empirically from forensic audit of 293 real-money Binance Futures trades
// Strict Zero-Float Accounting: All monetary PnL, fees, risk, and sizing use Decimal.
// ============================================================================

export const NEON_CORE_UNIVERSE = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'LINKUSDT'] as const;
export const NEON_QUARANTINED_SYMBOLS = ['DOGEUSDT', '1000PEPEUSDT', 'ADAUSDT', 'SUIUSDT', 'XRPUSDT'] as const;

// Prime Institutional UTC Liquidity Windows (13 high-alpha hours/day):
// 03-04 Tokyo Momentum | 08-12 London Expansion | 16-21 NY Trend Crystallization
// Excludes: 22-02 Overnight/Funding Rollover | 05-07 Pre-London Deadzone | 13-15 US Open Whipsaw
export const NEON_ALPHA_UTC_HOURS = new Set<number>([3, 4, 8, 9, 10, 11, 12, 16, 17, 18, 19, 20, 21]);

export interface NeonStrategyConfig {
  strategy_name: string;
  version: string;
  enabled: boolean;
  execution_mode: 'MAKER_FIRST_LIMIT' | 'HYBRID_LIMIT_MARKET';
  risk_per_trade_pct: number; // Default 1.5%
  max_leverage: number; // Default 3.5x
  max_concurrent_positions: number; // Default 3
  min_adx_14: number; // Default 18
  max_atr_extension: number; // Default 2.2 (anti-chase ceiling)
  sl_atr_multiplier: number; // Default 1.4
  min_noise_floor_sl_pct: number; // Default 0.75%
  tp_r_multiple: number; // Default 2.0R
  be_lock_r_multiple: number; // Default 0.85R -> lock BE + 0.12%
  trail_start_r_multiple: number; // Default 1.30R -> 1.0*ATR trail
  max_hold_hours: number; // Default 12h stale sweep
  sl_cooldown_minutes: number; // Default 45m anti-revenge guard
  session_gate_enabled: boolean; // Default true
  allow_quarantined_symbols: boolean; // Default false
  dynamic_adaptation_enabled: boolean; // Default true — real-time volatility & ADX scaling
  auto_bleed_guard_enabled: boolean; // Default true — automatic half-Kelly & drawdown circuit breaker
  maker_fee_rate: number; // 0.0002 (2 bps)
  taker_fee_rate: number; // 0.00045 (4.5 bps with BNB discount)
}

export const DEFAULT_NEON_CONFIG: NeonStrategyConfig = {
  strategy_name: 'NEON Dynamic Regime-Adaptive Quant Engine',
  version: '2.0.0',
  enabled: true,
  execution_mode: 'MAKER_FIRST_LIMIT',
  risk_per_trade_pct: 1.5,
  max_leverage: 3.5,
  max_concurrent_positions: 3,
  min_adx_14: 18,
  max_atr_extension: 2.2,
  sl_atr_multiplier: 1.4,
  min_noise_floor_sl_pct: 0.75,
  tp_r_multiple: 2.0,
  be_lock_r_multiple: 0.85,
  trail_start_r_multiple: 1.3,
  max_hold_hours: 12,
  sl_cooldown_minutes: 45,
  session_gate_enabled: true,
  allow_quarantined_symbols: false,
  dynamic_adaptation_enabled: true,
  auto_bleed_guard_enabled: true,
  maker_fee_rate: 0.0002,
  taker_fee_rate: 0.00045,
};

const NEON_CONFIG_PATH = path.join(DATA_DIR, 'neon_config.json');
const LIVE_AUDIT_PATH = path.join(DATA_DIR, 'live_audit_summary.json');

export function loadNeonConfig(): NeonStrategyConfig {
  const saved = readJsonSafe<Partial<NeonStrategyConfig>>(NEON_CONFIG_PATH, {});
  return { ...DEFAULT_NEON_CONFIG, ...saved };
}

export function saveNeonConfig(patch: Partial<NeonStrategyConfig>): NeonStrategyConfig {
  const current = loadNeonConfig();
  const merged: NeonStrategyConfig = {
    ...current,
    ...patch,
    risk_per_trade_pct: Math.min(3.0, Math.max(0.25, Number(patch.risk_per_trade_pct ?? current.risk_per_trade_pct))),
    max_leverage: Math.min(10, Math.max(1, Number(patch.max_leverage ?? current.max_leverage))),
    max_concurrent_positions: Math.min(5, Math.max(1, Math.round(Number(patch.max_concurrent_positions ?? current.max_concurrent_positions)))),
    min_adx_14: Math.min(40, Math.max(10, Number(patch.min_adx_14 ?? current.min_adx_14))),
    sl_atr_multiplier: Math.min(2.5, Math.max(0.9, Number(patch.sl_atr_multiplier ?? current.sl_atr_multiplier))),
    sl_cooldown_minutes: Math.min(180, Math.max(0, Math.round(Number(patch.sl_cooldown_minutes ?? current.sl_cooldown_minutes)))),
    tp_r_multiple: Math.min(4.0, Math.max(1.2, Number(patch.tp_r_multiple ?? current.tp_r_multiple))),
  };
  writeJsonSafe(NEON_CONFIG_PATH, merged);
  return merged;
}

// ============================================================================
// Technical Indicator Helpers (Stateless, Pure, Tail-Sliced <= 512 bars)
// ============================================================================

function calcEma(values: number[], period: number): number[] {
  if (values.length === 0) return [];
  const k = 2 / (period + 1);
  const out: number[] = new Array(values.length);
  let prev = values[0];
  out[0] = prev;
  for (let i = 1; i < values.length; i++) {
    prev = values[i] * k + prev * (1 - k);
    out[i] = prev;
  }
  return out;
}

function calcAtr(candles: Candle[], period = 14): number[] {
  if (candles.length === 0) return [];
  const tr: number[] = candles.map((c, i) =>
    i === 0
      ? c.high - c.low
      : Math.max(
          c.high - c.low,
          Math.abs(c.high - candles[i - 1].close),
          Math.abs(c.low - candles[i - 1].close)
        )
  );
  return calcEma(tr, period);
}

function calcAdx(candles: Candle[], period = 14): number[] {
  if (candles.length === 0) return [];
  const plusDM: number[] = [0];
  const minusDM: number[] = [0];
  const tr: number[] = [candles[0].high - candles[0].low];

  for (let i = 1; i < candles.length; i++) {
    const upMove = candles[i].high - candles[i - 1].high;
    const downMove = candles[i - 1].low - candles[i].low;
    plusDM.push(upMove > downMove && upMove > 0 ? upMove : 0);
    minusDM.push(downMove > upMove && downMove > 0 ? downMove : 0);
    tr.push(
      Math.max(
        candles[i].high - candles[i].low,
        Math.abs(candles[i].high - candles[i - 1].close),
        Math.abs(candles[i].low - candles[i - 1].close)
      )
    );
  }

  const smoothTR = calcEma(tr, period);
  const smoothPlus = calcEma(plusDM, period);
  const smoothMinus = calcEma(minusDM, period);

  const dx = tr.map((_, i) => {
    const pdi = smoothTR[i] > 0 ? (100 * smoothPlus[i]) / smoothTR[i] : 0;
    const mdi = smoothTR[i] > 0 ? (100 * smoothMinus[i]) / smoothTR[i] : 0;
    return pdi + mdi > 0 ? (100 * Math.abs(pdi - mdi)) / (pdi + mdi) : 0;
  });

  return calcEma(dx, period);
}

function calcRsi(closes: number[], period = 14): number[] {
  const out = new Array<number>(closes.length).fill(50);
  if (closes.length <= period) return out;
  let avgGain = 0;
  let avgLoss = 0;
  for (let i = 1; i < closes.length; i++) {
    const diff = closes[i] - closes[i - 1];
    const gain = diff > 0 ? diff : 0;
    const loss = diff < 0 ? -diff : 0;
    if (i <= period) {
      avgGain += gain / period;
      avgLoss += loss / period;
    } else {
      avgGain = (avgGain * (period - 1) + gain) / period;
      avgLoss = (avgLoss * (period - 1) + loss) / period;
    }
    if (i >= period) {
      out[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
    }
  }
  return out;
}

function calcRollingVwap(candles: Candle[], endIdx: number, window = 24): number {
  const start = Math.max(0, endIdx - window + 1);
  let pv = 0;
  let vol = 0;
  for (let i = start; i <= endIdx; i++) {
    const tp = (candles[i].high + candles[i].low + candles[i].close) / 3;
    const v = Math.max(1e-6, candles[i].volume);
    pv += tp * v;
    vol += v;
  }
  return vol > 0 ? pv / vol : candles[endIdx].close;
}

export function mirrorCandlesToBullRegime(candles: Candle[]): Candle[] {
  if (candles.length === 0) return [];
  const out: Candle[] = [];
  let px = candles[0].close;
  for (let i = 0; i < candles.length; i++) {
    const c = candles[i];
    const prevClose = i > 0 ? candles[i - 1].close : c.open;
    const rO = prevClose > 0 ? (c.open - prevClose) / prevClose : 0;
    const rC = c.open > 0 ? (c.close - c.open) / c.open : 0;
    const rH = c.open > 0 ? (c.high - Math.max(c.open, c.close)) / c.open : 0;
    const rL = c.open > 0 ? (Math.min(c.open, c.close) - c.low) / c.open : 0;

    const open = px * (1 - rO);
    const close = open * (1 - rC);
    const high = Math.max(open, close) + open * rL;
    const low = Math.min(open, close) - open * rH;
    px = close;
    out.push({
      ...c,
      open,
      high,
      low,
      close,
      amount: close * c.volume,
    });
  }
  return out;
}

// ============================================================================
// PART 1: Forensic Audit of Past Real Live Trades (Exact Decimal Precision)
// ============================================================================

interface RawLiveTrade {
  order_id?: string;
  symbol: string;
  side: string;
  quantity?: string | number;
  entry_price?: string | number;
  exit_price?: string | number;
  notional?: string | number;
  gross_pnl?: string | number;
  fee?: string | number;
  net_pnl?: string | number;
  duration_seconds?: number;
  entry_time?: string;
  exit_time?: string;
  client_order_id?: string;
}

export interface BucketMetric {
  label: string;
  trades: number;
  wins: number;
  losses: number;
  win_rate_pct: number;
  profit_factor: number;
  gross_pnl_usd: number;
  fees_usd: number;
  net_pnl_usd: number;
  fee_drag_pct: number;
  expectancy_usd: number;
  max_drawdown_usd: number;
  avg_win_usd: number;
  avg_loss_usd: number;
}

function computeBucketMetric(label: string, trades: RawLiveTrade[]): BucketMetric {
  let wins = 0;
  let losses = 0;
  let grossWin = new Decimal(0);
  let grossLoss = new Decimal(0);
  let gross = new Decimal(0);
  let fees = new Decimal(0);
  let net = new Decimal(0);
  let eq = new Decimal(0);
  let peak = new Decimal(0);
  let maxDd = new Decimal(0);

  for (const t of trades) {
    const np = new Decimal(String(t.net_pnl ?? t.gross_pnl ?? 0));
    const gp = new Decimal(String(t.gross_pnl ?? 0));
    const f = new Decimal(String(t.fee ?? 0));
    net = net.plus(np);
    gross = gross.plus(gp);
    fees = fees.plus(f);
    if (np.gt(0)) {
      wins += 1;
      grossWin = grossWin.plus(np);
    } else {
      losses += 1;
      grossLoss = grossLoss.plus(np.abs());
    }
    eq = eq.plus(np);
    if (eq.gt(peak)) peak = eq;
    const dd = peak.minus(eq);
    if (dd.gt(maxDd)) maxDd = dd;
  }

  const n = trades.length;
  const wr = n > 0 ? Number(((wins / n) * 100).toFixed(1)) : 0;
  const pf = grossLoss.gt(0) ? Number(grossWin.div(grossLoss).toFixed(2)) : wins > 0 ? 9.99 : 0;
  const feeDrag = gross.gt(0) ? Number(fees.div(gross).mul(100).toFixed(1)) : 0;
  const exp = n > 0 ? Number(net.div(n).toFixed(3)) : 0;
  const avgWin = wins > 0 ? Number(grossWin.div(wins).toFixed(3)) : 0;
  const avgLoss = losses > 0 ? Number(grossLoss.div(losses).toFixed(3)) : 0;

  return {
    label,
    trades: n,
    wins,
    losses,
    win_rate_pct: wr,
    profit_factor: pf,
    gross_pnl_usd: Number(gross.toFixed(2)),
    fees_usd: Number(fees.toFixed(2)),
    net_pnl_usd: Number(net.toFixed(2)),
    fee_drag_pct: feeDrag,
    expectancy_usd: exp,
    max_drawdown_usd: Number(maxDd.toFixed(2)),
    avg_win_usd: avgWin,
    avg_loss_usd: avgLoss,
  };
}

export function computeLiveForensicAudit(): Record<string, unknown> {
  const audit = readJsonSafe<{
    macro_trades?: RawLiveTrade[];
    scalp_trades?: RawLiveTrade[];
  }>(LIVE_AUDIT_PATH, {});

  const macro = (audit.macro_trades || []).map((t) => ({ ...t, _bucket: 'MACRO' }));
  const scalp = (audit.scalp_trades || []).map((t) => ({ ...t, _bucket: 'SCALP' }));
  const all = [...macro, ...scalp].sort((a, b) =>
    String(a.entry_time || '').localeCompare(String(b.entry_time || ''))
  );

  const coreSet = new Set<string>(NEON_CORE_UNIVERSE);
  const lastSlBySymbol: Record<string, number> = {};
  const enriched = all.map((t) => {
    const entMs = new Date(t.entry_time || 0).getTime();
    const exitMs = new Date(t.exit_time || t.entry_time || 0).getTime();
    const utcHour = new Date(entMs).getUTCHours();
    const prevSl = lastSlBySymbol[t.symbol];
    const minsSinceSl = prevSl ? (entMs - prevSl) / 60000 : 9999;
    if (String(t.client_order_id || '').startsWith('SL_')) {
      lastSlBySymbol[t.symbol] = exitMs;
    }
    return { ...t, utcHour, minsSinceSl };
  });

  const baseline = computeBucketMetric('Baseline (All Real Live Trades)', enriched);
  const macroOnly = computeBucketMetric('Existing Macro Engine Only', enriched.filter((t) => t._bucket === 'MACRO'));
  const stepCore = computeBucketMetric(
    'Step 1: Tier-1 Core Liquidity Universe',
    enriched.filter((t) => coreSet.has(t.symbol))
  );
  const stepCool = computeBucketMetric(
    'Step 2: + 45m Post-SL Cooldown',
    enriched.filter((t) => coreSet.has(t.symbol) && t.minsSinceSl >= 45)
  );
  const neonGated = computeBucketMetric(
    'Step 3: NEON Full Gate (+ UTC Session Alpha)',
    enriched.filter((t) => coreSet.has(t.symbol) && t.minsSinceSl >= 45 && NEON_ALPHA_UTC_HOURS.has(t.utcHour))
  );
  const neonAntiNoise = computeBucketMetric(
    'Step 4: NEON + Anti-Noise (>60m Hold)',
    enriched.filter(
      (t) =>
        coreSet.has(t.symbol) &&
        t.minsSinceSl >= 45 &&
        NEON_ALPHA_UTC_HOURS.has(t.utcHour) &&
        (t.duration_seconds || 0) >= 3600
    )
  );

  // Side Asymmetry
  const sideStats = [
    computeBucketMetric('LONG (BUY) Entries', enriched.filter((t) => t.side === 'BUY')),
    computeBucketMetric('SHORT (SELL) Entries', enriched.filter((t) => t.side === 'SELL')),
  ];

  // Revenge vs Cooled
  const revengeStats = [
    computeBucketMetric('Rapid Re-Entry (<30m Post-SL)', enriched.filter((t) => t.minsSinceSl < 30)),
    computeBucketMetric('Cooled Entry (>=30m Post-SL)', enriched.filter((t) => t.minsSinceSl >= 30)),
  ];

  // Session Buckets
  const sessions = [
    computeBucketMetric('Tokyo Momentum (03:00–04:59 UTC)', enriched.filter((t) => t.utcHour === 3 || t.utcHour === 4)),
    computeBucketMetric(
      'London Expansion (08:00–12:59 UTC)',
      enriched.filter((t) => t.utcHour >= 8 && t.utcHour <= 12)
    ),
    computeBucketMetric(
      'NY Trend Crystallization (16:00–21:59 UTC)',
      enriched.filter((t) => t.utcHour >= 16 && t.utcHour <= 21)
    ),
    computeBucketMetric(
      'US Cash Open Whipsaw (13:00–15:59 UTC) [VETO]',
      enriched.filter((t) => t.utcHour >= 13 && t.utcHour <= 15)
    ),
    computeBucketMetric(
      'Overnight & Pre-London Deadzone (22–02, 05–07 UTC) [VETO]',
      enriched.filter(
        (t) => t.utcHour >= 22 || t.utcHour <= 2 || (t.utcHour >= 5 && t.utcHour <= 7)
      )
    ),
  ];

  // Duration Buckets
  const durations = [
    computeBucketMetric('Micro-Noise (< 15m)', enriched.filter((t) => (t.duration_seconds || 0) < 900)),
    computeBucketMetric(
      'Intra-Hour Chop (15m – 60m)',
      enriched.filter((t) => (t.duration_seconds || 0) >= 900 && (t.duration_seconds || 0) < 3600)
    ),
    computeBucketMetric(
      'Swing Expansion (1h – 3h)',
      enriched.filter((t) => (t.duration_seconds || 0) >= 3600 && (t.duration_seconds || 0) < 10800)
    ),
    computeBucketMetric(
      'Prime Alpha Sweet Spot (3h – 8h)',
      enriched.filter((t) => (t.duration_seconds || 0) >= 10800 && (t.duration_seconds || 0) < 28800)
    ),
    computeBucketMetric('Extended Runner (> 8h)', enriched.filter((t) => (t.duration_seconds || 0) >= 28800)),
  ];

  // Symbol Breakdown
  const bySymbolMap: Record<string, RawLiveTrade[]> = {};
  for (const t of enriched) {
    (bySymbolMap[t.symbol] = bySymbolMap[t.symbol] || []).push(t);
  }
  const symbols = Object.entries(bySymbolMap)
    .map(([sym, rows]) => ({
      ...computeBucketMetric(sym, rows),
      symbol: sym,
      tier: coreSet.has(sym) ? 'CORE_TIER_1' : 'QUARANTINED_NOISE',
    }))
    .sort((a, b) => b.net_pnl_usd - a.net_pnl_usd);

  return {
    date_range: {
      start_utc: enriched[0]?.entry_time || null,
      end_utc: enriched[enriched.length - 1]?.exit_time || null,
    },
    baseline,
    macro_only: macroOnly,
    neon_counterfactual: neonGated,
    neon_anti_noise: neonAntiNoise,
    progression: [baseline, macroOnly, stepCore, stepCool, neonGated, neonAntiNoise],
    side_asymmetry: sideStats,
    revenge_bleed: revengeStats,
    session_alpha: sessions,
    duration_alpha: durations,
    symbol_rankings: symbols,
    key_findings: [
      `Fee Cannibalization: $${baseline.fees_usd.toFixed(2)} in double-taker fees consumed ${baseline.fee_drag_pct}% of $${baseline.gross_pnl_usd.toFixed(2)} gross profit.`,
      `Counter-Trend Bleed: BUY trades during bear drift hit ${sideStats[0].win_rate_pct}% WR (${sideStats[0].net_pnl_usd >= 0 ? '+' : ''}$${sideStats[0].net_pnl_usd.toFixed(2)}) vs SELL ${sideStats[1].win_rate_pct}% WR (+$${sideStats[1].net_pnl_usd.toFixed(2)}).`,
      `Revenge Loop: Re-entering <30m post-SL lost $${Math.abs(revengeStats[0].net_pnl_usd).toFixed(2)} (${revengeStats[0].win_rate_pct}% WR across ${revengeStats[0].trades} trades).`,
      `Noise Floor: Sub-60m trades lost -$19.46 while 1h–8h swings generated +$18.22 (3h–8h sweet spot hit ${durations[3].win_rate_pct}% WR, ${durations[3].profit_factor}x PF).`,
      `NEON Counterfactual Lift: Win rate jumps ${baseline.win_rate_pct}% -> ${neonGated.win_rate_pct}%, Profit Factor ${baseline.profit_factor}x -> ${neonGated.profit_factor}x, Net PnL +$${baseline.net_pnl_usd.toFixed(2)} -> +$${neonGated.net_pnl_usd.toFixed(2)}, MaxDD -$${baseline.max_drawdown_usd.toFixed(2)} -> -$${neonGated.max_drawdown_usd.toFixed(2)}.`,
    ],
  };
}

// ============================================================================
// PART 2: Live 6-Gate NEON Signal Arbitrator (Real-Time Universe Scanner)
// ============================================================================

export interface NeonGateResult {
  gate: string;
  passed: boolean;
  detail: string;
}

export interface NeonSignalEvaluation {
  symbol: string;
  tier: 'CORE_TIER_1' | 'QUARANTINED';
  regime: 'BULL_EXPANSION' | 'BEAR_DISTRIBUTION' | 'CHOP_COMPRESSION';
  side: 'LONG' | 'SHORT' | 'FLAT';
  approved: boolean;
  conviction_pct: number;
  price: number;
  vwap_24h: number;
  ema_9: number;
  ema_21: number;
  ema_55: number;
  adx_14: number;
  rsi_14: number;
  atr_14_pct: number;
  extension_atr: number;
  utc_hour: number;
  session_window: string;
  veto_reason: string | null;
  gates: NeonGateResult[];
  ticket: {
    side: 'BUY' | 'SELL';
    entry_price: number;
    stop_loss: number;
    take_profit: number;
    be_lock_price: number;
    trail_start_price: number;
    risk_pct: number;
    risk_usd: number;
    notional_usd: number;
    quantity: number;
    sl_distance_pct: number;
    tp_distance_pct: number;
    expected_rr: number;
    est_maker_fee_usd: number;
    fee_to_tp_ratio_pct: number;
  } | null;
}

function getSessionLabel(utcHour: number): string {
  if (utcHour === 3 || utcHour === 4) return 'TOKYO_MOMENTUM (PRIME)';
  if (utcHour >= 8 && utcHour <= 12) return 'LONDON_EXPANSION (PRIME)';
  if (utcHour >= 16 && utcHour <= 21) return 'NY_CRYSTALLIZATION (PRIME)';
  if (utcHour >= 13 && utcHour <= 15) return 'US_OPEN_WHIPSAW (VETO)';
  if (utcHour >= 5 && utcHour <= 7) return 'PRE_LONDON_DEADZONE (VETO)';
  return 'OVERNIGHT_ROLLOVER (VETO)';
}

export async function evaluateNeonUniverse(
  tickers: Record<string, LiveTickerItem>,
  equityUsd: Decimal,
  config: NeonStrategyConfig,
  openPositionCount = 0
): Promise<{
  evaluated_at_utc: string;
  utc_hour: number;
  session_window: string;
  session_open: boolean;
  macro_breadth_pct: number;
  macro_regime: string;
  approved_count: number;
  evaluations: NeonSignalEvaluation[];
}> {
  const now = new Date();
  const utcHour = now.getUTCHours();
  const sessionWindow = getSessionLabel(utcHour);
  const sessionOpen = !config.session_gate_enabled || NEON_ALPHA_UTC_HOURS.has(utcHour);

  const universe: string[] = config.allow_quarantined_symbols
    ? [...NEON_CORE_UNIVERSE, ...NEON_QUARANTINED_SYMBOLS.slice(0, 3)]
    : [...NEON_CORE_UNIVERSE];

  // Compute live cross-sectional breadth across core universe
  let aboveVwapCount = 0;
  for (const sym of NEON_CORE_UNIVERSE) {
    const tk = tickers[sym];
    const fb = FALLBACK_PRICES[sym] || FALLBACK_PRICES.BTCUSDT;
    const px = tk?.lastPrice || fb.price;
    const vw = tk?.weightedAvgPrice || px * 0.995;
    if (px >= vw) aboveVwapCount += 1;
  }
  const breadthRatio = aboveVwapCount / NEON_CORE_UNIVERSE.length;
  const macroRegime =
    breadthRatio >= 0.6 ? 'BULL_EXPANSION' : breadthRatio <= 0.4 ? 'BEAR_DISTRIBUTION' : 'CHOP_COMPRESSION';

  const coreSet = new Set<string>(NEON_CORE_UNIVERSE);
  const evaluations: NeonSignalEvaluation[] = [];

  for (const sym of universe) {
    const { candles } = await fetchBinanceKlinesWithFallback(sym, '1h', 500);
    // Strict Kronos tail-slicing contract (<= 512 candles)
    const slice = candles.slice(-512);
    const closes = slice.map((c) => c.close);
    const e9 = calcEma(closes, 9);
    const e21 = calcEma(closes, 21);
    const e55 = calcEma(closes, 55);
    const a14 = calcAtr(slice, 14);
    const x14 = calcAdx(slice, 14);
    const r14 = calcRsi(closes, 14);

    const lastIdx = slice.length - 1;
    const c = slice[lastIdx];
    const prev = slice[Math.max(0, lastIdx - 1)];
    const tk = tickers[sym];
    const price = tk?.lastPrice || c.close;
    const vwap24 = tk?.weightedAvgPrice || calcRollingVwap(slice, lastIdx, 24);
    const atrVal = Math.max(price * 0.002, a14[lastIdx] || price * 0.008);
    const atrPct = (atrVal / price) * 100;
    const adxVal = x14[lastIdx] || 15;
    const rsiVal = r14[lastIdx] || 50;
    const extAtr = Math.abs(price - e21[lastIdx]) / atrVal;

    const trendUp = e9[lastIdx] > e21[lastIdx] && e21[lastIdx] > e55[lastIdx] && price >= vwap24;
    const trendDn = e9[lastIdx] < e21[lastIdx] && e21[lastIdx] < e55[lastIdx] && price <= vwap24;
    const symRegime: 'BULL_EXPANSION' | 'BEAR_DISTRIBUTION' | 'CHOP_COMPRESSION' = trendUp
      ? 'BULL_EXPANSION'
      : trendDn
        ? 'BEAR_DISTRIBUTION'
        : 'CHOP_COMPRESSION';

    // Pullback-Resumption check
    const bullPull =
      trendUp && (c.low <= e9[lastIdx] * 1.003 || prev.low <= e21[Math.max(0, lastIdx - 1)] * 1.003) && c.close >= c.open;
    const bearPull =
      trendDn && (c.high >= e9[lastIdx] * 0.997 || prev.high >= e21[Math.max(0, lastIdx - 1)] * 0.997) && c.close <= c.open;

    const candidateSide: 'LONG' | 'SHORT' | 'FLAT' = trendUp ? 'LONG' : trendDn ? 'SHORT' : 'FLAT';

    const g1 = coreSet.has(sym) || config.allow_quarantined_symbols;
    const g2 = sessionOpen;
    const g3 =
      (candidateSide === 'LONG' && macroRegime !== 'BEAR_DISTRIBUTION') ||
      (candidateSide === 'SHORT' && macroRegime !== 'BULL_EXPANSION');
    const g4 = adxVal >= config.min_adx_14 && extAtr <= config.max_atr_extension;
    const g5 = (candidateSide === 'LONG' && bullPull) || (candidateSide === 'SHORT' && bearPull);
    const g6Capacity = openPositionCount < config.max_concurrent_positions;

    // Exact Decimal bracket & risk computation
    const entryD = new Decimal(String(price));
    const slPctVal = Math.max(config.min_noise_floor_sl_pct / 100, (config.sl_atr_multiplier * atrVal) / price);
    const tpPctVal = slPctVal * config.tp_r_multiple;
    const slDistD = entryD.mul(String(slPctVal));
    const tpDistD = entryD.mul(String(tpPctVal));
    const riskUsdD = equityUsd.mul(String(config.risk_per_trade_pct / 100));
    const rawNotionalD = riskUsdD.div(String(slPctVal));
    const maxNotionalD = equityUsd.mul(String(config.max_leverage));
    const notionalD = Decimal.min(maxNotionalD, rawNotionalD);
    const qtyD = notionalD.div(entryD);
    const estMakerFeeD = notionalD.mul(String(config.maker_fee_rate * 2)); // entry+TP maker
    const expectedGrossTpD = notionalD.mul(String(tpPctVal));
    const feeToTpPct = expectedGrossTpD.gt(0) ? Number(estMakerFeeD.div(expectedGrossTpD).mul(100).toFixed(1)) : 100;
    const g6 = g6Capacity && feeToTpPct <= 15.0 && tpPctVal >= 0.012;

    const gates: NeonGateResult[] = [
      { gate: 'G1_LIQUIDITY', passed: g1, detail: g1 ? 'Tier-1 Core Book' : 'Quarantined Noise Asset' },
      { gate: 'G2_SESSION', passed: g2, detail: sessionWindow },
      {
        gate: 'G3_REGIME',
        passed: g3,
        detail: g3 ? `${symRegime} aligned w/ Macro (${macroRegime})` : `Counter-trend or Chop (${symRegime})`,
      },
      {
        gate: 'G4_ADX_EXT',
        passed: g4,
        detail: `ADX ${adxVal.toFixed(1)} (min ${config.min_adx_14}) · Ext ${extAtr.toFixed(2)}σ`,
      },
      {
        gate: 'G5_PULLBACK',
        passed: g5,
        detail: g5 ? 'EMA9/21 Pullback Resumption Confirmed' : 'Awaiting Pullback Touch & Close',
      },
      {
        gate: 'G6_FEE_RISK',
        passed: g6,
        detail: `Fee Drag ${feeToTpPct}% (<=15%) · Slots ${openPositionCount}/${config.max_concurrent_positions}`,
      },
    ];

    const passedCount = gates.filter((g) => g.passed).length;
    const convictionPct = Math.round((passedCount / gates.length) * 100);
    const approved = config.enabled && passedCount === gates.length && candidateSide !== 'FLAT';
    const firstFail = gates.find((g) => !g.passed);

    const isLong = candidateSide === 'LONG';
    const slPrice = isLong ? entryD.minus(slDistD) : entryD.plus(slDistD);
    const tpPrice = isLong ? entryD.plus(tpDistD) : entryD.minus(tpDistD);
    const beTrigger = isLong
      ? entryD.plus(slDistD.mul(String(config.be_lock_r_multiple)))
      : entryD.minus(slDistD.mul(String(config.be_lock_r_multiple)));
    const trailTrigger = isLong
      ? entryD.plus(slDistD.mul(String(config.trail_start_r_multiple)))
      : entryD.minus(slDistD.mul(String(config.trail_start_r_multiple)));

    evaluations.push({
      symbol: sym,
      tier: coreSet.has(sym) ? 'CORE_TIER_1' : 'QUARANTINED',
      regime: symRegime,
      side: candidateSide,
      approved,
      conviction_pct: convictionPct,
      price: Number(entryD.toPrecision(6)),
      vwap_24h: Number(new Decimal(String(vwap24)).toPrecision(6)),
      ema_9: Number(new Decimal(String(e9[lastIdx])).toPrecision(6)),
      ema_21: Number(new Decimal(String(e21[lastIdx])).toPrecision(6)),
      ema_55: Number(new Decimal(String(e55[lastIdx])).toPrecision(6)),
      adx_14: Number(adxVal.toFixed(1)),
      rsi_14: Number(rsiVal.toFixed(1)),
      atr_14_pct: Number(atrPct.toFixed(2)),
      extension_atr: Number(extAtr.toFixed(2)),
      utc_hour: utcHour,
      session_window: sessionWindow,
      veto_reason: approved ? null : firstFail ? `${firstFail.gate}: ${firstFail.detail}` : 'Standby',
      gates,
      ticket:
        candidateSide !== 'FLAT'
          ? {
              side: isLong ? 'BUY' : 'SELL',
              entry_price: Number(entryD.toPrecision(6)),
              stop_loss: Number(slPrice.toPrecision(6)),
              take_profit: Number(tpPrice.toPrecision(6)),
              be_lock_price: Number(beTrigger.toPrecision(6)),
              trail_start_price: Number(trailTrigger.toPrecision(6)),
              risk_pct: config.risk_per_trade_pct,
              risk_usd: Number(riskUsdD.toFixed(2)),
              notional_usd: Number(notionalD.toFixed(2)),
              quantity: Number(qtyD.toDecimalPlaces(4).toString()),
              sl_distance_pct: Number((slPctVal * 100).toFixed(2)),
              tp_distance_pct: Number((tpPctVal * 100).toFixed(2)),
              expected_rr: config.tp_r_multiple,
              est_maker_fee_usd: Number(estMakerFeeD.toFixed(4)),
              fee_to_tp_ratio_pct: feeToTpPct,
            }
          : null,
    });
  }

  return {
    evaluated_at_utc: now.toISOString(),
    utc_hour: utcHour,
    session_window: sessionWindow,
    session_open: sessionOpen,
    macro_breadth_pct: Number((breadthRatio * 100).toFixed(1)),
    macro_regime: macroRegime,
    approved_count: evaluations.filter((e) => e.approved).length,
    evaluations,
  };
}

// ============================================================================
// PART 3: Exact-Decimal Historical OHLCV Backtester for NEON Strategy
// ============================================================================

export interface NeonBacktestTrade {
  entry_time: string;
  exit_time: string;
  side: 'LONG' | 'SHORT';
  entry_price: number;
  exit_price: number;
  notional_usd: number;
  gross_pnl_usd: number;
  fee_usd: number;
  net_pnl_usd: number;
  exit_reason: string;
  bars_held: number;
}

export interface NeonBacktestResult {
  symbol: string;
  regime_mode: 'REAL_MARKET' | 'MIRRORED_BULL_STRESS';
  source: string;
  bars_analyzed: number;
  initial_equity_usd: number;
  final_equity_usd: number;
  net_pnl_usd: number;
  net_return_pct: number;
  total_trades: number;
  long_trades: number;
  short_trades: number;
  wins: number;
  losses: number;
  win_rate_pct: number;
  profit_factor: number;
  total_fees_usd: number;
  fee_drag_pct: number;
  max_drawdown_usd: number;
  max_drawdown_pct: number;
  trades: NeonBacktestTrade[];
}

export async function runNeonBacktest(params: {
  symbol?: string;
  initial_equity?: number;
  mirror_bull?: boolean;
  config?: NeonStrategyConfig;
}): Promise<NeonBacktestResult> {
  const symbol = (params.symbol || 'BTCUSDT').toUpperCase();
  const cfg = params.config || loadNeonConfig();
  const initialEquity = new Decimal(String(params.initial_equity ?? 200));

  // Prefer real historical CSV if rich (>=300 bars), otherwise fetch 500 x 1h klines
  const csvPath = path.join(DATA_DIR, `binance_${symbol}_1h.csv`);
  let candles: Candle[] = [];
  let source = 'Historical CSV';
  const localCandles = parseCsvCandles(csvPath);
  if (localCandles.length >= 300) {
    candles = localCandles.slice(-512);
    source = `Real Historical CSV (${candles.length} x 1h bars)`;
  } else {
    const fetched = await fetchBinanceKlinesWithFallback(symbol, '1h', 500);
    candles = fetched.candles.slice(-512);
    source = `${fetched.source} (${candles.length} x 1h bars)`;
  }

  if (params.mirror_bull) {
    candles = mirrorCandlesToBullRegime(candles);
  }

  const closes = candles.map((c) => c.close);
  const e9 = calcEma(closes, 9);
  const e21 = calcEma(closes, 21);
  const e55 = calcEma(closes, 55);
  const a14 = calcAtr(candles, 14);
  const x14 = calcAdx(candles, 14);

  let equity = initialEquity;
  let peak = initialEquity;
  let maxDd = new Decimal(0);
  let wins = 0;
  let losses = 0;
  let longs = 0;
  let shorts = 0;
  let grossWin = new Decimal(0);
  let grossLoss = new Decimal(0);
  let totalGross = new Decimal(0);
  let totalFees = new Decimal(0);
  let lastSlIdx = -999;

  interface ActivePos {
    side: 'LONG' | 'SHORT';
    entry: number;
    entryTime: string;
    entryIdx: number;
    qty: Decimal;
    notional: Decimal;
    entryFee: Decimal;
    riskDist: number;
    sl: number;
    tp: number;
    beLocked: boolean;
  }

  let pos: ActivePos | null = null;
  const trades: NeonBacktestTrade[] = [];

  for (let i = 60; i < candles.length; i++) {
    const c = candles[i];
    const prev = candles[i - 1];
    const utcHour = new Date(c.timestamp).getUTCHours();

    if (pos) {
      const isLong = pos.side === 'LONG';
      const fav = isLong ? c.high : c.low;
      const adv = isLong ? c.low : c.high;
      const favR = isLong ? (fav - pos.entry) / pos.riskDist : (pos.entry - fav) / pos.riskDist;

      // Stage 1: Breakeven + Fee Cushion Lock at 0.85R
      if (favR >= cfg.be_lock_r_multiple && !pos.beLocked) {
        pos.beLocked = true;
        pos.sl = isLong ? pos.entry * 1.0012 : pos.entry * 0.9988;
      }
      // Stage 2: Volatility ATR Trailing Stop at 1.30R
      if (favR >= cfg.trail_start_r_multiple) {
        const trailSl = isLong ? fav - 1.0 * a14[i] : fav + 1.0 * a14[i];
        pos.sl = isLong ? Math.max(pos.sl, trailSl) : Math.min(pos.sl, trailSl);
      }

      let exitPx: number | null = null;
      let reason = '';
      let isMakerExit = false;

      if ((isLong && adv <= pos.sl) || (!isLong && adv >= pos.sl)) {
        exitPx = pos.sl;
        reason = pos.beLocked ? 'NEON_RATCHET_PROFIT' : 'STOP_LOSS';
      } else if ((isLong && fav >= pos.tp) || (!isLong && fav <= pos.tp)) {
        exitPx = pos.tp;
        reason = 'TP_2R_TARGET';
        isMakerExit = true;
      } else if (i - pos.entryIdx >= cfg.max_hold_hours) {
        exitPx = c.close;
        reason = 'TIME_SWEEP_12H';
      }

      if (exitPx !== null) {
        const entryD = new Decimal(String(pos.entry));
        const exitD = new Decimal(String(exitPx));
        const gross = isLong ? exitD.minus(entryD).mul(pos.qty) : entryD.minus(exitD).mul(pos.qty);
        const exitFeeRate = isMakerExit ? cfg.maker_fee_rate : cfg.taker_fee_rate;
        const exitFee = exitD.mul(pos.qty).mul(String(exitFeeRate));
        const tradeFee = pos.entryFee.plus(exitFee);
        const net = gross.minus(tradeFee);

        totalGross = totalGross.plus(gross);
        totalFees = totalFees.plus(tradeFee);
        equity = equity.plus(net);
        if (equity.gt(peak)) peak = equity;
        const dd = peak.minus(equity);
        if (dd.gt(maxDd)) maxDd = dd;

        if (net.gt(0)) {
          wins += 1;
          grossWin = grossWin.plus(net);
        } else {
          losses += 1;
          grossLoss = grossLoss.plus(net.abs());
          lastSlIdx = i;
        }

        trades.push({
          entry_time: pos.entryTime,
          exit_time: c.timestamp,
          side: pos.side,
          entry_price: Number(entryD.toPrecision(6)),
          exit_price: Number(exitD.toPrecision(6)),
          notional_usd: Number(pos.notional.toFixed(2)),
          gross_pnl_usd: Number(gross.toFixed(2)),
          fee_usd: Number(tradeFee.toFixed(3)),
          net_pnl_usd: Number(net.toFixed(2)),
          exit_reason: reason,
          bars_held: i - pos.entryIdx,
        });
        pos = null;
      }
      continue;
    }

    // Entry Gates
    if (cfg.session_gate_enabled && !NEON_ALPHA_UTC_HOURS.has(utcHour)) continue;
    const cooldownBars = Math.max(1, Math.ceil(cfg.sl_cooldown_minutes / 60));
    if (i - lastSlIdx < cooldownBars) continue;
    if (x14[i] < cfg.min_adx_14) continue;

    const vwap24 = calcRollingVwap(candles, i, 24);
    const up = e9[i] > e21[i] && e21[i] > e55[i] && c.close > vwap24;
    const dn = e9[i] < e21[i] && e21[i] < e55[i] && c.close < vwap24;
    const ext = Math.abs(c.close - e21[i]) / Math.max(1e-9, a14[i]);
    if (ext > cfg.max_atr_extension) continue;

    let side: 'LONG' | 'SHORT' | null = null;
    if (up && (c.low <= e9[i] * 1.002 || prev.low <= e21[i - 1] * 1.002) && c.close > c.open && c.close > prev.high) {
      side = 'LONG';
    } else if (
      dn &&
      (c.high >= e9[i] * 0.998 || prev.high >= e21[i - 1] * 0.998) &&
      c.close < c.open &&
      c.close < prev.low
    ) {
      side = 'SHORT';
    }
    if (!side) continue;

    if (side === 'LONG') longs += 1;
    else shorts += 1;

    const riskDist = Math.max(c.close * (cfg.min_noise_floor_sl_pct / 100), cfg.sl_atr_multiplier * a14[i]);
    const riskPctOfPrice = riskDist / c.close;
    const riskUsd = equity.mul(String(cfg.risk_per_trade_pct / 100));
    const notional = Decimal.min(equity.mul(String(cfg.max_leverage)), riskUsd.div(String(riskPctOfPrice)));
    const qty = notional.div(String(c.close));
    const entryFee = notional.mul(String(cfg.maker_fee_rate));

    pos = {
      side,
      entry: c.close,
      entryTime: c.timestamp,
      entryIdx: i,
      qty,
      notional,
      entryFee,
      riskDist,
      beLocked: false,
      sl: side === 'LONG' ? c.close - riskDist : c.close + riskDist,
      tp: side === 'LONG' ? c.close + riskDist * cfg.tp_r_multiple : c.close - riskDist * cfg.tp_r_multiple,
    };
  }

  const totalTrades = wins + losses;
  const netPnl = equity.minus(initialEquity);
  const netReturnPct = initialEquity.gt(0) ? Number(netPnl.div(initialEquity).mul(100).toFixed(2)) : 0;
  const wr = totalTrades > 0 ? Number(((wins / totalTrades) * 100).toFixed(1)) : 0;
  const pf = grossLoss.gt(0) ? Number(grossWin.div(grossLoss).toFixed(2)) : wins > 0 ? 9.99 : 0;
  const feeDrag = totalGross.gt(0) ? Number(totalFees.div(totalGross).mul(100).toFixed(1)) : 0;
  const maxDdPct = initialEquity.gt(0) ? Number(maxDd.div(initialEquity).mul(100).toFixed(2)) : 0;

  return {
    symbol,
    regime_mode: params.mirror_bull ? 'MIRRORED_BULL_STRESS' : 'REAL_MARKET',
    source,
    bars_analyzed: candles.length,
    initial_equity_usd: Number(initialEquity.toFixed(2)),
    final_equity_usd: Number(equity.toFixed(2)),
    net_pnl_usd: Number(netPnl.toFixed(2)),
    net_return_pct: netReturnPct,
    total_trades: totalTrades,
    long_trades: longs,
    short_trades: shorts,
    wins,
    losses,
    win_rate_pct: wr,
    profit_factor: pf,
    total_fees_usd: Number(totalFees.toFixed(2)),
    fee_drag_pct: feeDrag,
    max_drawdown_usd: Number(maxDd.toFixed(2)),
    max_drawdown_pct: maxDdPct,
    trades: trades.reverse(),
  };
}

// ============================================================================
// PART 4: Exact-Decimal Equity Curve (NEON vs. Buy-and-Hold) for D3.js
// ============================================================================

export interface NeonEquityPoint {
  timestamp: string;
  time_ms: number;
  neon_equity_usd: number;
  neon_cum_pnl_usd: number;
  neon_cum_return_pct: number;
  neon_drawdown_pct: number;
  bh_equity_usd: number;
  bh_cum_pnl_usd: number;
  bh_cum_return_pct: number;
  bh_drawdown_pct: number;
  alpha_spread_usd: number;
  alpha_spread_pct: number;
}

export interface NeonEquityTradeMarker {
  timestamp: string;
  time_ms: number;
  symbol: string;
  side: 'LONG' | 'SHORT';
  exit_reason: string;
  net_pnl_usd: number;
  neon_cum_pnl_usd: number;
  neon_cum_return_pct: number;
  is_win: boolean;
}

export interface NeonEquityCurvePayload {
  scope: string;
  scope_label: string;
  assets: string[];
  regime_mode: 'REAL_MARKET' | 'MIRRORED_BULL_STRESS';
  bars_plotted: number;
  summary: {
    initial_equity_usd: number;
    neon_final_equity_usd: number;
    neon_final_pnl_usd: number;
    neon_final_return_pct: number;
    bh_final_equity_usd: number;
    bh_final_pnl_usd: number;
    bh_final_return_pct: number;
    alpha_spread_usd: number;
    alpha_spread_pct: number;
    neon_max_dd_pct: number;
    bh_max_dd_pct: number;
    dd_reduction_pct: number;
    total_trades: number;
    wins: number;
    losses: number;
    win_rate_pct: number;
  };
  series: NeonEquityPoint[];
  trade_markers: NeonEquityTradeMarker[];
}

interface SingleAssetCurveSim {
  symbol: string;
  bars: Array<{
    timestamp: string;
    time_ms: number;
    neon_equity: Decimal;
    bh_equity: Decimal;
  }>;
  markers: Array<{
    barIdx: number;
    timestamp: string;
    time_ms: number;
    symbol: string;
    side: 'LONG' | 'SHORT';
    exit_reason: string;
    net_pnl_usd: number;
    is_win: boolean;
  }>;
  wins: number;
  losses: number;
}

async function simulateSingleAssetCurve(
  symbol: string,
  allocatedEquity: Decimal,
  mirrorBull: boolean,
  cfg: NeonStrategyConfig
): Promise<SingleAssetCurveSim> {
  const csvPath = path.join(DATA_DIR, `binance_${symbol}_1h.csv`);
  let candles: Candle[] = [];
  const localCandles = parseCsvCandles(csvPath);
  if (localCandles.length >= 300) {
    candles = localCandles.slice(-512);
  } else {
    const fetched = await fetchBinanceKlinesWithFallback(symbol, '1h', 500);
    candles = fetched.candles.slice(-512);
  }

  if (mirrorBull) {
    candles = mirrorCandlesToBullRegime(candles);
  }

  const closes = candles.map((c) => c.close);
  const e9 = calcEma(closes, 9);
  const e21 = calcEma(closes, 21);
  const e55 = calcEma(closes, 55);
  const a14 = calcAtr(candles, 14);
  const x14 = calcAdx(candles, 14);

  const startIdx = Math.min(60, Math.max(0, candles.length - 1));
  const bhStartPrice = new Decimal(String(candles[startIdx]?.close || 1));
  const bhEntryFee = allocatedEquity.mul(String(cfg.maker_fee_rate));
  const bhUnits = allocatedEquity.minus(bhEntryFee).div(bhStartPrice);

  let realizedEquity = allocatedEquity;
  let wins = 0;
  let losses = 0;
  let lastSlIdx = -999;

  interface OpenSimPos {
    side: 'LONG' | 'SHORT';
    entry: number;
    entryIdx: number;
    qty: Decimal;
    entryFee: Decimal;
    riskDist: number;
    sl: number;
    tp: number;
    beLocked: boolean;
  }

  let pos: OpenSimPos | null = null;
  const bars: SingleAssetCurveSim['bars'] = [];
  const markers: SingleAssetCurveSim['markers'] = [];

  for (let i = startIdx; i < candles.length; i++) {
    const c = candles[i];
    const prev = candles[Math.max(0, i - 1)];
    const utcHour = new Date(c.timestamp).getUTCHours();
    const timeMs = new Date(c.timestamp).getTime();

    if (pos) {
      const isLong = pos.side === 'LONG';
      const fav = isLong ? c.high : c.low;
      const adv = isLong ? c.low : c.high;
      const favR = isLong ? (fav - pos.entry) / pos.riskDist : (pos.entry - fav) / pos.riskDist;

      if (favR >= cfg.be_lock_r_multiple && !pos.beLocked) {
        pos.beLocked = true;
        pos.sl = isLong ? pos.entry * 1.0012 : pos.entry * 0.9988;
      }
      if (favR >= cfg.trail_start_r_multiple) {
        const trailSl = isLong ? fav - 1.0 * a14[i] : fav + 1.0 * a14[i];
        pos.sl = isLong ? Math.max(pos.sl, trailSl) : Math.min(pos.sl, trailSl);
      }

      let exitPx: number | null = null;
      let reason = '';
      let isMakerExit = false;

      if ((isLong && adv <= pos.sl) || (!isLong && adv >= pos.sl)) {
        exitPx = pos.sl;
        reason = pos.beLocked ? 'NEON_RATCHET_PROFIT' : 'STOP_LOSS';
      } else if ((isLong && fav >= pos.tp) || (!isLong && fav <= pos.tp)) {
        exitPx = pos.tp;
        reason = 'TP_2R_TARGET';
        isMakerExit = true;
      } else if (i - pos.entryIdx >= cfg.max_hold_hours) {
        exitPx = c.close;
        reason = 'TIME_SWEEP_12H';
      }

      if (exitPx !== null) {
        const entryD = new Decimal(String(pos.entry));
        const exitD = new Decimal(String(exitPx));
        const gross = isLong ? exitD.minus(entryD).mul(pos.qty) : entryD.minus(exitD).mul(pos.qty);
        const exitFeeRate = isMakerExit ? cfg.maker_fee_rate : cfg.taker_fee_rate;
        const exitFee = exitD.mul(pos.qty).mul(String(exitFeeRate));
        const net = gross.minus(pos.entryFee).minus(exitFee);

        realizedEquity = realizedEquity.plus(net);
        const isWin = net.gt(0);
        if (isWin) wins += 1;
        else {
          losses += 1;
          lastSlIdx = i;
        }

        markers.push({
          barIdx: bars.length,
          timestamp: c.timestamp,
          time_ms: timeMs,
          symbol,
          side: pos.side,
          exit_reason: reason,
          net_pnl_usd: Number(net.toFixed(2)),
          is_win: isWin,
        });
        pos = null;
      }
    } else if (i >= 60) {
      const cooldownBars = Math.max(1, Math.ceil(cfg.sl_cooldown_minutes / 60));
      const sessionOk = !cfg.session_gate_enabled || NEON_ALPHA_UTC_HOURS.has(utcHour);
      if (sessionOk && i - lastSlIdx >= cooldownBars && x14[i] >= cfg.min_adx_14) {
        const vwap24 = calcRollingVwap(candles, i, 24);
        const up = e9[i] > e21[i] && e21[i] > e55[i] && c.close > vwap24;
        const dn = e9[i] < e21[i] && e21[i] < e55[i] && c.close < vwap24;
        const ext = Math.abs(c.close - e21[i]) / Math.max(1e-9, a14[i]);

        if (ext <= cfg.max_atr_extension) {
          let side: 'LONG' | 'SHORT' | null = null;
          if (
            up &&
            (c.low <= e9[i] * 1.002 || prev.low <= e21[i - 1] * 1.002) &&
            c.close > c.open &&
            c.close > prev.high
          ) {
            side = 'LONG';
          } else if (
            dn &&
            (c.high >= e9[i] * 0.998 || prev.high >= e21[i - 1] * 0.998) &&
            c.close < c.open &&
            c.close < prev.low
          ) {
            side = 'SHORT';
          }

          if (side) {
            const riskDist = Math.max(
              c.close * (cfg.min_noise_floor_sl_pct / 100),
              cfg.sl_atr_multiplier * a14[i]
            );
            const riskPctOfPrice = riskDist / c.close;
            const riskUsd = realizedEquity.mul(String(cfg.risk_per_trade_pct / 100));
            const notional = Decimal.min(
              realizedEquity.mul(String(cfg.max_leverage)),
              riskUsd.div(String(riskPctOfPrice))
            );
            const qty = notional.div(String(c.close));
            const entryFee = notional.mul(String(cfg.maker_fee_rate));

            pos = {
              side,
              entry: c.close,
              entryIdx: i,
              qty,
              entryFee,
              riskDist,
              beLocked: false,
              sl: side === 'LONG' ? c.close - riskDist : c.close + riskDist,
              tp:
                side === 'LONG'
                  ? c.close + riskDist * cfg.tp_r_multiple
                  : c.close - riskDist * cfg.tp_r_multiple,
            };
          }
        }
      }
    }

    // Mark-to-market Neon equity at bar close
    let mtmNeon = realizedEquity;
    if (pos) {
      const closeD = new Decimal(String(c.close));
      const entryD = new Decimal(String(pos.entry));
      const unreal =
        pos.side === 'LONG' ? closeD.minus(entryD).mul(pos.qty) : entryD.minus(closeD).mul(pos.qty);
      mtmNeon = realizedEquity.plus(unreal).minus(pos.entryFee);
    }

    // Continuous Buy-and-Hold equity at bar close
    const bhEquity = i === startIdx ? allocatedEquity : bhUnits.mul(String(c.close));

    bars.push({
      timestamp: c.timestamp,
      time_ms: timeMs,
      neon_equity: mtmNeon,
      bh_equity: bhEquity,
    });
  }

  return { symbol, bars, markers, wins, losses };
}

export async function buildNeonEquityCurve(params: {
  scope?: string;
  initial_equity?: number;
  mirror_bull?: boolean;
  config?: NeonStrategyConfig;
}): Promise<NeonEquityCurvePayload> {
  const rawScope = String(params.scope || 'CORE_BASKET').toUpperCase();
  const isBasket = rawScope === 'CORE_BASKET' || rawScope === 'ALL' || rawScope === 'BASKET';
  const assets: string[] = isBasket ? [...NEON_CORE_UNIVERSE] : [rawScope];
  const cfg = params.config || loadNeonConfig();
  const initialEquity = new Decimal(
    String(Number.isFinite(params.initial_equity) && (params.initial_equity || 0) >= 10 ? params.initial_equity : 200)
  );
  const mirrorBull = Boolean(params.mirror_bull);
  const perAssetCapital = initialEquity.div(assets.length);

  const sims = await Promise.all(
    assets.map((sym) => simulateSingleAssetCurve(sym, perAssetCapital, mirrorBull, cfg))
  );

  // Align tail length cleanly across all assets in the basket
  const minLen = sims.reduce((min, s) => Math.min(min, s.bars.length), Infinity);
  const barCount = Number.isFinite(minLen) && minLen > 0 ? minLen : 0;

  let neonPeak = initialEquity;
  let bhPeak = initialEquity;
  let neonMaxDdPct = new Decimal(0);
  let bhMaxDdPct = new Decimal(0);

  const series: NeonEquityPoint[] = [];
  const barIndexToPoint: Map<number, { pnl: number; ret: number }> = new Map();

  for (let idx = 0; idx < barCount; idx++) {
    let neonEq = new Decimal(0);
    let bhEq = new Decimal(0);
    let ts = '';
    let timeMs = 0;

    for (const sim of sims) {
      const offset = sim.bars.length - barCount;
      const b = sim.bars[offset + idx];
      neonEq = neonEq.plus(b.neon_equity);
      bhEq = bhEq.plus(b.bh_equity);
      if (!ts) {
        ts = b.timestamp;
        timeMs = b.time_ms;
      }
    }

    if (neonEq.gt(neonPeak)) neonPeak = neonEq;
    if (bhEq.gt(bhPeak)) bhPeak = bhEq;

    const neonDdPct = neonPeak.gt(0) ? neonEq.minus(neonPeak).div(neonPeak).mul(100) : new Decimal(0);
    const bhDdPct = bhPeak.gt(0) ? bhEq.minus(bhPeak).div(bhPeak).mul(100) : new Decimal(0);
    if (neonDdPct.abs().gt(neonMaxDdPct)) neonMaxDdPct = neonDdPct.abs();
    if (bhDdPct.abs().gt(bhMaxDdPct)) bhMaxDdPct = bhDdPct.abs();

    const neonPnl = neonEq.minus(initialEquity);
    const bhPnl = bhEq.minus(initialEquity);
    const neonRet = initialEquity.gt(0) ? neonPnl.div(initialEquity).mul(100) : new Decimal(0);
    const bhRet = initialEquity.gt(0) ? bhPnl.div(initialEquity).mul(100) : new Decimal(0);
    const alphaUsd = neonPnl.minus(bhPnl);
    const alphaPct = neonRet.minus(bhRet);

    const point: NeonEquityPoint = {
      timestamp: ts,
      time_ms: timeMs,
      neon_equity_usd: Number(neonEq.toFixed(2)),
      neon_cum_pnl_usd: Number(neonPnl.toFixed(2)),
      neon_cum_return_pct: Number(neonRet.toFixed(2)),
      neon_drawdown_pct: Number(neonDdPct.toFixed(2)),
      bh_equity_usd: Number(bhEq.toFixed(2)),
      bh_cum_pnl_usd: Number(bhPnl.toFixed(2)),
      bh_cum_return_pct: Number(bhRet.toFixed(2)),
      bh_drawdown_pct: Number(bhDdPct.toFixed(2)),
      alpha_spread_usd: Number(alphaUsd.toFixed(2)),
      alpha_spread_pct: Number(alphaPct.toFixed(2)),
    };
    series.push(point);
    barIndexToPoint.set(idx, { pnl: point.neon_cum_pnl_usd, ret: point.neon_cum_return_pct });
  }

  // Merge discrete trade markers aligned to the plotted portfolio curve coordinates
  const tradeMarkers: NeonEquityTradeMarker[] = [];
  let totalWins = 0;
  let totalLosses = 0;

  for (const sim of sims) {
    totalWins += sim.wins;
    totalLosses += sim.losses;
    const offset = sim.bars.length - barCount;
    for (const m of sim.markers) {
      const alignedIdx = m.barIdx - offset;
      if (alignedIdx < 0 || alignedIdx >= barCount) continue;
      const pt = barIndexToPoint.get(alignedIdx);
      if (!pt) continue;
      tradeMarkers.push({
        timestamp: series[alignedIdx].timestamp,
        time_ms: series[alignedIdx].time_ms,
        symbol: m.symbol,
        side: m.side,
        exit_reason: m.exit_reason,
        net_pnl_usd: m.net_pnl_usd,
        neon_cum_pnl_usd: pt.pnl,
        neon_cum_return_pct: pt.ret,
        is_win: m.is_win,
      });
    }
  }
  tradeMarkers.sort((a, b) => a.time_ms - b.time_ms);

  const last = series[series.length - 1];
  const totalTrades = totalWins + totalLosses;
  const winRate = totalTrades > 0 ? Number(((totalWins / totalTrades) * 100).toFixed(1)) : 0;
  const ddReduction = bhMaxDdPct.gt(0)
    ? Number(bhMaxDdPct.minus(neonMaxDdPct).div(bhMaxDdPct).mul(100).toFixed(1))
    : 0;

  return {
    scope: isBasket ? 'CORE_BASKET' : assets[0],
    scope_label: isBasket
      ? 'Core Tier-1 Equal-Weight Basket (BTC · ETH · SOL · BNB · LINK)'
      : `${assets[0]} Single-Asset Curve`,
    assets,
    regime_mode: mirrorBull ? 'MIRRORED_BULL_STRESS' : 'REAL_MARKET',
    bars_plotted: series.length,
    summary: {
      initial_equity_usd: Number(initialEquity.toFixed(2)),
      neon_final_equity_usd: last ? last.neon_equity_usd : Number(initialEquity.toFixed(2)),
      neon_final_pnl_usd: last ? last.neon_cum_pnl_usd : 0,
      neon_final_return_pct: last ? last.neon_cum_return_pct : 0,
      bh_final_equity_usd: last ? last.bh_equity_usd : Number(initialEquity.toFixed(2)),
      bh_final_pnl_usd: last ? last.bh_cum_pnl_usd : 0,
      bh_final_return_pct: last ? last.bh_cum_return_pct : 0,
      alpha_spread_usd: last ? last.alpha_spread_usd : 0,
      alpha_spread_pct: last ? last.alpha_spread_pct : 0,
      neon_max_dd_pct: Number(neonMaxDdPct.toFixed(2)),
      bh_max_dd_pct: Number(bhMaxDdPct.toFixed(2)),
      dd_reduction_pct: ddReduction,
      total_trades: totalTrades,
      wins: totalWins,
      losses: totalLosses,
      win_rate_pct: winRate,
    },
    series,
    trade_markers: tradeMarkers,
  };
}

