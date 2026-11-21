import datetime
from decimal import Decimal
import pytest

from src.quant.kev_risk_arbiter import TradeTicket, invert_trade_ticket
from src.quant.binance_execution import BinanceAtomicExecutor
from src.quant.orchestrator import QuantBotOrchestrator
from src.quant.kronos_onnx_engine import TrajectoryVerdict

def test_invert_long_ticket_to_short():
    """Verify that a LONG ticket is correctly inverted to a SHORT ticket with mirrored brackets."""
    ticket = TradeTicket(
        symbol="BTCUSDT",
        side="BUY",
        entry_price=Decimal("60000.00"),
        stop_loss=Decimal("59000.00"),      # SL delta = 1,000
        take_profit=Decimal("62000.00"),    # TP delta = 2,000
        quantity=Decimal("0.002"),
        notional_usd=Decimal("120.00"),
        effective_leverage=3,
        risk_budget_usd=Decimal("2.00"),
        reward_risk_ratio=Decimal("2.00"),
        net_expected_gain_pct=Decimal("3.33"),
        forecast_confidence=Decimal("0.70")
    )

    inv = invert_trade_ticket(ticket)
    assert inv.symbol == "BTCUSDT"
    assert inv.side == "SELL"
    assert inv.entry_price == Decimal("60000.00")
    # Inverted TP must be entry - delta_tp = 60,000 - 2,000 = 58,000
    assert inv.take_profit == Decimal("58000.00")
    # Inverted SL must be entry + delta_sl = 60,000 + 1,000 = 61,000
    assert inv.stop_loss == Decimal("61000.00")
    # Verify bracket geometry invariant for SHORT: TP < entry < SL
    assert inv.take_profit < inv.entry_price < inv.stop_loss
    assert inv.quantity == Decimal("0.002")
    assert inv.effective_leverage == 3


def test_invert_short_ticket_to_long():
    """Verify that a SHORT ticket is correctly inverted to a LONG ticket with mirrored brackets."""
    ticket = TradeTicket(
        symbol="BNBUSDT",
        side="SELL",
        entry_price=Decimal("500.00"),
        stop_loss=Decimal("510.00"),       # SL delta = 10
        take_profit=Decimal("480.00"),     # TP delta = 20
        quantity=Decimal("0.1"),
        notional_usd=Decimal("50.00"),
        effective_leverage=3,
        risk_budget_usd=Decimal("1.00"),
        reward_risk_ratio=Decimal("2.00"),
        net_expected_gain_pct=Decimal("4.00"),
        forecast_confidence=Decimal("0.70")
    )

    inv = invert_trade_ticket(ticket)
    assert inv.symbol == "BNBUSDT"
    assert inv.side == "BUY"
    assert inv.entry_price == Decimal("500.00")
    # Inverted TP must be entry + delta_tp = 500 + 20 = 520
    assert inv.take_profit == Decimal("520.00")
    # Inverted SL must be entry - delta_sl = 500 - 10 = 490
    assert inv.stop_loss == Decimal("490.00")
    # Verify bracket geometry invariant for LONG: SL < entry < TP
    assert inv.stop_loss < inv.entry_price < inv.take_profit
    assert inv.quantity == Decimal("0.1")


def test_executor_contra_mode_execution():
    """Verify that BinanceAtomicExecutor automatically inverts when contra_mode is True."""
    executor = BinanceAtomicExecutor(dry_run=True, realistic_friction=False)
    executor.contra_mode = True

    # Submit a SHORT ticket
    ticket = TradeTicket(
        symbol="BNBUSDT",
        side="SELL",
        entry_price=Decimal("500.00"),
        stop_loss=Decimal("510.00"),
        take_profit=Decimal("480.00"),
        quantity=Decimal("0.09"),
        notional_usd=Decimal("45.00"),
        effective_leverage=3,
        risk_budget_usd=Decimal("1.00"),
        reward_risk_ratio=Decimal("2.00"),
        net_expected_gain_pct=Decimal("4.00"),
        forecast_confidence=Decimal("0.70")
    )

    now_u = datetime.datetime.now(datetime.timezone.utc)
    pos = executor.submit_bracket_order(ticket, fill_time_utc=now_u)

    # Position must have executed as BUY (LONG)
    assert pos.side == "BUY"
    assert pos.take_profit == Decimal("520.00")
    assert pos.stop_loss == Decimal("490.00")
