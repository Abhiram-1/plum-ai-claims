"""
Decision Agent
==============
RESPONSIBILITY: Apply all policy rules to produce a final claim decision.
Rule evaluation order (short-circuits on first failure):
  1. Member eligibility
  2. Waiting period
  3. General exclusions
  4. Pre-authorization
  5. Per-claim limit
  6. Line-item level checks (dental/vision partial approvals)
  7. Financial calculations (network discount → co-pay)
  8. Fraud routing

Contract:
  Input:  ClaimSubmission, ExtractedInfo, FraudDetectionResult
  Output: ClaimDecision (partial), AgentTrace
  Raises: Never — exceptions produce MANUAL_REVIEW with degraded confidence
"""
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

from models import (
    ClaimSubmission, ExtractedInfo, FraudDetectionResult,
    ClaimDecision, DecisionType, LineItemDecision,
    AgentTrace, AgentStatus, CheckResult
)
from policy_engine import PolicyEngine


class DecisionAgent:
    """Agent 4 (final) in the pipeline."""

    def __init__(self):
        self.policy_engine = PolicyEngine()

    def run(
        self,
        claim: ClaimSubmission,
        extracted_info: ExtractedInfo,
        fraud_result: FraudDetectionResult,
        component_failures: List[str],
    ) -> Tuple[ClaimDecision, AgentTrace]:
        started = datetime.utcnow()
        checks: List[CheckResult] = []
        rejection_reasons: List[str] = []
        approval_notes: List[str] = []

        # Build skeleton decision
        decision = ClaimDecision(
            claim_id=claim.claim_id,
            member_id=claim.member_id,
            policy_id=claim.policy_id,
            claim_category=claim.claim_category.value,
            claimed_amount=claim.claimed_amount,
            decision=DecisionType.APPROVED,
            confidence_score=extracted_info.confidence,
            fraud_score=fraud_result.fraud_score,
            fraud_signals=fraud_result.signals,
            component_failures=component_failures,
        )

        # Degrade confidence if there were component failures
        if component_failures:
            decision.confidence_score = min(decision.confidence_score, 0.55)
            decision.manual_review_recommended = True
            approval_notes.append(
                "⚠ One or more pipeline components failed during processing. "
                "Manual verification is recommended before disbursement."
            )

        # Amount guardrail:
        # - If we extracted a bill total, never process above it.
        # - If claimed is far above the bill, recommend manual review.
        effective_amount = float(claim.claimed_amount or 0.0)
        extracted_total = extracted_info.total_amount
        extracted_total_num: Optional[float] = None
        if extracted_total is not None:
            try:
                extracted_total_num = float(extracted_total)
            except Exception:
                extracted_total_num = None

        if extracted_total_num and extracted_total_num > 0:
            tol_abs = 50.0
            tol_pct = 0.05 * extracted_total_num
            tol = max(tol_abs, tol_pct)
            delta = effective_amount - extracted_total_num

            if delta > tol:
                decision.manual_review_recommended = True
                decision.confidence_score = min(decision.confidence_score, 0.65)
                approval_notes.append(
                    f"Claimed amount ₹{effective_amount:,.0f} is higher than the bill total ₹{extracted_total_num:,.0f}. "
                    f"Capping processing amount to ₹{extracted_total_num:,.0f} and recommending ops review."
                )
                effective_amount = extracted_total_num
            else:
                # Cap quietly even for small deltas to avoid overpaying due to OCR noise.
                effective_amount = min(effective_amount, extracted_total_num)

            checks.append(CheckResult(
                check_name="amount_consistency",
                passed=delta <= tol,
                detail=(
                    f"Claimed ₹{claim.claimed_amount:,.0f}; extracted bill total "
                    f"₹{extracted_total_num:,.0f}; delta ₹{delta:,.0f}; tolerance ₹{tol:,.0f}."
                ),
                value={"claimed_amount": claim.claimed_amount, "extracted_total": extracted_total_num, "effective_amount": effective_amount},
            ))
        else:
            checks.append(CheckResult(
                check_name="amount_consistency",
                passed=True,
                detail="No reliable bill total extracted; using claimed amount.",
                value={"claimed_amount": claim.claimed_amount, "extracted_total": extracted_total_num, "effective_amount": effective_amount},
            ))

        try:
            # ─── Check 1: Member eligibility ──────────────────────────────
            eligible, reason = self.policy_engine.is_member_eligible(claim.member_id)
            checks.append(CheckResult(
                check_name="member_eligibility",
                passed=eligible,
                detail=reason,
            ))
            if not eligible:
                decision.decision = DecisionType.REJECTED
                rejection_reasons.append(f"MEMBER_NOT_ELIGIBLE: {reason}")
                return self._finalise(decision, rejection_reasons, approval_notes, checks, started)

            # ─── Check 2: General exclusions (BEFORE waiting period) ──────
            # Categorically excluded treatments are rejected regardless of waiting period.
            diagnosis = extracted_info.diagnosis or ""
            is_excluded, exclusion_matches = self.policy_engine.check_exclusions(
                diagnosis, extracted_info.treatment, claim.claim_category
            )
            checks.append(CheckResult(
                check_name="policy_exclusions",
                passed=not is_excluded,
                detail=(
                    f"Excluded conditions/treatments matched: {exclusion_matches}"
                    if is_excluded
                    else "No policy exclusions triggered."
                ),
                value=exclusion_matches if is_excluded else None,
            ))
            if is_excluded:
                decision.decision = DecisionType.REJECTED
                exclusion_detail = "; ".join(exclusion_matches)
                rejection_reasons.append(
                    f"EXCLUDED_CONDITION: Treatment '{diagnosis}' falls under excluded category: {exclusion_detail}. "
                    f"This is explicitly excluded by the policy and cannot be covered."
                )
                decision.confidence_score = min(decision.confidence_score, 0.95)
                return self._finalise(decision, rejection_reasons, approval_notes, checks, started)

            # ─── Check 3: Waiting period ──────────────────────────────────
            member = self.policy_engine.get_member(claim.member_id)
            wp_ok, wp_reason, eligible_from = self.policy_engine.check_waiting_period(
                member, diagnosis, claim.treatment_date
            )
            checks.append(CheckResult(
                check_name="waiting_period",
                passed=wp_ok,
                detail=wp_reason,
                value=claim.treatment_date.isoformat(),
                limit=eligible_from.isoformat() if eligible_from else None,
            ))
            if not wp_ok:
                decision.decision = DecisionType.REJECTED
                rejection_reasons.append(f"WAITING_PERIOD: {wp_reason}")
                return self._finalise(decision, rejection_reasons, approval_notes, checks, started)

            # ─── Check 4: Pre-authorization ───────────────────────────────
            # Combine diagnosis + treatment + line_item descriptions for pre-auth scan
            line_items_text = " ".join(
                item.get("description", "") for item in (extracted_info.line_items or [])
            )
            combined_for_preauth = f"{diagnosis} {extracted_info.treatment or ''} {line_items_text}"
            requires_auth, auth_reason = self.policy_engine.requires_pre_auth(
                claim.claim_category,
                effective_amount,
                combined_for_preauth,
                extracted_info.treatment,
            )
            checks.append(CheckResult(
                check_name="pre_authorization",
                passed=not requires_auth,
                detail=auth_reason if requires_auth else "Pre-authorization not required for this claim.",
            ))
            if requires_auth:
                decision.decision = DecisionType.REJECTED
                rejection_reasons.append(
                    f"PRE_AUTH_REQUIRED: {auth_reason} "
                    f"Please obtain pre-authorization and resubmit the claim."
                )
                return self._finalise(decision, rejection_reasons, approval_notes, checks, started)

            # ─── Check 5a: Line-item level (Dental partial) — BEFORE limit check ──
            line_item_decisions: List[LineItemDecision] = []
            line_items = extracted_info.line_items or []
            # effective_amount already includes amount guardrails above

            if claim.claim_category.value == "DENTAL" and line_items:
                categorised = self.policy_engine.check_dental_exclusions(line_items)
                covered_total = 0.0
                excluded_total = 0.0
                for item in categorised:
                    amt = float(item.get("amount", 0))
                    if item["excluded"]:
                        line_item_decisions.append(LineItemDecision(
                            description=item.get("description", ""),
                            claimed_amount=amt,
                            approved_amount=0.0,
                            status="REJECTED",
                            reason=item.get("excluded_reason", "Excluded dental procedure"),
                        ))
                        excluded_total += amt
                    else:
                        line_item_decisions.append(LineItemDecision(
                            description=item.get("description", ""),
                            claimed_amount=amt,
                            approved_amount=amt,
                            status="APPROVED",
                            reason="Covered dental procedure",
                        ))
                        covered_total += amt

                checks.append(CheckResult(
                    check_name="dental_line_item_review",
                    passed=True,
                    detail=f"Dental items: ₹{covered_total:,.0f} covered, ₹{excluded_total:,.0f} excluded.",
                    value={"covered": covered_total, "excluded": excluded_total},
                ))

                if excluded_total > 0 and covered_total > 0:
                    decision.decision = DecisionType.PARTIAL
                    effective_amount = covered_total
                    approval_notes.append(
                        f"Partial approval: ₹{covered_total:,.0f} approved for covered dental procedures. "
                        f"₹{excluded_total:,.0f} excluded (cosmetic/non-covered dental procedures)."
                    )
                elif covered_total == 0:
                    decision.decision = DecisionType.REJECTED
                    rejection_reasons.append("EXCLUDED_CONDITION: All dental procedures claimed are excluded by policy.")
                    decision.line_item_decisions = line_item_decisions
                    return self._finalise(decision, rejection_reasons, approval_notes, checks, started)
                else:
                    effective_amount = covered_total

            decision.line_item_decisions = line_item_decisions

            # ─── Check 5b: Per-claim / sub_limit check (on effective_amount) ──
            CATEGORY_SPECIFIC_LIMIT_CATS = {"DENTAL", "VISION"}
            if claim.claim_category.value in CATEGORY_SPECIFIC_LIMIT_CATS:
                cat_config = self.policy_engine.get_category_config(claim.claim_category)
                effective_limit = cat_config.get("sub_limit", self.policy_engine.policy["coverage"]["per_claim_limit"])
                limit_ok = effective_amount <= effective_limit
                limit_reason = (
                    f"Effective approved amount ₹{effective_amount:,.0f} {'within' if limit_ok else 'exceeds'} "
                    f"{claim.claim_category.value} sub_limit of ₹{effective_limit:,.0f}."
                )
            else:
                limit_ok, limit_reason = self.policy_engine.check_per_claim_limit(effective_amount)
                effective_limit = self.policy_engine.policy["coverage"]["per_claim_limit"]

            checks.append(CheckResult(
                check_name="per_claim_limit",
                passed=limit_ok,
                detail=limit_reason,
                value=effective_amount,
                limit=effective_limit,
            ))
            if not limit_ok:
                decision.decision = DecisionType.REJECTED
                rejection_reasons.append(f"PER_CLAIM_EXCEEDED: {limit_reason}")
                return self._finalise(decision, rejection_reasons, approval_notes, checks, started)

            # ─── Check 6: Fraud routing ───────────────────────────────────
            checks.append(CheckResult(
                check_name="fraud_screening",
                passed=not fraud_result.route_to_manual,
                detail=fraud_result.detail,
                value=fraud_result.fraud_score,
            ))
            if fraud_result.route_to_manual:
                decision.decision = DecisionType.MANUAL_REVIEW
                decision.confidence_score = min(decision.confidence_score, 0.6)
                approval_notes.append(
                    f"Claim routed to manual review due to fraud signals: "
                    + "; ".join(fraud_result.signals)
                )
                return self._finalise(decision, rejection_reasons, approval_notes, checks, started)

            # ─── Check 7: Financial calculation ───────────────────────────
            hospital_name = (
                claim.hospital_name or
                extracted_info.hospital_name or
                (line_items[0].get("hospital_name") if line_items else None)
            )
            # For dental/vision, use category sub_limit as the cap, not global per_claim_limit
            CATEGORY_SPECIFIC_LIMIT_CATS2 = {"DENTAL", "VISION"}
            limit_override = None
            if claim.claim_category.value in CATEGORY_SPECIFIC_LIMIT_CATS2:
                cat_cfg = self.policy_engine.get_category_config(claim.claim_category)
                limit_override = float(cat_cfg.get("sub_limit", self.policy_engine.policy["coverage"]["per_claim_limit"]))

            financials = self.policy_engine.calculate_approved_amount(
                effective_amount,
                claim.claim_category,
                hospital_name,
                limit_override=limit_override,
            )

            decision.approved_amount = financials["approved_amount"]
            decision.network_discount_applied = financials["network_discount"]
            decision.copay_deducted = financials["copay_deducted"]
            decision.amount_after_discount = financials["amount_after_discount"]

            network_hospital = self.policy_engine.is_network_hospital(hospital_name)
            if network_hospital and financials["network_discount"] > 0:
                approval_notes.append(
                    f"Network hospital discount of {financials['network_discount_percent']}% applied: "
                    f"₹{financials['network_discount']:,.2f} deducted from ₹{effective_amount:,.2f} → ₹{financials['amount_after_discount']:,.2f}."
                )
            if financials["copay_deducted"] > 0:
                approval_notes.append(
                    f"Co-pay of {financials['copay_percent']}% applied: "
                    f"₹{financials['copay_deducted']:,.2f} deducted → Final approved: ₹{financials['approved_amount']:,.2f}."
                )
            if financials["capped_by_per_claim_limit"]:
                approval_notes.append(
                    f"Approved amount capped at per-claim limit of ₹{financials['per_claim_limit']:,.0f}."
                )

            checks.append(CheckResult(
                check_name="financial_calculation",
                passed=True,
                detail=(
                    f"Claimed: ₹{effective_amount:,.2f} | "
                    f"Network discount: ₹{financials['network_discount']:,.2f} | "
                    f"Co-pay: ₹{financials['copay_deducted']:,.2f} | "
                    f"Approved: ₹{financials['approved_amount']:,.2f}"
                ),
                value=financials["approved_amount"],
            ))

            # Keep decision type as APPROVED (or PARTIAL if set above)
            if decision.decision != DecisionType.PARTIAL:
                decision.decision = DecisionType.APPROVED

        except Exception as exc:
            # Graceful degradation — never crash
            decision.decision = DecisionType.MANUAL_REVIEW
            decision.confidence_score = min(decision.confidence_score, 0.3)
            decision.manual_review_recommended = True
            approval_notes.append(
                f"Decision Agent encountered an unexpected error: {str(exc)}. "
                f"Routing to manual review for safety."
            )
            decision.component_failures.append(f"DecisionAgent: {str(exc)}")
            checks.append(CheckResult(
                check_name="decision_agent_error",
                passed=False,
                detail=str(exc),
            ))

        return self._finalise(decision, rejection_reasons, approval_notes, checks, started)

    def _finalise(
        self,
        decision: ClaimDecision,
        rejection_reasons: List[str],
        approval_notes: List[str],
        checks: List[CheckResult],
        started: datetime,
    ) -> Tuple[ClaimDecision, AgentTrace]:
        decision.rejection_reasons = rejection_reasons
        decision.approval_notes = approval_notes

        ended = datetime.utcnow()
        decision.decided_at = ended.isoformat()
        decision.processing_time_ms = (ended - started).total_seconds() * 1000

        trace = AgentTrace(
            agent_name="DecisionAgent",
            status=AgentStatus.SUCCESS,
            started_at=started.isoformat(),
            completed_at=ended.isoformat(),
            duration_ms=decision.processing_time_ms,
            checks=checks,
            output={
                "decision": decision.decision.value,
                "approved_amount": decision.approved_amount,
                "confidence": decision.confidence_score,
                "rejection_count": len(rejection_reasons),
            },
            warnings=rejection_reasons + approval_notes,
        )

        return decision, trace
