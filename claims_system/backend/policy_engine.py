"""
Policy Engine — reads policy_terms.json and provides rule-enforcement helpers.
All policy logic lives here. Agents call this; they never read the JSON directly.
"""
import json
import os
from datetime import date, timedelta
from typing import Optional, Dict, Any, List, Tuple
from functools import lru_cache
from models import ClaimCategory


POLICY_PATH = os.path.join(os.path.dirname(__file__), "data", "policy_terms.json")


# ─────────────────────────────────────────────
# Condition → waiting-period keyword mapping
# ─────────────────────────────────────────────
DIAGNOSIS_WAITING_PERIOD_KEYWORDS: Dict[str, List[str]] = {
    "diabetes": [
        "diabetes", "diabetic", "t2dm", "type 2 diabetes", "type ii diabetes",
        "hyperglycemia", "insulin resistance", "metformin", "glimepiride", "januvia",
        "dm ", "dm,", "dm.", "dmii"
    ],
    "hypertension": [
        "hypertension", "htn", "high blood pressure", "bp elevated",
        "amlodipine", "losartan", "telmisartan", "antihypertensive"
    ],
    "thyroid_disorders": [
        "thyroid", "hypothyroid", "hyperthyroid", "hashimoto", "graves",
        "levothyroxine", "thyroxine", "t3", "t4", "tsh"
    ],
    "joint_replacement": [
        "joint replacement", "knee replacement", "hip replacement",
        "arthroplasty", "tkr", "thr"
    ],
    "maternity": [
        "pregnancy", "maternity", "antenatal", "prenatal", "obstetric",
        "delivery", "labour", "labor", "caesarean", "c-section"
    ],
    "mental_health": [
        "depression", "anxiety", "psychiatric", "schizophrenia", "bipolar",
        "mental health", "psychotherapy", "antidepressant", "ssri"
    ],
    "obesity_treatment": [
        "obesity", "obese", "bariatric", "weight loss", "bmi", "morbid obesity",
        "weight management"
    ],
    "hernia": [
        "inguinal hernia", "umbilical hernia", "hiatal hernia", "femoral hernia",
        "hernia repair", "hernioplasty", "herniorrhaphy", "abdominal hernia",
    ],
    "cataract": [
        "cataract", "lens opacity", "phacoemulsification"
    ],
}

# Exclusion keyword mapping
EXCLUSION_KEYWORDS: List[Tuple[str, List[str]]] = [
    ("Self-inflicted injuries", ["self-inflicted", "self inflicted", "self harm", "self-harm"]),
    ("Substance abuse treatment", ["substance abuse", "alcohol abuse", "drug abuse", "de-addiction", "deaddiction"]),
    ("Experimental treatments", ["experimental", "investigational", "clinical trial"]),
    ("Infertility and assisted reproduction", ["infertility", "ivf", "iui", "surrogacy", "assisted reproduction"]),
    ("Obesity and weight loss programs", [
        "obesity", "bariatric", "weight loss program", "weight reduction program",
        "bariatric consultation", "morbid obesity"
    ]),
    ("Cosmetic or aesthetic procedures", [
        "cosmetic", "aesthetic", "botox", "liposuction", "rhinoplasty",
        "filler", "facelift"
    ]),
    ("Vaccination (non-medically necessary)", ["vaccination", "vaccine", "immunization"]),
    ("Health supplements and tonics", ["supplement", "tonic", "multivitamin", "protein shake"]),
]

DENTAL_EXCLUSION_KEYWORDS = [
    "teeth whitening", "tooth whitening", "whitening",
    "veneer", "orthodontic", "braces", "implant cosmetic",
    "bleaching"
]

VISION_EXCLUSION_KEYWORDS = [
    "lasik", "refractive surgery", "cosmetic eye"
]


@lru_cache(maxsize=1)
def load_policy() -> Dict[str, Any]:
    with open(POLICY_PATH, "r") as f:
        return json.load(f)


class PolicyEngine:
    def __init__(self):
        self.policy = load_policy()

    # ─────────────────────────────────────────
    # Member helpers
    # ─────────────────────────────────────────

    def get_member(self, member_id: str) -> Optional[Dict[str, Any]]:
        for m in self.policy["members"]:
            if m["member_id"] == member_id:
                return m
        return None

    def is_member_eligible(self, member_id: str) -> Tuple[bool, str]:
        member = self.get_member(member_id)
        if not member:
            return False, f"Member '{member_id}' not found in policy."
        status = self.policy["policy_holder"]["renewal_status"]
        if status != "ACTIVE":
            return False, f"Policy is not active (status: {status})."
        return True, "Member is eligible."

    # ─────────────────────────────────────────
    # Waiting period
    # ─────────────────────────────────────────

    def get_waiting_period_days(self, diagnosis_text: str) -> Tuple[int, str]:
        """
        Returns (waiting_period_days, condition_key).
        Always checks the most specific applicable period.
        Defaults to initial_waiting_period_days if no condition match.
        """
        if not diagnosis_text:
            return self.policy["waiting_periods"]["initial_waiting_period_days"], "initial"

        diag_lower = diagnosis_text.lower()
        specific = self.policy["waiting_periods"]["specific_conditions"]

        for condition_key, keywords in DIAGNOSIS_WAITING_PERIOD_KEYWORDS.items():
            if condition_key in specific:
                for kw in keywords:
                    if kw in diag_lower:
                        return specific[condition_key], condition_key

        return self.policy["waiting_periods"]["initial_waiting_period_days"], "initial"

    def check_waiting_period(
        self,
        member: Dict[str, Any],
        diagnosis: Optional[str],
        treatment_date: date
    ) -> Tuple[bool, str, Optional[date]]:
        """
        Returns (eligible, reason, eligible_from_date).
        """
        join_date = date.fromisoformat(member["join_date"])
        waiting_days, condition_key = self.get_waiting_period_days(diagnosis or "")
        eligible_from = join_date + timedelta(days=waiting_days)

        if treatment_date < eligible_from:
            if condition_key == "initial":
                reason = (
                    f"Initial waiting period of {waiting_days} days not met. "
                    f"Member joined on {join_date}. "
                    f"Eligible for claims from {eligible_from}."
                )
            else:
                condition_label = condition_key.replace("_", " ").title()
                reason = (
                    f"Specific waiting period for {condition_label} is {waiting_days} days. "
                    f"Member joined on {join_date}. "
                    f"Eligible for {condition_label} claims from {eligible_from}."
                )
            return False, reason, eligible_from

        return True, "Waiting period satisfied.", eligible_from

    # ─────────────────────────────────────────
    # Exclusions
    # ─────────────────────────────────────────

    def check_exclusions(
        self,
        diagnosis: Optional[str],
        treatment: Optional[str],
        claim_category: ClaimCategory
    ) -> Tuple[bool, List[str]]:
        """
        Returns (is_excluded, list_of_matched_exclusions).
        """
        combined = f"{diagnosis or ''} {treatment or ''}".lower()
        matched = []

        for exclusion_label, keywords in EXCLUSION_KEYWORDS:
            for kw in keywords:
                if kw in combined:
                    matched.append(exclusion_label)
                    break

        return bool(matched), matched

    def check_dental_exclusions(self, line_items: List[Dict]) -> List[Dict]:
        """
        Returns line items split into covered/excluded for dental claims.
        Uses full-phrase matching to avoid false positives.
        """
        policy_covered = [p.lower() for p in self.policy["opd_categories"]["dental"]["covered_procedures"]]
        policy_excluded = [p.lower() for p in self.policy["opd_categories"]["dental"]["excluded_procedures"]]

        results = []
        for item in line_items:
            desc_lower = item.get("description", "").lower()
            excluded = False
            excluded_reason = ""

            # 1. Direct keyword match from our exclusion list
            for kw in DENTAL_EXCLUSION_KEYWORDS:
                if kw in desc_lower:
                    excluded = True
                    excluded_reason = f"Cosmetic/excluded dental procedure: {item['description']}"
                    break

            # 2. Full-phrase match against policy excluded procedures (not word-split)
            if not excluded:
                for ep in policy_excluded:
                    # Match at least 60% of the exclusion phrase words
                    ep_words = [w for w in ep.split() if len(w) > 3 and w not in ("with", "and", "for")]
                    if ep_words:
                        matches = sum(1 for w in ep_words if w in desc_lower)
                        if matches >= max(1, len(ep_words) * 0.6):
                            excluded = True
                            excluded_reason = f"Dental procedure not covered by policy: {item['description']}"
                            break

            # 3. Verify against covered procedures (takes precedence)
            if excluded:
                for cp in policy_covered:
                    cp_words = [w for w in cp.split() if len(w) > 3]
                    if cp_words:
                        matches = sum(1 for w in cp_words if w in desc_lower)
                        if matches >= max(1, len(cp_words) * 0.7):
                            # This item matches a covered procedure — override exclusion
                            excluded = False
                            excluded_reason = ""
                            break

            results.append({**item, "excluded": excluded, "excluded_reason": excluded_reason})
        return results

    # ─────────────────────────────────────────
    # Pre-authorization
    # ─────────────────────────────────────────

    def requires_pre_auth(
        self,
        claim_category: ClaimCategory,
        claimed_amount: float,
        diagnosis: Optional[str],
        treatment: Optional[str]
    ) -> Tuple[bool, str]:
        """Returns (requires_pre_auth, reason)."""
        combined = f"{diagnosis or ''} {treatment or ''}".lower()

        if claim_category == ClaimCategory.DIAGNOSTIC:
            threshold = self.policy["opd_categories"]["diagnostic"].get("pre_auth_threshold", 10000)
            high_value_tests = [t.lower() for t in self.policy["opd_categories"]["diagnostic"].get("high_value_tests_requiring_pre_auth", [])]
            for test in high_value_tests:
                if test.lower() in combined:
                    if claimed_amount > threshold:
                        return True, (
                            f"{test.upper()} requires pre-authorization when amount exceeds ₹{threshold:,.0f}. "
                            f"Claimed amount is ₹{claimed_amount:,.0f}."
                        )

        return False, ""

    # ─────────────────────────────────────────
    # Financial calculations
    # ─────────────────────────────────────────

    def get_category_config(self, claim_category: ClaimCategory) -> Dict[str, Any]:
        cat_map = {
            ClaimCategory.CONSULTATION: "consultation",
            ClaimCategory.DIAGNOSTIC: "diagnostic",
            ClaimCategory.PHARMACY: "pharmacy",
            ClaimCategory.DENTAL: "dental",
            ClaimCategory.VISION: "vision",
            ClaimCategory.ALTERNATIVE_MEDICINE: "alternative_medicine",
        }
        key = cat_map.get(claim_category, "consultation")
        return self.policy["opd_categories"].get(key, {})

    def is_network_hospital(self, hospital_name: Optional[str]) -> bool:
        if not hospital_name:
            return False
        hospital_lower = hospital_name.lower()
        for nh in self.policy["network_hospitals"]:
            if nh.lower() in hospital_lower or hospital_lower in nh.lower():
                return True
        return False

    def calculate_approved_amount(
        self,
        claimed_amount: float,
        claim_category: ClaimCategory,
        hospital_name: Optional[str],
        limit_override: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Applies: network discount -> co-pay -> per_claim_limit cap.
        limit_override: use category sub_limit instead (dental/vision).
        Returns a breakdown dict.
        """
        cat_config = self.get_category_config(claim_category)
        per_claim_limit = limit_override if limit_override is not None else self.policy["coverage"]["per_claim_limit"]

        amount = claimed_amount
        network_discount = 0.0
        copay_deducted = 0.0
        amount_after_discount = amount

        # Network discount applied FIRST
        if self.is_network_hospital(hospital_name):
            discount_pct = cat_config.get("network_discount_percent", 0)
            network_discount = amount * (discount_pct / 100)
            amount -= network_discount
            amount_after_discount = amount

        # Co-pay applied AFTER discount
        copay_pct = cat_config.get("copay_percent", 0)
        copay_deducted = amount * (copay_pct / 100)
        amount -= copay_deducted

        # Per-claim cap
        capped = False
        if amount > per_claim_limit:
            amount = float(per_claim_limit)
            capped = True

        return {
            "approved_amount": round(amount, 2),
            "network_discount": round(network_discount, 2),
            "copay_deducted": round(copay_deducted, 2),
            "amount_after_discount": round(amount_after_discount, 2),
            "copay_percent": copay_pct,
            "network_discount_percent": cat_config.get("network_discount_percent", 0),
            "capped_by_per_claim_limit": capped,
            "per_claim_limit": per_claim_limit,
        }

    # ─────────────────────────────────────────
    # Per-claim limit check
    # ─────────────────────────────────────────

    def check_per_claim_limit(self, claimed_amount: float) -> Tuple[bool, str]:
        limit = self.policy["coverage"]["per_claim_limit"]
        if claimed_amount > limit:
            return False, (
                f"Claimed amount ₹{claimed_amount:,.0f} exceeds the per-claim limit of ₹{limit:,.0f}."
            )
        return True, f"Claimed amount ₹{claimed_amount:,.0f} is within per-claim limit of ₹{limit:,.0f}."

    # ─────────────────────────────────────────
    # Document requirements
    # ─────────────────────────────────────────

    def get_required_documents(self, claim_category: ClaimCategory) -> Dict[str, List[str]]:
        return self.policy["document_requirements"].get(claim_category.value, {"required": [], "optional": []})

    # ─────────────────────────────────────────
    # Fraud thresholds
    # ─────────────────────────────────────────

    def get_fraud_thresholds(self) -> Dict[str, Any]:
        return self.policy["fraud_thresholds"]
