"""
Plum Claims Processing API - Multi-agent health insurance claims automation.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

try:
    from pathlib import Path
    from dotenv import load_dotenv
    _repo_root = Path(os.path.dirname(__file__)).parent
    load_dotenv(dotenv_path=_repo_root / ".env")
except Exception:
    pass

import json
import uuid
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, List, Any

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from models import ClaimSubmission, ClaimDecision, DecisionType, DocumentSubmission, ClaimCategory
from pipeline.orchestrator import ClaimsPipeline
from policy_engine import PolicyEngine

app = FastAPI(
    title="Plum Claims Processing API",
    description="Multi-agent health insurance claims processing system",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory decision store (production: use PostgreSQL)
decision_store: Dict[str, ClaimDecision] = {}

# Frontend static (optional).
# IMPORTANT: mount it under /ui so it doesn't shadow API routes like /claims/*.
FRONTEND_DIR = Path(os.path.dirname(__file__)).parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/ui", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

# Load test cases
TEST_CASES_PATH = os.path.join(os.path.dirname(__file__), "..", "tests", "test_cases.json")
with open(TEST_CASES_PATH) as f:
    TEST_CASES_DATA = json.load(f)


def _parse_test_case(tc: Dict) -> ClaimSubmission:
    """Convert a raw test-case dict to a ClaimSubmission."""
    inp = tc["input"]
    docs = []
    for d in inp.get("documents", []):
        content_raw = d.get("content")
        content = None
        if content_raw:
            from models import DocumentContent
            li = content_raw.get("line_items", [])
            content = DocumentContent(
                doctor_name=content_raw.get("doctor_name"),
                doctor_registration=content_raw.get("doctor_registration"),
                patient_name=content_raw.get("patient_name"),
                date=content_raw.get("date"),
                diagnosis=content_raw.get("diagnosis"),
                treatment=content_raw.get("treatment"),
                medicines=content_raw.get("medicines", []),
                hospital_name=content_raw.get("hospital_name"),
                line_items=li,
                total=content_raw.get("total"),
            )
        docs.append(DocumentSubmission(
            file_id=d["file_id"],
            file_name=d.get("file_name"),
            actual_type=d.get("actual_type"),
            content=content,
            quality=d.get("quality", "GOOD"),
            patient_name_on_doc=d.get("patient_name_on_doc"),
        ))

    from datetime import date
    treatment_date = date.fromisoformat(inp["treatment_date"])

    return ClaimSubmission(
        claim_id=f"TEST-{tc['case_id']}",
        member_id=inp["member_id"],
        policy_id=inp["policy_id"],
        claim_category=ClaimCategory(inp["claim_category"]),
        treatment_date=treatment_date,
        claimed_amount=float(inp["claimed_amount"]),
        hospital_name=inp.get("hospital_name"),
        ytd_claims_amount=float(inp.get("ytd_claims_amount", 0)),
        claims_history=inp.get("claims_history", []),
        documents=docs,
        simulate_component_failure=inp.get("simulate_component_failure", False),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.get("/policy/summary")
async def policy_summary():
    pe = PolicyEngine()
    p = pe.policy
    return {
        "policy_id": p["policy_id"],
        "policy_name": p["policy_name"],
        "insurer": p["insurer"],
        "company": p["policy_holder"]["company_name"],
        "sum_insured": p["coverage"]["sum_insured_per_employee"],
        "annual_opd_limit": p["coverage"]["annual_opd_limit"],
        "per_claim_limit": p["coverage"]["per_claim_limit"],
        "member_count": len(p["members"]),
        "network_hospitals": p["network_hospitals"],
        "categories": list(p["opd_categories"].keys()),
        "status": p["policy_holder"]["renewal_status"],
    }


@app.get("/members")
async def list_members():
    pe = PolicyEngine()
    return {"members": pe.policy["members"]}


@app.post("/claims/submit", response_model=ClaimDecision)
async def submit_claim(claim: ClaimSubmission):
    """
    Submit a structured claim for processing.
    Accepts pre-structured JSON with document content (for API/test usage).
    """
    pipeline = ClaimsPipeline()
    decision = pipeline.process(claim)
    decision_store[decision.claim_id] = decision
    return decision


@app.post("/claims/submit-with-files", response_model=ClaimDecision)
async def submit_claim_with_files(
    member_id: str = Form(...),
    policy_id: str = Form(...),
    claim_category: str = Form(...),
    treatment_date: str = Form(...),
    claimed_amount: float = Form(...),
    hospital_name: Optional[str] = Form(None),
    ytd_claims_amount: Optional[float] = Form(0.0),
    claims_history_json: Optional[str] = Form(None),
    document_types_json: Optional[str] = Form(None),
    documents: List[UploadFile] = File(...),
):
    """
    Submit a claim with real uploaded documents (images/PDFs).

    - `documents`: multiple UploadFile fields
    - `document_types_json` (optional): JSON list aligned with `documents` order (e.g. ["PRESCRIPTION","HOSPITAL_BILL"])
    - `claims_history_json` (optional): JSON list for fraud checks
    """
    # Parse optional JSON inputs
    claims_history = []
    if claims_history_json:
        try:
            claims_history = json.loads(claims_history_json)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid claims_history_json (must be valid JSON).")

    declared_types: Optional[List[str]] = None
    if document_types_json:
        try:
            declared_types = json.loads(document_types_json)
            if not isinstance(declared_types, list):
                raise ValueError("document_types_json must be a JSON list")
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid document_types_json (must be JSON list).")

    # Persist uploads to disk for ExtractionAgent vision mode
    claim_id = f"CLM-{uuid.uuid4().hex[:8].upper()}"
    upload_root = Path(os.path.dirname(__file__)) / "uploads" / claim_id
    upload_root.mkdir(parents=True, exist_ok=True)

    uploaded_files: Dict[str, str] = {}
    doc_submissions: List[DocumentSubmission] = []

    for idx, f in enumerate(documents):
        file_id = f"UPL-{idx+1:03d}"
        safe_name = (f.filename or f"{file_id}").replace("/", "_")
        target_path = upload_root / safe_name

        with open(target_path, "wb") as out:
            shutil.copyfileobj(f.file, out)

        uploaded_files[file_id] = str(target_path)

        actual_type = None
        if declared_types and idx < len(declared_types):
            actual_type = declared_types[idx]

        doc_submissions.append(DocumentSubmission(
            file_id=file_id,
            file_name=f.filename,
            actual_type=actual_type,
            content=None,
        ))

    from datetime import date
    try:
        td = date.fromisoformat(treatment_date)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid treatment_date (expected YYYY-MM-DD).")

    try:
        cat = ClaimCategory(claim_category)
    except Exception:
        raise HTTPException(status_code=400, detail=f"Invalid claim_category: {claim_category}")

    claim = ClaimSubmission(
        claim_id=claim_id,
        member_id=member_id,
        policy_id=policy_id,
        claim_category=cat,
        treatment_date=td,
        claimed_amount=float(claimed_amount),
        hospital_name=hospital_name,
        ytd_claims_amount=float(ytd_claims_amount or 0.0),
        claims_history=claims_history,
        documents=doc_submissions,
    )

    pipeline = ClaimsPipeline()
    decision = pipeline.process(claim, uploaded_files=uploaded_files)
    decision_store[decision.claim_id] = decision
    return decision


@app.get("/claims/{claim_id}", response_model=ClaimDecision)
async def get_claim(claim_id: str):
    if claim_id not in decision_store:
        raise HTTPException(status_code=404, detail=f"Claim '{claim_id}' not found.")
    return decision_store[claim_id]


@app.get("/claims")
async def list_claims():
    return {
        "count": len(decision_store),
        "claims": [
            {
                "claim_id": d.claim_id,
                "member_id": d.member_id,
                "decision": d.decision,
                "approved_amount": d.approved_amount,
                "confidence_score": d.confidence_score,
                "decided_at": d.decided_at,
            }
            for d in decision_store.values()
        ]
    }


@app.post("/claims/test/run-all", response_model=List[Dict])
async def run_all_test_cases():
    """Run all 12 test cases and return summary."""
    results = []
    pipeline = ClaimsPipeline()

    for tc in TEST_CASES_DATA["test_cases"]:
        claim = _parse_test_case(tc)
        decision = pipeline.process(claim)
        decision_store[decision.claim_id] = decision

        expected = tc.get("expected", {})
        expected_decision = expected.get("decision")
        matched = (
            expected_decision is None or
            decision.decision.value == expected_decision
        )

        results.append({
            "case_id": tc["case_id"],
            "case_name": tc["case_name"],
            "expected_decision": expected_decision,
            "actual_decision": decision.decision.value,
            "matched": matched,
            "approved_amount": decision.approved_amount,
            "confidence_score": decision.confidence_score,
            "rejection_reasons": decision.rejection_reasons,
            "approval_notes": decision.approval_notes,
            "fraud_signals": decision.fraud_signals,
            "component_failures": decision.component_failures,
            "processing_time_ms": decision.processing_time_ms,
        })

    return results


@app.post("/claims/test/{case_id}", response_model=ClaimDecision)
async def run_test_case(case_id: str):
    """
    Run a specific test case by ID (TC001 – TC012).
    Returns the full ClaimDecision with trace.
    """
    tc_map = {tc["case_id"]: tc for tc in TEST_CASES_DATA["test_cases"]}
    if case_id not in tc_map:
        raise HTTPException(status_code=404, detail=f"Test case '{case_id}' not found.")

    tc = tc_map[case_id]
    claim = _parse_test_case(tc)
    pipeline = ClaimsPipeline()
    decision = pipeline.process(claim)
    decision_store[decision.claim_id] = decision
    return decision
