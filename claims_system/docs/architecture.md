# Architecture Document
## Plum Health Insurance Claims Processing System

---

## 1. System Overview

This system automates OPD health insurance claims processing for Plum's Group Health Insurance platform. It uses a **multi-agent AI pipeline** to take a raw claim submission from receipt to decision — with full explainability, graceful failure handling, and zero reliance on hardcoded policy logic.

---

## 2. Component Map

```
ClaimSubmission (API / UI)
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│                    ClaimsPipeline Orchestrator                │
│                                                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐ │
│  │ DocumentVerifier│→│ExtractionAgent│→│FraudDetector │→│DecisionAgent │ │
│  │   Agent      │  │              │  │              │  │              │ │
│  │  (Agent 1)   │  │  (Agent 2)   │  │  (Agent 3)   │  │  (Agent 4)   │ │
│  └──────────────┘  └──────────────┘  └──────────────┘  └───────────────┘ │
│         │                │                  │                 │           │
│   Early exit         ExtractedInfo    FraudResult        ClaimDecision   │
│   on doc issues      (structured)     (score+flags)      (full trace)    │
└───────────────────────────────────────────────────────────────────────────┘
        │
        ▼
  ClaimDecision
  (decision + approved_amount + confidence + full_agent_traces)
        │
        ▼
  FastAPI Response / Streamlit UI
```

---

## 3. Agent Design

### Agent 1: DocumentVerifierAgent
**Single responsibility:** Detect document problems BEFORE any LLM calls or policy evaluation.

Checks performed, in order:
1. **Document type classification** — Uses explicit `actual_type` (test mode), filename heuristics, or content heuristics to classify each uploaded document.
2. **Required documents check** — Verifies that all required document types for the claim category are present (per `policy_terms.json → document_requirements`).
3. **Unreadable document detection** — Flags documents with `quality=UNREADABLE` and requests re-upload.
4. **Cross-patient name mismatch** — If patient names extracted from different documents don't match, the claim is stopped with the specific names found on each document.

**Output:** `DocumentVerificationResult(passed, issues[], missing_required[], unreadable_documents[], cross_patient_mismatch)`

**Early exit:** If `passed=False`, the orchestrator immediately returns a `DOCUMENT_ISSUE` decision with specific, actionable messages. No further agents run.

---

### Agent 2: ExtractionAgent
**Single responsibility:** Extract structured information from claim documents.

Two modes:
- **Test mode (structured content):** Uses pre-populated `DocumentContent` directly. No LLM call needed.
- **Real upload mode:** Calls `claude-sonnet-4-20250514` with vision for OCR and structured extraction. System prompt instructs the model to expand abbreviations, handle handwriting, flag obscured fields, and return JSON only.

Consolidation logic:
- Merges extractions from multiple documents into one `ExtractedInfo`
- First non-null value wins for scalar fields (patient_name, diagnosis, etc.)
- Line items and medicines are accumulated across all documents
- `confidence` = minimum confidence across all individual extractions

**Failure mode:** If the LLM call fails, returns partial extraction with `confidence=0.2` and a warning. The orchestrator records this as a component failure and continues.

---

### Agent 3: FraudDetectionAgent
**Single responsibility:** Score the claim for fraud signals and recommend manual review if warranted.

Checks:
1. **Same-day claim count** — Counts prior claims on the same treatment date (from `claims_history`). Triggers if count ≥ `same_day_claims_limit`.
2. **High-value threshold** — Claims above `high_value_claim_threshold` are automatically flagged.
3. **Document alteration** — Keyword scan of extraction warnings for signs of document modification.
4. **Monthly frequency** — Monthly claim count against `monthly_claims_limit`.

Each signal adds to a cumulative `fraud_score` (0–1). If `fraud_score ≥ fraud_score_manual_review_threshold` (0.80) OR specific high-risk patterns are present (same-day multi-provider), the claim is routed to `MANUAL_REVIEW`.

---

### Agent 4: DecisionAgent
**Single responsibility:** Apply all policy rules and produce the final claim decision.

Rule evaluation order (short-circuits on first failure):
1. **Member eligibility** — Member must exist in the policy roster; policy status must be ACTIVE.
2. **Waiting period** — Check `join_date + waiting_days ≤ treatment_date`. Uses diagnosis text to select the most specific waiting period (diabetes=90d, maternity=270d, etc.).
3. **General exclusions** — Keyword match against policy exclusions (bariatric, cosmetic, substance abuse, etc.).
4. **Pre-authorization** — MRI/CT/PET above ₹10,000 requires pre-auth. No pre-auth present → REJECTED.
5. **Line-item dental/vision check** — For DENTAL claims, each line item is checked against covered/excluded procedure lists. Items that match exclusion keywords are flagged, producing a PARTIAL decision.
6. **Per-claim/sub-limit check** — General categories use `per_claim_limit` (₹5,000). Dental/Vision use their category `sub_limit` (₹10,000 / ₹5,000). Checked against `effective_amount` after line-item exclusions.
7. **Fraud routing** — If `FraudDetectionResult.route_to_manual=True`, returns `MANUAL_REVIEW`.
8. **Financial calculation** — Network discount applied first, then co-pay. Formula: `((claimed_amount × (1 - discount%)) × (1 - copay%))`. Result capped at limit.

---

## 4. Orchestrator

The `ClaimsPipeline` orchestrator wraps each agent in an independent `try/except`. If any agent raises an exception:
- The failure is recorded in `component_failures[]`
- A safe default output is used (empty ExtractedInfo, zero FraudScore)
- Processing continues with remaining agents
- The final `ClaimDecision.confidence_score` is degraded to reflect incomplete processing
- `manual_review_recommended=True` is set

The orchestrator **never propagates exceptions to the caller**. A `ClaimDecision` is always returned.

---

## 5. Policy Engine

All policy rules are loaded from `data/policy_terms.json` at startup (cached via `@lru_cache`). The `PolicyEngine` class provides:

- `get_member(member_id)` — member lookup
- `check_waiting_period(member, diagnosis, treatment_date)` — returns (eligible, reason, eligible_from_date)
- `check_exclusions(diagnosis, treatment, category)` — returns (is_excluded, matched_exclusions[])
- `requires_pre_auth(category, amount, diagnosis, treatment)` — returns (required, reason)
- `check_dental_exclusions(line_items)` — per-item exclusion with covered-procedure override
- `calculate_approved_amount(amount, category, hospital, limit_override)` — network discount → copay → cap
- `is_network_hospital(name)` — fuzzy name match against network list

No policy logic is hardcoded in agents. All agents call PolicyEngine.

---

## 6. Explainability

Every agent produces an `AgentTrace`:
```json
{
  "agent_name": "DecisionAgent",
  "status": "SUCCESS",
  "duration_ms": 12.4,
  "checks": [
    {"check_name": "waiting_period", "passed": false, "detail": "90-day waiting period for Diabetes...", "value": "2024-10-15", "limit": "2024-11-30"}
  ],
  "output": {...},
  "warnings": [...]
}
```

The final `ClaimDecision.agent_traces[]` contains the full trace from all four agents. An operations team member can reconstruct the exact reason for any decision from the trace alone, without reading source code.

---

## 7. API Design

```
POST /claims/submit              — Submit structured claim
GET  /claims/{claim_id}          — Retrieve decision
GET  /claims                     — List all decisions
POST /claims/test/{case_id}      — Run a test case (TC001–TC012)
POST /claims/test/run-all        — Run all 12 test cases
GET  /policy/summary             — Policy overview
GET  /members                    — Member roster
```

---

## 8. Technology Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Framework | FastAPI | Async, type-safe, auto-docs. Pydantic models enforce contracts at runtime. |
| LLM | Claude claude-sonnet-4-20250514 (Anthropic) | Best-in-class vision/OCR for complex Indian medical documents. |
| Policy data | JSON loaded at startup | Keeps policy editable without code changes. Cached for performance. |
| Agent isolation | Each agent in a try/except with safe defaults | No single agent failure can crash the pipeline. |
| Frontend | Streamlit | Rapid prototyping with professional layout. React for production. |
| Storage | In-memory dict | Sufficient for demo; PostgreSQL for production. |

---

## 9. Trade-offs Made

1. **No database** — Using in-memory store. In production: PostgreSQL with async SQLAlchemy, partitioned by policy_id.
2. **Synchronous pipeline** — Agents run sequentially for simplicity and easy debugging. At 10x load: parallelize extraction + fraud detection (they don't depend on each other).
3. **Simplified dental logic** — Dental line-item check uses keyword matching, not a full procedure code (ICD/CDT) lookup. A real system would map procedure names to standard codes.
4. **No YTD per-category tracking** — We check annual OPD limit against ytd_claims_amount but don't track per-category annual usage. Production needs a claims ledger.

---

## 10. Scaling to 10x Load

| Concern | Current | At Scale |
|---------|---------|----------|
| Storage | In-memory | PostgreSQL + Redis cache |
| Pipeline | Sync sequential | Async parallel (Agents 2+3 in parallel) |
| LLM calls | Per-request | Rate-limit pool + retries + fallback to cheaper model |
| API | Single process | Kubernetes + load balancer + horizontal scaling |
| Observability | Trace in response | Structured logs → Datadog/OpenTelemetry |
