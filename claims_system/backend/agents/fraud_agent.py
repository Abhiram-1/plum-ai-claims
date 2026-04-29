"""
Fraud Detection Agent
=====================
RESPONSIBILITY: Score claim for fraud signals and decide if manual review is needed.
- Same-day duplicate claims
- High-value claim threshold
- Document alteration signals
- Monthly frequency check

Contract:
  Input:  ClaimSubmission, ExtractedInfo
  Output: FraudDetectionResult, AgentTrace
  Raises: Never — all failures are surface-level warnings
"""
from datetime import datetime, date
from typing import List, Dict, Any, Optional

from models import (
    ClaimSubmission, ExtractedInfo, FraudDetectionResult,
    AgentTrace, AgentStatus, CheckResult
)
from policy_engine import PolicyEngine


class FraudDetectionAgent:
    """Agent 3 in the pipeline."""

    def __init__(self):
        self.policy_engine = PolicyEngine()

    def run(
        self,
        claim: ClaimSubmission,
        extracted_info: ExtractedInfo,
    ) -> tuple[FraudDetectionResult, AgentTrace]:
        started = datetime.utcnow()
        checks: List[CheckResult] = []
        signals: List[str] = []
        score = 0.0
        thresholds = self.policy_engine.get_fraud_thresholds()

        # ── Check 1: Same-day claim count ─────────────────────────────────
        same_day_limit = thresholds.get("same_day_claims_limit", 2)
        if claim.claims_history:
            treatment_date_str = claim.treatment_date.isoformat()
            same_day = [
                c for c in claim.claims_history
                if c.get("date") == treatment_date_str
            ]
            same_day_count = len(same_day)

            if same_day_count >= same_day_limit:
                providers = list(set(c.get("provider", "Unknown") for c in same_day))
                signal = (
                    f"Unusual pattern: {same_day_count} other claims already submitted on "
                    f"{treatment_date_str} (limit: {same_day_limit}). "
                    f"Providers: {', '.join(providers)}."
                )
                signals.append(signal)
                score += 0.45
                checks.append(CheckResult(
                    check_name="same_day_claims",
                    passed=False,
                    detail=signal,
                    value=same_day_count,
                    limit=same_day_limit,
                ))
            else:
                checks.append(CheckResult(
                    check_name="same_day_claims",
                    passed=True,
                    detail=f"Same-day claim count ({same_day_count}) within limit ({same_day_limit}).",
                    value=same_day_count,
                    limit=same_day_limit,
                ))
        else:
            checks.append(CheckResult(
                check_name="same_day_claims",
                passed=True,
                detail="No claims history provided — skipped same-day check.",
            ))

        # ── Check 2: High-value claim ─────────────────────────────────────
        hv_threshold = thresholds.get("high_value_claim_threshold", 25000)
        auto_manual_threshold = thresholds.get("auto_manual_review_above", 25000)

        if claim.claimed_amount >= hv_threshold:
            signal = (
                f"High-value claim: ₹{claim.claimed_amount:,.0f} "
                f"(threshold: ₹{hv_threshold:,.0f}). Auto-routed for manual review."
            )
            signals.append(signal)
            score += 0.25
            checks.append(CheckResult(
                check_name="high_value_threshold",
                passed=False,
                detail=signal,
                value=claim.claimed_amount,
                limit=hv_threshold,
            ))
        else:
            checks.append(CheckResult(
                check_name="high_value_threshold",
                passed=True,
                detail=f"Claim amount ₹{claim.claimed_amount:,.0f} below high-value threshold ₹{hv_threshold:,.0f}.",
                value=claim.claimed_amount,
                limit=hv_threshold,
            ))

        # ── Check 3: Document alteration (keyword-based heuristic) ────────
        doc_alt_keywords = ["crossed out", "correction", "overwrite", "alteration", "cancelled"]
        doc_warnings = extracted_info.extraction_warnings or []
        alteration_detected = any(
            kw in w.lower() for w in doc_warnings for kw in doc_alt_keywords
        )
        if alteration_detected:
            signal = "Document alteration detected in extraction warnings."
            signals.append(signal)
            score += 0.2
        checks.append(CheckResult(
            check_name="document_alteration",
            passed=not alteration_detected,
            detail="Document alteration signals detected." if alteration_detected else "No document alteration detected.",
        ))

        # ── Check 4: Monthly claim frequency ─────────────────────────────
        monthly_limit = thresholds.get("monthly_claims_limit", 6)
        if claim.claims_history:
            treatment_month = claim.treatment_date.month
            treatment_year = claim.treatment_date.year
            monthly_count = sum(
                1 for c in claim.claims_history
                if c.get("date", "")[:7] == f"{treatment_year:04d}-{treatment_month:02d}"
            )
            if monthly_count >= monthly_limit:
                signal = f"Monthly claim frequency ({monthly_count}) exceeds limit ({monthly_limit})."
                signals.append(signal)
                score += 0.2
                checks.append(CheckResult(
                    check_name="monthly_frequency",
                    passed=False,
                    detail=signal,
                    value=monthly_count,
                    limit=monthly_limit,
                ))
            else:
                checks.append(CheckResult(
                    check_name="monthly_frequency",
                    passed=True,
                    detail=f"Monthly claims ({monthly_count}) within limit ({monthly_limit}).",
                ))
        else:
            checks.append(CheckResult(
                check_name="monthly_frequency",
                passed=True,
                detail="No claims history — skipped monthly frequency check.",
            ))

        # ── Clamp score ────────────────────────────────────────────────────
        score = min(score, 1.0)
        fraud_threshold = thresholds.get("fraud_score_manual_review_threshold", 0.80)
        route_to_manual = score >= fraud_threshold or (same_day_limit and len([s for s in signals if "same-day" in s.lower() or "Unusual pattern" in s]) > 0)

        # Same-day fraud pattern is the clearest signal — always flag
        if any("Unusual pattern" in s for s in signals):
            route_to_manual = True

        result = FraudDetectionResult(
            fraud_score=round(score, 2),
            signals=signals,
            route_to_manual=route_to_manual,
            detail=f"Fraud score: {score:.2f}. {'Routing to MANUAL_REVIEW.' if route_to_manual else 'Auto-processing allowed.'}",
        )

        ended = datetime.utcnow()
        trace = AgentTrace(
            agent_name="FraudDetectionAgent",
            status=AgentStatus.SUCCESS,
            started_at=started.isoformat(),
            completed_at=ended.isoformat(),
            duration_ms=(ended - started).total_seconds() * 1000,
            checks=checks,
            output={
                "fraud_score": score,
                "signals_count": len(signals),
                "route_to_manual": route_to_manual,
            },
            warnings=signals,
        )

        return result, trace
