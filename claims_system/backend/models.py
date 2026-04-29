"""
Core data models for the Plum Health Insurance Claims Processing System.
All request/response contracts are defined here.
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Union
from enum import Enum
from datetime import date, datetime
import uuid


# ─────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────

class ClaimCategory(str, Enum):
    CONSULTATION = "CONSULTATION"
    DIAGNOSTIC = "DIAGNOSTIC"
    PHARMACY = "PHARMACY"
    DENTAL = "DENTAL"
    VISION = "VISION"
    ALTERNATIVE_MEDICINE = "ALTERNATIVE_MEDICINE"


class DocumentType(str, Enum):
    PRESCRIPTION = "PRESCRIPTION"
    HOSPITAL_BILL = "HOSPITAL_BILL"
    LAB_REPORT = "LAB_REPORT"
    PHARMACY_BILL = "PHARMACY_BILL"
    DENTAL_REPORT = "DENTAL_REPORT"
    DIAGNOSTIC_REPORT = "DIAGNOSTIC_REPORT"
    DISCHARGE_SUMMARY = "DISCHARGE_SUMMARY"


class DecisionType(str, Enum):
    APPROVED = "APPROVED"
    PARTIAL = "PARTIAL"
    REJECTED = "REJECTED"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    DOCUMENT_ISSUE = "DOCUMENT_ISSUE"


class DocumentQuality(str, Enum):
    GOOD = "GOOD"
    POOR = "POOR"
    UNREADABLE = "UNREADABLE"


class AgentStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    PARTIAL = "PARTIAL"


# ─────────────────────────────────────────────
# Document Models
# ─────────────────────────────────────────────

class DocumentContent(BaseModel):
    """Structured content extracted from or provided for a document."""
    doctor_name: Optional[str] = None
    doctor_registration: Optional[str] = None
    patient_name: Optional[str] = None
    date: Optional[str] = None
    diagnosis: Optional[str] = None
    treatment: Optional[str] = None
    medicines: Optional[List[str]] = []
    hospital_name: Optional[str] = None
    line_items: Optional[List[Dict[str, Any]]] = []
    total: Optional[float] = None
    tests_ordered: Optional[List[str]] = []
    specialization: Optional[str] = None
    remarks: Optional[str] = None


class DocumentSubmission(BaseModel):
    """A single document uploaded as part of a claim."""
    file_id: str
    file_name: Optional[str] = None
    actual_type: Optional[str] = None       # For test cases or pre-classified docs
    content: Optional[DocumentContent] = None  # Pre-populated content for test cases
    quality: Optional[str] = DocumentQuality.GOOD
    patient_name_on_doc: Optional[str] = None  # For test cases that specify cross-patient checks


# ─────────────────────────────────────────────
# Claim Submission
# ─────────────────────────────────────────────

class ClaimSubmission(BaseModel):
    """Inbound claim from a member."""
    claim_id: Optional[str] = Field(default_factory=lambda: f"CLM-{uuid.uuid4().hex[:8].upper()}")
    member_id: str
    policy_id: str
    claim_category: ClaimCategory
    treatment_date: date
    claimed_amount: float
    hospital_name: Optional[str] = None
    ytd_claims_amount: Optional[float] = 0.0
    claims_history: Optional[List[Dict[str, Any]]] = []
    documents: List[DocumentSubmission]
    simulate_component_failure: Optional[bool] = False
    submitted_at: Optional[datetime] = Field(default_factory=datetime.utcnow)


# ─────────────────────────────────────────────
# Agent Trace Models (Explainability)
# ─────────────────────────────────────────────

class CheckResult(BaseModel):
    """Result of a single policy/rule check within an agent."""
    check_name: str
    passed: bool
    detail: str
    value: Optional[Any] = None
    limit: Optional[Any] = None


class AgentTrace(BaseModel):
    """Full execution trace for a single agent."""
    agent_name: str
    status: AgentStatus
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_ms: Optional[float] = None
    checks: List[CheckResult] = []
    output: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    warnings: List[str] = []


# ─────────────────────────────────────────────
# Extracted Document Info
# ─────────────────────────────────────────────

class ExtractedInfo(BaseModel):
    """Consolidated information extracted across all submitted documents."""
    patient_name: Optional[str] = None
    doctor_name: Optional[str] = None
    doctor_registration: Optional[str] = None
    diagnosis: Optional[str] = None
    treatment: Optional[str] = None
    treatment_date: Optional[str] = None
    hospital_name: Optional[str] = None
    total_amount: Optional[float] = None
    line_items: List[Dict[str, Any]] = []
    medicines: List[str] = []
    document_types_found: List[str] = []
    confidence: float = 1.0
    extraction_warnings: List[str] = []


# ─────────────────────────────────────────────
# Line Item Decision (for PARTIAL claims)
# ─────────────────────────────────────────────

class LineItemDecision(BaseModel):
    description: str
    claimed_amount: float
    approved_amount: float
    status: str        # APPROVED / REJECTED
    reason: Optional[str] = None


# ─────────────────────────────────────────────
# Claim Decision
# ─────────────────────────────────────────────

class ClaimDecision(BaseModel):
    """Final decision on a claim — the output of the full pipeline."""
    claim_id: str
    member_id: str
    policy_id: str
    claim_category: str
    claimed_amount: float

    # Decision
    decision: DecisionType
    approved_amount: Optional[float] = None
    confidence_score: float = Field(ge=0.0, le=1.0)

    # Explanation
    rejection_reasons: List[str] = []
    approval_notes: List[str] = []
    line_item_decisions: List[LineItemDecision] = []

    # Financial breakdown
    network_discount_applied: Optional[float] = None
    copay_deducted: Optional[float] = None
    amount_after_discount: Optional[float] = None

    # Fraud
    fraud_signals: List[str] = []
    fraud_score: Optional[float] = None

    # Degradation
    component_failures: List[str] = []
    manual_review_recommended: bool = False

    # Full trace
    agent_traces: List[AgentTrace] = []

    # Meta
    processing_time_ms: Optional[float] = None
    decided_at: Optional[str] = None


# ─────────────────────────────────────────────
# Document Verification Output
# ─────────────────────────────────────────────

class DocumentVerificationResult(BaseModel):
    """Output from the Document Verifier Agent."""
    passed: bool
    issues: List[Dict[str, str]] = []     # Each: {type, message, action_required}
    document_types_found: List[str] = []
    missing_required: List[str] = []
    unreadable_documents: List[str] = []
    cross_patient_mismatch: bool = False
    mismatch_detail: Optional[str] = None


# ─────────────────────────────────────────────
# Fraud Detection Output
# ─────────────────────────────────────────────

class FraudDetectionResult(BaseModel):
    fraud_score: float = Field(ge=0.0, le=1.0)
    signals: List[str] = []
    route_to_manual: bool = False
    detail: str = ""
