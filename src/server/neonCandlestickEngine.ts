import Decimal from 'decimal.js';
import { Candle, fetchBinanceKlinesWithFallback } from './dataStore.js';
import { NEON_CORE_UNIVERSE } from './neonStrategy.js';

// ============================================================================
// NEON TOP 25 CANDLESTICK CONFLUENCE ENGINE
//
// Evaluates all 25 classic candlestick formations normalized by ATR(14) and
// relative volume (Vol / SMA20) over real tail-sliced (<= 512 bar) OHLCV data.
// Supports 3 decision modes:
//   - OFF: Baseline Kronos + NEON 6-Gate without candlestick modifier
//   - VETO_CONFIRM: Institutional Anti-Knife Veto + Maker Limit Switch + Exit Ratchet
//   - DIRECT_TRIGGER: Raw standalone Top-25 entry voter (empirical overtrading stress)
// ============================================================================

export type CandlestickDecisionMode = 'OFF' | 'VETO_CONFIRM' | 'DIRECT_TRIGGER';
export type CandlestickBias = 'BULLISH' | 'BEARISH' | 'INDECISION';
export type CandlestickFamily = 'REVERSAL' | 'MOMENTUM' | 'CONTINUATION' | 'COMPRESSION' | 'EXHAUSTION';
export type CandlestickTier = 'TIER_1_CORE' | 'TIER_2_SECONDARY' | 'VETO_ONLY';

export interface CandlestickPatternDefinition {
  id: string;
  rank: number;
  name: string;
  bias: CandlestickBias;
  family: CandlestickFamily;
  tier: CandlestickTier;
  bars_required: 1 | 2 | 3 | 5;
  base_weight: number; // Contribution weight when ATR + Vol confirmed
  neon_role: string;
  description: string;
}

export interface CandlestickPatternMetric extends CandlestickPatternDefinition {
  detected_recently: boolean;
  bars_ago: number | null; // 0 = latest closed candle, 1..4 = recent bars
  latest_vol_ratio: number | null;
  latest_body_atr: number | null;
  active_score: number; // Signed contribution to composite score (-100..+100)
  occurrences_512: number;
  forward_3bar_hit_rate_pct: number;
  avg_3bar_move_atr: number;
  avg_rel_volume: number;
}

export interface SymbolCandlestickSummary {
  symbol: string;
  interval: string;
  bars_analyzed: number;
  last_close: number;
  atr_14_pct: number;
  rel_volume: number;
  composite_score: number; // -100 (strong bearish) to +100 (strong bullish)
  bias_label: 'STRONG_BULLISH' | 'BULLISH' | 'NEUTRAL' | 'BEARISH' | 'STRONG_BEARISH';
  bullish_active_count: number;
  bearish_active_count: number;
  indecision_active_count: number;
  top_pattern_name: string;
  top_pattern_bias: CandlestickBias | 'NONE';
  top_pattern_bars_ago: number | null;
  gate_action:
    | 'CONFIRM_LONG'
    | 'CONFIRM_SHORT'
    | 'VETO_LONG_KNIFE'
    | 'VETO_SHORT_SQUEEZE'
    | 'POST_MAKER_LIMIT'
    | 'TIGHTEN_STOP_DOJI'
    | 'NEUTRAL_PASS';
  gate_reason: string;
}

export interface CandlestickModeBenchmark {
  mode: CandlestickDecisionMode;
  label: string;
  role_summary: string;
  net_pnl_usd: number;
  return_pct: number;
  mc_p50_pnl_usd: number;
  mc_p50_return_pct: number;
  mc_win_prob_pct: number;
  mc_median_dd_pct: number;
  delta_mc_p50_vs_off_usd: number;
  trades: number;
  win_rate_pct: number;
  profit_factor: number;
  max_drawdown_pct: number;
  fee_drag_pct: number;
  fee_bps: number;
  slippage_bps: number;
  total_friction_bps: number;
  calibration_score_pct: number;
  delta_pnl_vs_off_usd: number;
  recommended: boolean;
}

export interface NeonCandlestickPayload {
  timestamp_utc: string;
  selected_symbol: string;
  interval: '15m' | '1h' | '4h';
  active_mode: CandlestickDecisionMode;
  selected_summary: SymbolCandlestickSummary;
  fleet_summaries: SymbolCandlestickSummary[];
  patterns: CandlestickPatternMetric[];
  mode_benchmarks?: CandlestickModeBenchmark[];
}

export const TOP_25_CANDLESTICK_CATALOG: CandlestickPatternDefinition[] = [
  // --- BULLISH (11) ---
  {
    id: 'BULLISH_ENGULFING',
    rank: 1,
    name: 'Bullish Engulfing',
    bias: 'BULLISH',
    family: 'REVERSAL',
    tier: 'TIER_1_CORE',
    bars_required: 2,
    base_weight: 26,
    neon_role: 'Confirm Long / Veto Short',
    description: 'Green real body completely swallows prior red body after a downswing with expanding volume.',
  },
  {
    id: 'HAMMER',
    rank: 2,
    name: 'Hammer (Pin Bar)',
    bias: 'BULLISH',
    family: 'REVERSAL',
    tier: 'TIER_1_CORE',
    bars_required: 1,
    base_weight: 22,
    neon_role: 'Post Maker Limit Retest',
    description: 'Long lower rejection wick (>= 2x body) rejecting lows; signals trapped shorts.',
  },
  {
    id: 'MORNING_STAR',
    rank: 3,
    name: 'Morning Star',
    bias: 'BULLISH',
    family: 'REVERSAL',
    tier: 'TIER_1_CORE',
    bars_required: 3,
    base_weight: 28,
    neon_role: 'Confirm Long / Tighten Short SL',
    description: '3-bar bottoming sequence: strong red bar, small indecision star, strong green recovery above midpoint.',
  },
  {
    id: 'BULLISH_MARUBOZU',
    rank: 4,
    name: 'Bullish Marubozu',
    bias: 'BULLISH',
    family: 'MOMENTUM',
    tier: 'TIER_1_CORE',
    bars_required: 1,
    base_weight: 24,
    neon_role: 'Breakout Confirmation',
    description: 'Full-body green expansion bar (>= 0.85x ATR) closing near high with minimal wicks.',
  },
  {
    id: 'THREE_WHITE_SOLDIERS',
    rank: 5,
    name: 'Three White Soldiers',
    bias: 'BULLISH',
    family: 'CONTINUATION',
    tier: 'TIER_1_CORE',
    bars_required: 3,
    base_weight: 25,
    neon_role: 'Trend Continuation Confirm',
    description: 'Three consecutive strong green closes stepping higher with controlled upper wicks.',
  },
  {
    id: 'PIERCING_LINE',
    rank: 6,
    name: 'Piercing Line',
    bias: 'BULLISH',
    family: 'REVERSAL',
    tier: 'TIER_2_SECONDARY',
    bars_required: 2,
    base_weight: 16,
    neon_role: 'Secondary Long Confirm',
    description: 'Green candle opens below prior close/low and recovers past 50% of prior red real body.',
  },
  {
    id: 'INVERTED_HAMMER',
    rank: 7,
    name: 'Inverted Hammer',
    bias: 'BULLISH',
    family: 'REVERSAL',
    tier: 'TIER_2_SECONDARY',
    bars_required: 1,
    base_weight: 12,
    neon_role: 'Watch Next-Bar Confirmation',
    description: 'Small body near lows with long upper probe after decline; requires bullish follow-through.',
  },
  {
    id: 'BULLISH_HARAMI',
    rank: 8,
    name: 'Bullish Harami',
    bias: 'BULLISH',
    family: 'COMPRESSION',
    tier: 'TIER_2_SECONDARY',
    bars_required: 2,
    base_weight: 13,
    neon_role: 'Post Maker Limit / Pause Short',
    description: 'Small green body fully contained inside prior large red body indicating selling exhaustion.',
  },
  {
    id: 'TWEEZER_BOTTOM',
    rank: 9,
    name: 'Tweezer Bottom',
    bias: 'BULLISH',
    family: 'REVERSAL',
    tier: 'TIER_2_SECONDARY',
    bars_required: 2,
    base_weight: 15,
    neon_role: 'Support Floor Confirm',
    description: 'Two consecutive bars defending nearly identical lows (<= 0.15x ATR) with bullish turn.',
  },
  {
    id: 'RISING_THREE_METHODS',
    rank: 10,
    name: 'Rising Three Methods',
    bias: 'BULLISH',
    family: 'CONTINUATION',
    tier: 'TIER_2_SECONDARY',
    bars_required: 5,
    base_weight: 18,
    neon_role: 'Pullback Resumption Confirm',
    description: 'Strong green impulse, 3 small controlled counter-bars inside range, then green breakout close.',
  },
  {
    id: 'BULLISH_KICKER',
    rank: 11,
    name: 'Bullish Kicker',
    bias: 'BULLISH',
    family: 'MOMENTUM',
    tier: 'TIER_2_SECONDARY',
    bars_required: 2,
    base_weight: 20,
    neon_role: 'Veto Short Immediately',
    description: 'Sharp sentiment flip from strong red candle straight into a strong expanding green candle.',
  },

  // --- BEARISH (11) ---
  {
    id: 'BEARISH_ENGULFING',
    rank: 12,
    name: 'Bearish Engulfing',
    bias: 'BEARISH',
    family: 'REVERSAL',
    tier: 'TIER_1_CORE',
    bars_required: 2,
    base_weight: 26,
    neon_role: 'Veto Long Knife / Confirm Short',
    description: 'Red real body completely swallows prior green body after an upswing with elevated volume.',
  },
  {
    id: 'SHOOTING_STAR',
    rank: 13,
    name: 'Shooting Star (Rejection)',
    bias: 'BEARISH',
    family: 'REVERSAL',
    tier: 'TIER_1_CORE',
    bars_required: 1,
    base_weight: 22,
    neon_role: 'Veto Long / Post Short Maker',
    description: 'Long upper rejection wick (>= 2x body) rejecting highs after an upward move.',
  },
  {
    id: 'EVENING_STAR',
    rank: 14,
    name: 'Evening Star',
    bias: 'BEARISH',
    family: 'REVERSAL',
    tier: 'TIER_1_CORE',
    bars_required: 3,
    base_weight: 28,
    neon_role: 'Veto Long / Ratchet Long TP',
    description: '3-bar topping reversal: strong green bar, small star bar, decisive red close past midpoint.',
  },
  {
    id: 'BEARISH_MARUBOZU',
    rank: 15,
    name: 'Bearish Marubozu',
    bias: 'BEARISH',
    family: 'MOMENTUM',
    tier: 'TIER_1_CORE',
    bars_required: 1,
    base_weight: 24,
    neon_role: 'Breakdown Confirm / Veto Long',
    description: 'Full-body red expansion bar (>= 0.85x ATR) closing near low with minimal lower wick.',
  },
  {
    id: 'THREE_BLACK_CROWS',
    rank: 16,
    name: 'Three Black Crows',
    bias: 'BEARISH',
    family: 'CONTINUATION',
    tier: 'TIER_1_CORE',
    bars_required: 3,
    base_weight: 25,
    neon_role: 'Short Continuation Confirm',
    description: 'Three consecutive strong red closes stepping lower showing sustained distribution.',
  },
  {
    id: 'DARK_CLOUD_COVER',
    rank: 17,
    name: 'Dark Cloud Cover',
    bias: 'BEARISH',
    family: 'REVERSAL',
    tier: 'TIER_2_SECONDARY',
    bars_required: 2,
    base_weight: 16,
    neon_role: 'Tighten Long Stop / Confirm Short',
    description: 'Red candle opens near/above prior high and slices past 50% of prior green real body.',
  },
  {
    id: 'HANGING_MAN',
    rank: 18,
    name: 'Hanging Man',
    bias: 'BEARISH',
    family: 'REVERSAL',
    tier: 'TIER_2_SECONDARY',
    bars_required: 1,
    base_weight: 12,
    neon_role: 'Exhaustion Caution on Longs',
    description: 'Hammer-shaped candle printing at local swing highs warning of buyer fatigue.',
  },
  {
    id: 'BEARISH_HARAMI',
    rank: 19,
    name: 'Bearish Harami',
    bias: 'BEARISH',
    family: 'COMPRESSION',
    tier: 'TIER_2_SECONDARY',
    bars_required: 2,
    base_weight: 13,
    neon_role: 'Pause Long Chase / Maker Limit',
    description: 'Small red real body enclosed inside prior large green bar signaling upside momentum stall.',
  },
  {
    id: 'TWEEZER_TOP',
    rank: 20,
    name: 'Tweezer Top',
    bias: 'BEARISH',
    family: 'REVERSAL',
    tier: 'TIER_2_SECONDARY',
    bars_required: 2,
    base_weight: 15,
    neon_role: 'Resistance Ceiling Veto',
    description: 'Two consecutive bars rejected at nearly identical highs (<= 0.15x ATR) turning red.',
  },
  {
    id: 'FALLING_THREE_METHODS',
    rank: 21,
    name: 'Falling Three Methods',
    bias: 'BEARISH',
    family: 'CONTINUATION',
    tier: 'TIER_2_SECONDARY',
    bars_required: 5,
    base_weight: 18,
    neon_role: 'Short Resumption Confirm',
    description: 'Strong red impulse, 3 small controlled bounce bars inside range, then red breakdown close.',
  },
  {
    id: 'BEARISH_KICKER',
    rank: 22,
    name: 'Bearish Kicker',
    bias: 'BEARISH',
    family: 'MOMENTUM',
    tier: 'TIER_2_SECONDARY',
    bars_required: 2,
    base_weight: 20,
    neon_role: 'Veto Long Immediately',
    description: 'Abrupt reversal from strong green bar into an immediate heavy red impulse bar.',
  },

  // --- INDECISION / WARNING / COMPRESSION (3) ---
  {
    id: 'DOJI_STAR',
    rank: 23,
    name: 'Doji / Spinning Top',
    bias: 'INDECISION',
    family: 'EXHAUSTION',
    tier: 'VETO_ONLY',
    bars_required: 1,
    base_weight: 10,
    neon_role: 'Skip Market Entry / Tighten SL',
    description: 'Tiny real body (<= 14% of range) with balanced wicks signaling equilibrium and chop risk.',
  },
  {
    id: 'DRAGONFLY_GRAVESTONE_DOJI',
    rank: 24,
    name: 'Dragonfly / Gravestone Doji',
    bias: 'INDECISION',
    family: 'EXHAUSTION',
    tier: 'VETO_ONLY',
    bars_required: 1,
    base_weight: 14,
    neon_role: 'Wick Sweep Warning / Maker Only',
    description: 'Near-zero body with extreme one-sided rejection wick (>= 65% of bar range).',
  },
  {
    id: 'INSIDE_BAR_SQUEEZE',
    rank: 25,
    name: 'Inside-Bar Squeeze',
    bias: 'INDECISION',
    family: 'COMPRESSION',
    tier: 'VETO_ONLY',
    bars_required: 2,
    base_weight: 12,
    neon_role: 'Switch Entry to Passive Maker',
    description: 'Current high/low strictly inside prior bar range; signals volatility compression before expansion.',
  },
];

export function normalizeCandlestickMode(raw?: string): CandlestickDecisionMode {
  const s = String(raw || 'OFF').toUpperCase();
  if (s === 'VETO_CONFIRM' || s === 'VETO' || s === 'GATE') return 'VETO_CONFIRM';
  if (s === 'DIRECT_TRIGGER' || s === 'TRIGGER' || s === 'RAW_25') return 'DIRECT_TRIGGER';
  return 'OFF';
}

function calcAtr14(candles: Candle[]): number[] {
  const n = candles.length;
  if (n === 0) return [];
  const tr = new Array<number>(n);
  for (let i = 0; i < n; i++) {
    if (i === 0) {
      tr[i] = Math.max(1e-9, candles[i].high - candles[i].low);
    } else {
      const pc = candles[i - 1].close;
      tr[i] = Math.max(
        1e-9,
        candles[i].high - candles[i].low,
        Math.abs(candles[i].high - pc),
        Math.abs(candles[i].low - pc)
      );
    }
  }
  const k = 2 / (14 + 1);
  const atr = new Array<number>(n);
  atr[0] = tr[0];
  for (let i = 1; i < n; i++) {
    atr[i] = tr[i] * k + atr[i - 1] * (1 - k);
  }
  return atr;
}

function calcVolSma20(candles: Candle[]): number[] {
  const n = candles.length;
  const out = new Array<number>(n).fill(1);
  let sum = 0;
  for (let i = 0; i < n; i++) {
    sum += candles[i].volume || 0;
    if (i >= 20) sum -= candles[i - 20].volume || 0;
    const denom = Math.min(20, i + 1);
    out[i] = Math.max(1e-9, sum / denom);
  }
  return out;
}

function barGeom(c: Candle) {
  const range = Math.max(1e-9, c.high - c.low);
  const body = Math.abs(c.close - c.open);
  const isBull = c.close > c.open;
  const isBear = c.close < c.open;
  const bodyTop = Math.max(c.open, c.close);
  const bodyBot = Math.min(c.open, c.close);
  const upperWick = Math.max(0, c.high - bodyTop);
  const lowerWick = Math.max(0, bodyBot - c.low);
  const mid = (c.open + c.close) / 2;
  return { range, body, isBull, isBear, bodyTop, bodyBot, upperWick, lowerWick, mid };
}

function isLocalDowntrend(candles: Candle[], i: number): boolean {
  if (i < 4) return false;
  return candles[i - 1].close < candles[i - 4].close;
}

function isLocalUptrend(candles: Candle[], i: number): boolean {
  if (i < 4) return false;
  return candles[i - 1].close > candles[i - 4].close;
}

/**
 * Pure geometric + ATR-normalized detector for all 25 patterns at candle index i.
 */
function detectPatternAtIndex(
  patternId: string,
  candles: Candle[],
  atr: number[],
  i: number
): boolean {
  const c0 = candles[i];
  const a0 = Math.max(1e-9, atr[i] || c0.close * 0.005);
  const g0 = barGeom(c0);

  const c1 = i >= 1 ? candles[i - 1] : null;
  const g1 = c1 ? barGeom(c1) : null;
  const c2 = i >= 2 ? candles[i - 2] : null;
  const g2 = c2 ? barGeom(c2) : null;

  switch (patternId) {
    // --- BULLISH (11) ---
    case 'BULLISH_ENGULFING':
      return Boolean(
        c1 &&
          g1 &&
          g1.isBear &&
          g0.isBull &&
          g0.body >= 0.45 * a0 &&
          g1.body >= 0.2 * a0 &&
          c0.close >= g1.bodyTop &&
          c0.open <= g1.bodyBot + 0.1 * a0 &&
          isLocalDowntrend(candles, i)
      );

    case 'HAMMER':
      return Boolean(
        g0.body > 0 &&
          g0.body <= 0.45 * g0.range &&
          g0.lowerWick >= 2.0 * g0.body &&
          g0.upperWick <= 0.6 * g0.body &&
          g0.range >= 0.65 * a0 &&
          isLocalDowntrend(candles, i)
      );

    case 'MORNING_STAR':
      return Boolean(
        c1 &&
          c2 &&
          g1 &&
          g2 &&
          g2.isBear &&
          g2.body >= 0.55 * a0 &&
          g1.body <= 0.35 * g2.body &&
          g0.isBull &&
          g0.body >= 0.45 * a0 &&
          c0.close >= g2.mid
      );

    case 'BULLISH_MARUBOZU':
      return Boolean(
        g0.isBull &&
          g0.body >= 0.85 * a0 &&
          g0.body >= 0.78 * g0.range &&
          g0.upperWick <= 0.12 * g0.range
      );

    case 'THREE_WHITE_SOLDIERS':
      return Boolean(
        c1 &&
          c2 &&
          g1 &&
          g2 &&
          g2.isBull &&
          g1.isBull &&
          g0.isBull &&
          g2.body >= 0.35 * a0 &&
          g1.body >= 0.35 * a0 &&
          g0.body >= 0.35 * a0 &&
          c1.close > c2.close &&
          c0.close > c1.close &&
          g0.upperWick <= 0.3 * g0.range
      );

    case 'PIERCING_LINE':
      return Boolean(
        c1 &&
          g1 &&
          g1.isBear &&
          g1.body >= 0.5 * a0 &&
          g0.isBull &&
          c0.low <= c1.low &&
          c0.close > g1.mid &&
          c0.close < g1.bodyTop &&
          isLocalDowntrend(candles, i)
      );

    case 'INVERTED_HAMMER':
      return Boolean(
        g0.body > 0 &&
          g0.body <= 0.42 * g0.range &&
          g0.upperWick >= 2.0 * g0.body &&
          g0.lowerWick <= 0.55 * g0.body &&
          g0.range >= 0.6 * a0 &&
          isLocalDowntrend(candles, i)
      );

    case 'BULLISH_HARAMI':
      return Boolean(
        c1 &&
          g1 &&
          g1.isBear &&
          g1.body >= 0.65 * a0 &&
          g0.isBull &&
          g0.body <= 0.5 * g1.body &&
          g0.bodyTop <= g1.bodyTop &&
          g0.bodyBot >= g1.bodyBot
      );

    case 'TWEEZER_BOTTOM':
      return Boolean(
        c1 &&
          g1 &&
          g1.isBear &&
          g0.isBull &&
          Math.abs(c0.low - c1.low) <= 0.16 * a0 &&
          g0.body >= 0.3 * a0 &&
          isLocalDowntrend(candles, i)
      );

    case 'RISING_THREE_METHODS': {
      if (i < 4) return false;
      const c4 = candles[i - 4];
      const g4 = barGeom(c4);
      if (!g4.isBull || g4.body < 0.7 * a0 || !g0.isBull || c0.close <= c4.close) return false;
      const mid3 = [candles[i - 3], candles[i - 2], candles[i - 1]];
      return mid3.every((m) => m.low >= c4.low && m.high <= c4.high * 1.003);
    }

    case 'BULLISH_KICKER':
      return Boolean(
        c1 &&
          g1 &&
          g1.isBear &&
          g1.body >= 0.6 * a0 &&
          g0.isBull &&
          g0.body >= 0.75 * a0 &&
          c0.close > c1.high
      );

    // --- BEARISH (11) ---
    case 'BEARISH_ENGULFING':
      return Boolean(
        c1 &&
          g1 &&
          g1.isBull &&
          g0.isBear &&
          g0.body >= 0.45 * a0 &&
          g1.body >= 0.2 * a0 &&
          c0.close <= g1.bodyBot &&
          c0.open >= g1.bodyTop - 0.1 * a0 &&
          isLocalUptrend(candles, i)
      );

    case 'SHOOTING_STAR':
      return Boolean(
        g0.body > 0 &&
          g0.body <= 0.45 * g0.range &&
          g0.upperWick >= 2.0 * g0.body &&
          g0.lowerWick <= 0.6 * g0.body &&
          g0.range >= 0.65 * a0 &&
          isLocalUptrend(candles, i)
      );

    case 'EVENING_STAR':
      return Boolean(
        c1 &&
          c2 &&
          g1 &&
          g2 &&
          g2.isBull &&
          g2.body >= 0.55 * a0 &&
          g1.body <= 0.35 * g2.body &&
          g0.isBear &&
          g0.body >= 0.45 * a0 &&
          c0.close <= g2.mid
      );

    case 'BEARISH_MARUBOZU':
      return Boolean(
        g0.isBear &&
          g0.body >= 0.85 * a0 &&
          g0.body >= 0.78 * g0.range &&
          g0.lowerWick <= 0.12 * g0.range
      );

    case 'THREE_BLACK_CROWS':
      return Boolean(
        c1 &&
          c2 &&
          g1 &&
          g2 &&
          g2.isBear &&
          g1.isBear &&
          g0.isBear &&
          g2.body >= 0.35 * a0 &&
          g1.body >= 0.35 * a0 &&
          g0.body >= 0.35 * a0 &&
          c1.close < c2.close &&
          c0.close < c1.close &&
          g0.lowerWick <= 0.3 * g0.range
      );

    case 'DARK_CLOUD_COVER':
      return Boolean(
        c1 &&
          g1 &&
          g1.isBull &&
          g1.body >= 0.5 * a0 &&
          g0.isBear &&
          c0.high >= c1.high &&
          c0.close < g1.mid &&
          c0.close > g1.bodyBot &&
          isLocalUptrend(candles, i)
      );

    case 'HANGING_MAN':
      return Boolean(
        g0.body > 0 &&
          g0.body <= 0.42 * g0.range &&
          g0.lowerWick >= 2.0 * g0.body &&
          g0.upperWick <= 0.55 * g0.body &&
          g0.range >= 0.6 * a0 &&
          isLocalUptrend(candles, i)
      );

    case 'BEARISH_HARAMI':
      return Boolean(
        c1 &&
          g1 &&
          g1.isBull &&
          g1.body >= 0.65 * a0 &&
          g0.isBear &&
          g0.body <= 0.5 * g1.body &&
          g0.bodyTop <= g1.bodyTop &&
          g0.bodyBot >= g1.bodyBot
      );

    case 'TWEEZER_TOP':
      return Boolean(
        c1 &&
          g1 &&
          g1.isBull &&
          g0.isBear &&
          Math.abs(c0.high - c1.high) <= 0.16 * a0 &&
          g0.body >= 0.3 * a0 &&
          isLocalUptrend(candles, i)
      );

    case 'FALLING_THREE_METHODS': {
      if (i < 4) return false;
      const c4 = candles[i - 4];
      const g4 = barGeom(c4);
      if (!g4.isBear || g4.body < 0.7 * a0 || !g0.isBear || c0.close >= c4.close) return false;
      const mid3 = [candles[i - 3], candles[i - 2], candles[i - 1]];
      return mid3.every((m) => m.high <= c4.high && m.low >= c4.low * 0.997);
    }

    case 'BEARISH_KICKER':
      return Boolean(
        c1 &&
          g1 &&
          g1.isBull &&
          g1.body >= 0.6 * a0 &&
          g0.isBear &&
          g0.body >= 0.75 * a0 &&
          c0.close < c1.low
      );

    // --- INDECISION / WARNING / COMPRESSION (3) ---
    case 'DOJI_STAR':
      return Boolean(
        g0.body <= 0.14 * g0.range &&
          g0.range >= 0.45 * a0 &&
          g0.upperWick >= 0.22 * g0.range &&
          g0.lowerWick >= 0.22 * g0.range
      );

    case 'DRAGONFLY_GRAVESTONE_DOJI':
      return Boolean(
        g0.body <= 0.15 * g0.range &&
          g0.range >= 0.55 * a0 &&
          (g0.lowerWick >= 0.65 * g0.range || g0.upperWick >= 0.65 * g0.range)
      );

    case 'INSIDE_BAR_SQUEEZE':
      return Boolean(
        c1 &&
          c0.high <= c1.high &&
          c0.low >= c1.low &&
          g0.range <= 0.72 * Math.max(1e-9, c1.high - c1.low)
      );

    default:
      return false;
  }
}

export function analyzeSymbolCandlesticks(
  symbol: string,
  interval: '15m' | '1h' | '4h',
  rawCandles: Candle[]
): { summary: SymbolCandlestickSummary; patterns: CandlestickPatternMetric[] } {
  // Mandatory Kronos Context Slicing Contract: ALWAYS slice from tail <= 512 bars
  const candles = rawCandles.slice(-512);
  const n = candles.length;
  const atr = calcAtr14(candles);
  const volSma = calcVolSma20(candles);

  const lastIdx = Math.max(0, n - 1);
  const lastCandle = candles[lastIdx] || {
    timestamp: Date.now(),
    open: 100,
    high: 100,
    low: 100,
    close: 100,
    volume: 1,
  };
  const lastAtr = atr[lastIdx] || lastCandle.close * 0.01;
  const lastAtrPct = lastCandle.close > 0 ? (lastAtr / lastCandle.close) * 100 : 1;
  const lastRelVol = volSma[lastIdx] > 0 ? (lastCandle.volume || 0) / volSma[lastIdx] : 1;

  const recentLookback = 5; // Active detection window: last 5 closed bars
  const patterns: CandlestickPatternMetric[] = [];

  let compositeScoreD = new Decimal(0);
  let bullActive = 0;
  let bearActive = 0;
  let indActive = 0;
  let hasMakerPattern = false;
  let hasDojiWarning = false;

  for (const def of TOP_25_CANDLESTICK_CATALOG) {
    let occurrences = 0;
    let hits = 0;
    let evalCount = 0;
    let sumAtrMove = 0;
    let sumRelVol = 0;

    let recentBarsAgo: number | null = null;
    let recentVolRatio: number | null = null;
    let recentBodyAtr: number | null = null;

    for (let i = Math.max(4, def.bars_required); i < n; i++) {
      if (!detectPatternAtIndex(def.id, candles, atr, i)) continue;
      occurrences += 1;

      const rv = volSma[i] > 0 ? (candles[i].volume || 0) / volSma[i] : 1;
      const bodyAtr = atr[i] > 0 ? Math.abs(candles[i].close - candles[i].open) / atr[i] : 0;
      sumRelVol += rv;

      // Track most recent detection inside last 5 bars
      const barsAgo = lastIdx - i;
      if (barsAgo < recentLookback) {
        recentBarsAgo = barsAgo;
        recentVolRatio = rv;
        recentBodyAtr = bodyAtr;
      }

      // Forward 3-bar empirical hit-rate evaluation
      if (i + 3 < n) {
        evalCount += 1;
        const fwdDiff = candles[i + 3].close - candles[i].close;
        const fwdAtrMove = atr[i] > 0 ? fwdDiff / atr[i] : 0;
        if (def.bias === 'BULLISH') {
          if (fwdDiff > 0) hits += 1;
          sumAtrMove += fwdAtrMove;
        } else if (def.bias === 'BEARISH') {
          if (fwdDiff < 0) hits += 1;
          sumAtrMove += -fwdAtrMove;
        } else {
          // For indecision/compression, measure whether volatility expanded > 0.8 ATR within 3 bars
          const hi3 = Math.max(candles[i + 1].high, candles[i + 2].high, candles[i + 3].high);
          const lo3 = Math.min(candles[i + 1].low, candles[i + 2].low, candles[i + 3].low);
          const expAtr = atr[i] > 0 ? (hi3 - lo3) / atr[i] : 0;
          if (expAtr >= 1.2) hits += 1;
          sumAtrMove += expAtr;
        }
      }
    }

    const detectedRecently = recentBarsAgo !== null;
    let activeScore = 0;

    if (detectedRecently && recentBarsAgo !== null) {
      // Recency decay: bar 0 = 1.0x, bar 1 = 0.82x, bar 2 = 0.65x, bar 3 = 0.48x, bar 4 = 0.35x
      const decayTable = [1.0, 0.82, 0.65, 0.48, 0.35];
      const recencyMult = decayTable[Math.min(decayTable.length - 1, recentBarsAgo)];
      const volBoost = Math.min(1.45, Math.max(0.65, recentVolRatio ?? 1.0));
      const rawScoreD = new Decimal(String(def.base_weight))
        .mul(new Decimal(String(recencyMult)))
        .mul(new Decimal(String(volBoost)));

      if (def.bias === 'BULLISH') {
        activeScore = Number(rawScoreD.toFixed(1));
        compositeScoreD = compositeScoreD.plus(rawScoreD);
        bullActive += 1;
      } else if (def.bias === 'BEARISH') {
        activeScore = -Number(rawScoreD.toFixed(1));
        compositeScoreD = compositeScoreD.minus(rawScoreD);
        bearActive += 1;
      } else {
        activeScore = 0;
        indActive += 1;
      }

      if (
        def.id === 'HAMMER' ||
        def.id === 'SHOOTING_STAR' ||
        def.id === 'INSIDE_BAR_SQUEEZE' ||
        def.id === 'BULLISH_HARAMI' ||
        def.id === 'BEARISH_HARAMI'
      ) {
        hasMakerPattern = true;
      }
      if (def.id === 'DOJI_STAR' || def.id === 'DRAGONFLY_GRAVESTONE_DOJI') {
        hasDojiWarning = true;
      }
    }

    const hitRatePct =
      evalCount > 0
        ? Number(new Decimal(hits).div(evalCount).mul(100).toFixed(1))
        : 0;
    const avgAtrMove =
      evalCount > 0
        ? Number(new Decimal(String(sumAtrMove)).div(evalCount).toFixed(2))
        : 0;
    const avgRelVol =
      occurrences > 0
        ? Number(new Decimal(String(sumRelVol)).div(occurrences).toFixed(2))
        : 0;

    patterns.push({
      ...def,
      detected_recently: detectedRecently,
      bars_ago: recentBarsAgo,
      latest_vol_ratio: recentVolRatio !== null ? Number(recentVolRatio.toFixed(2)) : null,
      latest_body_atr: recentBodyAtr !== null ? Number(recentBodyAtr.toFixed(2)) : null,
      active_score: activeScore,
      occurrences_512: occurrences,
      forward_3bar_hit_rate_pct: hitRatePct,
      avg_3bar_move_atr: avgAtrMove,
      avg_rel_volume: avgRelVol,
    });
  }

  // Clamp composite score to [-100, +100]
  const clampedScore = Number(Decimal.max(-100, Decimal.min(100, compositeScoreD)).toFixed(1));

  let biasLabel: SymbolCandlestickSummary['bias_label'] = 'NEUTRAL';
  if (clampedScore >= 35) biasLabel = 'STRONG_BULLISH';
  else if (clampedScore >= 14) biasLabel = 'BULLISH';
  else if (clampedScore <= -35) biasLabel = 'STRONG_BEARISH';
  else if (clampedScore <= -14) biasLabel = 'BEARISH';

  // Pick dominant active pattern (highest |active_score|, fallback to most recent indecision)
  const activePatterns = patterns
    .filter((p) => p.detected_recently)
    .sort((a, b) => {
      const diff = Math.abs(b.active_score) - Math.abs(a.active_score);
      if (Math.abs(diff) > 0.01) return diff;
      return (a.bars_ago ?? 9) - (b.bars_ago ?? 9);
    });
  const topPat = activePatterns[0] || null;

  // Institutional NEON Veto/Confirmation Gate Verdict
  let gateAction: SymbolCandlestickSummary['gate_action'] = 'NEUTRAL_PASS';
  let gateReason = 'No conflicting reversal formation — defer to Kronos 6-Gate trend & session filter.';

  if (clampedScore <= -26) {
    gateAction = 'VETO_LONG_KNIFE';
    gateReason = `${topPat?.name || 'Bearish reversal'} (${clampedScore} bias) blocks Long entries & tightens open Long SL.`;
  } else if (clampedScore >= 26) {
    gateAction = 'VETO_SHORT_SQUEEZE';
    gateReason = `${topPat?.name || 'Bullish impulse'} (+${clampedScore} bias) blocks Short entries & confirms Long pullback.`;
  } else if (hasMakerPattern && Math.abs(clampedScore) < 26) {
    gateAction = 'POST_MAKER_LIMIT';
    gateReason = `${topPat?.name || 'Compression/Pin-bar'} detected — route NEON-6 passive Maker limit to cut fee drag.`;
  } else if (hasDojiWarning) {
    gateAction = 'TIGHTEN_STOP_DOJI';
    gateReason = 'Indecision Doji/Wick sweep printed — skip market chase & ratchet active trailing stops.';
  } else if (clampedScore >= 14) {
    gateAction = 'CONFIRM_LONG';
    gateReason = `Bullish candle structure (+${clampedScore}) aligns with trend resumption; allow Maker-first Long.`;
  } else if (clampedScore <= -14) {
    gateAction = 'CONFIRM_SHORT';
    gateReason = `Bearish candle structure (${clampedScore}) aligns with downward drift; allow Maker-first Short.`;
  }

  return {
    summary: {
      symbol,
      interval,
      bars_analyzed: n,
      last_close: Number(new Decimal(String(lastCandle.close)).toPrecision(6)),
      atr_14_pct: Number(lastAtrPct.toFixed(2)),
      rel_volume: Number(lastRelVol.toFixed(2)),
      composite_score: clampedScore,
      bias_label: biasLabel,
      bullish_active_count: bullActive,
      bearish_active_count: bearActive,
      indecision_active_count: indActive,
      top_pattern_name: topPat ? topPat.name : 'No Active Pattern (5 bars)',
      top_pattern_bias: topPat ? topPat.bias : 'NONE',
      top_pattern_bars_ago: topPat ? topPat.bars_ago : null,
      gate_action: gateAction,
      gate_reason: gateReason,
    },
    patterns,
  };
}

export async function scanNeonCandlestickUniverse(options: {
  symbol?: string;
  interval?: string;
  active_mode?: CandlestickDecisionMode | string;
}): Promise<NeonCandlestickPayload> {
  const intervalRaw = String(options.interval || '1h').toLowerCase();
  const interval: '15m' | '1h' | '4h' =
    intervalRaw === '15m' ? '15m' : intervalRaw === '4h' ? '4h' : '1h';
  const requestedSym = String(options.symbol || 'BTCUSDT').toUpperCase();
  const selectedSymbol = (NEON_CORE_UNIVERSE as readonly string[]).includes(requestedSym)
    ? requestedSym
    : 'BTCUSDT';
  const activeMode = normalizeCandlestickMode(options.active_mode);

  const results = await Promise.all(
    NEON_CORE_UNIVERSE.map(async (sym) => {
      const { candles } = await fetchBinanceKlinesWithFallback(sym, interval, 512);
      return analyzeSymbolCandlesticks(sym, interval, candles);
    })
  );

  const fleetSummaries = results.map((r) => r.summary);
  const selectedIdx = Math.max(
    0,
    NEON_CORE_UNIVERSE.findIndex((s) => s === selectedSymbol)
  );
  const selected = results[selectedIdx];

  return {
    timestamp_utc: new Date().toISOString(),
    selected_symbol: selectedSymbol,
    interval,
    active_mode: activeMode,
    selected_summary: selected.summary,
    fleet_summaries: fleetSummaries,
    patterns: selected.patterns,
  };
}
