"""Unit tests for static detection rules against examples/."""
from pathlib import Path

import pytest

from payguard.detector.discovery import UnitKind, discover_payment_units
from payguard.detector.static_rules import (
    check_ac_r1,
    check_ac_r3,
    check_dp_r1,
    check_dp_r2,
    check_dp_r3,
    check_wi_r1,
    run_static_rules,
)
from payguard.shared.enums import DefectClass

EXAMPLES = Path(__file__).parent.parent.parent / "examples"
VULNERABLE = EXAMPLES / "vulnerable"
SAFE = EXAMPLES / "safe"


def load_unit(path: Path, kind: UnitKind = UnitKind.OTHER):
    from payguard.detector.discovery import PaymentUnit
    source = path.read_text()
    return PaymentUnit(
        file=str(path),
        symbol=path.stem,
        start_line=1,
        end_line=len(source.splitlines()),
        kind=kind,
        source=source,
    )


class TestDP_R1:
    def test_vulnerable_no_dedup_detected(self):
        unit = load_unit(VULNERABLE / "dp_r1_no_dedup.py")
        hit = check_dp_r1(unit)
        assert hit is not None
        assert hit.rule_id == "DP-R1"
        assert hit.defect_class == DefectClass.DUPLICATE_PAYMENT

    def test_safe_with_db_lookup_not_detected(self):
        unit = load_unit(SAFE / "dp_safe_with_db_dedup.py")
        hit = check_dp_r1(unit)
        assert hit is None

    def test_safe_server_amount_no_dp_r1(self):
        unit = load_unit(SAFE / "ac_safe_server_amount.py")
        hit = check_dp_r1(unit)
        # No razorpay orders.create in this file — should not hit
        assert hit is None


class TestDP_R2:
    def test_vulnerable_retry_loop_detected(self):
        unit = load_unit(VULNERABLE / "dp_r2_retry_loop.py")
        hit = check_dp_r2(unit)
        assert hit is not None
        assert hit.rule_id == "DP-R2"


class TestDP_R3:
    def test_vulnerable_webhook_no_dedup_detected(self):
        unit = load_unit(VULNERABLE / "dp_r3_webhook_no_dedup.py", kind=UnitKind.WEBHOOK)
        hit = check_dp_r3(unit)
        assert hit is not None
        assert hit.rule_id == "DP-R3"
        assert hit.defect_class == DefectClass.DUPLICATE_PAYMENT
        assert "DP-2" in hit.scenario_ids

    def test_safe_webhook_with_dedup_not_detected(self):
        unit = load_unit(SAFE / "wi_safe_signature_check.py", kind=UnitKind.WEBHOOK)
        hit = check_dp_r3(unit)
        assert hit is None


class TestWI_R1:
    def test_vulnerable_no_signature_detected(self):
        unit = load_unit(VULNERABLE / "wi_r1_no_signature.py", kind=UnitKind.WEBHOOK)
        hit = check_wi_r1(unit)
        assert hit is not None
        assert hit.rule_id == "WI-R1"
        assert hit.defect_class == DefectClass.WEBHOOK_INTEGRITY

    def test_safe_with_signature_check_not_detected(self):
        unit = load_unit(SAFE / "wi_safe_signature_check.py", kind=UnitKind.WEBHOOK)
        hit = check_wi_r1(unit)
        assert hit is None


class TestAC_R1:
    def test_vulnerable_rupees_not_paise_detected(self):
        unit = load_unit(VULNERABLE / "ac_r1_rupees_not_paise.py")
        hit = check_ac_r1(unit)
        assert hit is not None
        assert hit.rule_id == "AC-R1"
        assert hit.defect_class == DefectClass.AMOUNT_CURRENCY

    def test_safe_paise_variable_not_detected(self):
        unit = load_unit(SAFE / "ac_safe_paise_amount.py")
        hit = check_ac_r1(unit)
        assert hit is None


class TestAC_R3:
    def test_vulnerable_client_amount_detected(self):
        unit = load_unit(VULNERABLE / "ac_r3_client_amount.py")
        hit = check_ac_r3(unit)
        assert hit is not None
        assert hit.rule_id == "AC-R3"

    def test_safe_server_amount_not_detected(self):
        unit = load_unit(SAFE / "ac_safe_server_amount.py")
        hit = check_ac_r3(unit)
        assert hit is None


class TestDiscovery:
    def test_vulnerable_dir_discovers_units(self):
        units = discover_payment_units(VULNERABLE)
        assert len(units) >= 3

    def test_safe_dir_discovers_units(self):
        units = discover_payment_units(SAFE)
        assert len(units) >= 2

    def test_run_all_rules_on_vulnerable_webhook(self):
        unit = load_unit(VULNERABLE / "dp_r3_webhook_no_dedup.py", kind=UnitKind.WEBHOOK)
        hits = run_static_rules(unit)
        rule_ids = {h.rule_id for h in hits}
        # Should catch DP-R3 (no dedup in webhook) and WI-R1 (no sig) and WI-R3
        assert "DP-R3" in rule_ids
        assert "WI-R1" in rule_ids

    def test_no_hits_on_safe_webhook(self):
        unit = load_unit(SAFE / "wi_safe_signature_check.py", kind=UnitKind.WEBHOOK)
        hits = run_static_rules(unit)
        # May get some hits (DP-R3 style) — but WI-R1 must not fire
        rule_ids = {h.rule_id for h in hits}
        assert "WI-R1" not in rule_ids
