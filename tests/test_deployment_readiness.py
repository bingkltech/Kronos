"""
tests/test_deployment_readiness.py — Unit test verifying all 18 Quant-Grade Deployment Gates.
"""

import pytest
from scripts.verify_deployment_readiness import DeploymentAuditor


def test_quant_grade_deployment_readiness():
    """Verify that all 6 pillars and 18 deployment gates pass with zero regressions."""
    auditor = DeploymentAuditor()
    all_passed, results = auditor.run_full_audit()
    
    failed_checks = [r for r in results if not r["passed"]]
    assert all_passed, f"Deployment readiness audit failed on {len(failed_checks)} checks: {failed_checks}"
    assert len(results) >= 18, f"Expected at least 18 audit checks, got {len(results)}"
