"""
Document Verifier - Early validation before processing.
Checks document types, quality, and patient name consistency.
"""
import os
import re
import base64
import json
from datetime import datetime
from typing import Optional, List, Dict, Any

from models import (
    ClaimSubmission, ClaimCategory, DocumentType,
    DocumentVerificationResult, DocumentSubmission, AgentTrace, AgentStatus, CheckResult
)
from policy_engine import PolicyEngine
from openai import OpenAI

# Document classification keywords
DOC_TYPE_KEYWORDS: Dict[str, List[str]] = {
    "PRESCRIPTION": [
        "prescription", "rx", "diagnosis", "medicines", "tab ", "cap ",
        "syrup", "inj ", "doctor", "registration", "mbbs", "md ", "ms ",
        "reg no", "reg. no", "dosage", "follow-up", "advised", "sos"
    ],
    "HOSPITAL_BILL": [
        "bill", "invoice", "receipt", "total amount", "subtotal", "consultation fee",
        "gst", "gstin", "payment", "cashier", "paid", "amount", "charges"
    ],
    "LAB_REPORT": [
        "lab report", "laboratory", "diagnostic report", "test result", "pathology",
        "sample", "haemoglobin", "cbc", "wbc", "platelet", "report date", "nabl",
        "normal range", "result", "reference range"
    ],
    "PHARMACY_BILL": [
        "pharmacy", "chemist", "drug", "medicine bill", "pharma", "drug lic",
        "batch", "expiry", "mrp", "strip", "pharmacist"
    ],
    "DENTAL_REPORT": [
        "dental", "tooth", "teeth", "periodontal", "root canal", "extraction",
        "scaling", "crown", "filling", "dental x-ray"
    ],
    "DIAGNOSTIC_REPORT": [
        "mri", "ct scan", "x-ray", "ultrasound", "sonography", "ecg",
        "echo", "radiology", "imaging", "scan report", "pet scan"
    ],
    "DISCHARGE_SUMMARY": [
        "discharge summary", "discharge note", "admitted", "discharged",
        "hospital stay", "inpatient", "ipd"
    ],
}

HUMAN_READABLE_TYPES = {
    "PRESCRIPTION": "Doctor's Prescription",
    "HOSPITAL_BILL": "Hospital / Clinic Bill",
    "LAB_REPORT": "Laboratory Report",
    "PHARMACY_BILL": "Pharmacy Bill",
    "DENTAL_REPORT": "Dental Report",
    "DIAGNOSTIC_REPORT": "Diagnostic / Imaging Report",
    "DISCHARGE_SUMMARY": "Discharge Summary",
}


def _classify_document(doc: DocumentSubmission) -> str:
    """
    Classify the document type.
    Priority:
    - Test cases (pre-structured content): explicit actual_type
    - Otherwise: file name heuristic > content heuristic

    For real uploads, `actual_type` is user-declared — don't trust it as truth.
    """
    # 1. Trust explicit actual_type only for test cases (where content is pre-populated)
    if doc.actual_type and doc.content is not None:
        return doc.actual_type.upper()

    # 2. File name heuristic
    if doc.file_name:
        fname = doc.file_name.lower()
        for dtype, keywords in DOC_TYPE_KEYWORDS.items():
            for kw in keywords:
                if kw in fname:
                    return dtype

    # 3. Content heuristic
    if doc.content:
        content_str = str(doc.content).lower()
        for dtype, keywords in DOC_TYPE_KEYWORDS.items():
            hits = sum(1 for kw in keywords if kw in content_str)
            if hits >= 2:
                return dtype

    return "UNKNOWN"


def _is_unreadable(doc: DocumentSubmission) -> bool:
    return (doc.quality or "").upper() == "UNREADABLE"


def _extract_patient_name(doc: DocumentSubmission) -> Optional[str]:
    """Extract patient name from document for cross-patient validation."""
    if doc.patient_name_on_doc:
        return doc.patient_name_on_doc
    if doc.content and doc.content.patient_name:
        return doc.content.patient_name
    return None


OPENAI_VISION_MODEL_DEFAULT = "gpt-4o-mini"

def _strip_json_fences(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        # common patterns: ```json ... ``` or ``` ... ```
        parts = t.split("```")
        if len(parts) >= 2:
            inner = parts[1].strip()
            if inner.lower().startswith("json"):
                inner = inner[4:].strip()
            return inner.strip()
    return t

def _extract_first_json_object(text: str) -> Optional[str]:
    """
    Best-effort: grab the first {...} block for json.loads().
    Handles models that prepend/append text around JSON.
    """
    t = _strip_json_fences(text)
    m = re.search(r"\{[\s\S]*\}", t)
    return m.group(0) if m else None


def _media_type_for_path(file_path: str) -> str:
    ext = (file_path.split(".")[-1] if file_path else "").lower()
    if ext in ("jpg", "jpeg"):
        return "image/jpeg"
    if ext == "png":
        return "image/png"
    # Default to jpeg for unknown image extensions
    return "image/jpeg"


def _vision_verify_and_classify(
    client: OpenAI,
    model: str,
    file_path: str,
    declared_type: Optional[str],
) -> Dict[str, Any]:
    """
    Cheap vision-side validation to catch obviously irrelevant uploads early.
    Returns JSON:
      {is_medical: bool, detected_type: str|null, confidence: float, reason: str, patient_name: str|null, document_date: str|null}
    """
    with open(file_path, "rb") as f:
        b64 = base64.standard_b64encode(f.read()).decode("utf-8")

    media_type = _media_type_for_path(file_path)
    allowed_types = list(DOC_TYPE_KEYWORDS.keys())

    prompt = (
        "You are validating uploaded documents for a health insurance claim. "
        "Decide whether the image is a medical document, and if yes, what type it is.\n\n"
        "Return ONLY valid JSON with keys: "
        '{"is_medical": true/false, "detected_type": string|null, "confidence": number, "reason": string, "patient_name": string|null, "document_date": string|null}.\n'
        "- If the image is a non-document photo (vehicles, people, scenery, selfies), a meme, or unrelated screenshot, set is_medical=false.\n"
        f"- detected_type must be one of: {allowed_types} (or null if not medical).\n"
        "- confidence must be between 0 and 1.\n"
        "- reason must be short and specific.\n"
        "- If is_medical=true, set patient_name and document_date if clearly visible; otherwise null.\n"
        "- document_date should be YYYY-MM-DD when possible; otherwise null.\n"
    )
    # Do not bias detection with user-declared type.

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{media_type};base64,{b64}", "detail": "low"},
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        temperature=0.0,
        max_tokens=300,
    )

    raw = (resp.choices[0].message.content or "").strip()
    try:
        candidate = _extract_first_json_object(raw) or raw
        return json.loads(candidate)
    except Exception:
        # Fail safe: treat as irrelevant so we stop early rather than approving junk.
        return {
            "is_medical": False,
            "detected_type": None,
            "confidence": 0.0,
            "reason": f"Verifier returned non-JSON output: {raw[:120]}",
            "patient_name": None,
            "document_date": None,
        }


class DocumentVerifierAgent:
    """
    Agent 1 in the pipeline.
    Performs early, fast checks before any LLM calls or policy evaluation.
    """

    def __init__(self):
        self.policy_engine = PolicyEngine()
        openai_key = os.getenv("OPENAI_API_KEY", "")
        self.openai_vision_model = os.getenv("OPENAI_VISION_MODEL", OPENAI_VISION_MODEL_DEFAULT) or OPENAI_VISION_MODEL_DEFAULT
        self.openai_client = OpenAI(api_key=openai_key) if openai_key else None

    def run(
        self,
        claim: ClaimSubmission,
        uploaded_files: Optional[Dict[str, str]] = None,
    ) -> tuple[DocumentVerificationResult, AgentTrace]:
        started = datetime.utcnow()
        checks: List[CheckResult] = []
        issues: List[Dict[str, str]] = []
        warnings: List[str] = []

        # ── Step 1: Classify all documents ────────────────────────────────
        classified: List[Dict[str, Any]] = []
        unreadable_docs: List[str] = []

        for doc in claim.documents:
            declared_type = (doc.actual_type or "").upper().strip() or None
            doc_type = _classify_document(doc)

            vision = None
            file_path = None
            if uploaded_files and doc.file_id in uploaded_files:
                file_path = uploaded_files[doc.file_id]

            # For real uploads: verify content with vision (if available)
            # This prevents "car.png marked as PRESCRIPTION" from passing.
            if self.openai_client and file_path and doc.content is None:
                try:
                    vision = _vision_verify_and_classify(
                        client=self.openai_client,
                        model=self.openai_vision_model,
                        file_path=file_path,
                        declared_type=declared_type,
                    )

                    if not vision.get("is_medical", False):
                        preview_bits = []
                        conf = vision.get("confidence")
                        if conf is not None:
                            try:
                                preview_bits.append(f"Detection confidence: {float(conf):.2f}")
                            except Exception:
                                pass
                        preview = f" ({', '.join(preview_bits)})" if preview_bits else ""
                        issues.append({
                            "type": "IRRELEVANT_DOCUMENT",
                            "file_id": doc.file_id,
                            "message": (
                                f"The uploaded file '{doc.file_name or doc.file_id}' does not look like a medical document. "
                                f"{(vision.get('reason') or '').strip()}{preview}"
                            ).strip(),
                            "action_required": "UPLOAD_MEDICAL_DOCUMENT",
                        })
                        doc_type = "UNKNOWN"
                    else:
                        detected = (vision.get("detected_type") or "").upper().strip()
                        doc_type = detected if detected in DOC_TYPE_KEYWORDS else "UNKNOWN"

                    # If user picked the wrong type in the UI, auto-correct it.
                    if declared_type and doc_type != "UNKNOWN" and declared_type != doc_type:
                        preview_bits = []
                        pn = (vision.get("patient_name") or "").strip() if vision else ""
                        dd = (vision.get("document_date") or "").strip() if vision else ""
                        if pn:
                            preview_bits.append(f"Patient: {pn}")
                        if dd:
                            preview_bits.append(f"Date: {dd}")
                        conf = vision.get("confidence") if vision else None
                        if conf is not None:
                            try:
                                preview_bits.append(f"Detection confidence: {float(conf):.2f}")
                            except Exception:
                                pass
                        preview = f" ({', '.join(preview_bits)})" if preview_bits else ""
                        warnings.append(
                            f"Auto-corrected document type for '{doc.file_name or doc.file_id}' "
                            f"from {declared_type} to {doc_type}.{preview}"
                        )
                        # Update the claim object so downstream agents use the detected type.
                        try:
                            doc.actual_type = doc_type
                        except Exception:
                            pass
                except Exception as e:
                    warnings.append(f"Vision verifier skipped for {doc.file_id}: {str(e)}")
            is_unreadable = _is_unreadable(doc)
            patient_name = _extract_patient_name(doc)

            classified.append({
                "file_id": doc.file_id,
                "file_name": doc.file_name,
                "classified_type": doc_type,
                "declared_type": declared_type,
                "is_unreadable": is_unreadable,
                "patient_name": patient_name,
                "vision": vision,
            })

            if is_unreadable:
                unreadable_docs.append(doc.file_id)
                issues.append({
                    "type": "UNREADABLE_DOCUMENT",
                    "file_id": doc.file_id,
                    "message": (
                        f"The document '{doc.file_name or doc.file_id}' could not be read — "
                        f"the image is too blurry or low quality. "
                        f"Please re-upload a clear, well-lit photo or scan of this document."
                    ),
                    "action_required": "RE_UPLOAD",
                })

        # ── Step 2: Check required document types ─────────────────────────
        doc_reqs = self.policy_engine.get_required_documents(claim.claim_category)
        required_types = doc_reqs.get("required", [])
        found_types = [d["classified_type"] for d in classified if not d["is_unreadable"]]

        missing_required: List[str] = []
        type_check_passed = True

        for req in required_types:
            if req not in found_types:
                missing_required.append(req)
                type_check_passed = False

        # Detect wrong document types (found types not in required/optional)
        optional_types = doc_reqs.get("optional", [])
        all_allowed = set(required_types + optional_types)

        wrong_type_issues: List[str] = []
        for d in classified:
            if not d["is_unreadable"] and d["classified_type"] not in all_allowed and d["classified_type"] != "UNKNOWN":
                wrong_type_issues.append(d["classified_type"])

        # Check for duplicate types when they shouldn't be duplicated
        from collections import Counter
        type_counts = Counter(d["classified_type"] for d in classified if not d["is_unreadable"])

        # For CONSULTATION: needs PRESCRIPTION + HOSPITAL_BILL (not 2 prescriptions)
        if claim.claim_category == ClaimCategory.CONSULTATION:
            if type_counts.get("PRESCRIPTION", 0) >= 2 and type_counts.get("HOSPITAL_BILL", 0) == 0:
                issues.append({
                    "type": "WRONG_DOCUMENT_TYPE",
                    "message": (
                        f"You uploaded {type_counts['PRESCRIPTION']} prescriptions, "
                        f"but a {HUMAN_READABLE_TYPES['HOSPITAL_BILL']} is required for a "
                        f"CONSULTATION claim. "
                        f"Please upload your clinic/hospital bill that shows the consultation charges."
                    ),
                    "action_required": "UPLOAD_HOSPITAL_BILL",
                })
                type_check_passed = False

        for missing in missing_required:
            already_reported = any(
                i.get("action_required") in (f"UPLOAD_{missing}", "UPLOAD_HOSPITAL_BILL")
                for i in issues
            )
            if not already_reported:
                issues.append({
                    "type": "MISSING_REQUIRED_DOCUMENT",
                    "missing_type": missing,
                    "message": (
                        f"Missing required document: {HUMAN_READABLE_TYPES.get(missing, missing)}. "
                        f"A {HUMAN_READABLE_TYPES.get(missing, missing)} is required for "
                        f"{claim.claim_category.value} claims. Please upload this document to proceed."
                    ),
                    "action_required": f"UPLOAD_{missing}",
                })

        checks.append(CheckResult(
            check_name="required_documents_present",
            passed=type_check_passed and not unreadable_docs,
            detail=f"Required: {required_types}. Found: {found_types}. Missing: {missing_required}.",
        ))

        # ── Step 3: Cross-patient name validation ─────────────────────────
        patient_names = {}
        for d in classified:
            if d["patient_name"] and not d["is_unreadable"]:
                patient_names[d["file_id"]] = {
                    "name": d["patient_name"],
                    "file_name": d["file_name"],
                    "doc_type": d["classified_type"],
                }

        cross_patient_mismatch = False
        mismatch_detail = None

        if len(patient_names) >= 2:
            names = [v["name"].strip().lower() for v in patient_names.values()]
            # Check if all names are the same
            if len(set(names)) > 1:
                cross_patient_mismatch = True
                name_details = [
                    f"'{v['name']}' on {HUMAN_READABLE_TYPES.get(v['doc_type'], v['doc_type'])} ({v['file_name'] or v['doc_type']})"
                    for v in patient_names.values()
                ]
                mismatch_detail = (
                    "Documents appear to belong to different patients: " +
                    " and ".join(name_details) +
                    ". All documents in a claim must belong to the same patient."
                )
                issues.append({
                    "type": "CROSS_PATIENT_MISMATCH",
                    "message": mismatch_detail,
                    "action_required": "UPLOAD_CORRECT_DOCUMENTS",
                })

        checks.append(CheckResult(
            check_name="cross_patient_name_validation",
            passed=not cross_patient_mismatch,
            detail=mismatch_detail or "All documents belong to the same patient.",
        ))

        # ── Assemble result ────────────────────────────────────────────────
        passed = (
            not issues and
            not unreadable_docs and
            not cross_patient_mismatch
        )

        result = DocumentVerificationResult(
            passed=passed,
            issues=issues,
            document_types_found=found_types,
            missing_required=missing_required,
            unreadable_documents=unreadable_docs,
            cross_patient_mismatch=cross_patient_mismatch,
            mismatch_detail=mismatch_detail,
        )

        ended = datetime.utcnow()
        trace = AgentTrace(
            agent_name="DocumentVerifierAgent",
            status=AgentStatus.SUCCESS if not issues else AgentStatus.FAILED,
            started_at=started.isoformat(),
            completed_at=ended.isoformat(),
            duration_ms=(ended - started).total_seconds() * 1000,
            checks=checks,
            output={
                "passed": passed,
                "issues_count": len(issues),
                "documents_classified": [
                    {"file_id": d["file_id"], "type": d["classified_type"], "declared_type": d.get("declared_type")}
                    for d in classified
                ],
            },
            warnings=warnings,
        )

        return result, trace
