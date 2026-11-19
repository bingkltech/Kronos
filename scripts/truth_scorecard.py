"""
scripts/truth_scorecard.py — Institutional 6-Block Trade Result Assessment Engine
=================================================================================
Implements Pillar 4 of docs/INSTITUTIONAL_ACCURACY_AND_VERIFICATION_STANDARD.md.

Computes unvarnished, Decimal-exact truth scorecards for BOTH:
  - Tiger Paper / Live DB (`--source tiger`, data/tiger_trades.db)
  - Main Kronos Live Ledger (`--source live`, data/live_audit_summary.json)

Includes:
  Block 1: Core Expectancy, Gross vs. Friction Drag & Net Realized PnL
  Block 2: Max Drawdown, Losing Streak, Risk Budget Compliance & Outlier-Stripped Net PnL
  Block 3: Execution Fidelity & QuantFlawAuditor Hallucination Check (TP Overshoot, etc.)
  Block 4: Friction Stress-Test Matrix (1.0x / 1.5x / 2.0x slippage resilience)
  Block 5: Multi-Axis Attribution (BUY vs SELL, UTC Session, Regime, Symbol Concentration)
  Block 6: 6-Gate Paper -> Live Graduation Verdict
"""

import argparse
import datetime
from decimal import Decimal, ROUND_HALF_UP
import json
import os
import sqlite3
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.quant.quant_flaw_auditor import QuantFlawAuditor, FlawSeverity


def _utc_session(iso_ts: str) -> str:
    try:
        dt = datetime.datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        hm = dt.hour * 60 + dt.minute
        if 0 <= hm < 420:        # 00:00-07:00 UTC
            return "ASIA"
        if 420 <= hm < 810:      # 07:00-13:30 UTC
            return "EU_PRIME"
        if 810 <= hm < 930:      # 13:30-15:30 UTC
            return "US_OPEN_LOCK"
        if 930 <= hm < 1320:     # 15:30-22:00 UTC
            return "US_SESSION"
        return "LATE_UTC"        # 22:00-00:00 UTC
    except Exception:
        return "UNKNOWN"


def load_tiger_trades(db_path: str = "data/tiger_trades.db") -> List[Dict[str, Any]]:
    if not os.path.exists(db_path):
        return []
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM tiger_trades ORDER BY closed_at_utc ASC")
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    conn.close()

    normalized = []
    for r in rows:
        notional = Decimal(str(r.get("notional_usd") or "100.00"))
        entry = Decimal(str(r.get("entry_price") or "0"))
        exit_px = Decimal(str(r.get("exit_price") or "0"))
        side = str(r.get("side") or "").upper()
        net_usd = Decimal(str(r.get("net_pnl_usd") or "0"))
        if entry > Decimal("0") and exit_px > Decimal("0"):
            gross_ret = (exit_px - entry) / entry if side == "BUY" else (entry - exit_px) / entry
        else:
            gross_ret = Decimal("0")
        gross_usd = (notional * gross_ret).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        friction_usd = max(Decimal("0"), gross_usd - net_usd)
        is_slow = bool(r.get("is_slow_regime", 1))
        normalized.append({
            "trade_id": r.get("trade_id"),
            "symbol": r.get("symbol"),
            "side": side,
            "entry_price": entry,
            "exit_price": exit_px,
            "notional_usd": notional,
            "gross_pnl_usd": gross_usd,
            "friction_usd": friction_usd,
            "net_pnl_usd": net_usd,
            "is_win": net_usd > Decimal("0"),
            "duration_seconds": int(r.get("duration_seconds") or 0),
            "mfe_pct": Decimal(str(r.get("mfe_pct") or "0")),
            "mae_pct": Decimal(str(r.get("mae_pct") or "0")),
            "reason": str(r.get("exit_reason") or ""),
            "autopsy_code": str(r.get("autopsy_code") or "UNKNOWN"),
            "regime": "SLOW_ATR" if is_slow else "FAST_ATR",
            "max_tp_pct": Decimal("0.0110") if is_slow else Decimal("0.0190"),
            "risk_budget_usd": Decimal("1.50"),
            "closed_at_utc": str(r.get("closed_at_utc") or ""),
        })
    return normalized


def load_live_trades(json_path: str = "data/live_audit_summary.json") -> List[Dict[str, Any]]:
    if not os.path.exists(json_path):
        return []
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    raw_trades = data.get("trades", []) if isinstance(data, dict) else data
    normalized = []
    for idx, r in enumerate(raw_trades):
        net_usd = Decimal(str(r.get("net_pnl", r.get("net_pnl_usd", r.get("realizedPnl", "0")))))
        fee_usd = abs(Decimal(str(r.get("commission", r.get("fees", "0")))))
        gross_usd = net_usd + fee_usd
        notional = Decimal(str(r.get("notional", r.get("notional_usd", "100.00"))))
        normalized.append({
            "trade_id": str(r.get("id", f"LIVE_{idx}")),
            "symbol": str(r.get("symbol", "UNKNOWN")),
            "side": str(r.get("side", r.get("direction", "UNKNOWN"))).upper(),
            "entry_price": Decimal(str(r.get("entry_price", r.get("price", "1")))),
            "exit_price": Decimal(str(r.get("exit_price", r.get("price", "1")))),
            "notional_usd": notional if notional > Decimal("0") else Decimal("100.00"),
            "gross_pnl_usd": gross_usd,
            "friction_usd": fee_usd,
            "net_pnl_usd": net_usd,
            "is_win": net_usd > Decimal("0"),
            "duration_seconds": int(r.get("duration_seconds", 0)),
            "mfe_pct": Decimal(str(r.get("mfe_pct", "0"))),
            "mae_pct": Decimal(str(r.get("mae_pct", "0"))),
            "reason": str(r.get("exit_reason", r.get("strategy", "LIVE"))),
            "autopsy_code": str(r.get("autopsy_code", "LIVE_FILL")),
            "regime": str(r.get("strategy", "LIVE")),
            "max_tp_pct": None,
            "risk_budget_usd": Decimal("2.00"),
            "closed_at_utc": str(r.get("closed_at_utc", r.get("time_utc", ""))),
        })
    return normalized


def compute_scorecard(
    trades: List[Dict[str, Any]],
    allocated_capital_usd: Decimal = Decimal("100.00"),
) -> Dict[str, Any]:
    n = len(trades)
    if n == 0:
        return {"total_trades": 0}

    wins = [t for t in trades if t["is_win"]]
    losses = [t for t in trades if not t["is_win"]]

    gross_total = sum((t["gross_pnl_usd"] for t in trades), Decimal("0"))
    friction_total = sum((t["friction_usd"] for t in trades), Decimal("0"))
    net_total = sum((t["net_pnl_usd"] for t in trades), Decimal("0"))

    gross_wins = sum((t["net_pnl_usd"] for t in wins), Decimal("0"))
    gross_losses = sum((abs(t["net_pnl_usd"]) for t in losses), Decimal("0"))

    wr = (Decimal(len(wins)) / Decimal(n)) * Decimal("100")
    pf = (gross_wins / gross_losses) if gross_losses > Decimal("0") else Decimal("999.00")
    avg_win = (gross_wins / Decimal(len(wins))) if wins else Decimal("0")
    avg_loss = (gross_losses / Decimal(len(losses))) if losses else Decimal("0")
    payoff = (avg_win / avg_loss) if avg_loss > Decimal("0") else Decimal("0")
    expectancy = net_total / Decimal(n)
    friction_drag_pct = (friction_total / gross_total * Decimal("100")) if gross_total > Decimal("0") else Decimal("0")

    # Block 2: Equity curve, Max DD, Losing Streak, Outlier-Stripped Net PnL
    peak = Decimal("0")
    eq = Decimal("0")
    max_dd = Decimal("0")
    cur_streak = 0
    max_streak = 0
    worst_loss = Decimal("0")
    for t in trades:
        eq += t["net_pnl_usd"]
        if eq > peak:
            peak = eq
        dd = peak - eq
        if dd > max_dd:
            max_dd = dd
        if t["is_win"]:
            cur_streak = 0
        else:
            cur_streak += 1
            max_streak = max(max_streak, cur_streak)
            if abs(t["net_pnl_usd"]) > worst_loss:
                worst_loss = abs(t["net_pnl_usd"])

    max_dd_pct = (max_dd / allocated_capital_usd * Decimal("100")) if allocated_capital_usd > Decimal("0") else Decimal("0")
    best_trade = max(trades, key=lambda t: t["net_pnl_usd"])
    net_ex_best = net_total - max(Decimal("0"), best_trade["net_pnl_usd"])

    # Block 3: QuantFlawAuditor Execution Fidelity Check
    auditor = QuantFlawAuditor()
    audit_records = [
        {
            "entry_price": str(t["entry_price"]),
            "exit_price": str(t["exit_price"]),
            "side": t["side"],
            "realized_pnl_usd": str(t["net_pnl_usd"]),
            "gross_pnl_usd": str(t["gross_pnl_usd"]),
            "reason": t["reason"],
            "max_tp_pct": str(t["max_tp_pct"]) if t["max_tp_pct"] is not None else None,
            "risk_budget_usd": str(t["risk_budget_usd"]),
            "duration_minutes": t["duration_seconds"] // 60,
        }
        for t in trades
    ]
    verdict = auditor.audit_performance_summary({
        "total_trades": n,
        "winning_trades": len(wins),
        "win_rate_pct": str(wr.quantize(Decimal("0.1"))),
        "profit_factor": str(pf.quantize(Decimal("0.01"))),
        "initial_equity": str(allocated_capital_usd),
        "current_equity": str(allocated_capital_usd + net_total),
        "closed_trades": audit_records,
    })
    tp_overshoots = [f for f in verdict.flaws if f.code == "FLAW_PHANTOM_TP_OVERSHOOT"]

    # Block 4: Friction Stress-Test Matrix (extra slippage: +0bps / +5bps / +10bps roundtrip)
    stress_results = {}
    for label, extra_bps in [("1.0x_BASE", Decimal("0")), ("1.5x_STRESSED (+5bps)", Decimal("5")), ("2.0x_HOSTILE (+10bps)", Decimal("10"))]:
        extra_rate = extra_bps / Decimal("10000")
        s_net = Decimal("0")
        s_wins = Decimal("0")
        s_losses = Decimal("0")
        for t in trades:
            adj = t["net_pnl_usd"] - (t["notional_usd"] * extra_rate)
            s_net += adj
            if adj > Decimal("0"):
                s_wins += adj
            else:
                s_losses += abs(adj)
        s_pf = (s_wins / s_losses) if s_losses > Decimal("0") else Decimal("999.00")
        stress_results[label] = {"net_usd": s_net, "pf": s_pf}

    # Block 5: Multi-Axis Attribution
    def _slice_by(key_fn):
        buckets: Dict[str, Dict[str, Any]] = {}
        for t in trades:
            k = key_fn(t)
            b = buckets.setdefault(k, {"n": 0, "w": 0, "net": Decimal("0"), "gw": Decimal("0"), "gl": Decimal("0")})
            b["n"] += 1
            if t["is_win"]:
                b["w"] += 1
                b["gw"] += t["net_pnl_usd"]
            else:
                b["gl"] += abs(t["net_pnl_usd"])
            b["net"] += t["net_pnl_usd"]
        for b in buckets.values():
            b["wr"] = (Decimal(b["w"]) / Decimal(b["n"]) * Decimal("100")) if b["n"] else Decimal("0")
            b["pf"] = (b["gw"] / b["gl"]) if b["gl"] > Decimal("0") else Decimal("999.00")
        return buckets

    by_side = _slice_by(lambda t: t["side"])
    by_session = _slice_by(lambda t: _utc_session(t["closed_at_utc"]))
    by_regime = _slice_by(lambda t: t["regime"])
    by_symbol = _slice_by(lambda t: t["symbol"])

    # Time span in hours
    timestamps = []
    for t in trades:
        try:
            timestamps.append(datetime.datetime.fromisoformat(t["closed_at_utc"].replace("Z", "+00:00")))
        except Exception:
            pass
    span_hours = Decimal("0")
    if len(timestamps) >= 2:
        span_hours = Decimal(str((max(timestamps) - min(timestamps)).total_seconds() / 3600.0))

    # Block 6: 6-Gate Paper -> Live Graduation Check
    budget = trades[0]["risk_budget_usd"]
    dir_bleed = any(b["n"] >= 10 and b["pf"] < Decimal("0.75") for b in by_side.values())
    gates = {
        "G1_SAMPLE_SIZE (N>=40 & >=72h)": (n >= 40 and span_hours >= Decimal("72")),
        "G2_NET_PF (>=1.40x)": (pf >= Decimal("1.40")),
        "G3_OUTLIER_STRIPPED (NetExBest > $0)": (net_ex_best > Decimal("0")),
        "G4_DIRECTIONAL_BALANCE (No side PF<0.75)": (not dir_bleed),
        "G5_DRAWDOWN_AND_RISK (DD<=5% & Worst<=1.8x)": (max_dd_pct <= Decimal("5.0") and worst_loss <= budget * Decimal("1.8")),
        "G6_ZERO_HALLUCINATIONS (Auditor CLEAN)": (verdict.is_valid and len(tp_overshoots) == 0),
    }

    return {
        "total_trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "wr": wr,
        "pf": pf,
        "gross_total": gross_total,
        "friction_total": friction_total,
        "net_total": net_total,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "payoff": payoff,
        "expectancy": expectancy,
        "friction_drag_pct": friction_drag_pct,
        "max_dd": max_dd,
        "max_dd_pct": max_dd_pct,
        "max_streak": max_streak,
        "worst_loss": worst_loss,
        "risk_budget": budget,
        "best_trade": best_trade,
        "net_ex_best": net_ex_best,
        "span_hours": span_hours,
        "verdict": verdict,
        "tp_overshoot_count": len(tp_overshoots),
        "stress": stress_results,
        "by_side": by_side,
        "by_session": by_session,
        "by_regime": by_regime,
        "by_symbol": by_symbol,
        "gates": gates,
        "ready_for_live": all(gates.values()),
    }


def print_scorecard(title: str, sc: Dict[str, Any]) -> None:
    print("=" * 88)
    print(f"  KRONOS INSTITUTIONAL TRUTH SCORECARD — {title}")
    print("=" * 88)
    if sc.get("total_trades", 0) == 0:
        print("  No trades in selected window.")
        return

    print(f"\n[BLOCK 1] CORE EXPECTANCY & FRICTION DRAG (N={sc['total_trades']} over {sc['span_hours']:.1f}h)")
    print(f"  Win Rate:       {sc['wr']:.1f}% ({sc['wins']}W / {sc['losses']}L) | Payoff: {sc['payoff']:.2f}x")
    print(f"  Gross PnL:      ${sc['gross_total']:+.2f} | Friction: -${sc['friction_total']:.2f} (Drag: {sc['friction_drag_pct']:.1f}%)")
    print(f"  Net Realized:   ${sc['net_total']:+.2f} USDT | Expectancy: ${sc['expectancy']:+.3f}/trade | Net PF: {sc['pf']:.2f}x")

    print("\n[BLOCK 2] RISK, TAIL & CONCENTRATION REALITY")
    print(f"  Max Drawdown:   -${sc['max_dd']:.2f} ({sc['max_dd_pct']:.2f}%) | Max Loss Streak: {sc['max_streak']}")
    print(f"  Worst Loss:     -${sc['worst_loss']:.2f} vs Risk Budget ${sc['risk_budget']:.2f}")
    bt = sc["best_trade"]
    print(f"  Outlier Check:  Best trade = {bt['symbol']} {bt['side']} (${bt['net_pnl_usd']:+.2f}) -> Net Ex-Best: ${sc['net_ex_best']:+.2f}")

    print("\n[BLOCK 3] EXECUTION FIDELITY & HALLUCINATION AUDIT")
    v = sc["verdict"]
    print(f"  Auditor Status: {'CLEAN' if v.is_valid else 'REJECTED'} (Confidence: {v.confidence_score:.2f}) | TP Overshoots: {sc['tp_overshoot_count']}")
    for f in v.flaws[:5]:
        print(f"    - [{f.severity.value}] {f.code}: {f.observed_value}")

    print("\n[BLOCK 4] FRICTION STRESS-TEST MATRIX")
    for lbl, res in sc["stress"].items():
        print(f"  {lbl:<24} -> Net: ${res['net_usd']:>+7.2f} | PF: {res['pf']:.2f}x")

    print("\n[BLOCK 5] MULTI-AXIS ATTRIBUTION")
    print("  By Direction:")
    for k, b in sc["by_side"].items():
        print(f"    {k:<12}: {b['n']:>3} trades | WR: {b['wr']:>5.1f}% | PF: {b['pf']:>6.2f}x | Net: ${b['net']:>+7.2f}")
    print("  By UTC Session:")
    for k, b in sc["by_session"].items():
        print(f"    {k:<12}: {b['n']:>3} trades | WR: {b['wr']:>5.1f}% | PF: {b['pf']:>6.2f}x | Net: ${b['net']:>+7.2f}")
    syms = sorted(sc["by_symbol"].items(), key=lambda x: x[1]["net"], reverse=True)
    top_syms = [(k, f"${b['net']:+.2f}") for k, b in syms[:3]]
    bot_syms = [(k, f"${b['net']:+.2f}") for k, b in syms[-3:]]
    print(f"  Top Symbols:    {top_syms}")
    print(f"  Bottom Symbols: {bot_syms}")

    print("\n[BLOCK 6] PAPER -> LIVE GRADUATION GATE")
    for gate, passed in sc["gates"].items():
        mark = "PASS" if passed else "FAIL"
        print(f"  [{mark}] {gate}")
    verdict_str = "APPROVED FOR LIVE CAPITAL" if sc["ready_for_live"] else "BLOCKED — CONTINUE TRUTH-GRADE PAPER RUN"
    print(f"\n  >>> FINAL VERDICT: {verdict_str}")
    print("=" * 88)


def main():
    parser = argparse.ArgumentParser(description="Kronos Institutional 6-Block Truth Scorecard")
    parser.add_argument("--source", choices=["tiger", "live"], default="tiger")
    parser.add_argument("--hours", type=float, default=0.0, help="Lookback hours (0 = all trades)")
    parser.add_argument("--since", type=str, default="", help="ISO UTC cutoff (e.g. 2026-11-17T18:00:00)")
    args = parser.parse_args()

    trades = load_tiger_trades() if args.source == "tiger" else load_live_trades()
    now_utc = datetime.datetime.now(datetime.timezone.utc)

    if args.since:
        cutoff = datetime.datetime.fromisoformat(args.since.replace("Z", "+00:00"))
        if cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=datetime.timezone.utc)
        trades = [
            t for t in trades
            if t["closed_at_utc"] and datetime.datetime.fromisoformat(t["closed_at_utc"].replace("Z", "+00:00")) >= cutoff
        ]
    elif args.hours > 0:
        cutoff = now_utc - datetime.timedelta(hours=args.hours)
        trades = [
            t for t in trades
            if t["closed_at_utc"] and datetime.datetime.fromisoformat(t["closed_at_utc"].replace("Z", "+00:00")) >= cutoff
        ]

    title = f"{args.source.upper()} ({f'since {args.since}' if args.since else (f'last {args.hours:g}h' if args.hours > 0 else 'ALL TRADES')})"
    sc = compute_scorecard(trades)
    print_scorecard(title, sc)


if __name__ == "__main__":
    main()
