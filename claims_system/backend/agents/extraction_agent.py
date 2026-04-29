"""
Extraction Agent - OCR and structured data extraction from medical documents.
Supports both test mode (pre-structured content) and production mode (LLM vision).
"""
import os
import base64
import json
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple

import anthropic
from openai import OpenAI

from models import (
    ClaimSubmission, ExtractedInfo, AgentTrace, AgentStatus, CheckResult,
    DocumentSubmission
)

OPENAI_VISION_MODEL_DEFAULT = "gpt-4o-mini"

EXTRACTION_SYSTEM_PROMPT = """You are a medical document extraction assistant. Extract structured data from medical documents and return it as JSON.

Extract all relevant information and format it exactly as follows:

{
  "patient_name": "string",
  "doctor_name": "string", 
  "doctor_registration": "string",
  "diagnosis": "string",
  "treatment": "string",
  "document_date": "YYYY-MM-DD",
  "hospital_name": "string",
  "total_amount": number,
  "line_items": [{"description": "string", "amount": number}],
  "medicines": ["string"],
  "document_type": "string",
  "confidence": 0.0-1.0,
  "extraction_warnings": ["string"]
}

Guidelines:
- Handle illegible or unclear text by lowering the confidence score
- If text is partially readable, extract what you can and note issues in extraction_warnings
- For line_items, extract individual charges/services with their amounts
- For medicines, list all prescribed medications
- Set confidence between 0.0 (completely unreadable) and 1.0 (perfect extraction)
- Return only valid JSON, no additional text or formatting"""

EXTRACTION_PROMPT = """Extract structured data from this medical document as JSON:

{
  "patient_name": "string",
  "doctor_name": "string", 
  "diagnosis": "string",
  "treatment": "string",
  "document_date": "YYYY-MM-DD",
  "hospital_name": "string",
  "total_amount": number,
  "line_items": [{"description": "string", "amount": number}],
  "medicines": ["string"],
  "confidence": 0.0-1.0,
  "extraction_warnings": ["string"]
}

Handle illegible text by lowering confidence. Return JSON only."""


class ExtractionAgent:
    """OCR and data extraction from medical documents using LLM vision."""

    def __init__(self, simulate_failure: bool = False):
        self.simulate_failure = simulate_failure
        
        anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
        openai_key = os.getenv("OPENAI_API_KEY", "") 
        self.openai_vision_model = os.getenv("OPENAI_VISION_MODEL", OPENAI_VISION_MODEL_DEFAULT) or OPENAI_VISION_MODEL_DEFAULT

        self.client = anthropic.Anthropic(api_key=anthropic_key) if anthropic_key else None
        self.openai_client = OpenAI(api_key=openai_key) if openai_key else None

    def _strip_json_fences(self, text: str) -> str:
        text = (text or "").strip()
        if text.startswith("```"):
            parts = text.split("```")
            # common patterns: ```json ... ``` or ``` ... ```
            if len(parts) >= 2:
                inner = parts[1]
                if inner.startswith("json"):
                    inner = inner[4:]
                return inner.strip()
        return text

    def _extract_from_content(self, doc: DocumentSubmission) -> Dict[str, Any]:
        """
        Direct extraction from pre-structured content (used in test cases).
        """
        c = doc.content
        if not c:
            return {}
        return {
            "patient_name": c.patient_name,
            "doctor_name": c.doctor_name,
            "doctor_registration": c.doctor_registration,
            "diagnosis": c.diagnosis,
            "treatment": c.treatment,
            "document_date": c.date,
            "hospital_name": c.hospital_name,
            "total_amount": c.total,
            "line_items": c.line_items or [],
            "medicines": c.medicines or [],
            "document_type": doc.actual_type,
            "confidence": 0.95,
            "extraction_warnings": [],
        }

    def _extract_from_image(self, file_path: str) -> Dict[str, Any]:
        """
        LLM-based extraction from an actual uploaded image/PDF.
        """
        # Prefer OpenAI when configured.
        if self.openai_client:
            try:
                with open(file_path, "rb") as f:
                    b64 = base64.standard_b64encode(f.read()).decode("utf-8")

                ext = file_path.split(".")[-1].lower()
                
                # OpenAI Vision API only supports image formats, not PDF
                if ext == "pdf":
                    # For PDF files, fall back to Anthropic or return simulated data
                    raise ValueError("PDF not supported by OpenAI Vision API")
                
                media_type_map = {
                    "jpg": "image/jpeg", "jpeg": "image/jpeg",
                    "png": "image/png"
                }
                media_type = media_type_map.get(ext, "image/jpeg")

                # Ask for strict JSON only. We keep the prompt you already tuned.
                resp = self.openai_client.chat.completions.create(
                    model=self.openai_vision_model,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:{media_type};base64,{b64}",
                                        "detail": "low"
                                    }
                                },
                                {"type": "text", "text": EXTRACTION_SYSTEM_PROMPT + "\n\nExtract all information from this medical document."},
                            ],
                        },
                    ],
                    temperature=0.1,
                    max_tokens=1500,
                )

                text = (resp.choices[0].message.content or "").strip()
                text = self._strip_json_fences(text)
                parsed = json.loads(text)
                if not isinstance(parsed, dict):
                    raise ValueError("OpenAI returned non-object JSON")
                return parsed
            except Exception as e:
                return {
                    "confidence": 0.2,
                    "extraction_warnings": [f"OpenAI extraction failed: {str(e)}"],
                }

        if not self.client:
            return {
                "confidence": 0.3,
                "extraction_warnings": [
                    "No LLM configured for uploads. Set OPENAI_API_KEY (OpenAI Vision), "
                    "or ANTHROPIC_API_KEY (Claude Vision)."
                ],
            }

        try:
            with open(file_path, "rb") as f:
                image_data = base64.standard_b64encode(f.read()).decode("utf-8")

            ext = file_path.split(".")[-1].lower()
            media_type_map = {
                "jpg": "image/jpeg", "jpeg": "image/jpeg",
                "png": "image/png", "pdf": "application/pdf",
            }
            media_type = media_type_map.get(ext, "image/jpeg")

            response = self.client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=1500,
                timeout=120.0,
                system=EXTRACTION_SYSTEM_PROMPT,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_data,
                            },
                        },
                        {"type": "text", "text": "Extract all information from this medical document."}
                    ],
                }],
            )

            text = response.content[0].text.strip()
            text = self._strip_json_fences(text)
            return json.loads(text)

        except Exception as e:
            return {
                "confidence": 0.2,
                "extraction_warnings": [f"LLM extraction failed: {str(e)}"],
            }

    def _consolidate(self, extractions: List[Dict[str, Any]]) -> ExtractedInfo:
        """
        Merge extractions from multiple documents into one ExtractedInfo.
        Priority: most complete value wins; lower confidence propagates down.
        """
        info = ExtractedInfo()
        min_confidence = 1.0
        all_warnings: List[str] = []
        all_line_items: List[Dict] = []
        all_medicines: List[str] = []
        all_doc_types: List[str] = []

        for ext in extractions:
            if not ext:
                continue

            # Take first non-null value for single fields
            if not info.patient_name and ext.get("patient_name"):
                info.patient_name = ext["patient_name"]
            if not info.doctor_name and ext.get("doctor_name"):
                info.doctor_name = ext["doctor_name"]
            if not info.doctor_registration and ext.get("doctor_registration"):
                info.doctor_registration = ext["doctor_registration"]
            if not info.diagnosis and ext.get("diagnosis"):
                info.diagnosis = ext["diagnosis"]
            if not info.treatment and ext.get("treatment"):
                info.treatment = ext["treatment"]
            if not info.hospital_name and ext.get("hospital_name"):
                info.hospital_name = ext["hospital_name"]
            if not info.treatment_date and ext.get("document_date"):
                info.treatment_date = ext["document_date"]

            # Take max total amount (hospital bill total is authoritative)
            if ext.get("total_amount"):
                if not info.total_amount or ext["total_amount"] > info.total_amount:
                    info.total_amount = ext["total_amount"]

            # Accumulate line items and medicines
            all_line_items.extend(ext.get("line_items", []))
            all_medicines.extend(ext.get("medicines", []))

            # Track doc types
            if ext.get("document_type"):
                all_doc_types.append(ext["document_type"])

            # Propagate confidence
            conf = ext.get("confidence", 1.0)
            min_confidence = min(min_confidence, conf)
            all_warnings.extend(ext.get("extraction_warnings", []))

        info.line_items = all_line_items
        info.medicines = list(set(all_medicines))
        info.document_types_found = list(set(all_doc_types))
        info.confidence = round(min_confidence, 2)
        info.extraction_warnings = list(set(all_warnings))
        return info

    def run(
        self,
        claim: ClaimSubmission,
        uploaded_files: Optional[Dict[str, str]] = None
    ) -> tuple[ExtractedInfo, AgentTrace]:
        started = datetime.utcnow()
        checks: List[CheckResult] = []
        warnings: List[str] = []
        extractions: List[Dict[str, Any]] = []

        if self.simulate_failure:
            # Simulate a component failure — partial extraction only
            warnings.append("SIMULATED FAILURE: ExtractionAgent encountered a timeout. Partial data only.")
            ended = datetime.utcnow()
            info = ExtractedInfo(
                confidence=0.4,
                extraction_warnings=["Component failure: extraction incomplete."],
            )
            # Still extract what we can from content
            for doc in claim.documents:
                if doc.content:
                    ext = self._extract_from_content(doc)
                    extractions.append(ext)
            if extractions:
                info = self._consolidate(extractions)
                info.confidence = min(info.confidence, 0.5)
                info.extraction_warnings.append("ExtractionAgent partially failed — confidence degraded.")

            trace = AgentTrace(
                agent_name="ExtractionAgent",
                status=AgentStatus.PARTIAL,
                started_at=started.isoformat(),
                completed_at=ended.isoformat(),
                duration_ms=(ended - started).total_seconds() * 1000,
                checks=checks,
                output={"partial": True, "confidence": info.confidence},
                warnings=warnings,
                error="Simulated component failure — extraction degraded.",
            )
            return info, trace

        # Normal extraction path
        for doc in claim.documents:
            ext: Dict[str, Any] = {}

            if doc.content:
                # Test-case mode: use pre-structured content
                ext = self._extract_from_content(doc)
                checks.append(CheckResult(
                    check_name=f"extract_{doc.file_id}",
                    passed=True,
                    detail=f"Extracted from pre-structured content for {doc.file_id}",
                    value=doc.actual_type,
                ))
            elif uploaded_files and doc.file_id in uploaded_files:
                # Real upload mode: use LLM vision
                file_path = uploaded_files[doc.file_id]
                ext = self._extract_from_image(file_path)
                success = ext.get("confidence", 0) > 0.3
                checks.append(CheckResult(
                    check_name=f"extract_{doc.file_id}",
                    passed=success,
                    detail=f"LLM extraction confidence: {ext.get('confidence', 0):.2f}",
                    value=ext.get("document_type"),
                ))
                if not success:
                    warnings.append(f"Low-confidence extraction for {doc.file_id}")
            else:
                # No content and no file — placeholder
                ext = {"confidence": 0.5, "extraction_warnings": ["No content or file available for extraction."]}
                warnings.append(f"No extractable content for {doc.file_id}")

            extractions.append(ext)

        info = self._consolidate(extractions)

        # Override total_amount with claimed_amount if not extractable
        if not info.total_amount:
            info.total_amount = claim.claimed_amount
            info.extraction_warnings.append("Total amount taken from claim submission (not extracted from document).")

        # If line_items empty, build from claim content
        if not info.line_items:
            for doc in claim.documents:
                if doc.content and doc.content.line_items:
                    info.line_items = doc.content.line_items
                    break

        ended = datetime.utcnow()
        trace = AgentTrace(
            agent_name="ExtractionAgent",
            status=AgentStatus.SUCCESS if not warnings else AgentStatus.PARTIAL,
            started_at=started.isoformat(),
            completed_at=ended.isoformat(),
            duration_ms=(ended - started).total_seconds() * 1000,
            checks=checks,
            output={
                "patient_name": info.patient_name,
                "diagnosis": info.diagnosis,
                "total_amount": info.total_amount,
                "confidence": info.confidence,
                "line_items_count": len(info.line_items),
                "warnings": info.extraction_warnings,
            },
            warnings=warnings,
        )

        return info, trace
