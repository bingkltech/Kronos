# Unified Trade Forensics Documentation

## Overview
This module (`src/quant/trade_forensics.py`) operationalizes the **46-item Unified Trade Assessment Framework**.

It provides:
1. `TelemetryRecord`: Strict `Decimal` container for all 46 parameters across Accounting, Bot Intent, Market Snapshot, Microstructure, In-Trade Excursion, and Diagnosis.
2. `TradeForensicsEngine`: Evaluates whether the bot accurately guessed the outcome, separates predictive alpha from execution drag, categorizes failures into 6 deterministic root causes, and applies asymmetric live vs. paper weights.
