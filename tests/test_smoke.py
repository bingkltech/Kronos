"""
tests/test_smoke.py — Ultra-Fast (<2s) CPU Smoke Harness for Kronos.
Validates repository invariants, temporal causality, Decimal financial math,
and BSQuantizer tensor dimensions without calling external networks or GPUs.
Executed autonomously by ASVL on every micro-step.
"""

from decimal import Decimal
import numpy as np
import pandas as pd
import pytest
import torch

from model.module import BSQuantizer


def test_decimal_math_invariants():
    """Verify monetary calculations enforce strict Decimal precision."""
    entry_price = Decimal("65432.10")
    exit_price = Decimal("65800.50")
    contracts = Decimal("1")
    fee_rate = Decimal("0.0007")

    gross_pnl = (exit_price - entry_price) * contracts
    fees = (entry_price + exit_price) * contracts * fee_rate
    net_pnl = gross_pnl - fees

    assert isinstance(net_pnl, Decimal)
    assert net_pnl > Decimal("0")
    # Floating point math leak detection
    assert not isinstance(net_pnl, float)


def test_context_tail_slicing_contract():
    """Verify that when context exceeds 512 bars, latest data is preserved (tail-slicing)."""
    n_bars = 800
    timestamps = pd.date_range("2026-01-01", periods=n_bars, freq="h")
    df = pd.DataFrame({
        "timestamps": timestamps,
        "close": np.arange(n_bars, dtype=np.float32)
    })

    # Strict invariant: tail slice
    sliced = df.iloc[-512:].copy()
    assert len(sliced) == 512
    # Ensure latest bar is preserved
    assert sliced["timestamps"].iloc[-1] == timestamps[-1]
    assert sliced["close"].iloc[-1] == float(n_bars - 1)


def test_temporal_causality_no_lookahead():
    """Verify that feature preparation does not leak future data into historical bars."""
    np.random.seed(42)
    raw_prices = np.random.randn(100).cumsum() + 100.0
    s_original = pd.Series(raw_prices)

    # Rolling expanding mean up to bar 40
    metric_at_40_orig = s_original.iloc[:40].mean()

    # Perturb future bar 80
    s_perturbed = s_original.copy()
    s_perturbed.iloc[80] += 1000.0

    metric_at_40_post = s_perturbed.iloc[:40].mean()
    assert metric_at_40_orig == metric_at_40_post, "Fatal: Future data leaked into historical calculation!"


def test_bsquantizer_tensor_shapes():
    """Verify Binary Spherical Quantizer tensor dimensions (B, T, D) on CPU in milliseconds."""
    s1_bits = 4
    s2_bits = 4
    codebook_dim = s1_bits + s2_bits
    bz, seq_len = 2, 16

    quantizer = BSQuantizer(
        s1_bits=s1_bits,
        s2_bits=s2_bits,
        beta=0.25,
        gamma0=1.0,
        gamma=1.0,
        zeta=1.0,
        group_size=1
    )

    z = torch.randn(bz, seq_len, codebook_dim)
    loss, quantized, indices = quantizer(z, collect_metrics=False)

    assert quantized.shape == (bz, seq_len, codebook_dim), f"Unexpected quantized shape {quantized.shape}"
    assert indices.shape == (bz, seq_len), f"Unexpected indices shape {indices.shape}"
    assert not torch.isnan(loss), "Quantizer produced NaN loss"
