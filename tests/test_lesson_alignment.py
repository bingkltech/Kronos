"""
tests/test_lesson_alignment.py — Automated Two-Tier Alignment Audit between
`data/lessons.db` (all empirical lessons) and `risk_engine/risk_config.yaml`.

Ensures:
1. 100% of trading lessons in `data/lessons.db` are registered in LESSON_REGISTRY.
2. Zero structural invariant conflicts exist in the production `risk_config.yaml`.
3. Deliberately broken configs (e.g. removing mandatory SL, setting SL ROI > 6%,
   or allowing duplicate same-symbol stacking) are caught immediately as ERRORs.
"""

from decimal import Decimal
import os

from risk_engine import (
    DEFAULT_CONFIG_PATH,
    RiskConfig,
    audit_lesson_alignment,
)


def test_production_risk_config_aligned_with_all_lessons_db():
    cfg = RiskConfig.from_file(DEFAULT_CONFIG_PATH)
    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "lessons.db")
    report = audit_lesson_alignment(cfg, lessons_db_path=db_path)

    assert report.total_lessons_in_db >= 45
    assert report.mapped_count == report.total_lessons_in_db
    assert report.structural_invariants_passed >= 10
    assert report.structural_invariants_failed == 0
    assert report.is_aligned is True, f"Alignment issues detected: {report.issues}"


def test_lesson_auditor_catches_structural_conflicts():
    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "lessons.db")

    # Violate Lesson #15 (same-symbol lock), Lesson #16/#39 (SL floor), Lesson #25 (SL ROI clamp), Lesson #17 (HALT exits)
    broken_cfg = RiskConfig(
        max_positions_per_symbol=3,
        require_stop_loss_on_entries=False,
        max_sl_roi_pct=Decimal("0.15"),
        allow_reduce_only_in_non_desync_halt=False,
    )
    report = audit_lesson_alignment(broken_cfg, lessons_db_path=db_path)
    assert report.is_aligned is False
    failed_ids = {i.lesson_id for i in report.issues if i.code == "STRUCTURAL_INVARIANT_CONFLICT"}
    assert {15, 16, 17, 25, 39, 41}.issubset(failed_ids)
