"""
Unit Tests — Plum Claims Processing System
==========================================
Run: pytest tests/test_pipeline.py -v
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import pytest
from datetime import date

from models import (
    ClaimSubmission, ClaimCategory, DocumentSubmission, DocumentContent,
    ExtractedInfo, FraudDetectionResult, DecisionType
)
from policy_engine import PolicyEngine
from agents.document_verifier import DocumentVerifierAgent
from agents.fraud_agent import FraudDetectionAgent
from agents.decision_agent import DecisionAgent
from pipeline.orchestrator import ClaimsPipeline


# ─────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────

@pytest.fixture
def pe():
    return PolicyEngine()


@pytest.fixture
def pipeline():
    return ClaimsPipeline()


def make_claim(
    member_id="EMP001",
    category=ClaimCategory.CONSULTATION,
    treatment_date=date(2024, 11, 1),
    amount=1500.0,
    docs=None,
    hospital=None,
    claims_history=None,
    simulate_failure=False,
):
    if docs is None:
        docs = [
            DocumentSubmission(
                file_id="D1", actual_type="PRESCRIPTION",
                content=DocumentContent(patient_name="Rajesh Kumar", diagnosis="Viral Fever"),
            ),
            DocumentSubmission(
                file_id="D2", actual_type="HOSPITAL_BILL",
                content=DocumentContent(patient_name="Rajesh Kumar", total=amount,
                                        line_items=[{"description": "Consultation", "amount": amount}]),
            ),
        ]
    return ClaimSubmission(
        claim_id="TEST-UNIT",
        member_id=member_id,
        policy_id="PLUM_GHI_2024",
        claim_category=category,
        treatment_date=treatment_date,
        claimed_amount=amount,
        hospital_name=hospital,
        claims_history=claims_history or [],
        documents=docs,
        simulate_component_failure=simulate_failure,
    )


# ─────────────────────────────────────────────
# Policy Engine Tests
# ─────────────────────────────────────────────

class TestPolicyEngine:

    def test_member_lookup_valid(self, pe):
        member = pe.get_member("EMP001")
        assert member is not None
        assert member["name"] == "Rajesh Kumar"

    def test_member_lookup_invalid(self, pe):
        member = pe.get_member("INVALID")
        assert member is None

    def test_member_eligibility_valid(self, pe):
        ok, reason = pe.is_member_eligible("EMP001")
        assert ok is True

    def test_member_eligibility_invalid(self, pe):
        ok, reason = pe.is_member_eligible("NOTEXIST")
        assert ok is False

    def test_waiting_period_initial(self, pe):
        member = pe.get_member("EMP001")
        ok, reason, elig_from = pe.check_waiting_period(member, "viral fever", date(2024, 5, 1))
        assert ok is True

    def test_waiting_period_diabetes_within(self, pe):
        """EMP005 joined 2024-09-01, diabetes wait=90 days → eligible 2024-11-30"""
        member = pe.get_member("EMP005")
        ok, reason, elig_from = pe.check_waiting_period(member, "Type 2 Diabetes Mellitus", date(2024, 10, 15))
        assert ok is False
        assert "90" in reason or "Diabetes" in reason
        assert elig_from == date(2024, 11, 30)

    def test_waiting_period_diabetes_after(self, pe):
        member = pe.get_member("EMP005")
        ok, reason, _ = pe.check_waiting_period(member, "Type 2 Diabetes Mellitus", date(2024, 12, 1))
        assert ok is True

    def test_exclusion_bariatric(self, pe):
        excluded, matches = pe.check_exclusions("Morbid Obesity", "Bariatric Consultation", ClaimCategory.CONSULTATION)
        assert excluded is True
        assert len(matches) > 0

    def test_exclusion_viral_fever_not_excluded(self, pe):
        excluded, matches = pe.check_exclusions("Viral Fever", None, ClaimCategory.CONSULTATION)
        assert excluded is False

    def test_network_hospital_match(self, pe):
        assert pe.is_network_hospital("Apollo Hospitals") is True
        assert pe.is_network_hospital("Apollo Hospitals, Bangalore") is True

    def test_network_hospital_no_match(self, pe):
        assert pe.is_network_hospital("City Clinic") is False
        assert pe.is_network_hospital(None) is False

    def test_financial_calc_copay_only(self, pe):
        result = pe.calculate_approved_amount(1500.0, ClaimCategory.CONSULTATION, "City Clinic")
        assert result["network_discount"] == 0.0
        assert result["copay_deducted"] == 150.0  # 10% of 1500
        assert result["approved_amount"] == 1350.0

    def test_financial_calc_network_plus_copay(self, pe):
        result = pe.calculate_approved_amount(4500.0, ClaimCategory.CONSULTATION, "Apollo Hospitals")
        assert result["network_discount"] == 900.0   # 20% of 4500
        assert result["copay_deducted"] == 360.0     # 10% of 3600
        assert result["approved_amount"] == 3240.0

    def test_financial_calc_per_claim_cap(self, pe):
        result = pe.calculate_approved_amount(8000.0, ClaimCategory.CONSULTATION, None)
        assert result["capped_by_per_claim_limit"] is True
        assert result["approved_amount"] == 5000.0

    def test_pre_auth_mri_above_threshold(self, pe):
        req, reason = pe.requires_pre_auth(ClaimCategory.DIAGNOSTIC, 15000, "MRI brain scan", None)
        assert req is True
        assert "MRI" in reason.upper() or "pre-auth" in reason.lower()

    def test_pre_auth_mri_below_threshold(self, pe):
        req, reason = pe.requires_pre_auth(ClaimCategory.DIAGNOSTIC, 8000, "MRI scan", None)
        assert req is False

    def test_dental_exclusions(self, pe):
        items = [
            {"description": "Root Canal Treatment", "amount": 8000},
            {"description": "Teeth Whitening", "amount": 4000},
        ]
        result = pe.check_dental_exclusions(items)
        assert result[0]["excluded"] is False   # Root canal: covered
        assert result[1]["excluded"] is True    # Whitening: excluded

    def test_per_claim_limit(self, pe):
        ok, _ = pe.check_per_claim_limit(4999)
        assert ok is True
        ok2, _ = pe.check_per_claim_limit(5001)
        assert ok2 is False


# ─────────────────────────────────────────────
# Document Verifier Tests
# ─────────────────────────────────────────────

class TestDocumentVerifier:

    def test_correct_docs_pass(self):
        agent = DocumentVerifierAgent()
        claim = make_claim(docs=[
            DocumentSubmission(file_id="D1", actual_type="PRESCRIPTION",
                               content=DocumentContent(patient_name="Rajesh Kumar")),
            DocumentSubmission(file_id="D2", actual_type="HOSPITAL_BILL",
                               content=DocumentContent(patient_name="Rajesh Kumar", total=1500)),
        ])
        result, trace = agent.run(claim)
        assert result.passed is True
        assert result.issues == []

    def test_two_prescriptions_fail(self):
        agent = DocumentVerifierAgent()
        claim = make_claim(docs=[
            DocumentSubmission(file_id="D1", actual_type="PRESCRIPTION"),
            DocumentSubmission(file_id="D2", actual_type="PRESCRIPTION"),
        ])
        result, trace = agent.run(claim)
        assert result.passed is False
        assert any(i["type"] == "WRONG_DOCUMENT_TYPE" for i in result.issues)
        # Message must name the specific types
        messages = " ".join(i["message"] for i in result.issues)
        assert "prescription" in messages.lower() or "PRESCRIPTION" in messages
        assert "bill" in messages.lower() or "Hospital" in messages

    def test_unreadable_document_fails(self):
        agent = DocumentVerifierAgent()
        claim = make_claim(docs=[
            DocumentSubmission(file_id="D1", actual_type="PRESCRIPTION", quality="GOOD"),
            DocumentSubmission(file_id="D2", actual_type="PHARMACY_BILL", quality="UNREADABLE"),
        ], category=ClaimCategory.PHARMACY)
        result, trace = agent.run(claim)
        assert result.passed is False
        assert len(result.unreadable_documents) > 0
        assert any(i["type"] == "UNREADABLE_DOCUMENT" for i in result.issues)

    def test_cross_patient_mismatch_fails(self):
        agent = DocumentVerifierAgent()
        claim = make_claim(docs=[
            DocumentSubmission(file_id="D1", actual_type="PRESCRIPTION",
                               patient_name_on_doc="Rajesh Kumar",
                               content=DocumentContent(patient_name="Rajesh Kumar")),
            DocumentSubmission(file_id="D2", actual_type="HOSPITAL_BILL",
                               patient_name_on_doc="Arjun Mehta",
                               content=DocumentContent(patient_name="Arjun Mehta")),
        ])
        result, trace = agent.run(claim)
        assert result.passed is False
        assert result.cross_patient_mismatch is True
        assert "Rajesh Kumar" in result.mismatch_detail
        assert "Arjun Mehta" in result.mismatch_detail


# ─────────────────────────────────────────────
# Fraud Detection Tests
# ─────────────────────────────────────────────

class TestFraudDetection:

    def test_clean_claim_no_fraud(self):
        agent = FraudDetectionAgent()
        claim = make_claim(amount=1500)
        info = ExtractedInfo(confidence=0.95)
        result, _ = agent.run(claim, info)
        assert result.fraud_score < 0.5
        assert result.route_to_manual is False

    def test_same_day_fraud_flag(self):
        agent = FraudDetectionAgent()
        claim = make_claim(
            amount=4800,
            treatment_date=date(2024, 10, 30),
            claims_history=[
                {"claim_id": "C1", "date": "2024-10-30", "amount": 1200, "provider": "Clinic A"},
                {"claim_id": "C2", "date": "2024-10-30", "amount": 1800, "provider": "Clinic B"},
                {"claim_id": "C3", "date": "2024-10-30", "amount": 2100, "provider": "Clinic C"},
            ]
        )
        info = ExtractedInfo(confidence=0.95)
        result, _ = agent.run(claim, info)
        assert result.route_to_manual is True
        assert len(result.signals) > 0

    def test_high_value_flagged(self):
        agent = FraudDetectionAgent()
        claim = make_claim(amount=30000)
        info = ExtractedInfo(confidence=0.95)
        result, _ = agent.run(claim, info)
        assert result.fraud_score > 0.2
        assert any("high-value" in s.lower() or "₹30" in s or "High" in s for s in result.signals)


# ─────────────────────────────────────────────
# Full Pipeline Tests (12 Test Cases)
# ─────────────────────────────────────────────

class TestFullPipeline:

    def _run(self, pipeline, tc_data, case_id):
        import json
        from datetime import date
        for tc in tc_data["test_cases"]:
            if tc["case_id"] == case_id:
                inp = tc["input"]
                docs = []
                for d in inp.get("documents", []):
                    cr = d.get("content")
                    content = None
                    if cr:
                        content = DocumentContent(
                            doctor_name=cr.get("doctor_name"), patient_name=cr.get("patient_name"),
                            diagnosis=cr.get("diagnosis"), treatment=cr.get("treatment"),
                            medicines=cr.get("medicines", []), hospital_name=cr.get("hospital_name"),
                            line_items=cr.get("line_items", []), total=cr.get("total"),
                            doctor_registration=cr.get("doctor_registration"),
                        )
                    docs.append(DocumentSubmission(
                        file_id=d["file_id"], actual_type=d.get("actual_type"),
                        content=content, quality=d.get("quality", "GOOD"),
                        patient_name_on_doc=d.get("patient_name_on_doc"),
                    ))
                claim = ClaimSubmission(
                    claim_id=f"TEST-{case_id}", member_id=inp["member_id"],
                    policy_id=inp["policy_id"],
                    claim_category=ClaimCategory(inp["claim_category"]),
                    treatment_date=date.fromisoformat(inp["treatment_date"]),
                    claimed_amount=float(inp["claimed_amount"]),
                    hospital_name=inp.get("hospital_name"),
                    ytd_claims_amount=float(inp.get("ytd_claims_amount", 0)),
                    claims_history=inp.get("claims_history", []),
                    documents=docs,
                    simulate_component_failure=inp.get("simulate_component_failure", False),
                )
                return pipeline.process(claim)
        raise ValueError(f"Case {case_id} not found")

    @pytest.fixture
    def tc_data(self):
        tc_path = os.path.join(os.path.dirname(__file__), "test_cases.json")
        with open(tc_path) as f:
            return json.load(f)

    def test_TC001_wrong_docs(self, pipeline, tc_data):
        d = self._run(pipeline, tc_data, "TC001")
        assert d.decision == DecisionType.DOCUMENT_ISSUE
        assert any("bill" in r.lower() or "hospital" in r.lower() for r in d.rejection_reasons)

    def test_TC002_unreadable_doc(self, pipeline, tc_data):
        d = self._run(pipeline, tc_data, "TC002")
        assert d.decision == DecisionType.DOCUMENT_ISSUE
        assert any("re-upload" in r.lower() or "clear" in r.lower() for r in d.rejection_reasons)

    def test_TC003_different_patients(self, pipeline, tc_data):
        d = self._run(pipeline, tc_data, "TC003")
        assert d.decision == DecisionType.DOCUMENT_ISSUE
        assert any("Rajesh Kumar" in r and "Arjun Mehta" in r for r in d.rejection_reasons)

    def test_TC004_full_approval(self, pipeline, tc_data):
        d = self._run(pipeline, tc_data, "TC004")
        assert d.decision == DecisionType.APPROVED
        assert d.approved_amount == 1350.0
        assert d.confidence_score >= 0.85

    def test_TC005_waiting_period(self, pipeline, tc_data):
        d = self._run(pipeline, tc_data, "TC005")
        assert d.decision == DecisionType.REJECTED
        assert any("WAITING_PERIOD" in r for r in d.rejection_reasons)
        # Must state the eligible date
        all_text = " ".join(d.rejection_reasons)
        assert "2024-11-30" in all_text or "November" in all_text or "eligible" in all_text.lower()

    def test_TC006_dental_partial(self, pipeline, tc_data):
        d = self._run(pipeline, tc_data, "TC006")
        assert d.decision == DecisionType.PARTIAL
        assert d.approved_amount == 8000.0
        assert len(d.line_item_decisions) == 2
        approved = [li for li in d.line_item_decisions if li.status == "APPROVED"]
        rejected = [li for li in d.line_item_decisions if li.status == "REJECTED"]
        assert len(approved) == 1
        assert len(rejected) == 1

    def test_TC007_mri_no_preauth(self, pipeline, tc_data):
        d = self._run(pipeline, tc_data, "TC007")
        assert d.decision == DecisionType.REJECTED
        assert any("PRE_AUTH" in r or "pre-auth" in r.lower() for r in d.rejection_reasons)

    def test_TC008_per_claim_limit(self, pipeline, tc_data):
        d = self._run(pipeline, tc_data, "TC008")
        assert d.decision == DecisionType.REJECTED
        assert any("PER_CLAIM" in r for r in d.rejection_reasons)
        all_text = " ".join(d.rejection_reasons)
        assert "5,000" in all_text or "5000" in all_text
        assert "7,500" in all_text or "7500" in all_text

    def test_TC009_fraud_manual_review(self, pipeline, tc_data):
        d = self._run(pipeline, tc_data, "TC009")
        assert d.decision == DecisionType.MANUAL_REVIEW
        assert len(d.fraud_signals) > 0

    def test_TC010_network_discount(self, pipeline, tc_data):
        d = self._run(pipeline, tc_data, "TC010")
        assert d.decision == DecisionType.APPROVED
        assert d.approved_amount == 3240.0
        assert d.network_discount_applied == 900.0
        assert d.copay_deducted == 360.0

    def test_TC011_graceful_degradation(self, pipeline, tc_data):
        d = self._run(pipeline, tc_data, "TC011")
        assert d.decision == DecisionType.APPROVED
        assert len(d.component_failures) > 0
        assert d.confidence_score < 0.75
        assert d.manual_review_recommended is True

    def test_TC012_excluded_treatment(self, pipeline, tc_data):
        d = self._run(pipeline, tc_data, "TC012")
        assert d.decision == DecisionType.REJECTED
        assert any("EXCLUDED" in r for r in d.rejection_reasons)
        assert d.confidence_score >= 0.90


import json
