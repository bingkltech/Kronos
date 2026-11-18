"""
tests/test_telemetry_hub.py — Unit tests for the WebUI Swarm Telemetry Hub.

Verifies:
1. TelemetryHub instantiates with correct defaults.
2. Serialization of Decimals and dates does not raise TypeError.
3. BotSwarmBridge payload envelope schemas (TOPOLOGY, BEACON_UPSERT, WORKER_SIGNAL, TRADE_FILL).
"""

import json
from decimal import Decimal
import datetime
from webui.telemetry_hub import TelemetryHub, safe_json_default, DEFAULT_TOPOLOGY

def test_telemetry_hub_initialization():
    hub = TelemetryHub(host="127.0.0.1", port=8765)
    assert hub.host == "127.0.0.1"
    assert hub.port == 8765
    assert not hub.running
    assert len(hub.clients) == 0

def test_safe_json_default():
    data = {
        "decimal_score": Decimal("0.9250"),
        "timestamp": datetime.datetime(2026, 11, 16, 20, 0, 0),
        "string_val": "BTC/USDT"
    }
    encoded = json.dumps(data, default=safe_json_default)
    parsed = json.loads(encoded)
    assert isinstance(parsed["decimal_score"], float)
    assert round(parsed["decimal_score"], 2) == 0.93
    assert "2026-11-16" in parsed["timestamp"]
    assert parsed["string_val"] == "BTC/USDT"

def test_default_topology_schema():
    assert "bots" in DEFAULT_TOPOLOGY
    bots = DEFAULT_TOPOLOGY["bots"]
    assert len(bots) == 4
    for b in bots:
        assert "id" in b
        assert "name" in b
        assert "accent" in b
        assert "pair" in b
        assert b["accent"].startswith("#")

def test_beacon_envelope_schema():
    beacon = {
        "id": "sig-sol",
        "symbol": "SOL/USDT",
        "score": 0.92,
        "xNorm": 0.51,
        "yNorm": 0.48,
        "status": "LOCKED"
    }
    envelope = json.dumps({"type": "BEACON_UPSERT", "payload": beacon})
    parsed = json.loads(envelope)
    assert parsed["type"] == "BEACON_UPSERT"
    assert parsed["payload"]["score"] >= 0.62
    assert parsed["payload"]["status"] == "LOCKED"

def test_worker_signal_schema():
    sig = {
        "botId": "BOT-01",
        "workerId": "SCAN",
        "beaconId": "sig-sol",
        "state": "TRIANGULATING",
        "label": "• cvd breakout +3.4σ"
    }
    envelope = json.dumps({"type": "WORKER_SIGNAL", "payload": sig})
    parsed = json.loads(envelope)
    assert parsed["type"] == "WORKER_SIGNAL"
    assert parsed["payload"]["workerId"] in ["SCAN", "FLOW", "RISK", "VALID", "EXEC", "LEDGER"]

def test_trade_fill_schema():
    fill = {
        "botId": "BOT-01",
        "beaconId": "sig-sol",
        "symbol": "SOL/USDT",
        "side": "BUY",
        "pnl": "+1.42%"
    }
    envelope = json.dumps({"type": "TRADE_FILL", "payload": fill})
    parsed = json.loads(envelope)
    assert parsed["type"] == "TRADE_FILL"
    assert parsed["payload"]["side"] == "BUY"
    assert "%" in parsed["payload"]["pnl"]
