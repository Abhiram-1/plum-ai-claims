"""
Multi-agent claims processing pipeline.
Orchestrates document verification, extraction, fraud detection, and decision making.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import datetime
from typing import Optional, Dict, List

from models import (
    ClaimSubmission, ClaimDecision, DecisionType, ExtractedInfo,
    FraudDetectionResult, AgentTrace, AgentStatus, DocumentVerificationResult
)

from agents.document_verifier import DocumentVerifierAgent
from agents.extraction_agent import ExtractionAgent
from agents.fraud_agent import FraudDetectionAgent
from agents.decision_agent import DecisionAgent


class ClaimsPipeline:
    """
    Multi-agent orchestrator.
    Each agent is instantiated fresh per-run to ensure statelessness.
    """

    def process(
        self,
        claim: ClaimSubmission,
        uploaded_files: Optional[Dict[str, str]] = None,
    ) -> ClaimDecision:
        pipeline_started = datetime.utcnow()
        all_traces: List[AgentTrace] = []
        component_failures: List[str] = []

        # ─────────────────────────────────────────────────────────────────
        # AGENT 1: Document Verification (EARLY EXIT on failure)
        # ─────────────────────────────────────────────────────────────────
        doc_result: Optional[DocumentVerificationResult] = None
        try:
            verifier = DocumentVerifierAgent()
            doc_result, verifier_trace = verifier.run(claim, uploaded_files=uploaded_files)
            all_traces.append(verifier_trace)
        except Exception as e:
            component_failures.append(f"DocumentVerifierAgent: {str(e)}")
            all_traces.append(AgentTrace(
                agent_name="DocumentVerifierAgent",
                status=AgentStatus.FAILED,
                error=str(e),
            ))
            doc_result = DocumentVerificationResult(passed=True, issues=[])  # Allow through

        # If document verification failed → return DOCUMENT_ISSUE immediately
        if doc_result and not doc_result.passed:
            ms = (datetime.utcnow() - pipeline_started).total_seconds() * 1000
            decision = ClaimDecision(
                claim_id=claim.claim_id,
                member_id=claim.member_id,
                policy_id=claim.policy_id,
                claim_category=claim.claim_category.value,
                claimed_amount=claim.claimed_amount,
                decision=DecisionType.DOCUMENT_ISSUE,
                approved_amount=None,
                confidence_score=1.0,  # We are highly confident this is a doc problem
                rejection_reasons=[
                    issue["message"]
                    for issue in doc_result.issues
                ],
                approval_notes=[],
                component_failures=component_failures,
                agent_traces=all_traces,
                processing_time_ms=ms,
                decided_at=datetime.utcnow().isoformat(),
            )
            return decision

        # ─────────────────────────────────────────────────────────────────
        # AGENT 2: Extraction
        # ─────────────────────────────────────────────────────────────────
        extracted_info: ExtractedInfo = ExtractedInfo()
        try:
            extractor = ExtractionAgent(
                simulate_failure=claim.simulate_component_failure
            )
            extracted_info, extraction_trace = extractor.run(claim, uploaded_files)
            all_traces.append(extraction_trace)
            if extraction_trace.status == AgentStatus.PARTIAL:
                component_failures.append("ExtractionAgent: partial failure (simulated or real)")
        except Exception as e:
            component_failures.append(f"ExtractionAgent: {str(e)}")
            all_traces.append(AgentTrace(
                agent_name="ExtractionAgent",
                status=AgentStatus.FAILED,
                error=str(e),
            ))
            # Use claim data as fallback
            extracted_info = ExtractedInfo(
                total_amount=claim.claimed_amount,
                confidence=0.3,
                extraction_warnings=[f"Extraction failed: {str(e)}"],
            )

        # ─────────────────────────────────────────────────────────────────
        # AGENT 3: Fraud Detection
        # ─────────────────────────────────────────────────────────────────
        fraud_result: FraudDetectionResult = FraudDetectionResult(fraud_score=0.0)
        try:
            fraud_agent = FraudDetectionAgent()
            fraud_result, fraud_trace = fraud_agent.run(claim, extracted_info)
            all_traces.append(fraud_trace)
        except Exception as e:
            component_failures.append(f"FraudDetectionAgent: {str(e)}")
            all_traces.append(AgentTrace(
                agent_name="FraudDetectionAgent",
                status=AgentStatus.FAILED,
                error=str(e),
            ))

        # ─────────────────────────────────────────────────────────────────
        # AGENT 4: Decision
        # ─────────────────────────────────────────────────────────────────
        final_decision: Optional[ClaimDecision] = None
        try:
            decision_agent = DecisionAgent()
            final_decision, decision_trace = decision_agent.run(
                claim, extracted_info, fraud_result, component_failures
            )
            all_traces.append(decision_trace)
        except Exception as e:
            component_failures.append(f"DecisionAgent: {str(e)}")
            all_traces.append(AgentTrace(
                agent_name="DecisionAgent",
                status=AgentStatus.FAILED,
                error=str(e),
            ))
            ms = (datetime.utcnow() - pipeline_started).total_seconds() * 1000
            final_decision = ClaimDecision(
                claim_id=claim.claim_id,
                member_id=claim.member_id,
                policy_id=claim.policy_id,
                claim_category=claim.claim_category.value,
                claimed_amount=claim.claimed_amount,
                decision=DecisionType.MANUAL_REVIEW,
                confidence_score=0.2,
                rejection_reasons=[f"Critical pipeline failure: {str(e)}"],
                component_failures=component_failures,
                manual_review_recommended=True,
                processing_time_ms=ms,
                decided_at=datetime.utcnow().isoformat(),
            )

        # Attach all traces to final decision
        final_decision.agent_traces = all_traces
        final_decision.processing_time_ms = (
            datetime.utcnow() - pipeline_started
        ).total_seconds() * 1000

        return final_decision
