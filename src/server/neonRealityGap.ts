import path from 'path';
import Decimal from 'decimal.js';
import { DATA_DIR, readJsonSafe } from './dataStore.js';
import { NEON_ALPHA_UTC_HOURS, NEON_CORE_UNIVERSE } from './neonStrategy.js';

// ============================================================================
// NEON REALITY GAP ENGINE — Exact-Decimal Simulated vs. Observed Live Binance
// Compares active simulated Win/Loss performance, Fee Drag, and Slippage
// against real historical Binance Futures execution outcomes in
// data/live_audit_summary.json.
// ============================================================================

export type LiveCohortKey = 'ALL_LIVE' | 'NEON_GATED_LIVE';

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

export interface ExecutionSnapshotMetrics {
  label: string;
  trades: number;
  wins: number;
  losses: number;
  win_rate_pct: number;
  loss_rate_pct: number;
  profit_factor: number;
  payoff_ratio: number;
  expectancy_usd: number;
  gross_pnl_usd: number;
  fees_usd: number;
  slippage_usd: number;
  funding_usd: number;
  net_pnl_usd: number;
  total_notional_usd: number;
  fee_drag_pct: number; // Exchange fees as % of gross profit
  fee_bps: number; // Round-trip fees in bps of notional
  slippage_bps: number; // Realized/estimated execution & SL overshoot slippage in bps
  funding_bps: number; // 8h perpetual funding drag in bps of notional
  total_friction_bps: number; // fee_bps + slippage_bps + funding_bps
  sl_hit_rate_pct: number;
  avg_hold_minutes: number;
  inferred_taker_share_pct: number;
}

export interface RealityGapVarianceRow {
  metric_key: string;
  metric_label: string;
  unit: 'pct' | 'x' | 'bps' | 'usd';
  simulated_value: number;
  observed_value: number;
  variance: number; // simulated - observed
  status: 'ALIGNED' | 'FAVORABLE_EDGE' | 'OPTIMISM_RISK' | 'UNDER_MODELED' | 'CONSERVATIVE';
  note: string;
}

export interface RealityGapCohortComparison {
  cohort_key: LiveCohortKey;
  cohort_label: string;
  cohort_description: string;
  date_start_utc: string | null;
  date_end_utc: string | null;
  alignment_status: 'WELL_CALIBRATED' | 'MODERATE_DRIFT' | 'OPTIMISM_BIAS' | 'CONSERVATIVE_BIAS';
  calibration_score_pct: number; // 0..100
  headline: string;
  observed_live: ExecutionSnapshotMetrics;
  simulated: ExecutionSnapshotMetrics;
  variances: {
    win_rate_gap_pp: number;
    loss_rate_gap_pp: number;
    profit_factor_gap: number;
    payoff_ratio_gap: number;
    fee_drag_gap_pp: number;
    fee_bps_gap: number;
    slippage_bps_gap: number;
    funding_bps_gap: number;
    total_friction_bps_gap: number;
  };
  rows: RealityGapVarianceRow[];
  slippage_audit_detail: {
    sl_fills_count: number;
    avg_sl_loss_pct: number;
    sl_overshoot_bps: number;
    price_residual_bps: number;
    spread_impact_bps: number;
  };
}

export interface NeonRealityGapPayload {
  computed_at_utc: string;
  scenario: string;
  scenario_label: string;
  cohorts: Record<LiveCohortKey, RealityGapCohortComparison>;
}

export interface SimulatedGapInput {
  scenario: string;
  scenario_label: string;
  trades: number;
  wins: number;
  losses: number;
  gross_profit_usd: Decimal;
  gross_loss_usd: Decimal;
  gross_before_friction_usd: Decimal;
  fees_usd: Decimal;
  slippage_usd: Decimal;
  funding_usd: Decimal;
  net_pnl_usd: Decimal;
  total_notional_usd: Decimal;
  maker_fill_ratio_pct: number;
  sl_fills_count: number;
}

const LIVE_AUDIT_PATH = path.join(DATA_DIR, 'live_audit_summary.json');

function computeObservedCohort(
  label: string,
  trades: Array<RawLiveTrade & { utcHour: number; minsSinceSl: number }>
): {
  metrics: ExecutionSnapshotMetrics;
  slippageDetail: RealityGapCohortComparison['slippage_audit_detail'];
  startUtc: string | null;
  endUtc: string | null;
} {
  let wins = 0;
  let losses = 0;
  let slCount = 0;
  let grossWinD = new Decimal(0);
  let grossLossD = new Decimal(0);
  let grossPnlD = new Decimal(0);
  let feesD = new Decimal(0);
  let netPnlD = new Decimal(0);
  let notionalD = new Decimal(0);
  let slLossPctSumD = new Decimal(0);
  let slOvershootUsdD = new Decimal(0);
  let residualImpactUsdD = new Decimal(0);
  let fundingUsdD = new Decimal(0);
  let totalDurationSec = 0;

  // Nominal stop baseline on Binance live audit (1.00% stop distance)
  const nominalStopFracD = new Decimal('0.0100');
  const stdFunding8hRateD = new Decimal('0.0001'); // 1.0 bps per 8h standard Binance perp funding

  for (const t of trades) {
    const np = new Decimal(String(t.net_pnl ?? t.gross_pnl ?? 0));
    const gp = new Decimal(String(t.gross_pnl ?? 0));
    const fee = new Decimal(String(t.fee ?? 0));
    const not = new Decimal(String(t.notional ?? 0));
    const qty = new Decimal(String(t.quantity ?? 0));
    const entryPx = new Decimal(String(t.entry_price ?? 0));
    const exitPx = new Decimal(String(t.exit_price ?? 0));
    const durSec = Math.max(0, Number(t.duration_seconds || 0));

    totalDurationSec += durSec;
    netPnlD = netPnlD.plus(np);
    grossPnlD = grossPnlD.plus(gp);
    feesD = feesD.plus(fee);
    notionalD = notionalD.plus(not);

    if (np.gt(0)) {
      wins += 1;
      grossWinD = grossWinD.plus(np);
    } else {
      losses += 1;
      grossLossD = grossLossD.plus(np.abs());
    }

    // 1. Price-to-gross residual impact (micro-fill / tick slippage variance)
    if (qty.gt(0) && entryPx.gt(0) && exitPx.gt(0)) {
      const sideSign = String(t.side || '').toUpperCase() === 'BUY' ? new Decimal(1) : new Decimal(-1);
      const theoreticalGross = exitPx.minus(entryPx).mul(qty).mul(sideSign);
      const residual = gp.minus(theoreticalGross).abs();
      // Ignore extreme outlier discrepancies > 1% of notional (e.g., multi-scale partial exits)
      if (not.gt(0) && residual.div(not).lte('0.01')) {
        residualImpactUsdD = residualImpactUsdD.plus(residual);
      }
    }

    // 2. Stop-loss market-order overshoot beyond nominal 1.00% stop distance
    const cid = String(t.client_order_id || '');
    if (cid.startsWith('SL_') && not.gt(0)) {
      slCount += 1;
      const absLossFrac = gp.abs().div(not);
      slLossPctSumD = slLossPctSumD.plus(absLossFrac.mul(100));
      if (absLossFrac.gt(nominalStopFracD)) {
        // Excess beyond nominal stop capped at 0.35% per stop-out (attribute realistic tail wick slip)
        const excessFrac = Decimal.min(new Decimal('0.0035'), absLossFrac.minus(nominalStopFracD));
        slOvershootUsdD = slOvershootUsdD.plus(not.mul(excessFrac));
      }
    }

    // 3. Observed 8-hour funding carry exposure proportional to exact hold duration
    if (not.gt(0) && durSec > 0) {
      const intervals = new Decimal(durSec).div(28800); // 8 hours = 28,800s
      fundingUsdD = fundingUsdD.plus(not.mul(stdFunding8hRateD).mul(intervals));
    }
  }

  const n = trades.length;
  const wrD = n > 0 ? new Decimal(wins).div(n).mul(100) : new Decimal(0);
  const lrD = n > 0 ? new Decimal(losses).div(n).mul(100) : new Decimal(0);
  const pfD = grossLossD.gt(0)
    ? grossWinD.div(grossLossD)
    : wins > 0
    ? new Decimal(9.99)
    : new Decimal(0);
  const avgWinD = wins > 0 ? grossWinD.div(wins) : new Decimal(0);
  const avgLossD = losses > 0 ? grossLossD.div(losses) : new Decimal(0);
  const payoffD = avgLossD.gt(0) ? avgWinD.div(avgLossD) : new Decimal(0);
  const expD = n > 0 ? netPnlD.div(n) : new Decimal(0);

  const feeDragD = grossPnlD.gt(0)
    ? feesD.div(grossPnlD).mul(100)
    : feesD.gt(0)
    ? new Decimal(100)
    : new Decimal(0);
  const feeBpsD = notionalD.gt(0) ? feesD.div(notionalD).mul(10000) : new Decimal(0);

  // Infer actual taker leg share from observed round-trip fee bps (4.0 bps = 100% maker, 9.0 bps = 100% taker)
  const takerShareD = Decimal.max(
    0,
    Decimal.min(1, feeBpsD.minus(4).div(5))
  );
  // Taker spread crossing impact (~1.6 bps per taker leg -> up to 3.2 bps round-trip on 100% taker)
  const spreadImpactBpsD = takerShareD.mul('3.2');
  const slOvershootBpsD = notionalD.gt(0) ? slOvershootUsdD.div(notionalD).mul(10000) : new Decimal(0);
  const priceResidualBpsD = notionalD.gt(0)
    ? residualImpactUsdD.div(notionalD).mul(10000)
    : new Decimal(0);
  const totalSlippageBpsD = slOvershootBpsD.plus(priceResidualBpsD).plus(spreadImpactBpsD);
  const totalSlippageUsdD = notionalD.mul(totalSlippageBpsD).div(10000);
  const fundingBpsD = notionalD.gt(0) ? fundingUsdD.div(notionalD).mul(10000) : new Decimal(0);
  const totalFrictionBpsD = feeBpsD.plus(totalSlippageBpsD).plus(fundingBpsD);

  const avgSlLossPct = slCount > 0 ? Number(slLossPctSumD.div(slCount).toFixed(2)) : 0;
  const slHitRatePct = n > 0 ? Number(new Decimal(slCount).div(n).mul(100).toFixed(1)) : 0;
  const avgHoldMin = n > 0 ? Number((totalDurationSec / n / 60).toFixed(1)) : 0;

  return {
    metrics: {
      label,
      trades: n,
      wins,
      losses,
      win_rate_pct: Number(wrD.toFixed(1)),
      loss_rate_pct: Number(lrD.toFixed(1)),
      profit_factor: Number(Decimal.min(9.99, pfD).toFixed(2)),
      payoff_ratio: Number(payoffD.toFixed(2)),
      expectancy_usd: Number(expD.toFixed(3)),
      gross_pnl_usd: Number(grossPnlD.toFixed(2)),
      fees_usd: Number(feesD.toFixed(2)),
      slippage_usd: Number(totalSlippageUsdD.toFixed(2)),
      funding_usd: Number(fundingUsdD.toFixed(2)),
      net_pnl_usd: Number(netPnlD.toFixed(2)),
      total_notional_usd: Number(notionalD.toFixed(2)),
      fee_drag_pct: Number(Decimal.min(250, feeDragD).toFixed(1)),
      fee_bps: Number(feeBpsD.toFixed(2)),
      slippage_bps: Number(totalSlippageBpsD.toFixed(2)),
      funding_bps: Number(fundingBpsD.toFixed(2)),
      total_friction_bps: Number(totalFrictionBpsD.toFixed(2)),
      sl_hit_rate_pct: slHitRatePct,
      avg_hold_minutes: avgHoldMin,
      inferred_taker_share_pct: Number(takerShareD.mul(100).toFixed(1)),
    },
    slippageDetail: {
      sl_fills_count: slCount,
      avg_sl_loss_pct: avgSlLossPct,
      sl_overshoot_bps: Number(slOvershootBpsD.toFixed(2)),
      price_residual_bps: Number(priceResidualBpsD.toFixed(2)),
      spread_impact_bps: Number(spreadImpactBpsD.toFixed(2)),
    },
    startUtc: trades[0]?.entry_time || null,
    endUtc: trades[trades.length - 1]?.exit_time || null,
  };
}

function buildSimulatedSnapshot(sim: SimulatedGapInput): ExecutionSnapshotMetrics {
  const n = Math.max(0, sim.trades);
  const wrD = n > 0 ? new Decimal(sim.wins).div(n).mul(100) : new Decimal(0);
  const lrD = n > 0 ? new Decimal(sim.losses).div(n).mul(100) : new Decimal(0);
  const pfD = sim.gross_loss_usd.gt(0)
    ? sim.gross_profit_usd.div(sim.gross_loss_usd)
    : sim.gross_profit_usd.gt(0)
    ? new Decimal(9.99)
    : new Decimal(0);
  const avgWinD = sim.wins > 0 ? sim.gross_profit_usd.div(sim.wins) : new Decimal(0);
  const avgLossD = sim.losses > 0 ? sim.gross_loss_usd.div(sim.losses) : new Decimal(0);
  const payoffD = avgLossD.gt(0) ? avgWinD.div(avgLossD) : new Decimal(0);
  const expD = n > 0 ? sim.net_pnl_usd.div(n) : new Decimal(0);

  const feeDragD = sim.gross_before_friction_usd.gt(0)
    ? sim.fees_usd.div(sim.gross_before_friction_usd).mul(100)
    : sim.fees_usd.gt(0)
    ? new Decimal(100)
    : new Decimal(0);

  const feeBpsD = sim.total_notional_usd.gt(0)
    ? sim.fees_usd.div(sim.total_notional_usd).mul(10000)
    : new Decimal(0);
  const slipBpsD = sim.total_notional_usd.gt(0)
    ? sim.slippage_usd.div(sim.total_notional_usd).mul(10000)
    : new Decimal(0);
  const fundBpsD = sim.total_notional_usd.gt(0)
    ? sim.funding_usd.div(sim.total_notional_usd).mul(10000)
    : new Decimal(0);
  const totalFricBpsD = feeBpsD.plus(slipBpsD).plus(fundBpsD);
  const slHitRatePct = n > 0 ? Number(new Decimal(sim.sl_fills_count).div(n).mul(100).toFixed(1)) : 0;

  return {
    label: sim.scenario_label,
    trades: n,
    wins: sim.wins,
    losses: sim.losses,
    win_rate_pct: Number(wrD.toFixed(1)),
    loss_rate_pct: Number(lrD.toFixed(1)),
    profit_factor: Number(Decimal.min(9.99, pfD).toFixed(2)),
    payoff_ratio: Number(payoffD.toFixed(2)),
    expectancy_usd: Number(expD.toFixed(3)),
    gross_pnl_usd: Number(sim.gross_before_friction_usd.toFixed(2)),
    fees_usd: Number(sim.fees_usd.toFixed(2)),
    slippage_usd: Number(sim.slippage_usd.toFixed(2)),
    funding_usd: Number(sim.funding_usd.toFixed(2)),
    net_pnl_usd: Number(sim.net_pnl_usd.toFixed(2)),
    total_notional_usd: Number(sim.total_notional_usd.toFixed(2)),
    fee_drag_pct: Number(Decimal.min(250, feeDragD).toFixed(1)),
    fee_bps: Number(feeBpsD.toFixed(2)),
    slippage_bps: Number(slipBpsD.toFixed(2)),
    funding_bps: Number(fundBpsD.toFixed(2)),
    total_friction_bps: Number(totalFricBpsD.toFixed(2)),
    sl_hit_rate_pct: slHitRatePct,
    avg_hold_minutes: 315,
    inferred_taker_share_pct: Number(Math.max(0, 100 - sim.maker_fill_ratio_pct).toFixed(1)),
  };
}

function buildCohortComparison(
  cohortKey: LiveCohortKey,
  cohortLabel: string,
  cohortDescription: string,
  observed: ExecutionSnapshotMetrics,
  simulated: ExecutionSnapshotMetrics,
  slippageDetail: RealityGapCohortComparison['slippage_audit_detail'],
  startUtc: string | null,
  endUtc: string | null
): RealityGapCohortComparison {
  const diff = (a: number, b: number, dp = 2) =>
    Number(new Decimal(String(a)).minus(new Decimal(String(b))).toFixed(dp));

  const wrGap = diff(simulated.win_rate_pct, observed.win_rate_pct, 1);
  const lrGap = diff(simulated.loss_rate_pct, observed.loss_rate_pct, 1);
  const pfGap = diff(simulated.profit_factor, observed.profit_factor, 2);
  const payoffGap = diff(simulated.payoff_ratio, observed.payoff_ratio, 2);
  const feeDragGap = diff(simulated.fee_drag_pct, observed.fee_drag_pct, 1);
  const feeBpsGap = diff(simulated.fee_bps, observed.fee_bps, 2);
  const slipBpsGap = diff(simulated.slippage_bps, observed.slippage_bps, 2);
  const fundBpsGap = diff(simulated.funding_bps, observed.funding_bps, 2);
  const totalFricGap = diff(simulated.total_friction_bps, observed.total_friction_bps, 2);

  // Calibration fidelity score (0..100): penalizes unrealistic WR inflation, zero/under-modeled slippage, and friction blind spots
  let penalty = new Decimal(0);
  // Win-rate gap penalty (excessive optimism penalized heavier than conservatism)
  penalty = penalty.plus(wrGap > 0 ? new Decimal(wrGap).mul('1.4') : new Decimal(Math.abs(wrGap)).mul('0.9'));
  // Slippage realism penalty (under-modeling slippage is a classic backtest trap)
  penalty = penalty.plus(
    slipBpsGap < -1.0 ? new Decimal(Math.abs(slipBpsGap)).mul('4.2') : new Decimal(Math.abs(slipBpsGap)).mul('1.5')
  );
  // Total friction bps divergence
  penalty = penalty.plus(
    totalFricGap < -2.0
      ? new Decimal(Math.abs(totalFricGap)).mul('3.0')
      : new Decimal(Math.abs(totalFricGap)).mul('1.0')
  );

  const calScore = Math.max(12, Math.min(99, Math.round(new Decimal(100).minus(penalty).toNumber())));

  let alignmentStatus: RealityGapCohortComparison['alignment_status'] = 'WELL_CALIBRATED';
  let headline = '';

  if (simulated.slippage_bps === 0 && observed.slippage_bps > 1) {
    alignmentStatus = 'OPTIMISM_BIAS';
    headline = `Zero-friction ceiling under-models live Binance slippage by ${Math.abs(slipBpsGap).toFixed(2)} bps and total friction by ${Math.abs(totalFricGap).toFixed(2)} bps.`;
  } else if (wrGap >= 8 || totalFricGap <= -4.5) {
    alignmentStatus = 'OPTIMISM_BIAS';
    headline = `Simulated assumptions outpace observed Binance live history (${wrGap >= 0 ? '+' : ''}${wrGap.toFixed(1)} pp WR gap, ${totalFricGap.toFixed(2)} bps friction delta).`;
  } else if (wrGap <= -6 || totalFricGap >= 4.0) {
    alignmentStatus = 'CONSERVATIVE_BIAS';
    headline = `Simulator models stricter friction & lower win rate than observed live cohort (${totalFricGap >= 0 ? '+' : ''}${totalFricGap.toFixed(2)} bps stress margin).`;
  } else if (calScore >= 72) {
    alignmentStatus = 'WELL_CALIBRATED';
    headline = `Near-realistic execution calibration: slippage (${slipBpsGap >= 0 ? '+' : ''}${slipBpsGap.toFixed(2)} bps) and total friction (${totalFricGap >= 0 ? '+' : ''}${totalFricGap.toFixed(2)} bps) track observed Binance Futures closely.`;
  } else {
    alignmentStatus = 'MODERATE_DRIFT';
    headline = `Moderate variance vs. observed Binance ledger: ${wrGap >= 0 ? '+' : ''}${wrGap.toFixed(1)} pp WR delta and ${feeDragGap >= 0 ? '+' : ''}${feeDragGap.toFixed(1)} pp fee-drag spread.`;
  }

  const rows: RealityGapVarianceRow[] = [
    {
      metric_key: 'win_rate_pct',
      metric_label: 'Win Rate',
      unit: 'pct',
      simulated_value: simulated.win_rate_pct,
      observed_value: observed.win_rate_pct,
      variance: wrGap,
      status: Math.abs(wrGap) <= 5 ? 'ALIGNED' : wrGap > 8 ? 'OPTIMISM_RISK' : wrGap > 0 ? 'FAVORABLE_EDGE' : 'CONSERVATIVE',
      note:
        wrGap > 8
          ? 'Sim WR materially above live history — verify regime & fill assumptions'
          : wrGap < -4
          ? 'Sim is stress-testing below observed historical win rate'
          : 'Within realistic ±5 pp sampling variance',
    },
    {
      metric_key: 'loss_rate_pct',
      metric_label: 'Loss Rate',
      unit: 'pct',
      simulated_value: simulated.loss_rate_pct,
      observed_value: observed.loss_rate_pct,
      variance: lrGap,
      status: Math.abs(lrGap) <= 5 ? 'ALIGNED' : lrGap < -8 ? 'OPTIMISM_RISK' : lrGap > 4 ? 'CONSERVATIVE' : 'FAVORABLE_EDGE',
      note: `Observed live SL market stops: ${observed.sl_hit_rate_pct}% of trades`,
    },
    {
      metric_key: 'profit_factor',
      metric_label: 'Profit Factor',
      unit: 'x',
      simulated_value: simulated.profit_factor,
      observed_value: observed.profit_factor,
      variance: pfGap,
      status: Math.abs(pfGap) <= 0.35 ? 'ALIGNED' : pfGap > 0.65 ? 'OPTIMISM_RISK' : pfGap > 0 ? 'FAVORABLE_EDGE' : 'CONSERVATIVE',
      note:
        cohortKey === 'ALL_LIVE'
          ? 'Live baseline dragged down by double-taker fees & quarantined alts'
          : 'Compared directly against NEON-gated Core Tier-1 live cohort',
    },
    {
      metric_key: 'payoff_ratio',
      metric_label: 'Payoff Ratio (Avg Win / Loss)',
      unit: 'x',
      simulated_value: simulated.payoff_ratio,
      observed_value: observed.payoff_ratio,
      variance: payoffGap,
      status: Math.abs(payoffGap) <= 0.25 ? 'ALIGNED' : payoffGap > 0.45 ? 'OPTIMISM_RISK' : 'CONSERVATIVE',
      note: 'Net realized R-asymmetry after fees, slippage & BE locks',
    },
    {
      metric_key: 'fee_drag_pct',
      metric_label: 'Fee Drag (% of Gross Profit)',
      unit: 'pct',
      simulated_value: simulated.fee_drag_pct,
      observed_value: observed.fee_drag_pct,
      variance: feeDragGap,
      status: feeDragGap <= -15 ? 'FAVORABLE_EDGE' : Math.abs(feeDragGap) <= 15 ? 'ALIGNED' : 'CONSERVATIVE',
      note:
        feeDragGap < 0
          ? `Maker-first rail cuts gross-profit fee erosion by ${Math.abs(feeDragGap).toFixed(1)} pp vs. live history`
          : 'Simulated fee drag exceeds observed live fee share',
    },
    {
      metric_key: 'fee_bps',
      metric_label: 'Effective Round-Trip Fee Rate',
      unit: 'bps',
      simulated_value: simulated.fee_bps,
      observed_value: observed.fee_bps,
      variance: feeBpsGap,
      status:
        simulated.fee_bps <= 4.1 && observed.fee_bps > 7
          ? 'UNDER_MODELED'
          : Math.abs(feeBpsGap) <= 2.0
          ? 'ALIGNED'
          : 'FAVORABLE_EDGE',
      note: `Live Binance observed ${observed.fee_bps} bps (${observed.inferred_taker_share_pct}% taker) vs. Sim ${simulated.fee_bps} bps (${simulated.inferred_taker_share_pct}% taker)`,
    },
    {
      metric_key: 'slippage_bps',
      metric_label: 'Execution & SL Slippage',
      unit: 'bps',
      simulated_value: simulated.slippage_bps,
      observed_value: observed.slippage_bps,
      variance: slipBpsGap,
      status:
        simulated.slippage_bps === 0
          ? 'UNDER_MODELED'
          : slipBpsGap < -1.5
          ? 'UNDER_MODELED'
          : Math.abs(slipBpsGap) <= 2.0
          ? 'ALIGNED'
          : 'CONSERVATIVE',
      note: `Observed live breakdown: ${slippageDetail.sl_overshoot_bps} bps SL overshoot + ${slippageDetail.spread_impact_bps} bps spread + ${slippageDetail.price_residual_bps} bps tick drift`,
    },
    {
      metric_key: 'funding_bps',
      metric_label: '8h Perpetual Funding Drag',
      unit: 'bps',
      simulated_value: simulated.funding_bps,
      observed_value: observed.funding_bps,
      variance: fundBpsGap,
      status:
        simulated.funding_bps === 0 && observed.funding_bps > 0.2
          ? 'UNDER_MODELED'
          : Math.abs(fundBpsGap) <= 0.75
          ? 'ALIGNED'
          : 'CONSERVATIVE',
      note: `Live avg hold ${observed.avg_hold_minutes}m vs. Sim multi-hour swing hold`,
    },
    {
      metric_key: 'total_friction_bps',
      metric_label: 'Total Execution Friction',
      unit: 'bps',
      simulated_value: simulated.total_friction_bps,
      observed_value: observed.total_friction_bps,
      variance: totalFricGap,
      status:
        totalFricGap < -3.0
          ? 'UNDER_MODELED'
          : Math.abs(totalFricGap) <= 2.5
          ? 'ALIGNED'
          : 'CONSERVATIVE',
      note: 'All-in execution hurdle per trade notional (Fees + Slippage + Funding)',
    },
  ];

  return {
    cohort_key: cohortKey,
    cohort_label: cohortLabel,
    cohort_description: cohortDescription,
    date_start_utc: startUtc,
    date_end_utc: endUtc,
    alignment_status: alignmentStatus,
    calibration_score_pct: calScore,
    headline,
    observed_live: observed,
    simulated,
    variances: {
      win_rate_gap_pp: wrGap,
      loss_rate_gap_pp: lrGap,
      profit_factor_gap: pfGap,
      payoff_ratio_gap: payoffGap,
      fee_drag_gap_pp: feeDragGap,
      fee_bps_gap: feeBpsGap,
      slippage_bps_gap: slipBpsGap,
      funding_bps_gap: fundBpsGap,
      total_friction_bps_gap: totalFricGap,
    },
    rows,
    slippage_audit_detail: slippageDetail,
  };
}

export function computeNeonRealityGap(simInput: SimulatedGapInput): NeonRealityGapPayload {
  const audit = readJsonSafe<{
    macro_trades?: RawLiveTrade[];
    scalp_trades?: RawLiveTrade[];
  }>(LIVE_AUDIT_PATH, {});

  const allRaw = [
    ...(audit.macro_trades || []),
    ...(audit.scalp_trades || []),
  ].sort((a, b) => String(a.entry_time || '').localeCompare(String(b.entry_time || '')));

  const coreSet = new Set<string>(NEON_CORE_UNIVERSE);
  const lastSlBySymbol: Record<string, number> = {};

  const enriched = allRaw.map((t) => {
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

  const neonGatedTrades = enriched.filter(
    (t) => coreSet.has(t.symbol) && t.minsSinceSl >= 45 && NEON_ALPHA_UTC_HOURS.has(t.utcHour)
  );

  const allLive = computeObservedCohort('All Observed Live Binance Trades', enriched);
  const neonLive = computeObservedCohort('NEON-Gated Observed Live Cohort', neonGatedTrades);
  const simMetrics = buildSimulatedSnapshot(simInput);

  return {
    computed_at_utc: new Date().toISOString(),
    scenario: simInput.scenario,
    scenario_label: simInput.scenario_label,
    cohorts: {
      ALL_LIVE: buildCohortComparison(
        'ALL_LIVE',
        `All ${allLive.metrics.trades} Observed Live Binance Trades`,
        'Unfiltered historical real-money Binance Futures ledger (double-taker execution across all traded pairs).',
        allLive.metrics,
        simMetrics,
        allLive.slippageDetail,
        allLive.startUtc,
        allLive.endUtc
      ),
      NEON_GATED_LIVE: buildCohortComparison(
        'NEON_GATED_LIVE',
        `NEON-Gated Live Cohort (${neonLive.metrics.trades} Trades)`,
        'Historical real-money Binance trades filtered by NEON Core Tier-1 symbols, 45m post-SL cooldown, and Prime UTC Alpha sessions.',
        neonLive.metrics,
        simMetrics,
        neonLive.slippageDetail,
        neonLive.startUtc,
        neonLive.endUtc
      ),
    },
  };
}
