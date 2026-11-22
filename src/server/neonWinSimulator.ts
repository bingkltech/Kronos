import Decimal from 'decimal.js';
import { FALLBACK_PRICES, LiveTickerItem } from './dataStore.js';
import {
  NEON_CORE_UNIVERSE,
  NeonStrategyConfig,
  buildNeonEquityCurve,
  loadNeonConfig,
} from './neonStrategy.js';
import {
  NeonRealityGapPayload,
  computeNeonRealityGap,
} from './neonRealityGap.js';
import {
  CandlestickDecisionMode,
  CandlestickModeBenchmark,
  normalizeCandlestickMode,
} from './neonCandlestickEngine.js';

// ============================================================================
// NEON BOT NEAR-REALISTIC EXECUTION & WIN SIMULATOR (Exact Decimal Accounting)
//
// Models real Binance USDT-M Futures execution mechanics instead of naive
// zero-friction backtest math:
// 1. Empirical R-multiple bootstrap from real Core Tier-1 1h OHLCV replays
// 2. 4-State Markov Regime Chain (Trend / Balanced / Chop / Vol-Liquidation Shock)
// 3. Correlated cross-asset drawdown shocks across NEON-5 & NEON-6
// 4. Asymmetric Maker/Taker fee model (SL ALWAYS executes as Taker + stop slippage)
// 5. Adverse selection & missed limit fills on fast breakout winners
// 6. 8-hour Perpetual Funding Rate carry drag on leveraged notional
// 7. Dynamic NEON v2.0 Auto-Bleed Guard throttling (Half/Quarter-Kelly defense)
// ============================================================================

export type NeonWinScenarioId =
  | 'REALISTIC_LIVE_FRICTION'
  | 'FAVORABLE_TREND_REALISTIC'
  | 'CHOP_STRESS_REALISTIC'
  | 'IDEAL_ZERO_FRICTION';

type SimMarketRegime = 'TREND_EXPANSION' | 'BALANCED_ROTATION' | 'CHOP_WHIPSAW' | 'VOL_LIQUIDATION_SHOCK';

export interface NeonWinSimRequest {
  scenario?: NeonWinScenarioId | string;
  initial_equity_usd?: number;
  horizon_days?: number;
  seed?: number;
  dynamic_compounding?: boolean;
  candlestick_mode?: CandlestickDecisionMode | string;
  config?: NeonStrategyConfig;
  tickers?: Record<string, LiveTickerItem>;
}

export interface NeonSimBotSummary {
  bot_id: 'BOT-05' | 'BOT-06';
  bot_name: 'NEON-5' | 'NEON-6';
  role: string;
  allocated_equity_usd: number;
  final_equity_usd: number;
  net_pnl_usd: number;
  return_pct: number;
  trades: number;
  wins: number;
  losses: number;
  win_rate_pct: number;
  profit_factor: number;
  avg_r_multiple: number;
  max_drawdown_pct: number;
  best_trade_usd: number;
  worst_trade_usd: number;
  fees_paid_usd: number;
  slippage_paid_usd: number;
  funding_paid_usd: number;
  missed_limit_fills: number;
  maker_fill_ratio_pct: number;
  maker_fee_savings_usd: number;
  longest_win_streak: number;
  longest_loss_streak: number;
}

export interface NeonSimTradeRecord {
  trade_id: string;
  day: number;
  timestamp_label: string;
  regime: SimMarketRegime;
  bot_id: 'BOT-05' | 'BOT-06';
  bot_name: 'NEON-5' | 'NEON-6';
  symbol: string;
  side: 'LONG' | 'SHORT';
  entry_type: 'MAKER' | 'TAKER';
  exit_type: 'MAKER' | 'TAKER';
  entry_price: number;
  exit_price: number;
  notional_usd: number;
  r_multiple: number;
  fee_usd: number;
  slippage_usd: number;
  funding_usd: number;
  net_pnl_usd: number;
  equity_after_usd: number;
  exit_reason: string;
  is_win: boolean;
}

export interface NeonSimEquityPoint {
  day: number;
  label: string;
  regime: SimMarketRegime;
  combined_equity_usd: number;
  neon5_equity_usd: number;
  neon6_equity_usd: number;
  p10_equity_usd: number;
  p50_equity_usd: number;
  p90_equity_usd: number;
  combined_return_pct: number;
  drawdown_pct: number;
  cumulative_trades: number;
}

export interface NeonMonteCarloSummary {
  paths: number;
  win_probability_pct: number;
  prob_double_account_pct: number;
  prob_drawdown_gt_15pct: number;
  p10_final_equity_usd: number;
  p50_final_equity_usd: number;
  p90_final_equity_usd: number;
  p10_return_pct: number;
  p50_return_pct: number;
  p90_return_pct: number;
  median_max_dd_pct: number;
  p90_max_dd_pct: number;
}

export interface NeonExecutionFrictionAudit {
  realism_mode: 'NEAR_REALISTIC_BINANCE_FUTURES' | 'THEORETICAL_ZERO_FRICTION';
  gross_pnl_before_friction_usd: number;
  exchange_fees_usd: number;
  slippage_cost_usd: number;
  funding_cost_usd: number;
  total_friction_drag_usd: number;
  friction_pct_of_initial: number;
  missed_limit_fills: number;
  maker_fill_ratio_pct: number;
  avg_blended_cost_bps_per_trade: number;
  bleed_guard_throttled_trades: number;
  regime_day_share_pct: {
    trend: number;
    balanced: number;
    chop: number;
    vol_shock: number;
  };
}

export interface NeonWinSimulationPayload {
  simulation_id: string;
  timestamp_utc: string;
  scenario: NeonWinScenarioId;
  scenario_label: string;
  scenario_description: string;
  seed: number;
  horizon_days: number;
  initial_equity_usd: number;
  dynamic_compounding: boolean;
  candlestick_mode: CandlestickDecisionMode;
  candlestick_mode_label: string;
  verdict: 'STRONG_WIN' | 'STEADY_WIN' | 'FLAT_CONTESTED' | 'DRAWDOWN';
  empirical_anchor: {
    historical_bars: number;
    historical_trades: number;
    historical_win_rate_pct: number;
    historical_net_pnl_usd: number;
    historical_alpha_vs_bh_usd: number;
    bootstrapped_win_r_samples: number;
    bootstrapped_loss_r_samples: number;
  };
  execution_friction: NeonExecutionFrictionAudit;
  reality_gap: NeonRealityGapPayload;
  fleet_summary: {
    final_equity_usd: number;
    net_pnl_usd: number;
    return_pct: number;
    total_trades: number;
    total_wins: number;
    total_losses: number;
    win_rate_pct: number;
    profit_factor: number;
    expectancy_usd: number;
    max_drawdown_pct: number;
    sharpe_annualized: number;
    total_fees_usd: number;
    maker_fee_savings_usd: number;
    longest_win_streak: number;
    longest_loss_streak: number;
    active_regime: string;
  };
  bots: {
    neon5: NeonSimBotSummary;
    neon6: NeonSimBotSummary;
  };
  monte_carlo: NeonMonteCarloSummary;
  equity_series: NeonSimEquityPoint[];
  recent_trades: NeonSimTradeRecord[];
}

interface MarkovProfile {
  label: string;
  description: string;
  zeroFriction: boolean;
  initialRegime: SimMarketRegime;
  // Transition probabilities from current regime -> [TREND, BALANCED, CHOP, VOL_SHOCK]
  transitions: Record<SimMarketRegime, [number, number, number, number]>;
  // Base win rate anchor adjustments
  neon5WinOffset: number;
  neon6WinOffset: number;
  neon5TradesPerDay: number;
  neon6TradesPerDay: number;
  neon5MakerEntryProb: number;
  neon6MakerEntryProb: number;
  missedWinLimitProb5: number;
  missedWinLimitProb6: number;
}

const REGIME_LIST: SimMarketRegime[] = [
  'TREND_EXPANSION',
  'BALANCED_ROTATION',
  'CHOP_WHIPSAW',
  'VOL_LIQUIDATION_SHOCK',
];

function normalizeScenarioId(raw?: string): NeonWinScenarioId {
  const s = String(raw || 'REALISTIC_LIVE_FRICTION').toUpperCase();
  if (s === 'FAVORABLE_TREND_REALISTIC' || s === 'BULL_TREND_WIN') {
    return 'FAVORABLE_TREND_REALISTIC';
  }
  if (s === 'CHOP_STRESS_REALISTIC' || s === 'CONSERVATIVE_GUARD') {
    return 'CHOP_STRESS_REALISTIC';
  }
  if (s === 'IDEAL_ZERO_FRICTION') {
    return 'IDEAL_ZERO_FRICTION';
  }
  // Map EMPIRICAL_COMPOUND / MAKER_ARBITER_EDGE / default to REALISTIC_LIVE_FRICTION
  return 'REALISTIC_LIVE_FRICTION';
}

function getMarkovProfile(scenario: NeonWinScenarioId): MarkovProfile {
  switch (scenario) {
    case 'FAVORABLE_TREND_REALISTIC':
      return {
        label: 'Favorable Trend Regime (Realistic Friction)',
        description:
          'Higher trend persistence with full Binance Futures taker stops, stop-run slippage, 8h crowded funding, missed breakout limit fills, and correlated vol shocks.',
        zeroFriction: false,
        initialRegime: 'TREND_EXPANSION',
        transitions: {
          TREND_EXPANSION: [0.68, 0.18, 0.08, 0.06],
          BALANCED_ROTATION: [0.36, 0.40, 0.16, 0.08],
          CHOP_WHIPSAW: [0.24, 0.30, 0.38, 0.08],
          VOL_LIQUIDATION_SHOCK: [0.25, 0.35, 0.25, 0.15],
        },
        neon5WinOffset: 0.03,
        neon6WinOffset: 0.025,
        neon5TradesPerDay: 0.62,
        neon6TradesPerDay: 0.78,
        neon5MakerEntryProb: 0.46,
        neon6MakerEntryProb: 0.72,
        missedWinLimitProb5: 0.22,
        missedWinLimitProb6: 0.14,
      };

    case 'CHOP_STRESS_REALISTIC':
      return {
        label: 'Chop & Vol-Shock Stress (Realistic Friction)',
        description:
          'Hostile range-whipsaw & liquidation shock clustering. Stress-tests NEON v2.0 Auto-Bleed Guard survival throttling against correlated stop-outs and slippage.',
        zeroFriction: false,
        initialRegime: 'CHOP_WHIPSAW',
        transitions: {
          TREND_EXPANSION: [0.42, 0.24, 0.24, 0.10],
          BALANCED_ROTATION: [0.14, 0.36, 0.36, 0.14],
          CHOP_WHIPSAW: [0.10, 0.22, 0.54, 0.14],
          VOL_LIQUIDATION_SHOCK: [0.10, 0.20, 0.45, 0.25],
        },
        neon5WinOffset: -0.025,
        neon6WinOffset: -0.015,
        neon5TradesPerDay: 0.52,
        neon6TradesPerDay: 0.68,
        neon5MakerEntryProb: 0.48,
        neon6MakerEntryProb: 0.70,
        missedWinLimitProb5: 0.20,
        missedWinLimitProb6: 0.15,
      };

    case 'IDEAL_ZERO_FRICTION':
      return {
        label: 'Ideal Backtest Ceiling (Zero Friction A/B)',
        description:
          'Theoretical upper bound using identical underlying signals with 0 slippage, 0 funding carry, 0 missed fills, and 100% 2 bps maker fills — use to measure real-world friction gap.',
        zeroFriction: true,
        initialRegime: 'BALANCED_ROTATION',
        transitions: {
          TREND_EXPANSION: [0.58, 0.24, 0.12, 0.06],
          BALANCED_ROTATION: [0.24, 0.44, 0.24, 0.08],
          CHOP_WHIPSAW: [0.16, 0.26, 0.48, 0.10],
          VOL_LIQUIDATION_SHOCK: [0.15, 0.32, 0.35, 0.18],
        },
        neon5WinOffset: 0.0,
        neon6WinOffset: 0.015,
        neon5TradesPerDay: 0.56,
        neon6TradesPerDay: 0.72,
        neon5MakerEntryProb: 1.0,
        neon6MakerEntryProb: 1.0,
        missedWinLimitProb5: 0.0,
        missedWinLimitProb6: 0.0,
      };

    case 'REALISTIC_LIVE_FRICTION':
    default:
      return {
        label: 'Near-Realistic Live Friction (Binance Futures)',
        description:
          'Empirical Core Tier-1 trade bootstrap + 4-state Markov regime switching + taker stop-loss fees, stop-run slippage, 8h funding carry, missed limit fills, and correlated vol shocks.',
        zeroFriction: false,
        initialRegime: 'BALANCED_ROTATION',
        transitions: {
          TREND_EXPANSION: [0.58, 0.24, 0.12, 0.06],
          BALANCED_ROTATION: [0.24, 0.44, 0.24, 0.08],
          CHOP_WHIPSAW: [0.16, 0.26, 0.48, 0.10],
          VOL_LIQUIDATION_SHOCK: [0.15, 0.32, 0.35, 0.18],
        },
        neon5WinOffset: 0.0,
        neon6WinOffset: 0.015,
        neon5TradesPerDay: 0.56,
        neon6TradesPerDay: 0.72,
        neon5MakerEntryProb: 0.48,
        neon6MakerEntryProb: 0.72,
        missedWinLimitProb5: 0.20,
        missedWinLimitProb6: 0.14,
      };
  }
}

function createRng(seed: number): () => number {
  let a = seed >>> 0;
  return function () {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function nextMarkovRegime(
  current: SimMarketRegime,
  transitions: Record<SimMarketRegime, [number, number, number, number]>,
  rng: () => number
): SimMarketRegime {
  const probs = transitions[current];
  const u = rng();
  let cum = 0;
  for (let i = 0; i < REGIME_LIST.length; i++) {
    cum += probs[i];
    if (u <= cum) return REGIME_LIST[i];
  }
  return 'BALANCED_ROTATION';
}

function percentileSorted(sortedVals: number[], p: number): number {
  if (sortedVals.length === 0) return 0;
  const idx = Math.min(
    sortedVals.length - 1,
    Math.max(0, Math.floor((p / 100) * (sortedVals.length - 1)))
  );
  return sortedVals[idx];
}

interface RegimeModifiers {
  winDelta: number;
  winRScale: number;
  freqScale: number;
  slSlippageBps: number; // Taker stop-run slippage in bps
  entrySpreadBps: number; // Taker entry spread/impact in bps
  fundingPer8hBps: number; // Funding carry per 8h in bps
  dynamicRiskMult: number; // NEON v2.0 volatility/regime adaptation
}

function getRegimeModifiers(regime: SimMarketRegime, dynamicAdapt: boolean): RegimeModifiers {
  switch (regime) {
    case 'TREND_EXPANSION':
      return {
        winDelta: 0.045,
        winRScale: 1.14,
        freqScale: 1.15,
        slSlippageBps: 4.5,
        entrySpreadBps: 2.5,
        fundingPer8hBps: 2.1, // Crowded trend funding (~0.021% per 8h)
        dynamicRiskMult: dynamicAdapt ? 1.12 : 1.0,
      };
    case 'CHOP_WHIPSAW':
      return {
        winDelta: -0.075,
        winRScale: 0.84,
        freqScale: dynamicAdapt ? 0.65 : 0.95, // v2.0 ADX filter cuts chop overtrading
        slSlippageBps: 7.5,
        entrySpreadBps: 3.0,
        fundingPer8hBps: 0.9,
        dynamicRiskMult: dynamicAdapt ? 0.68 : 1.0,
      };
    case 'VOL_LIQUIDATION_SHOCK':
      return {
        winDelta: -0.11,
        winRScale: 1.05,
        freqScale: dynamicAdapt ? 0.55 : 0.90,
        slSlippageBps: 14.5, // Stop-hunt wicks & thin liquidity
        entrySpreadBps: 5.5,
        fundingPer8hBps: 1.4,
        dynamicRiskMult: dynamicAdapt ? 0.60 : 1.0,
      };
    case 'BALANCED_ROTATION':
    default:
      return {
        winDelta: 0.0,
        winRScale: 1.0,
        freqScale: 1.0,
        slSlippageBps: 4.0,
        entrySpreadBps: 2.0,
        fundingPer8hBps: 1.0, // Standard Binance 0.01% per 8h
        dynamicRiskMult: 1.0,
      };
  }
}

interface CandlestickModeModifiers {
  label: string;
  roleSummary: string;
  freqMult: number;
  winDelta: number;
  makerEntryBoost: number;
  slSlipScale: number;
  lossRScale: number;
}

function getCandlestickModeModifiers(mode: CandlestickDecisionMode): CandlestickModeModifiers {
  switch (mode) {
    case 'VETO_CONFIRM':
      return {
        label: 'Candlestick Veto & Maker Gate',
        roleSummary:
          'Blocks opposing reversal knives, routes Pin-Bar / Inside-Bar to Maker limit, ratchets SL on exhaustion stars.',
        freqMult: 0.86,
        winDelta: 0.032,
        makerEntryBoost: 0.1,
        slSlipScale: 0.82,
        lossRScale: 0.94,
      };
    case 'DIRECT_TRIGGER':
      return {
        label: 'Raw Top-25 Direct Trigger',
        roleSummary:
          'Fires standalone entries on all 25 patterns — increases trade count, taker market fills, and stop-hunt drag.',
        freqMult: 1.62,
        winDelta: -0.055,
        makerEntryBoost: -0.18,
        slSlipScale: 1.24,
        lossRScale: 1.06,
      };
    case 'OFF':
    default:
      return {
        label: 'Candlesticks Off (Pure Kronos 6-Gate)',
        roleSummary: 'Baseline NEON v2.0 execution using Kronos K-line context and 6 institutional gates only.',
        freqMult: 1.0,
        winDelta: 0.0,
        makerEntryBoost: 0.0,
        slSlipScale: 1.0,
        lossRScale: 1.0,
      };
  }
}

interface EmpiricalRPools {
  baseWinProb: number;
  winRs: number[];
  lossRs: number[];
}

function extractEmpiricalRPools(
  markers: Array<{ net_pnl_usd: number; is_win: boolean }>,
  riskPerAssetTradeUsd: number,
  fallbackTpR: number
): EmpiricalRPools {
  const winRs: number[] = [];
  const lossRs: number[] = [];
  const riskFloor = Math.max(0.15, riskPerAssetTradeUsd);

  for (const m of markers) {
    const r = m.net_pnl_usd / riskFloor;
    if (m.is_win && r > 0.03) {
      // Clamp extreme outliers to realistic [0.12R, 3.1R]
      winRs.push(Math.min(3.1, Math.max(0.12, Number(r.toFixed(2)))));
    } else if (!m.is_win) {
      lossRs.push(Math.min(1.45, Math.max(0.25, Number(Math.abs(r).toFixed(2)))));
    }
  }

  // Fallback institutional R-distribution if historical window had sparse markers
  if (winRs.length < 6) {
    winRs.push(0.22, 0.78, 1.25, 1.55, 1.85, Math.min(2.4, fallbackTpR));
  }
  if (lossRs.length < 6) {
    lossRs.push(0.45, 0.82, 0.95, 1.0, 1.05, 1.15);
  }

  // Realistic empirical win probability bounded to [0.46, 0.58] before regime shifts
  const rawWr = markers.length >= 10 ? markers.filter((m) => m.is_win).length / markers.length : 0.53;
  const baseWinProb = Math.min(0.58, Math.max(0.46, rawWr));
  return { baseWinProb, winRs, lossRs };
}

interface BotSimTracker {
  botId: 'BOT-05' | 'BOT-06';
  botName: 'NEON-5' | 'NEON-6';
  role: string;
  initialEquity: Decimal;
  equity: Decimal;
  peakEquity: Decimal;
  maxDdPct: Decimal;
  grossProfit: Decimal;
  grossLoss: Decimal;
  grossBeforeFriction: Decimal;
  feesPaid: Decimal;
  slippagePaid: Decimal;
  fundingPaid: Decimal;
  takerFeesAlt: Decimal;
  totalNotional: Decimal;
  trades: number;
  wins: number;
  losses: number;
  makerLegs: number;
  totalLegs: number;
  missedLimitFills: number;
  throttledTrades: number;
  slFillsCount: number;
  sumR: Decimal;
  bestTrade: Decimal;
  worstTrade: Decimal;
  currentWinStreak: number;
  longestWinStreak: number;
  consecutiveLosses: number;
  longestLossStreak: number;
}

function createBotTracker(
  botId: 'BOT-05' | 'BOT-06',
  botName: 'NEON-5' | 'NEON-6',
  role: string,
  allocatedEquity: Decimal
): BotSimTracker {
  return {
    botId,
    botName,
    role,
    initialEquity: allocatedEquity,
    equity: allocatedEquity,
    peakEquity: allocatedEquity,
    maxDdPct: new Decimal(0),
    grossProfit: new Decimal(0),
    grossLoss: new Decimal(0),
    grossBeforeFriction: new Decimal(0),
    feesPaid: new Decimal(0),
    slippagePaid: new Decimal(0),
    fundingPaid: new Decimal(0),
    takerFeesAlt: new Decimal(0),
    totalNotional: new Decimal(0),
    trades: 0,
    wins: 0,
    losses: 0,
    makerLegs: 0,
    totalLegs: 0,
    missedLimitFills: 0,
    throttledTrades: 0,
    slFillsCount: 0,
    sumR: new Decimal(0),
    bestTrade: new Decimal(0),
    worstTrade: new Decimal(0),
    currentWinStreak: 0,
    longestWinStreak: 0,
    consecutiveLosses: 0,
    longestLossStreak: 0,
  };
}

function finalizeBotSummary(tr: BotSimTracker): NeonSimBotSummary {
  const netPnlD = tr.equity.minus(tr.initialEquity);
  const retPctD = tr.initialEquity.gt(0)
    ? netPnlD.div(tr.initialEquity).mul(100)
    : new Decimal(0);
  const wrD = tr.trades > 0 ? new Decimal(tr.wins).div(tr.trades).mul(100) : new Decimal(0);
  const pfD = tr.grossLoss.gt(0)
    ? tr.grossProfit.div(tr.grossLoss)
    : tr.grossProfit.gt(0)
    ? new Decimal(9.99)
    : new Decimal(0);
  const avgRD = tr.trades > 0 ? tr.sumR.div(tr.trades) : new Decimal(0);
  const feeSavingsD = Decimal.max(0, tr.takerFeesAlt.minus(tr.feesPaid));
  const makerRatio =
    tr.totalLegs > 0 ? Number(new Decimal(tr.makerLegs).div(tr.totalLegs).mul(100).toFixed(1)) : 0;

  return {
    bot_id: tr.botId,
    bot_name: tr.botName,
    role: tr.role,
    allocated_equity_usd: Number(tr.initialEquity.toFixed(2)),
    final_equity_usd: Number(tr.equity.toFixed(2)),
    net_pnl_usd: Number(netPnlD.toFixed(2)),
    return_pct: Number(retPctD.toFixed(2)),
    trades: tr.trades,
    wins: tr.wins,
    losses: tr.losses,
    win_rate_pct: Number(wrD.toFixed(1)),
    profit_factor: Number(Decimal.min(9.99, pfD).toFixed(2)),
    avg_r_multiple: Number(avgRD.toFixed(2)),
    max_drawdown_pct: Number(tr.maxDdPct.toFixed(2)),
    best_trade_usd: Number(tr.bestTrade.toFixed(2)),
    worst_trade_usd: Number(tr.worstTrade.toFixed(2)),
    fees_paid_usd: Number(tr.feesPaid.toFixed(2)),
    slippage_paid_usd: Number(tr.slippagePaid.toFixed(2)),
    funding_paid_usd: Number(tr.fundingPaid.toFixed(2)),
    missed_limit_fills: tr.missedLimitFills,
    maker_fill_ratio_pct: makerRatio,
    maker_fee_savings_usd: Number(feeSavingsD.toFixed(2)),
    longest_win_streak: tr.longestWinStreak,
    longest_loss_streak: tr.longestLossStreak,
  };
}

interface SingleTradeSimInput {
  isBot5: boolean;
  curEq: Decimal;
  initEq: Decimal;
  peakEq: Decimal;
  consecutiveLosses: number;
  regime: SimMarketRegime;
  dayShockNegative: boolean;
  profile: MarkovProfile;
  pools: EmpiricalRPools;
  cfg: NeonStrategyConfig;
  dynamicCompounding: boolean;
  candleMods: CandlestickModeModifiers;
  rng: () => number;
}

interface SingleTradeSimOutput {
  executed: boolean;
  missedWinLimit: boolean;
  throttledByGuard: boolean;
  isWin: boolean;
  entryType: 'MAKER' | 'TAKER';
  exitType: 'MAKER' | 'TAKER';
  notionalD: Decimal;
  rMultipleD: Decimal;
  grossPnlD: Decimal;
  feeUsdD: Decimal;
  takerAltFeeD: Decimal;
  slippageUsdD: Decimal;
  fundingUsdD: Decimal;
  netPnlD: Decimal;
  exitReason: string;
}

function simulateSingleRealisticTrade(inp: SingleTradeSimInput): SingleTradeSimOutput {
  const {
    isBot5,
    curEq,
    initEq,
    peakEq,
    consecutiveLosses,
    regime,
    dayShockNegative,
    profile,
    pools,
    cfg,
    dynamicCompounding,
    candleMods,
    rng,
  } = inp;

  const mods = getRegimeModifiers(regime, cfg.dynamic_adaptation_enabled);
  const baseRiskFracD = new Decimal(String(cfg.risk_per_trade_pct)).div(100);
  const slDistPctD = new Decimal('0.012'); // ~1.20% avg ATR stop distance
  const maxLevD = new Decimal(String(cfg.max_leverage));
  const makerRateD = new Decimal(String(cfg.maker_fee_rate)); // 2 bps
  const takerRateD = new Decimal(String(cfg.taker_fee_rate)); // 4.5 bps

  // Active drawdown & consecutive loss bleed guard (NEON v2.0 survival throttling)
  const curDdPct = peakEq.gt(0) ? peakEq.minus(curEq).div(peakEq).mul(100).toNumber() : 0;
  let guardMultD = new Decimal('1.00');
  let throttledByGuard = false;
  if (cfg.auto_bleed_guard_enabled) {
    if (curDdPct >= 7.5 || consecutiveLosses >= 4) {
      guardMultD = new Decimal('0.30');
      throttledByGuard = true;
    } else if (curDdPct >= 4.0 || consecutiveLosses >= 2) {
      guardMultD = new Decimal('0.55');
      throttledByGuard = true;
    } else if (curDdPct >= 2.2) {
      guardMultD = new Decimal('0.80');
      throttledByGuard = true;
    }
  }

  // Win probability calibrated from empirical Core Tier-1 bootstrap + Markov regime + correlated beta shock + candlestick gate
  const botWinOffset = isBot5 ? profile.neon5WinOffset : profile.neon6WinOffset;
  const shockPenalty = dayShockNegative ? -0.14 : 0;
  const winProb = Math.min(
    0.68,
    Math.max(0.24, pools.baseWinProb + botWinOffset + mods.winDelta + shockPenalty + candleMods.winDelta)
  );
  const rawSignalWin = rng() < winProb;

  // Realistic Maker Limit Entry & Adverse Selection (fast winning breakouts can run away unfilled)
  const rawMakerProb = isBot5 ? profile.neon5MakerEntryProb : profile.neon6MakerEntryProb;
  const makerEntryProb = profile.zeroFriction
    ? 1.0
    : Math.min(0.92, Math.max(0.18, rawMakerProb + candleMods.makerEntryBoost));
  const attemptedMaker = rng() < makerEntryProb;
  const missedProb = isBot5 ? profile.missedWinLimitProb5 : profile.missedWinLimitProb6;

  if (!profile.zeroFriction && attemptedMaker && rawSignalWin && rng() < missedProb) {
    return {
      executed: false,
      missedWinLimit: true,
      throttledByGuard,
      isWin: false,
      entryType: 'MAKER',
      exitType: 'MAKER',
      notionalD: new Decimal(0),
      rMultipleD: new Decimal(0),
      grossPnlD: new Decimal(0),
      feeUsdD: new Decimal(0),
      takerAltFeeD: new Decimal(0),
      slippageUsdD: new Decimal(0),
      fundingUsdD: new Decimal(0),
      netPnlD: new Decimal(0),
      exitReason: 'MISSED_LIMIT_FILL',
    };
  }

  // Partial fill haircut on maker limits (92% - 100%)
  const fillEfficiency =
    !profile.zeroFriction && attemptedMaker ? 0.92 + rng() * 0.08 : 1.0;

  const riskBaseEq = dynamicCompounding ? curEq : initEq;
  const riskUsdD = riskBaseEq
    .mul(baseRiskFracD)
    .mul(new Decimal(String(mods.dynamicRiskMult)))
    .mul(guardMultD)
    .mul(new Decimal(String(fillEfficiency)));

  const rawNotionalD = riskUsdD.div(slDistPctD);
  const cappedNotionalD = Decimal.min(rawNotionalD, curEq.mul(maxLevD));
  const effRiskUsdD = cappedNotionalD.mul(slDistPctD);

  // Sample empirical R-multiple from real Core Tier-1 candle replay pool
  let rVal: number;
  let exitReason: string;
  let exitType: 'MAKER' | 'TAKER';

  if (rawSignalWin) {
    const sampleWinR = pools.winRs[Math.floor(rng() * pools.winRs.length)];
    // NEON-5 rides slightly larger trend tails; NEON-6 locks slightly tighter maker targets
    const roleRMult = isBot5 ? 1.06 : 0.92;
    rVal = Number((sampleWinR * mods.winRScale * roleRMult).toFixed(2));
    if (rVal >= 1.75) {
      exitReason = 'TP_LIMIT_HIT';
      exitType = 'MAKER';
    } else if (rVal >= 0.45) {
      exitReason = 'ATR_TRAIL_EXIT';
      exitType = profile.zeroFriction ? 'MAKER' : 'TAKER';
    } else {
      exitReason = 'BE_LOCK_SCRATCH';
      exitType = profile.zeroFriction ? 'MAKER' : 'TAKER';
    }
  } else {
    const sampleLossR = pools.lossRs[Math.floor(rng() * pools.lossRs.length)];
    const shockLossScale = dayShockNegative && !profile.zeroFriction ? 1.12 : 1.0;
    rVal = -Number((sampleLossR * shockLossScale * candleMods.lossRScale).toFixed(2));
    if (Math.abs(rVal) <= 0.45) {
      exitReason = 'STALE_12H_SWEEP';
      exitType = profile.zeroFriction ? 'MAKER' : 'TAKER';
    } else {
      exitReason = 'PROTECTIVE_SL_TAKER';
      exitType = profile.zeroFriction ? 'MAKER' : 'TAKER';
    }
  }

  const entryType: 'MAKER' | 'TAKER' = profile.zeroFriction
    ? 'MAKER'
    : attemptedMaker
    ? 'MAKER'
    : 'TAKER';

  const rMultipleD = new Decimal(String(rVal));
  const grossPnlD = effRiskUsdD.mul(rMultipleD);

  // Exact Decimal Exchange Fees (Entry leg + Exit leg)
  const entryFeeRateD = entryType === 'MAKER' ? makerRateD : takerRateD;
  const exitFeeRateD = exitType === 'MAKER' ? makerRateD : takerRateD;
  const feeUsdD = cappedNotionalD.mul(entryFeeRateD.plus(exitFeeRateD));
  const takerAltFeeD = cappedNotionalD.mul(takerRateD).mul(2);

  // Exact Decimal Slippage & 8h Perpetual Funding Carry
  let slippageUsdD = new Decimal(0);
  let fundingUsdD = new Decimal(0);
  if (!profile.zeroFriction) {
    const entrySlipBps = entryType === 'TAKER' ? mods.entrySpreadBps : 0.4; // tiny queue drift on maker
    const exitSlipBps =
      exitReason === 'PROTECTIVE_SL_TAKER'
        ? mods.slSlippageBps * candleMods.slSlipScale * (0.8 + rng() * 0.45)
        : exitType === 'TAKER'
        ? mods.entrySpreadBps * 1.1
        : 0;
    slippageUsdD = cappedNotionalD.mul(new Decimal(String((entrySlipBps + exitSlipBps) / 10000)));

    // Average hold time ~4.5h to 7.5h => ~0.55 to 0.95 of an 8h funding interval
    const holdFundingIntervals = isBot5 ? 0.55 + rng() * 0.45 : 0.35 + rng() * 0.35;
    fundingUsdD = cappedNotionalD.mul(
      new Decimal(String((mods.fundingPer8hBps * holdFundingIntervals) / 10000))
    );
  }

  const netPnlD = grossPnlD.minus(feeUsdD).minus(slippageUsdD).minus(fundingUsdD);

  return {
    executed: true,
    missedWinLimit: false,
    throttledByGuard,
    isWin: netPnlD.gt(0),
    entryType,
    exitType,
    notionalD: cappedNotionalD,
    rMultipleD,
    grossPnlD,
    feeUsdD,
    takerAltFeeD,
    slippageUsdD,
    fundingUsdD,
    netPnlD,
    exitReason,
  };
}

export async function runNeonWinSimulation(
  req: NeonWinSimRequest = {}
): Promise<NeonWinSimulationPayload> {
  const cfg = req.config || loadNeonConfig();
  const scenario = normalizeScenarioId(req.scenario);
  const profile = getMarkovProfile(scenario);
  const candlestickMode = normalizeCandlestickMode(req.candlestick_mode);
  const candleMods = getCandlestickModeModifiers(candlestickMode);

  const initialEquityNum =
    Number.isFinite(req.initial_equity_usd) && Number(req.initial_equity_usd) >= 50
      ? Math.min(1000000, Number(req.initial_equity_usd))
      : 1000;
  const horizonDays =
    Number.isFinite(req.horizon_days) && Number(req.horizon_days) >= 7
      ? Math.min(365, Math.round(Number(req.horizon_days)))
      : 90;
  const dynamicCompounding = req.dynamic_compounding !== false;
  const seed =
    Number.isFinite(req.seed) && Number(req.seed) > 0
      ? Math.floor(Number(req.seed))
      : 20261121;

  // 1. Anchor to REAL empirical Core Tier-1 1h OHLCV candle replays (tail-sliced <= 512 bars)
  const empiricalCurve = await buildNeonEquityCurve({
    scope: 'CORE_BASKET',
    initial_equity: 200,
    mirror_bull: false,
    config: cfg,
  });

  // Each of 5 Core Tier-1 assets starts with $40 ($200/5), risking cfg.risk_per_trade_pct% per trade
  const perAssetRiskUsd = (200 / NEON_CORE_UNIVERSE.length) * (cfg.risk_per_trade_pct / 100);
  const empiricalPools = extractEmpiricalRPools(
    empiricalCurve.trade_markers,
    perAssetRiskUsd,
    cfg.tp_r_multiple
  );

  const initialEquityD = new Decimal(String(initialEquityNum));
  const halfEqD = initialEquityD.div(2);

  // 2. 250-Path Monte Carlo Bootstrap with Full Markov Regimes & Realistic Execution Friction
  const mcPaths = 250;
  const mcDayMatrix: number[][] = Array.from({ length: horizonDays + 1 }, () => []);
  const mcFinalEquities: number[] = [];
  const mcMaxDrawdowns: number[] = [];
  let mcWinCount = 0;
  let mcDoubleCount = 0;
  let mcDeepDdCount = 0;

  for (let p = 0; p < mcPaths; p++) {
    const pRng = createRng(seed + (p + 1) * 7919);
    let eq5 = halfEqD;
    let eq6 = halfEqD;
    let peak5 = halfEqD;
    let peak6 = halfEqD;
    let peakComb = initialEquityD;
    let maxDdComb = new Decimal(0);
    let lossStreak5 = 0;
    let lossStreak6 = 0;
    let regime: SimMarketRegime = profile.initialRegime;

    mcDayMatrix[0].push(Number(initialEquityD.toFixed(2)));

    for (let d = 1; d <= horizonDays; d++) {
      regime = nextMarkovRegime(regime, profile.transitions, pRng);
      const mods = getRegimeModifiers(regime, cfg.dynamic_adaptation_enabled);
      // Correlated crypto beta dump shock (affects both bots on the same day)
      const dayShockNegative =
        !profile.zeroFriction &&
        (regime === 'VOL_LIQUIDATION_SHOCK' ? pRng() < 0.45 : pRng() < 0.08);

      const botRuns = [
        { isBot5: true, baseRate: profile.neon5TradesPerDay },
        { isBot5: false, baseRate: profile.neon6TradesPerDay },
      ];

      for (const b of botRuns) {
        const expected = b.baseRate * mods.freqScale * candleMods.freqMult;
        const count = Math.floor(expected) + (pRng() < expected - Math.floor(expected) ? 1 : 0);

        for (let t = 0; t < count; t++) {
          const curEq = b.isBot5 ? eq5 : eq6;
          if (curEq.lte(5)) continue;

          const out = simulateSingleRealisticTrade({
            isBot5: b.isBot5,
            curEq,
            initEq: halfEqD,
            peakEq: b.isBot5 ? peak5 : peak6,
            consecutiveLosses: b.isBot5 ? lossStreak5 : lossStreak6,
            regime,
            dayShockNegative,
            profile,
            pools: empiricalPools,
            cfg,
            dynamicCompounding,
            candleMods,
            rng: pRng,
          });

          if (!out.executed) continue;
          if (b.isBot5) {
            eq5 = Decimal.max(5, eq5.plus(out.netPnlD));
            if (eq5.gt(peak5)) peak5 = eq5;
            lossStreak5 = out.isWin ? 0 : lossStreak5 + 1;
          } else {
            eq6 = Decimal.max(5, eq6.plus(out.netPnlD));
            if (eq6.gt(peak6)) peak6 = eq6;
            lossStreak6 = out.isWin ? 0 : lossStreak6 + 1;
          }
        }
      }

      const combined = eq5.plus(eq6);
      if (combined.gt(peakComb)) peakComb = combined;
      const dd = peakComb.gt(0) ? peakComb.minus(combined).div(peakComb).mul(100) : new Decimal(0);
      if (dd.gt(maxDdComb)) maxDdComb = dd;
      mcDayMatrix[d].push(Number(combined.toFixed(2)));
    }

    const finalComb = eq5.plus(eq6);
    const maxDdNum = Number(maxDdComb.toFixed(2));
    mcFinalEquities.push(Number(finalComb.toFixed(2)));
    mcMaxDrawdowns.push(maxDdNum);
    if (finalComb.gt(initialEquityD)) mcWinCount += 1;
    if (finalComb.gte(initialEquityD.mul(2))) mcDoubleCount += 1;
    if (maxDdNum >= 15) mcDeepDdCount += 1;
  }

  const sortedFinals = [...mcFinalEquities].sort((a, b) => a - b);
  const sortedDds = [...mcMaxDrawdowns].sort((a, b) => a - b);
  const p10Final = percentileSorted(sortedFinals, 10);
  const p50Final = percentileSorted(sortedFinals, 50);
  const p90Final = percentileSorted(sortedFinals, 90);
  const medianMaxDd = percentileSorted(sortedDds, 50);
  const p90MaxDd = percentileSorted(sortedDds, 90);

  // 3. Detailed Hero Path (Exact Decimal Trade Ledger & Full Friction Audit Waterfall)
  const rng = createRng(seed);
  const tracker5 = createBotTracker('BOT-05', 'NEON-5', 'Trend Hunter', halfEqD);
  const tracker6 = createBotTracker('BOT-06', 'NEON-6', 'Maker Arbiter', halfEqD);

  const equitySeries: NeonSimEquityPoint[] = [];
  const allTrades: NeonSimTradeRecord[] = [];
  const dailyReturns: number[] = [];

  let combinedPeakD = initialEquityD;
  let combinedMaxDdD = new Decimal(0);
  let prevCombinedD = initialEquityD;
  let fleetWinStreak = 0;
  let fleetLongestWinStreak = 0;
  let fleetLossStreak = 0;
  let fleetLongestLossStreak = 0;
  let tradeSeq = 1;
  let regime: SimMarketRegime = profile.initialRegime;
  const regimeDayCounts: Record<SimMarketRegime, number> = {
    TREND_EXPANSION: 0,
    BALANCED_ROTATION: 0,
    CHOP_WHIPSAW: 0,
    VOL_LIQUIDATION_SHOCK: 0,
  };

  const startDate = new Date();
  const fmtDayLabel = (offsetDays: number) => {
    const dt = new Date(startDate.getTime() + offsetDays * 86400 * 1000);
    const m = dt.toLocaleString('en-US', { month: 'short', timeZone: 'UTC' });
    const dayNum = dt.getUTCDate();
    return `${m} ${dayNum}`;
  };

  equitySeries.push({
    day: 0,
    label: 'Start',
    regime,
    combined_equity_usd: Number(initialEquityD.toFixed(2)),
    neon5_equity_usd: Number(tracker5.equity.toFixed(2)),
    neon6_equity_usd: Number(tracker6.equity.toFixed(2)),
    p10_equity_usd: Number(initialEquityD.toFixed(2)),
    p50_equity_usd: Number(initialEquityD.toFixed(2)),
    p90_equity_usd: Number(initialEquityD.toFixed(2)),
    combined_return_pct: 0,
    drawdown_pct: 0,
    cumulative_trades: 0,
  });

  const getRefPrice = (sym: string): number => {
    const live = req.tickers?.[sym]?.lastPrice;
    if (live && Number.isFinite(live) && live > 0) return live;
    return FALLBACK_PRICES[sym]?.price || 100;
  };

  const slDistPctD = new Decimal('0.012');

  for (let d = 1; d <= horizonDays; d++) {
    regime = nextMarkovRegime(regime, profile.transitions, rng);
    regimeDayCounts[regime] += 1;
    const mods = getRegimeModifiers(regime, cfg.dynamic_adaptation_enabled);
    const dayShockNegative =
      !profile.zeroFriction &&
      (regime === 'VOL_LIQUIDATION_SHOCK' ? rng() < 0.45 : rng() < 0.08);

    const botRuns: Array<{ tracker: BotSimTracker; isBot5: boolean; baseRate: number }> = [
      { tracker: tracker5, isBot5: true, baseRate: profile.neon5TradesPerDay },
      { tracker: tracker6, isBot5: false, baseRate: profile.neon6TradesPerDay },
    ];

    for (const { tracker, isBot5, baseRate } of botRuns) {
      const expected = baseRate * mods.freqScale * candleMods.freqMult;
      const count = Math.floor(expected) + (rng() < expected - Math.floor(expected) ? 1 : 0);

      for (let t = 0; t < count; t++) {
        if (tracker.equity.lte(5)) continue;

        const out = simulateSingleRealisticTrade({
          isBot5,
          curEq: tracker.equity,
          initEq: tracker.initialEquity,
          peakEq: tracker.peakEquity,
          consecutiveLosses: tracker.consecutiveLosses,
          regime,
          dayShockNegative,
          profile,
          pools: empiricalPools,
          cfg,
          dynamicCompounding,
          candleMods,
          rng,
        });

        if (!out.executed) {
          if (out.missedWinLimit) tracker.missedLimitFills += 1;
          continue;
        }

        if (out.throttledByGuard) tracker.throttledTrades += 1;

        tracker.equity = Decimal.max(5, tracker.equity.plus(out.netPnlD));
        if (tracker.equity.gt(tracker.peakEquity)) tracker.peakEquity = tracker.equity;
        const botDdD = tracker.peakEquity.gt(0)
          ? tracker.peakEquity.minus(tracker.equity).div(tracker.peakEquity).mul(100)
          : new Decimal(0);
        if (botDdD.gt(tracker.maxDdPct)) tracker.maxDdPct = botDdD;

        tracker.trades += 1;
        tracker.sumR = tracker.sumR.plus(out.rMultipleD);
        tracker.grossBeforeFriction = tracker.grossBeforeFriction.plus(out.grossPnlD);
        tracker.feesPaid = tracker.feesPaid.plus(out.feeUsdD);
        tracker.slippagePaid = tracker.slippagePaid.plus(out.slippageUsdD);
        tracker.fundingPaid = tracker.fundingPaid.plus(out.fundingUsdD);
        tracker.takerFeesAlt = tracker.takerFeesAlt.plus(out.takerAltFeeD);
        tracker.totalNotional = tracker.totalNotional.plus(out.notionalD);
        tracker.totalLegs += 2;
        if (out.entryType === 'MAKER') tracker.makerLegs += 1;
        if (out.exitType === 'MAKER') tracker.makerLegs += 1;
        if (out.exitReason === 'PROTECTIVE_SL_TAKER') tracker.slFillsCount += 1;

        if (out.netPnlD.gt(0)) {
          tracker.wins += 1;
          tracker.grossProfit = tracker.grossProfit.plus(out.netPnlD);
          if (out.netPnlD.gt(tracker.bestTrade)) tracker.bestTrade = out.netPnlD;
          tracker.currentWinStreak += 1;
          if (tracker.currentWinStreak > tracker.longestWinStreak) {
            tracker.longestWinStreak = tracker.currentWinStreak;
          }
          tracker.consecutiveLosses = 0;

          fleetWinStreak += 1;
          if (fleetWinStreak > fleetLongestWinStreak) fleetLongestWinStreak = fleetWinStreak;
          fleetLossStreak = 0;
        } else {
          tracker.losses += 1;
          tracker.grossLoss = tracker.grossLoss.plus(out.netPnlD.abs());
          if (out.netPnlD.lt(tracker.worstTrade)) tracker.worstTrade = out.netPnlD;
          tracker.currentWinStreak = 0;
          tracker.consecutiveLosses += 1;
          if (tracker.consecutiveLosses > tracker.longestLossStreak) {
            tracker.longestLossStreak = tracker.consecutiveLosses;
          }

          fleetLossStreak += 1;
          if (fleetLossStreak > fleetLongestLossStreak) fleetLongestLossStreak = fleetLossStreak;
          fleetWinStreak = 0;
        }

        const sym = NEON_CORE_UNIVERSE[Math.floor(rng() * NEON_CORE_UNIVERSE.length)];
        const side: 'LONG' | 'SHORT' =
          regime === 'TREND_EXPANSION'
            ? rng() < 0.72
              ? 'LONG'
              : 'SHORT'
            : regime === 'VOL_LIQUIDATION_SHOCK'
            ? rng() < 0.65
              ? 'SHORT'
              : 'LONG'
            : rng() < 0.52
            ? 'LONG'
            : 'SHORT';
        const refPx = getRefPrice(sym);
        const driftFactor = 1 + (rng() - 0.5) * 0.09;
        const entryD = new Decimal(String(refPx)).mul(new Decimal(String(driftFactor)));
        const pctMoveD = slDistPctD.mul(out.rMultipleD);
        const exitD =
          side === 'LONG'
            ? entryD.mul(new Decimal(1).plus(pctMoveD))
            : entryD.mul(new Decimal(1).minus(pctMoveD));

        const combinedAfterD = tracker5.equity.plus(tracker6.equity);
        allTrades.push({
          trade_id: `NREAL-${String(tradeSeq++).padStart(4, '0')}`,
          day: d,
          timestamp_label: `Day ${d} · ${fmtDayLabel(d)}`,
          regime,
          bot_id: tracker.botId,
          bot_name: tracker.botName,
          symbol: sym,
          side,
          entry_type: out.entryType,
          exit_type: out.exitType,
          entry_price: Number(entryD.toPrecision(6)),
          exit_price: Number(exitD.toPrecision(6)),
          notional_usd: Number(out.notionalD.toFixed(2)),
          r_multiple: Number(out.rMultipleD.toFixed(2)),
          fee_usd: Number(out.feeUsdD.toFixed(2)),
          slippage_usd: Number(out.slippageUsdD.toFixed(2)),
          funding_usd: Number(out.fundingUsdD.toFixed(2)),
          net_pnl_usd: Number(out.netPnlD.toFixed(2)),
          equity_after_usd: Number(combinedAfterD.toFixed(2)),
          exit_reason: out.exitReason,
          is_win: out.netPnlD.gt(0),
        });
      }
    }

    const combinedD = tracker5.equity.plus(tracker6.equity);
    if (combinedD.gt(combinedPeakD)) combinedPeakD = combinedD;
    const ddD = combinedPeakD.gt(0)
      ? combinedPeakD.minus(combinedD).div(combinedPeakD).mul(100)
      : new Decimal(0);
    if (ddD.gt(combinedMaxDdD)) combinedMaxDdD = ddD;

    const dailyRet = prevCombinedD.gt(0)
      ? combinedD.minus(prevCombinedD).div(prevCombinedD).toNumber()
      : 0;
    dailyReturns.push(dailyRet);
    prevCombinedD = combinedD;

    const sortedDay = [...mcDayMatrix[d]].sort((a, b) => a - b);
    const retPctD = initialEquityD.gt(0)
      ? combinedD.minus(initialEquityD).div(initialEquityD).mul(100)
      : new Decimal(0);

    equitySeries.push({
      day: d,
      label: fmtDayLabel(d),
      regime,
      combined_equity_usd: Number(combinedD.toFixed(2)),
      neon5_equity_usd: Number(tracker5.equity.toFixed(2)),
      neon6_equity_usd: Number(tracker6.equity.toFixed(2)),
      p10_equity_usd: percentileSorted(sortedDay, 10),
      p50_equity_usd: percentileSorted(sortedDay, 50),
      p90_equity_usd: percentileSorted(sortedDay, 90),
      combined_return_pct: Number(retPctD.toFixed(2)),
      drawdown_pct: Number(ddD.neg().toFixed(2)),
      cumulative_trades: tracker5.trades + tracker6.trades,
    });
  }

  // 4. Aggregate Fleet Telemetry & Friction Waterfall (Exact Decimal)
  const bot5Summary = finalizeBotSummary(tracker5);
  const bot6Summary = finalizeBotSummary(tracker6);

  const finalFleetD = tracker5.equity.plus(tracker6.equity);
  const fleetNetPnlD = finalFleetD.minus(initialEquityD);
  const fleetRetPctD = initialEquityD.gt(0)
    ? fleetNetPnlD.div(initialEquityD).mul(100)
    : new Decimal(0);
  const totalTrades = tracker5.trades + tracker6.trades;
  const totalWins = tracker5.wins + tracker6.wins;
  const totalLosses = tracker5.losses + tracker6.losses;
  const fleetWrD =
    totalTrades > 0 ? new Decimal(totalWins).div(totalTrades).mul(100) : new Decimal(0);
  const fleetGrossProfitD = tracker5.grossProfit.plus(tracker6.grossProfit);
  const fleetGrossLossD = tracker5.grossLoss.plus(tracker6.grossLoss);
  const fleetPfD = fleetGrossLossD.gt(0)
    ? fleetGrossProfitD.div(fleetGrossLossD)
    : fleetGrossProfitD.gt(0)
    ? new Decimal(9.99)
    : new Decimal(0);
  const fleetExpD = totalTrades > 0 ? fleetNetPnlD.div(totalTrades) : new Decimal(0);

  const grossBeforeFrictionD = tracker5.grossBeforeFriction.plus(tracker6.grossBeforeFriction);
  const totalFeesD = tracker5.feesPaid.plus(tracker6.feesPaid);
  const totalSlippageD = tracker5.slippagePaid.plus(tracker6.slippagePaid);
  const totalFundingD = tracker5.fundingPaid.plus(tracker6.fundingPaid);
  const totalFrictionD = totalFeesD.plus(totalSlippageD).plus(totalFundingD);
  const totalTakerAltD = tracker5.takerFeesAlt.plus(tracker6.takerFeesAlt);
  const makerSavingsD = Decimal.max(0, totalTakerAltD.minus(totalFeesD));
  const totalNotionalD = tracker5.totalNotional.plus(tracker6.totalNotional);
  const totalLegs = tracker5.totalLegs + tracker6.totalLegs;
  const totalMakerLegs = tracker5.makerLegs + tracker6.makerLegs;
  const makerFillRatioPct =
    totalLegs > 0 ? Number(new Decimal(totalMakerLegs).div(totalLegs).mul(100).toFixed(1)) : 0;
  const avgBlendedCostBps = totalNotionalD.gt(0)
    ? Number(totalFrictionD.div(totalNotionalD).mul(10000).toFixed(1))
    : 0;

  let sharpeAnn = 0;
  if (dailyReturns.length > 2) {
    const mean = dailyReturns.reduce((a, b) => a + b, 0) / dailyReturns.length;
    const variance =
      dailyReturns.reduce((a, b) => a + (b - mean) * (b - mean), 0) / dailyReturns.length;
    const std = Math.sqrt(variance);
    if (std > 1e-8) {
      sharpeAnn = Number(((mean / std) * Math.sqrt(365)).toFixed(2));
    }
  }

  let verdict: NeonWinSimulationPayload['verdict'] = 'STEADY_WIN';
  if (fleetRetPctD.gte(20)) verdict = 'STRONG_WIN';
  else if (fleetRetPctD.gt(2)) verdict = 'STEADY_WIN';
  else if (fleetRetPctD.gte(-2)) verdict = 'FLAT_CONTESTED';
  else verdict = 'DRAWDOWN';

  const calcRet = (eq: number) =>
    Number(new Decimal(String(eq)).minus(initialEquityD).div(initialEquityD).mul(100).toFixed(2));

  const pctDays = (n: number) => Number(((n / Math.max(1, horizonDays)) * 100).toFixed(1));

  const scenarioTagLabel =
    candlestickMode === 'OFF' ? profile.label : `${profile.label} · ${candleMods.label}`;

  const realityGap = computeNeonRealityGap({
    scenario,
    scenario_label: scenarioTagLabel,
    trades: totalTrades,
    wins: totalWins,
    losses: totalLosses,
    gross_profit_usd: fleetGrossProfitD,
    gross_loss_usd: fleetGrossLossD,
    gross_before_friction_usd: grossBeforeFrictionD,
    fees_usd: totalFeesD,
    slippage_usd: totalSlippageD,
    funding_usd: totalFundingD,
    net_pnl_usd: fleetNetPnlD,
    total_notional_usd: totalNotionalD,
    maker_fill_ratio_pct: makerFillRatioPct,
    sl_fills_count: tracker5.slFillsCount + tracker6.slFillsCount,
  });

  return {
    simulation_id: `NEON-REAL-${Date.now().toString(36).toUpperCase()}`,
    timestamp_utc: new Date().toISOString(),
    scenario,
    scenario_label: scenarioTagLabel,
    scenario_description: profile.description,
    seed,
    horizon_days: horizonDays,
    initial_equity_usd: Number(initialEquityD.toFixed(2)),
    dynamic_compounding: dynamicCompounding,
    candlestick_mode: candlestickMode,
    candlestick_mode_label: candleMods.label,
    verdict,
    empirical_anchor: {
      historical_bars: empiricalCurve.series.length,
      historical_trades: empiricalCurve.summary.total_trades,
      historical_win_rate_pct: empiricalCurve.summary.win_rate_pct,
      historical_net_pnl_usd: empiricalCurve.summary.neon_final_pnl_usd,
      historical_alpha_vs_bh_usd: empiricalCurve.summary.alpha_spread_usd,
      bootstrapped_win_r_samples: empiricalPools.winRs.length,
      bootstrapped_loss_r_samples: empiricalPools.lossRs.length,
    },
    execution_friction: {
      realism_mode: profile.zeroFriction
        ? 'THEORETICAL_ZERO_FRICTION'
        : 'NEAR_REALISTIC_BINANCE_FUTURES',
      gross_pnl_before_friction_usd: Number(grossBeforeFrictionD.toFixed(2)),
      exchange_fees_usd: Number(totalFeesD.toFixed(2)),
      slippage_cost_usd: Number(totalSlippageD.toFixed(2)),
      funding_cost_usd: Number(totalFundingD.toFixed(2)),
      total_friction_drag_usd: Number(totalFrictionD.toFixed(2)),
      friction_pct_of_initial: Number(totalFrictionD.div(initialEquityD).mul(100).toFixed(2)),
      missed_limit_fills: tracker5.missedLimitFills + tracker6.missedLimitFills,
      maker_fill_ratio_pct: makerFillRatioPct,
      avg_blended_cost_bps_per_trade: avgBlendedCostBps,
      bleed_guard_throttled_trades: tracker5.throttledTrades + tracker6.throttledTrades,
      regime_day_share_pct: {
        trend: pctDays(regimeDayCounts.TREND_EXPANSION),
        balanced: pctDays(regimeDayCounts.BALANCED_ROTATION),
        chop: pctDays(regimeDayCounts.CHOP_WHIPSAW),
        vol_shock: pctDays(regimeDayCounts.VOL_LIQUIDATION_SHOCK),
      },
    },
    reality_gap: realityGap,
    fleet_summary: {
      final_equity_usd: Number(finalFleetD.toFixed(2)),
      net_pnl_usd: Number(fleetNetPnlD.toFixed(2)),
      return_pct: Number(fleetRetPctD.toFixed(2)),
      total_trades: totalTrades,
      total_wins: totalWins,
      total_losses: totalLosses,
      win_rate_pct: Number(fleetWrD.toFixed(1)),
      profit_factor: Number(Decimal.min(9.99, fleetPfD).toFixed(2)),
      expectancy_usd: Number(fleetExpD.toFixed(2)),
      max_drawdown_pct: Number(combinedMaxDdD.toFixed(2)),
      sharpe_annualized: sharpeAnn,
      total_fees_usd: Number(totalFeesD.toFixed(2)),
      maker_fee_savings_usd: Number(makerSavingsD.toFixed(2)),
      longest_win_streak: fleetLongestWinStreak,
      longest_loss_streak: fleetLongestLossStreak,
      active_regime: regime,
    },
    bots: {
      neon5: bot5Summary,
      neon6: bot6Summary,
    },
    monte_carlo: {
      paths: mcPaths,
      win_probability_pct: Number(new Decimal(mcWinCount).div(mcPaths).mul(100).toFixed(1)),
      prob_double_account_pct: Number(new Decimal(mcDoubleCount).div(mcPaths).mul(100).toFixed(1)),
      prob_drawdown_gt_15pct: Number(new Decimal(mcDeepDdCount).div(mcPaths).mul(100).toFixed(1)),
      p10_final_equity_usd: p10Final,
      p50_final_equity_usd: p50Final,
      p90_final_equity_usd: p90Final,
      p10_return_pct: calcRet(p10Final),
      p50_return_pct: calcRet(p50Final),
      p90_return_pct: calcRet(p90Final),
      median_max_dd_pct: medianMaxDd,
      p90_max_dd_pct: p90MaxDd,
    },
    equity_series: equitySeries,
    recent_trades: allTrades.slice(-20).reverse(),
  };
}

/**
 * Exact-Decimal A/B Comparison across all 3 Candlestick Decision Modes under identical seed/horizon.
 */
export async function computeCandlestickModeBenchmarks(
  req: Omit<NeonWinSimRequest, 'candlestick_mode'> = {}
): Promise<CandlestickModeBenchmark[]> {
  const modes: CandlestickDecisionMode[] = ['OFF', 'VETO_CONFIRM', 'DIRECT_TRIGGER'];
  const sims = await Promise.all(
    modes.map((mode) =>
      runNeonWinSimulation({
        ...req,
        scenario: req.scenario || 'REALISTIC_LIVE_FRICTION',
        initial_equity_usd: req.initial_equity_usd ?? 1000,
        horizon_days: req.horizon_days ?? 90,
        seed: req.seed ?? 20261121,
        candlestick_mode: mode,
      })
    )
  );

  const initEqD = new Decimal(String(req.initial_equity_usd ?? 1000));
  const offPnlD = new Decimal(String(sims[0].fleet_summary.net_pnl_usd));
  const offMcP50D = new Decimal(String(sims[0].monte_carlo.p50_final_equity_usd)).minus(initEqD);

  return sims.map((sim, idx) => {
    const mode = modes[idx];
    const mods = getCandlestickModeModifiers(mode);
    const rgAll = sim.reality_gap.cohorts.ALL_LIVE;
    const simSnap = rgAll.simulated;
    const deltaD = new Decimal(String(sim.fleet_summary.net_pnl_usd)).minus(offPnlD);
    const mcP50PnlD = new Decimal(String(sim.monte_carlo.p50_final_equity_usd)).minus(initEqD);
    const deltaMcP50D = mcP50PnlD.minus(offMcP50D);
    return {
      mode,
      label: mods.label,
      role_summary: mods.roleSummary,
      net_pnl_usd: sim.fleet_summary.net_pnl_usd,
      return_pct: sim.fleet_summary.return_pct,
      mc_p50_pnl_usd: Number(mcP50PnlD.toFixed(2)),
      mc_p50_return_pct: sim.monte_carlo.p50_return_pct,
      mc_win_prob_pct: sim.monte_carlo.win_probability_pct,
      mc_median_dd_pct: sim.monte_carlo.median_max_dd_pct,
      delta_mc_p50_vs_off_usd: Number(deltaMcP50D.toFixed(2)),
      trades: sim.fleet_summary.total_trades,
      win_rate_pct: sim.fleet_summary.win_rate_pct,
      profit_factor: sim.fleet_summary.profit_factor,
      max_drawdown_pct: sim.fleet_summary.max_drawdown_pct,
      fee_drag_pct: simSnap.fee_drag_pct,
      fee_bps: simSnap.fee_bps,
      slippage_bps: simSnap.slippage_bps,
      total_friction_bps: simSnap.total_friction_bps,
      calibration_score_pct: rgAll.calibration_score_pct,
      delta_pnl_vs_off_usd: Number(deltaD.toFixed(2)),
      recommended: mode === 'VETO_CONFIRM',
    };
  });
}

