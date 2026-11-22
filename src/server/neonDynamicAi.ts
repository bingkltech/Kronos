import path from 'path';
import Decimal from 'decimal.js';
import { GoogleGenAI, ThinkingLevel, Type } from '@google/genai';
import {
  DATA_DIR,
  LiveTickerItem,
  fetchBinanceKlinesWithFallback,
  readJsonSafe,
  writeJsonSafe,
} from './dataStore.js';
import {
  NEON_CORE_UNIVERSE,
  NeonStrategyConfig,
  buildNeonEquityCurve,
  evaluateNeonUniverse,
  loadNeonConfig,
} from './neonStrategy.js';

// ============================================================================
// NEON v2.0 DYNAMIC QUANT ENGINE & AI-ASSISTED BLEED ASSESSMENT
// Exact Decimal math for all bleed telemetry, Kelly sizing, and adaptive bounds.
// Server-side @google/genai (gemini-4-hydrogen) for root-cause bleed diagnosis.
// ============================================================================

export type DynamicMarketRegime =
  | 'TREND_EXPANSION'
  | 'NORMAL_BALANCED'
  | 'VOLATILITY_SPIKE'
  | 'CHOP_COMPRESSION';

export type BleedCircuitTier =
  | 'NOMINAL'
  | 'WATCH'
  | 'BLEED_WARNING'
  | 'CRITICAL_BLEED_LOCK';

export interface SymbolBleedStat {
  symbol: string;
  trades: number;
  wins: number;
  losses: number;
  win_rate_pct: number;
  net_pnl_usd: number;
  status: 'HEALTHY' | 'DRIFTING' | 'BLEEDING';
}

export interface NeonDynamicParameters {
  base_risk_pct: number;
  effective_risk_pct: number;
  risk_multiplier: number;
  kelly_half_pct: number;
  base_min_adx: number;
  effective_min_adx: number;
  base_sl_atr: number;
  effective_sl_atr: number;
  base_tp_r: number;
  effective_tp_r: number;
  base_max_slots: number;
  effective_max_slots: number;
  base_cooldown_min: number;
  effective_cooldown_min: number;
  adaptation_reasons: string[];
}

export interface NeonBleedTelemetry {
  data_mode: 'LIVE_TELEMETRY' | 'BLEED_STRESS_DRILL' | 'WIN_SIMULATION';
  bleed_score: number; // 0..100
  circuit_tier: BleedCircuitTier;
  current_drawdown_pct: number;
  max_drawdown_pct: number;
  consecutive_losses: number;
  rolling_10_win_rate_pct: number;
  rolling_10_expectancy_usd: number;
  rolling_10_net_pnl_usd: number;
  fee_drag_ratio_pct: number;
  bleed_velocity_usd_per_trade: number;
  is_bleeding: boolean;
  triggers: string[];
  symbol_health: SymbolBleedStat[];
}

export interface NeonVolatilityMicrostructure {
  regime: DynamicMarketRegime;
  avg_atr_pct: number;
  vol_expansion_ratio: number;
  avg_adx_14: number;
  macro_regime: string;
  macro_breadth_pct: number;
  approved_signals: number;
  total_universe: number;
}

export interface NeonAiRootCause {
  category: string;
  severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  evidence: string;
  impact: string;
}

export interface NeonAiConfigPatch {
  risk_per_trade_pct: number;
  min_adx_14: number;
  tp_r_multiple: number;
  sl_atr_multiplier: number;
  sl_cooldown_minutes: number;
  max_concurrent_positions: number;
  session_gate_enabled: boolean;
  enabled: boolean;
}

export interface NeonAiBleedAssessment {
  assessment_id: string;
  timestamp_utc: string;
  model: string;
  data_mode: 'LIVE_TELEMETRY' | 'BLEED_STRESS_DRILL' | 'WIN_SIMULATION';
  bleed_score_at_audit: number;
  diagnosis_headline: string;
  bleed_severity: BleedCircuitTier;
  confidence_pct: number;
  executive_summary: string;
  root_causes: NeonAiRootCause[];
  surgical_remediation_plan: string[];
  recommended_config_patch: NeonAiConfigPatch;
  symbols_to_quarantine: string[];
  expected_impact_summary: string;
}

export interface NeonDynamicStatePayload {
  timestamp_utc: string;
  dynamic_adaptation_enabled: boolean;
  auto_bleed_guard_enabled: boolean;
  microstructure: NeonVolatilityMicrostructure;
  bleed_telemetry: NeonBleedTelemetry;
  adaptive_params: NeonDynamicParameters;
  latest_ai_assessment: NeonAiBleedAssessment | null;
  ai_history_count: number;
}

const AI_ASSESSMENTS_PATH = path.join(DATA_DIR, 'neon_ai_assessments.json');

function getGeminiClient(): GoogleGenAI | null {
  const apiKey = process.env.GEMINI_API_KEY?.trim();
  if (!apiKey) return null;
  return new GoogleGenAI({
    apiKey,
    httpOptions: {
      headers: {
        'User-Agent': 'aistudio-build',
      },
    },
  });
}

function loadAiAssessmentHistory(): NeonAiBleedAssessment[] {
  const saved = readJsonSafe<NeonAiBleedAssessment[]>(AI_ASSESSMENTS_PATH, []);
  return Array.isArray(saved) ? saved : [];
}

function saveAiAssessment(entry: NeonAiBleedAssessment): NeonAiBleedAssessment[] {
  const history = loadAiAssessmentHistory();
  const next = [entry, ...history].slice(0, 12);
  writeJsonSafe(AI_ASSESSMENTS_PATH, next);
  return next;
}

function calcSimpleAtrSeries(highs: number[], lows: number[], closes: number[], period = 14): number[] {
  if (closes.length === 0) return [];
  const k = 2 / (period + 1);
  const out: number[] = [];
  let ema = highs[0] - lows[0];
  out.push(ema);
  for (let i = 1; i < closes.length; i++) {
    const tr = Math.max(
      highs[i] - lows[i],
      Math.abs(highs[i] - closes[i - 1]),
      Math.abs(lows[i] - closes[i - 1])
    );
    ema = tr * k + ema * (1 - k);
    out.push(ema);
  }
  return out;
}

function median(vals: number[]): number {
  if (vals.length === 0) return 0;
  const sorted = [...vals].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid];
}

export async function computeNeonDynamicState(params: {
  tickers: Record<string, LiveTickerItem>;
  equityUsd: Decimal;
  openPositionCount?: number;
  config?: NeonStrategyConfig;
  simulateBleed?: boolean;
  simulateWin?: boolean;
}): Promise<NeonDynamicStatePayload> {
  const cfg = params.config || loadNeonConfig();
  const simulateBleed = Boolean(params.simulateBleed);
  const simulateWin = !simulateBleed && Boolean(params.simulateWin);

  // 1. Live Tier-1 Universe Scan + Core Basket Equity Curve (Exact Decimal)
  const [scanner, basketCurve] = await Promise.all([
    evaluateNeonUniverse(params.tickers, params.equityUsd, cfg, params.openPositionCount || 0),
    buildNeonEquityCurve({
      scope: 'CORE_BASKET',
      initial_equity: 200,
      mirror_bull: false,
      config: cfg,
    }),
  ]);
  const macroRegime = scanner.macro_regime;
  const macroBreadthPct = scanner.macro_breadth_pct;

  // 2. Real-time Volatility Expansion Ratio across Core Tier-1 (tail-sliced <= 512 bars)
  const volRatios: number[] = [];
  const atrPcts: number[] = [];
  const adxVals: number[] = [];

  for (const ev of scanner.evaluations) {
    if (Number.isFinite(ev.atr_14_pct) && ev.atr_14_pct > 0) atrPcts.push(ev.atr_14_pct);
    if (Number.isFinite(ev.adx_14) && ev.adx_14 > 0) adxVals.push(ev.adx_14);
  }

  await Promise.all(
    NEON_CORE_UNIVERSE.map(async (sym) => {
      try {
        const res = await fetchBinanceKlinesWithFallback(sym, '1h', 160);
        const candles = res.candles.slice(-160);
        if (candles.length < 40) return;
        const atrArr = calcSimpleAtrSeries(
          candles.map((c) => c.high),
          candles.map((c) => c.low),
          candles.map((c) => c.close),
          14
        );
        const atrPctSeries = atrArr.map((a, idx) =>
          candles[idx].close > 0 ? (a / candles[idx].close) * 100 : 0
        );
        const currentAtrPct = atrPctSeries[atrPctSeries.length - 1];
        const baselineMed = median(atrPctSeries.slice(-96, -1));
        if (baselineMed > 0) {
          volRatios.push(currentAtrPct / baselineMed);
        }
      } catch {
        // Skip single-symbol transient fetch issue
      }
    })
  );

  const avgAtrPct = atrPcts.length
    ? Number(
        atrPcts
          .reduce((acc, v) => acc.plus(new Decimal(String(v))), new Decimal(0))
          .div(atrPcts.length)
          .toFixed(3)
      )
    : 1.15;

  const volExpansionRatio = volRatios.length
    ? Number(
        volRatios
          .reduce((acc, v) => acc.plus(new Decimal(String(v))), new Decimal(0))
          .div(volRatios.length)
          .toFixed(2)
      )
    : 1.0;

  const avgAdx = adxVals.length
    ? Number(
        adxVals
          .reduce((acc, v) => acc.plus(new Decimal(String(v))), new Decimal(0))
          .div(adxVals.length)
          .toFixed(1)
      )
    : 20.0;

  let regime: DynamicMarketRegime = 'NORMAL_BALANCED';
  if (volExpansionRatio >= 1.45 || avgAtrPct >= 2.1) {
    regime = 'VOLATILITY_SPIKE';
  } else if (avgAdx >= 24 && (macroBreadthPct >= 62 || macroBreadthPct <= 38)) {
    regime = 'TREND_EXPANSION';
  } else if (avgAdx < 18) {
    regime = 'CHOP_COMPRESSION';
  }

  // 3. Exact-Decimal Bleed Telemetry Engine
  const markers = [...basketCurve.trade_markers].sort((a, b) => a.time_ms - b.time_ms);
  const series = basketCurve.series;
  const lastPoint = series.length ? series[series.length - 1] : null;

  let currentDdPct = lastPoint ? Math.abs(lastPoint.neon_drawdown_pct) : 0;
  let maxDdPct = basketCurve.summary.neon_max_dd_pct;
  let consecutiveLosses = 0;

  for (let i = markers.length - 1; i >= 0; i--) {
    if (!markers[i].is_win) consecutiveLosses += 1;
    else break;
  }

  const last10 = markers.slice(-10);
  const last10Wins = last10.filter((m) => m.is_win).length;
  let rolling10Wr = last10.length
    ? Number(new Decimal(last10Wins).div(last10.length).mul(100).toFixed(1))
    : basketCurve.summary.win_rate_pct;

  const last10NetD = last10.reduce(
    (acc, m) => acc.plus(new Decimal(String(m.net_pnl_usd))),
    new Decimal(0)
  );
  let rolling10Net = Number(last10NetD.toFixed(2));
  let rolling10Exp = last10.length
    ? Number(last10NetD.div(last10.length).toFixed(2))
    : 0;

  const grossProfitD = markers
    .filter((m) => m.net_pnl_usd > 0)
    .reduce((acc, m) => acc.plus(new Decimal(String(m.net_pnl_usd))), new Decimal(0));
  const estFeesD = new Decimal(markers.length).mul('0.08'); // maker 2bps conservative estimate
  let feeDragRatio = grossProfitD.gt(0)
    ? Number(Decimal.min(99, estFeesD.div(grossProfitD).mul(100)).toFixed(1))
    : 0;

  const last5 = markers.slice(-5);
  const last5NetD = last5.reduce(
    (acc, m) => acc.plus(new Decimal(String(m.net_pnl_usd))),
    new Decimal(0)
  );
  let bleedVelocity = last5.length
    ? Number(last5NetD.div(last5.length).toFixed(2))
    : 0;

  // Per-symbol bleed breakdown
  const symMap = new Map<string, { trades: number; wins: number; losses: number; pnl: Decimal }>();
  for (const sym of NEON_CORE_UNIVERSE) {
    symMap.set(sym, { trades: 0, wins: 0, losses: 0, pnl: new Decimal(0) });
  }
  for (const m of markers) {
    const entry = symMap.get(m.symbol) || { trades: 0, wins: 0, losses: 0, pnl: new Decimal(0) };
    entry.trades += 1;
    if (m.is_win) entry.wins += 1;
    else entry.losses += 1;
    entry.pnl = entry.pnl.plus(new Decimal(String(m.net_pnl_usd)));
    symMap.set(m.symbol, entry);
  }

  let symbolHealth: SymbolBleedStat[] = Array.from(symMap.entries())
    .map(([symbol, st]) => {
      const wr = st.trades > 0 ? Number(new Decimal(st.wins).div(st.trades).mul(100).toFixed(1)) : 0;
      const pnl = Number(st.pnl.toFixed(2));
      const status: SymbolBleedStat['status'] =
        st.trades >= 3 && (pnl < -1.2 || wr < 40)
          ? 'BLEEDING'
          : pnl < 0 || (st.trades >= 3 && wr < 50)
          ? 'DRIFTING'
          : 'HEALTHY';
      return {
        symbol,
        trades: st.trades,
        wins: st.wins,
        losses: st.losses,
        win_rate_pct: wr,
        net_pnl_usd: pnl,
        status,
      };
    })
    .sort((a, b) => a.net_pnl_usd - b.net_pnl_usd);

  // Optional Stress Drill or Win Simulation injection (explicitly tagged)
  if (simulateBleed) {
    currentDdPct = 6.84;
    maxDdPct = Math.max(maxDdPct, 7.12);
    consecutiveLosses = 4;
    rolling10Wr = 30.0;
    rolling10Net = -13.68;
    rolling10Exp = -1.37;
    feeDragRatio = 44.6;
    bleedVelocity = -2.42;
    regime = 'CHOP_COMPRESSION';
    symbolHealth = [
      { symbol: 'SOLUSDT', trades: 9, wins: 2, losses: 7, win_rate_pct: 22.2, net_pnl_usd: -7.85, status: 'BLEEDING' },
      { symbol: 'ETHUSDT', trades: 7, wins: 2, losses: 5, win_rate_pct: 28.6, net_pnl_usd: -4.92, status: 'BLEEDING' },
      { symbol: 'LINKUSDT', trades: 5, wins: 2, losses: 3, win_rate_pct: 40.0, net_pnl_usd: -1.45, status: 'DRIFTING' },
      { symbol: 'BNBUSDT', trades: 4, wins: 2, losses: 2, win_rate_pct: 50.0, net_pnl_usd: 0.18, status: 'HEALTHY' },
      { symbol: 'BTCUSDT', trades: 6, wins: 4, losses: 2, win_rate_pct: 66.7, net_pnl_usd: 2.36, status: 'HEALTHY' },
    ];
  } else if (simulateWin) {
    currentDdPct = 0.42;
    maxDdPct = 1.85;
    consecutiveLosses = 0;
    rolling10Wr = 70.0;
    rolling10Net = 48.6;
    rolling10Exp = 4.86;
    feeDragRatio = 6.4;
    bleedVelocity = 5.45;
    regime = 'TREND_EXPANSION';
    symbolHealth = [
      { symbol: 'BTCUSDT', trades: 12, wins: 9, losses: 3, win_rate_pct: 75.0, net_pnl_usd: 28.4, status: 'HEALTHY' },
      { symbol: 'ETHUSDT', trades: 10, wins: 7, losses: 3, win_rate_pct: 70.0, net_pnl_usd: 21.15, status: 'HEALTHY' },
      { symbol: 'SOLUSDT', trades: 11, wins: 8, losses: 3, win_rate_pct: 72.7, net_pnl_usd: 24.8, status: 'HEALTHY' },
      { symbol: 'LINKUSDT', trades: 9, wins: 6, losses: 3, win_rate_pct: 66.7, net_pnl_usd: 15.65, status: 'HEALTHY' },
      { symbol: 'BNBUSDT', trades: 8, wins: 5, losses: 3, win_rate_pct: 62.5, net_pnl_usd: 11.2, status: 'HEALTHY' },
    ];
  }

  // Composite Bleed Score (0..100) using exact Decimal arithmetic
  let scoreD = new Decimal(0);
  const triggers: string[] = [];

  if (currentDdPct >= 5.0) {
    scoreD = scoreD.plus(35);
    triggers.push(`Active drawdown ${currentDdPct.toFixed(2)}% exceeds 5.0% critical threshold`);
  } else if (currentDdPct >= 2.5) {
    scoreD = scoreD.plus(18);
    triggers.push(`Active drawdown ${currentDdPct.toFixed(2)}% above 2.5% watch band`);
  } else if (currentDdPct >= 1.2) {
    scoreD = scoreD.plus(8);
  }

  if (consecutiveLosses >= 4) {
    scoreD = scoreD.plus(30);
    triggers.push(`${consecutiveLosses} consecutive stop-outs (revenge-trade risk)`);
  } else if (consecutiveLosses >= 2) {
    scoreD = scoreD.plus(14);
    triggers.push(`${consecutiveLosses}-trade losing streak detected`);
  }

  if (rolling10Exp < 0) {
    scoreD = scoreD.plus(rolling10Exp < -0.75 ? 20 : 12);
    triggers.push(`Negative rolling 10-trade expectancy (${rolling10Exp >= 0 ? '+' : ''}$${rolling10Exp.toFixed(2)}/trade)`);
  }

  if (feeDragRatio >= 35) {
    scoreD = scoreD.plus(15);
    triggers.push(`Elevated fee drag (${feeDragRatio.toFixed(1)}% of gross profit)`);
  } else if (feeDragRatio >= 22) {
    scoreD = scoreD.plus(7);
  }

  const bleedingSymbols = symbolHealth.filter((s) => s.status === 'BLEEDING');
  if (bleedingSymbols.length > 0) {
    scoreD = scoreD.plus(Math.min(15, bleedingSymbols.length * 7));
    triggers.push(`Bleeding symbols: ${bleedingSymbols.map((s) => `${s.symbol} ($${s.net_pnl_usd.toFixed(2)})`).join(', ')}`);
  }

  const bleedScore = Math.min(100, Math.max(0, Math.round(scoreD.toNumber())));
  let circuitTier: BleedCircuitTier = 'NOMINAL';
  if (bleedScore >= 75) circuitTier = 'CRITICAL_BLEED_LOCK';
  else if (bleedScore >= 50) circuitTier = 'BLEED_WARNING';
  else if (bleedScore >= 25) circuitTier = 'WATCH';

  if (triggers.length === 0) {
    triggers.push('All bleed sensors nominal — positive expectancy & bounded drawdown.');
  }

  // 4. Dynamic Adaptive Quant Parameter Computation (Exact Decimal)
  const baseRiskD = new Decimal(String(cfg.risk_per_trade_pct));
  const baseAdxD = new Decimal(String(cfg.min_adx_14));
  const baseSlAtrD = new Decimal(String(cfg.sl_atr_multiplier));
  const baseTpRD = new Decimal(String(cfg.tp_r_multiple));
  const baseSlots = cfg.max_concurrent_positions;
  const baseCooldown = cfg.sl_cooldown_minutes;

  let riskMultD = new Decimal(1);
  let adxDelta = 0;
  let slAtrDeltaD = new Decimal(0);
  let tpRDeltaD = new Decimal(0);
  let slotsCap = baseSlots;
  let cooldownDelta = 0;
  const reasons: string[] = [];

  if (cfg.dynamic_adaptation_enabled) {
    if (regime === 'TREND_EXPANSION') {
      riskMultD = riskMultD.mul('1.15');
      tpRDeltaD = tpRDeltaD.plus('0.25');
      reasons.push('Trend Expansion: +15% dynamic risk lift & +0.25R TP extension for fat tails.');
    } else if (regime === 'VOLATILITY_SPIKE') {
      riskMultD = riskMultD.mul('0.70');
      slAtrDeltaD = slAtrDeltaD.plus('0.25');
      slotsCap = Math.min(slotsCap, 2);
      reasons.push(`Volatility Spike (${volExpansionRatio}x ATR): -30% risk throttle, +0.25x ATR stop buffer, max 2 slots.`);
    } else if (regime === 'CHOP_COMPRESSION') {
      riskMultD = riskMultD.mul('0.65');
      adxDelta += 4;
      cooldownDelta += 25;
      slotsCap = Math.min(slotsCap, 2);
      reasons.push(`Chop Compression (Avg ADX ${avgAdx}): -35% risk, +4 ADX floor, +25m cooldown.`);
    } else {
      reasons.push('Balanced Microstructure: baseline 1.00x dynamic risk scaling active.');
    }
  } else {
    reasons.push('Dynamic volatility adaptation paused — using fixed base parameters.');
  }

  if (cfg.auto_bleed_guard_enabled) {
    if (circuitTier === 'CRITICAL_BLEED_LOCK') {
      riskMultD = riskMultD.mul('0.25');
      adxDelta += 6;
      cooldownDelta += 45;
      slotsCap = 1;
      reasons.push('CRITICAL BLEED GUARD: Quarter-Kelly survival sizing (0.25x), +6 ADX gate, 1-slot cap.');
    } else if (circuitTier === 'BLEED_WARNING') {
      riskMultD = riskMultD.mul('0.50');
      adxDelta += 3;
      cooldownDelta += 20;
      slotsCap = Math.min(slotsCap, 2);
      reasons.push('BLEED WARNING GUARD: Half-Kelly defense (0.50x), +3 ADX gate, +20m post-SL cooldown.');
    } else if (circuitTier === 'WATCH') {
      riskMultD = riskMultD.mul('0.80');
      adxDelta += 1;
      reasons.push('WATCH GUARD: Early drawdown friction — 0.80x conservative risk throttle.');
    }
  }

  // Half-Kelly theoretical reference from rolling win rate & reward/risk
  const wrProbD = new Decimal(String(Math.max(10, Math.min(85, rolling10Wr)))).div(100);
  const payoffD = Decimal.max('1.1', baseTpRD.plus(tpRDeltaD));
  const rawKellyD = wrProbD.minus(new Decimal(1).minus(wrProbD).div(payoffD));
  const halfKellyPct = Number(
    Decimal.max(0.25, Decimal.min(2.5, rawKellyD.mul(100).mul('0.25'))).toFixed(2)
  );

  const effectiveRiskPct = Number(
    Decimal.max('0.25', Decimal.min('2.50', baseRiskD.mul(riskMultD))).toFixed(2)
  );
  const effectiveMinAdx = Math.min(36, Math.max(12, Math.round(baseAdxD.plus(adxDelta).toNumber())));
  const effectiveSlAtr = Number(
    Decimal.max('1.00', Decimal.min('2.40', baseSlAtrD.plus(slAtrDeltaD))).toFixed(2)
  );
  const effectiveTpR = Number(
    Decimal.max('1.40', Decimal.min('3.50', baseTpRD.plus(tpRDeltaD))).toFixed(2)
  );
  const effectiveCooldown = Math.min(180, Math.max(0, baseCooldown + cooldownDelta));

  const aiHistory = loadAiAssessmentHistory();

  return {
    timestamp_utc: new Date().toISOString(),
    dynamic_adaptation_enabled: cfg.dynamic_adaptation_enabled,
    auto_bleed_guard_enabled: cfg.auto_bleed_guard_enabled,
    microstructure: {
      regime,
      avg_atr_pct: avgAtrPct,
      vol_expansion_ratio: volExpansionRatio,
      avg_adx_14: avgAdx,
      macro_regime: macroRegime,
      macro_breadth_pct: macroBreadthPct,
      approved_signals: scanner.approved_count,
      total_universe: scanner.evaluations.length,
    },
    bleed_telemetry: {
      data_mode: simulateBleed
        ? 'BLEED_STRESS_DRILL'
        : simulateWin
        ? 'WIN_SIMULATION'
        : 'LIVE_TELEMETRY',
      bleed_score: bleedScore,
      circuit_tier: circuitTier,
      current_drawdown_pct: Number(currentDdPct.toFixed(2)),
      max_drawdown_pct: Number(maxDdPct.toFixed(2)),
      consecutive_losses: consecutiveLosses,
      rolling_10_win_rate_pct: rolling10Wr,
      rolling_10_expectancy_usd: rolling10Exp,
      rolling_10_net_pnl_usd: rolling10Net,
      fee_drag_ratio_pct: feeDragRatio,
      bleed_velocity_usd_per_trade: bleedVelocity,
      is_bleeding: bleedScore >= 50,
      triggers,
      symbol_health: symbolHealth,
    },
    adaptive_params: {
      base_risk_pct: cfg.risk_per_trade_pct,
      effective_risk_pct: effectiveRiskPct,
      risk_multiplier: Number(riskMultD.toFixed(2)),
      kelly_half_pct: halfKellyPct,
      base_min_adx: cfg.min_adx_14,
      effective_min_adx: effectiveMinAdx,
      base_sl_atr: cfg.sl_atr_multiplier,
      effective_sl_atr: effectiveSlAtr,
      base_tp_r: cfg.tp_r_multiple,
      effective_tp_r: effectiveTpR,
      base_max_slots: baseSlots,
      effective_max_slots: Math.max(1, slotsCap),
      base_cooldown_min: baseCooldown,
      effective_cooldown_min: effectiveCooldown,
      adaptation_reasons: reasons,
    },
    latest_ai_assessment: aiHistory[0] || null,
    ai_history_count: aiHistory.length,
  };
}

export async function runNeonAiBleedAssessment(params: {
  dynamicState: NeonDynamicStatePayload;
  config: NeonStrategyConfig;
  focusNote?: string;
}): Promise<NeonAiBleedAssessment> {
  const ai = getGeminiClient();
  if (!ai) {
    throw new Error(
      'GEMINI_API_KEY is not configured on the server. Add your Gemini API key in Settings > Secrets to run AI Bleed Assessments.'
    );
  }

  const primaryModel = 'gemini-4-hydrogen';
  const fallbackModel = 'gemini-3.1-flash-lite';
  const { dynamicState, config, focusNote } = params;

  const telemetryDigest = {
    strategy: `${config.strategy_name} v${config.version}`,
    current_config: {
      enabled: config.enabled,
      risk_per_trade_pct: config.risk_per_trade_pct,
      min_adx_14: config.min_adx_14,
      sl_atr_multiplier: config.sl_atr_multiplier,
      tp_r_multiple: config.tp_r_multiple,
      sl_cooldown_minutes: config.sl_cooldown_minutes,
      max_concurrent_positions: config.max_concurrent_positions,
      session_gate_enabled: config.session_gate_enabled,
    },
    microstructure: dynamicState.microstructure,
    bleed_telemetry: dynamicState.bleed_telemetry,
    adaptive_params_computed: dynamicState.adaptive_params,
    trader_focus_note: focusNote ? focusNote.trim().slice(0, 300) : null,
  };

  const systemInstruction =
    'You are a senior quantitative risk officer and algorithmic crypto futures strategist auditing the NEON Regime-Adaptive Pullback-Resumption strategy. ' +
    'Analyze the exact telemetry payload (drawdown, consecutive losses, rolling 10-trade expectancy, fee drag ratio, volatility expansion, ADX chop, and per-symbol PnL). ' +
    'Diagnose precisely WHY the strategy is bleeding or where hidden bleed vulnerability exists, and output a surgical, mathematically disciplined remediation patch within strict institutional risk bounds: ' +
    'risk_per_trade_pct in [0.25, 2.5], min_adx_14 in [14, 34], tp_r_multiple in [1.5, 3.2], sl_atr_multiplier in [1.1, 2.2], sl_cooldown_minutes in [15, 120], max_concurrent_positions in [1, 4]. ' +
    'Keep prose concise, quantitative, and free of filler.';

  const responseSchema = {
    type: Type.OBJECT,
    properties: {
      diagnosis_headline: {
        type: Type.STRING,
        description: 'Concise 1-sentence institutional diagnosis headline.',
      },
      bleed_severity: {
        type: Type.STRING,
        description: 'One of NOMINAL, WATCH, BLEED_WARNING, CRITICAL_BLEED_LOCK.',
      },
      confidence_pct: {
        type: Type.INTEGER,
        description: 'Assessment confidence from 50 to 99.',
      },
      executive_summary: {
        type: Type.STRING,
        description: '2-3 crisp sentences explaining current performance health, bleed vectors, and regime fit.',
      },
      root_causes: {
        type: Type.ARRAY,
        items: {
          type: Type.OBJECT,
          properties: {
            category: { type: Type.STRING },
            severity: { type: Type.STRING },
            evidence: { type: Type.STRING },
            impact: { type: Type.STRING },
          },
          required: ['category', 'severity', 'evidence', 'impact'],
        },
      },
      surgical_remediation_plan: {
        type: Type.ARRAY,
        items: { type: Type.STRING },
      },
      recommended_config_patch: {
        type: Type.OBJECT,
        properties: {
          risk_per_trade_pct: { type: Type.NUMBER },
          min_adx_14: { type: Type.INTEGER },
          tp_r_multiple: { type: Type.NUMBER },
          sl_atr_multiplier: { type: Type.NUMBER },
          sl_cooldown_minutes: { type: Type.INTEGER },
          max_concurrent_positions: { type: Type.INTEGER },
          session_gate_enabled: { type: Type.BOOLEAN },
          enabled: { type: Type.BOOLEAN },
        },
        required: [
          'risk_per_trade_pct',
          'min_adx_14',
          'tp_r_multiple',
          'sl_atr_multiplier',
          'sl_cooldown_minutes',
          'max_concurrent_positions',
          'session_gate_enabled',
          'enabled',
        ],
      },
      symbols_to_quarantine: {
        type: Type.ARRAY,
        items: { type: Type.STRING },
      },
      expected_impact_summary: {
        type: Type.STRING,
        description: 'Concrete expected impact on drawdown, win rate, and expectancy.',
      },
    },
    required: [
      'diagnosis_headline',
      'bleed_severity',
      'confidence_pct',
      'executive_summary',
      'root_causes',
      'surgical_remediation_plan',
      'recommended_config_patch',
      'symbols_to_quarantine',
      'expected_impact_summary',
    ],
  };

  const promptContents = `Perform an institutional NEON Bleed & Adaptive Strategy Audit on the following live telemetry:\n${JSON.stringify(telemetryDigest, null, 2)}`;

  const attempts: Array<{ model: string; thinking: ThinkingLevel | null; delayMs: number }> = [
    { model: primaryModel, thinking: ThinkingLevel.MEDIUM, delayMs: 0 },
    { model: primaryModel, thinking: ThinkingLevel.LOW, delayMs: 900 },
    { model: fallbackModel, thinking: null, delayMs: 600 },
  ];

  let responseText = '';
  let modelName = primaryModel;
  let lastError: unknown = null;

  for (const attempt of attempts) {
    if (attempt.delayMs > 0) {
      await new Promise((r) => setTimeout(r, attempt.delayMs));
    }
    try {
      const cfgPayload: Record<string, unknown> = {
        systemInstruction,
        responseMimeType: 'application/json',
        responseSchema,
      };
      if (attempt.thinking) {
        cfgPayload.thinkingConfig = { thinkingLevel: attempt.thinking };
      }
      const resp = await ai.models.generateContent({
        model: attempt.model,
        contents: promptContents,
        config: cfgPayload,
      });
      responseText = (resp.text ?? '').trim();
      modelName = attempt.model;
      if (responseText) break;
    } catch (err) {
      lastError = err;
      const errStr = err instanceof Error ? err.message : String(err);
      const isTransient = errStr.includes('503') || errStr.includes('UNAVAILABLE') || errStr.includes('429');
      if (!isTransient) break;
    }
  }

  if (!responseText) {
    const rawMsg = lastError instanceof Error ? lastError.message : String(lastError || 'Gemini API request failed.');
    try {
      const parsedErr = JSON.parse(rawMsg) as { error?: { message?: string } };
      if (parsedErr?.error?.message) {
        throw new Error(parsedErr.error.message);
      }
    } catch (inner) {
      if (inner instanceof Error && inner.message !== rawMsg && !inner.message.includes('JSON')) {
        throw inner;
      }
    }
    throw new Error(rawMsg);
  }

  const rawText = responseText;
  if (!rawText) {
    throw new Error('Gemini returned an empty response during NEON bleed assessment.');
  }

  let parsed: Record<string, unknown>;
  try {
    parsed = JSON.parse(rawText) as Record<string, unknown>;
  } catch {
    throw new Error('Failed to parse structured JSON response from Gemini AI Bleed Auditor.');
  }

  const validTiers: BleedCircuitTier[] = ['NOMINAL', 'WATCH', 'BLEED_WARNING', 'CRITICAL_BLEED_LOCK'];
  const rawTier = String(parsed.bleed_severity || dynamicState.bleed_telemetry.circuit_tier).toUpperCase();
  const bleedSeverity: BleedCircuitTier = validTiers.includes(rawTier as BleedCircuitTier)
    ? (rawTier as BleedCircuitTier)
    : dynamicState.bleed_telemetry.circuit_tier;

  const rawPatch = (parsed.recommended_config_patch || {}) as Record<string, unknown>;
  const clamp = (val: unknown, min: number, max: number, fallback: number, decimals = 2) => {
    const n = Number(val);
    const safe = Number.isFinite(n) ? Math.min(max, Math.max(min, n)) : fallback;
    return Number(safe.toFixed(decimals));
  };

  const sanitizedPatch: NeonAiConfigPatch = {
    risk_per_trade_pct: clamp(rawPatch.risk_per_trade_pct, 0.25, 2.5, dynamicState.adaptive_params.effective_risk_pct, 2),
    min_adx_14: Math.round(clamp(rawPatch.min_adx_14, 14, 34, dynamicState.adaptive_params.effective_min_adx, 0)),
    tp_r_multiple: clamp(rawPatch.tp_r_multiple, 1.5, 3.2, dynamicState.adaptive_params.effective_tp_r, 2),
    sl_atr_multiplier: clamp(rawPatch.sl_atr_multiplier, 1.1, 2.2, dynamicState.adaptive_params.effective_sl_atr, 2),
    sl_cooldown_minutes: Math.round(clamp(rawPatch.sl_cooldown_minutes, 15, 120, dynamicState.adaptive_params.effective_cooldown_min, 0)),
    max_concurrent_positions: Math.round(clamp(rawPatch.max_concurrent_positions, 1, 4, dynamicState.adaptive_params.effective_max_slots, 0)),
    session_gate_enabled: typeof rawPatch.session_gate_enabled === 'boolean' ? rawPatch.session_gate_enabled : true,
    enabled: typeof rawPatch.enabled === 'boolean' ? rawPatch.enabled : true,
  };

  const validSeverities = new Set(['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']);
  const rootCauses: NeonAiRootCause[] = Array.isArray(parsed.root_causes)
    ? parsed.root_causes.slice(0, 5).map((item: unknown) => {
        const obj = (item && typeof item === 'object' ? item : {}) as Record<string, unknown>;
        const sev = String(obj.severity || 'MEDIUM').toUpperCase();
        return {
          category: String(obj.category || 'RISK_DRIFT').slice(0, 48),
          severity: (validSeverities.has(sev) ? sev : 'MEDIUM') as NeonAiRootCause['severity'],
          evidence: String(obj.evidence || '').slice(0, 240),
          impact: String(obj.impact || '').slice(0, 220),
        };
      })
    : [];

  const assessment: NeonAiBleedAssessment = {
    assessment_id: `NEON-AI-${Date.now().toString(36).toUpperCase()}`,
    timestamp_utc: new Date().toISOString(),
    model: modelName,
    data_mode: dynamicState.bleed_telemetry.data_mode,
    bleed_score_at_audit: dynamicState.bleed_telemetry.bleed_score,
    diagnosis_headline: String(parsed.diagnosis_headline || 'NEON Dynamic Strategy Audit Completed').slice(0, 180),
    bleed_severity: bleedSeverity,
    confidence_pct: Math.round(clamp(parsed.confidence_pct, 50, 99, 82, 0)),
    executive_summary: String(parsed.executive_summary || '').slice(0, 600),
    root_causes: rootCauses,
    surgical_remediation_plan: Array.isArray(parsed.surgical_remediation_plan)
      ? parsed.surgical_remediation_plan.slice(0, 6).map((s) => String(s).slice(0, 220))
      : [],
    recommended_config_patch: sanitizedPatch,
    symbols_to_quarantine: Array.isArray(parsed.symbols_to_quarantine)
      ? parsed.symbols_to_quarantine.slice(0, 5).map((s) => String(s).toUpperCase())
      : [],
    expected_impact_summary: String(parsed.expected_impact_summary || '').slice(0, 320),
  };

  saveAiAssessment(assessment);
  return assessment;
}
