# Component Contracts
## Plum Health Insurance Claims Processing System

Each contract below is precise enough for another engineer to reimplement the component without reading its code.

---

## 1. ClaimsPipeline (Orchestrator)

**File:** `backend/pipeline/orchestrator.py`

### Input
```python
claim: ClaimSubmission   # Full claim submission object
uploaded_files: Optional[Dict[str, str]]  # file_id → local file path (for real uploads)
```

### Output
```python
ClaimDecision  # Always returned, never raises
```

### Guarantees
- **Never raises** — all exceptions are caught; failures are reflected in `component_failures[]` and reduced `confidence_score`
- Agents run in order: DocumentVerifier → Extraction → Fraud → Decision
- If DocumentVerifier reports `passed=False`, returns `DOCUMENT_ISSUE` immediately; remaining agents do not run
- If any agent fails, processing continues with safe defaults
- `agent_traces[]` in the output contains execution records from every agent that ran

---

## 2. DocumentVerifierAgent

**File:** `backend/agents/document_verifier.py`

### Input
```python
claim: ClaimSubmission   # Needs: claim_category, documents[]
```

### Output
```python
Tuple[DocumentVerificationResult, AgentTrace]

DocumentVerificationResult:
  passed: bool                  # True only if ALL checks pass
  issues: List[Dict]            # Each: {type, message, action_required, file_id?}
  document_types_found: List[str]
  missing_required: List[str]
  unreadable_documents: List[str]  # file_ids
  cross_patient_mismatch: bool
  mismatch_detail: Optional[str]
```

### Error types in `issues[].type`
| Type | Meaning |
|------|---------|
| `WRONG_DOCUMENT_TYPE` | Document type uploaded doesn't match what's required |
| `MISSING_REQUIRED_DOCUMENT` | A required document type is absent |
| `UNREADABLE_DOCUMENT` | Document quality=UNREADABLE; re-upload needed |
| `CROSS_PATIENT_MISMATCH` | Patient names differ across documents |

### Raises
Never — all failures surfaced in `issues[]`

---

## 3. ExtractionAgent

**File:** `backend/agents/extraction_agent.py`

### Input
```python
claim: ClaimSubmission             # For document list and content
uploaded_files: Optional[Dict[str, str]]  # file_id → path for LLM vision
simulate_failure: bool = False     # For TC011 testing
```

### Output
```python
Tuple[ExtractedInfo, AgentTrace]

ExtractedInfo:
  patient_name: Optional[str]
  doctor_name: Optional[str]
  doctor_registration: Optional[str]     # Format: STATE/NUMBER/YEAR
  diagnosis: Optional[str]              # Expanded from abbreviations
  treatment: Optional[str]
  treatment_date: Optional[str]         # ISO format
  hospital_name: Optional[str]
  total_amount: Optional[float]
  line_items: List[{description: str, amount: float}]
  medicines: List[str]
  document_types_found: List[str]
  confidence: float                     # 0.0–1.0; min across all docs
  extraction_warnings: List[str]
```

### Confidence rules
- `0.9+` — clean structured content or high-quality LLM extraction
- `0.5–0.89` — partial extraction (some fields missing or low quality)
- `< 0.5` — extraction failed or component simulated failure

### Raises
Never — failures reduce confidence and add to `extraction_warnings`

---

## 4. FraudDetectionAgent

**File:** `backend/agents/fraud_agent.py`

### Input
```python
claim: ClaimSubmission     # Needs: claimed_amount, treatment_date, claims_history
extracted_info: ExtractedInfo   # Needs: extraction_warnings
```

### Output
```python
Tuple[FraudDetectionResult, AgentTrace]

FraudDetectionResult:
  fraud_score: float           # 0.0–1.0
  signals: List[str]           # Human-readable fraud signal descriptions
  route_to_manual: bool        # True if score ≥ threshold OR hard pattern detected
  detail: str                  # Summary message
```

### Scoring table
| Signal | Score Added |
|--------|-------------|
| Same-day claim count ≥ limit | +0.45 |
| Amount ≥ high_value_threshold | +0.25 |
| Document alteration detected | +0.20 |
| Monthly frequency ≥ limit | +0.20 |
| Max score (clamped) | 1.0 |

### Route-to-manual override
`route_to_manual = True` if:
- `fraud_score ≥ 0.80` (configurable), OR
- Same-day multi-provider pattern detected (regardless of score)

### Raises
Never

---

## 5. DecisionAgent

**File:** `backend/agents/decision_agent.py`

### Input
```python
claim: ClaimSubmission
extracted_info: ExtractedInfo
fraud_result: FraudDetectionResult
component_failures: List[str]        # From orchestrator; degrades confidence
```

### Output
```python
Tuple[ClaimDecision, AgentTrace]
```

### Decision values
| Value | Condition |
|-------|-----------|
| `APPROVED` | All checks pass; full approved amount calculated |
| `PARTIAL` | Some line items excluded (dental); approved amount < claimed |
| `REJECTED` | Any hard policy rule fails |
| `MANUAL_REVIEW` | Fraud signals triggered; or uncaught exception in agent |
| `DOCUMENT_ISSUE` | Set by orchestrator, not this agent |

### Rule evaluation order (short-circuit on first failure)
```
1. Member eligibility
2. Waiting period (most specific applicable period)
3. General exclusions (diagnosis + treatment keyword scan)
4. Pre-authorization (MRI/CT/PET above threshold)
5a. Line-item dental exclusions → sets effective_amount
5b. Per-claim / category sub-limit (on effective_amount)
6. Fraud routing (from FraudDetectionResult)
7. Financial calculation (network discount → copay → cap)
```

### Financial calculation
```
effective_amount = claimed_amount  (or sum of covered dental items)
if network_hospital:
    amount = effective_amount × (1 - network_discount_pct/100)
copay = amount × (copay_pct/100)
approved = amount - copay
if approved > limit:
    approved = limit
```

### `approved_amount` rules
- `APPROVED`: full calculation above
- `PARTIAL`: sum of covered line items after calculation
- `REJECTED`, `MANUAL_REVIEW`: `None`

### Raises
Never — exceptions caught, stored in `component_failures`, decision set to `MANUAL_REVIEW`

---

## 6. PolicyEngine

**File:** `backend/policy_engine.py`

### `check_waiting_period(member, diagnosis, treatment_date) → (bool, str, date)`
Returns `(eligible, reason_string, eligible_from_date)`.
- Selects waiting period from most-specific matching condition keyword
- Returns the date from which the member is eligible

### `check_exclusions(diagnosis, treatment, category) → (bool, List[str])`
Returns `(is_excluded, matched_exclusion_labels[])`.
- Scans combined `diagnosis + treatment` string against keyword lists
- Returns all matched exclusion labels

### `check_dental_exclusions(line_items) → List[Dict]`
Each returned item has original fields plus `excluded: bool` and `excluded_reason: str`.
- Covered procedures take precedence over exclusion matches (prevents false positives)

### `calculate_approved_amount(amount, category, hospital, limit_override) → Dict`
Returns:
```python
{
  "approved_amount": float,
  "network_discount": float,
  "copay_deducted": float,
  "amount_after_discount": float,
  "copay_percent": float,
  "network_discount_percent": float,
  "capped_by_per_claim_limit": bool,
  "per_claim_limit": float,
}
```

---

## 7. Data Models

### ClaimSubmission (Input)
```python
claim_id: str                    # Auto-generated if not provided
member_id: str                   # Must match policy roster
policy_id: str                   # Must match loaded policy
claim_category: ClaimCategory    # CONSULTATION|DIAGNOSTIC|PHARMACY|DENTAL|VISION|ALTERNATIVE_MEDICINE
treatment_date: date
claimed_amount: float
hospital_name: Optional[str]     # Used for network discount check
ytd_claims_amount: float = 0
claims_history: List[Dict]       # For fraud detection
documents: List[DocumentSubmission]
simulate_component_failure: bool = False
```

### ClaimDecision (Output)
```python
claim_id: str
decision: DecisionType
approved_amount: Optional[float]
confidence_score: float          # 0.0–1.0
rejection_reasons: List[str]
approval_notes: List[str]
line_item_decisions: List[LineItemDecision]
network_discount_applied: Optional[float]
copay_deducted: Optional[float]
fraud_signals: List[str]
fraud_score: Optional[float]
component_failures: List[str]
manual_review_recommended: bool
agent_traces: List[AgentTrace]
processing_time_ms: float
decided_at: str                  # ISO datetime
```
