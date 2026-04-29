# Eval Report — Plum Claims AI
**Result: 12/12 test cases passed (100%)**
---
## ✅ TC001 — Wrong Document Uploaded
| Field | Value |
|-------|-------|
| Expected Decision | `STOP (doc issue)` |
| Actual Decision | `DOCUMENT_ISSUE` |
| Decision Matched | ✅ Yes |
| Confidence | 100% |
| Processing Time | 0ms |

**Rejection Reasons:**
- You uploaded 2 prescriptions, but a Hospital / Clinic Bill is required for a CONSULTATION claim. Please upload your clinic/hospital bill that shows the consultation charges.

**Agent Trace Summary:**
- **DocumentVerifierAgent**: `FAILED`
  - ❌ `required_documents_present`: Required: ['PRESCRIPTION', 'HOSPITAL_BILL']. Found: ['PRESCRIPTION', 'PRESCRIPTI
  - ✅ `cross_patient_name_validation`: All documents belong to the same patient.

---

## ✅ TC002 — Unreadable Document
| Field | Value |
|-------|-------|
| Expected Decision | `STOP (doc issue)` |
| Actual Decision | `DOCUMENT_ISSUE` |
| Decision Matched | ✅ Yes |
| Confidence | 100% |
| Processing Time | 0ms |

**Rejection Reasons:**
- The document 'blurry_bill.jpg' could not be read — the image is too blurry or low quality. Please re-upload a clear, well-lit photo or scan of this document.
- Missing required document: Pharmacy Bill. A Pharmacy Bill is required for PHARMACY claims. Please upload this document to proceed.

**Agent Trace Summary:**
- **DocumentVerifierAgent**: `FAILED`
  - ❌ `required_documents_present`: Required: ['PRESCRIPTION', 'PHARMACY_BILL']. Found: ['PRESCRIPTION']. Missing: [
  - ✅ `cross_patient_name_validation`: All documents belong to the same patient.

---

## ✅ TC003 — Documents Belong to Different Patients
| Field | Value |
|-------|-------|
| Expected Decision | `STOP (doc issue)` |
| Actual Decision | `DOCUMENT_ISSUE` |
| Decision Matched | ✅ Yes |
| Confidence | 100% |
| Processing Time | 0ms |

**Rejection Reasons:**
- Documents appear to belong to different patients: 'Rajesh Kumar' on Doctor's Prescription (prescription_rajesh.jpg) and 'Arjun Mehta' on Hospital / Clinic Bill (bill_arjun.jpg). All documents in a claim must belong to the same patient.

**Agent Trace Summary:**
- **DocumentVerifierAgent**: `FAILED`
  - ✅ `required_documents_present`: Required: ['PRESCRIPTION', 'HOSPITAL_BILL']. Found: ['PRESCRIPTION', 'HOSPITAL_B
  - ❌ `cross_patient_name_validation`: Documents appear to belong to different patients: 'Rajesh Kumar' on Doctor's Pre

---

## ✅ TC004 — Clean Consultation — Full Approval
| Field | Value |
|-------|-------|
| Expected Decision | `APPROVED` |
| Actual Decision | `APPROVED` |
| Decision Matched | ✅ Yes |
| Expected Amount | ₹1,350 |
| Actual Amount | ₹1,350 |
| Confidence | 95% |
| Processing Time | 0ms |

**Approval Notes:**
- Co-pay of 10% applied: ₹150.00 deducted → Final approved: ₹1,350.00.

**Agent Trace Summary:**
- **DocumentVerifierAgent**: `SUCCESS`
  - ✅ `required_documents_present`: Required: ['PRESCRIPTION', 'HOSPITAL_BILL']. Found: ['PRESCRIPTION', 'HOSPITAL_B
  - ✅ `cross_patient_name_validation`: All documents belong to the same patient.
- **ExtractionAgent**: `SUCCESS`
  - ✅ `extract_F007`: Extracted from pre-structured content for F007
  - ✅ `extract_F008`: Extracted from pre-structured content for F008
- **FraudDetectionAgent**: `SUCCESS`
  - ✅ `same_day_claims`: No claims history provided — skipped same-day check.
  - ✅ `high_value_threshold`: Claim amount ₹1,500 below high-value threshold ₹25,000.
  - ✅ `document_alteration`: No document alteration detected.
  - ✅ `monthly_frequency`: No claims history — skipped monthly frequency check.
- **DecisionAgent**: `SUCCESS`
  - ✅ `member_eligibility`: Member is eligible.
  - ✅ `policy_exclusions`: No policy exclusions triggered.
  - ✅ `waiting_period`: Waiting period satisfied.
  - ✅ `pre_authorization`: Pre-authorization not required for this claim.
  - ✅ `per_claim_limit`: Claimed amount ₹1,500 is within per-claim limit of ₹5,000.
  - ✅ `fraud_screening`: Fraud score: 0.00. Auto-processing allowed.
  - ✅ `financial_calculation`: Claimed: ₹1,500.00 | Network discount: ₹0.00 | Co-pay: ₹150.00 | Approved: ₹1,35

---

## ✅ TC005 — Waiting Period — Diabetes
| Field | Value |
|-------|-------|
| Expected Decision | `REJECTED` |
| Actual Decision | `REJECTED` |
| Decision Matched | ✅ Yes |
| Confidence | 95% |
| Processing Time | 0ms |

**Rejection Reasons:**
- WAITING_PERIOD: Specific waiting period for Diabetes is 90 days. Member joined on 2024-09-01. Eligible for Diabetes claims from 2024-11-30.

**Agent Trace Summary:**
- **DocumentVerifierAgent**: `SUCCESS`
  - ✅ `required_documents_present`: Required: ['PRESCRIPTION', 'HOSPITAL_BILL']. Found: ['PRESCRIPTION', 'HOSPITAL_B
  - ✅ `cross_patient_name_validation`: All documents belong to the same patient.
- **ExtractionAgent**: `SUCCESS`
  - ✅ `extract_F009`: Extracted from pre-structured content for F009
  - ✅ `extract_F010`: Extracted from pre-structured content for F010
- **FraudDetectionAgent**: `SUCCESS`
  - ✅ `same_day_claims`: No claims history provided — skipped same-day check.
  - ✅ `high_value_threshold`: Claim amount ₹3,000 below high-value threshold ₹25,000.
  - ✅ `document_alteration`: No document alteration detected.
  - ✅ `monthly_frequency`: No claims history — skipped monthly frequency check.
- **DecisionAgent**: `SUCCESS`
  - ✅ `member_eligibility`: Member is eligible.
  - ✅ `policy_exclusions`: No policy exclusions triggered.
  - ❌ `waiting_period`: Specific waiting period for Diabetes is 90 days. Member joined on 2024-09-01. El

---

## ✅ TC006 — Dental Partial Approval — Cosmetic Exclusion
| Field | Value |
|-------|-------|
| Expected Decision | `PARTIAL` |
| Actual Decision | `PARTIAL` |
| Decision Matched | ✅ Yes |
| Expected Amount | ₹8,000 |
| Actual Amount | ₹8,000 |
| Confidence | 95% |
| Processing Time | 0ms |

**Approval Notes:**
- Partial approval: ₹8,000 approved for covered dental procedures. ₹4,000 excluded (cosmetic/non-covered dental procedures).

**Agent Trace Summary:**
- **DocumentVerifierAgent**: `SUCCESS`
  - ✅ `required_documents_present`: Required: ['HOSPITAL_BILL']. Found: ['HOSPITAL_BILL']. Missing: [].
  - ✅ `cross_patient_name_validation`: All documents belong to the same patient.
- **ExtractionAgent**: `SUCCESS`
  - ✅ `extract_F011`: Extracted from pre-structured content for F011
- **FraudDetectionAgent**: `SUCCESS`
  - ✅ `same_day_claims`: No claims history provided — skipped same-day check.
  - ✅ `high_value_threshold`: Claim amount ₹12,000 below high-value threshold ₹25,000.
  - ✅ `document_alteration`: No document alteration detected.
  - ✅ `monthly_frequency`: No claims history — skipped monthly frequency check.
- **DecisionAgent**: `SUCCESS`
  - ✅ `member_eligibility`: Member is eligible.
  - ✅ `policy_exclusions`: No policy exclusions triggered.
  - ✅ `waiting_period`: Waiting period satisfied.
  - ✅ `pre_authorization`: Pre-authorization not required for this claim.
  - ✅ `dental_line_item_review`: Dental items: ₹8,000 covered, ₹4,000 excluded.
  - ✅ `per_claim_limit`: Effective approved amount ₹8,000 within DENTAL sub_limit of ₹10,000.
  - ✅ `fraud_screening`: Fraud score: 0.00. Auto-processing allowed.
  - ✅ `financial_calculation`: Claimed: ₹8,000.00 | Network discount: ₹0.00 | Co-pay: ₹0.00 | Approved: ₹8,000.

---

## ✅ TC007 — MRI Without Pre-Authorization
| Field | Value |
|-------|-------|
| Expected Decision | `REJECTED` |
| Actual Decision | `REJECTED` |
| Decision Matched | ✅ Yes |
| Confidence | 95% |
| Processing Time | 0ms |

**Rejection Reasons:**
- PRE_AUTH_REQUIRED: MRI requires pre-authorization when amount exceeds ₹10,000. Claimed amount is ₹15,000. Please obtain pre-authorization and resubmit the claim.

**Agent Trace Summary:**
- **DocumentVerifierAgent**: `SUCCESS`
  - ✅ `required_documents_present`: Required: ['PRESCRIPTION', 'LAB_REPORT', 'HOSPITAL_BILL']. Found: ['PRESCRIPTION
  - ✅ `cross_patient_name_validation`: All documents belong to the same patient.
- **ExtractionAgent**: `SUCCESS`
  - ✅ `extract_F012`: Extracted from pre-structured content for F012
  - ✅ `extract_F013`: Extracted from pre-structured content for F013
  - ✅ `extract_F014`: Extracted from pre-structured content for F014
- **FraudDetectionAgent**: `SUCCESS`
  - ✅ `same_day_claims`: No claims history provided — skipped same-day check.
  - ✅ `high_value_threshold`: Claim amount ₹15,000 below high-value threshold ₹25,000.
  - ✅ `document_alteration`: No document alteration detected.
  - ✅ `monthly_frequency`: No claims history — skipped monthly frequency check.
- **DecisionAgent**: `SUCCESS`
  - ✅ `member_eligibility`: Member is eligible.
  - ✅ `policy_exclusions`: No policy exclusions triggered.
  - ✅ `waiting_period`: Waiting period satisfied.
  - ❌ `pre_authorization`: MRI requires pre-authorization when amount exceeds ₹10,000. Claimed amount is ₹1

---

## ✅ TC008 — Per-Claim Limit Exceeded
| Field | Value |
|-------|-------|
| Expected Decision | `REJECTED` |
| Actual Decision | `REJECTED` |
| Decision Matched | ✅ Yes |
| Confidence | 95% |
| Processing Time | 0ms |

**Rejection Reasons:**
- PER_CLAIM_EXCEEDED: Claimed amount ₹7,500 exceeds the per-claim limit of ₹5,000.

**Agent Trace Summary:**
- **DocumentVerifierAgent**: `SUCCESS`
  - ✅ `required_documents_present`: Required: ['PRESCRIPTION', 'HOSPITAL_BILL']. Found: ['PRESCRIPTION', 'HOSPITAL_B
  - ✅ `cross_patient_name_validation`: All documents belong to the same patient.
- **ExtractionAgent**: `SUCCESS`
  - ✅ `extract_F015`: Extracted from pre-structured content for F015
  - ✅ `extract_F016`: Extracted from pre-structured content for F016
- **FraudDetectionAgent**: `SUCCESS`
  - ✅ `same_day_claims`: No claims history provided — skipped same-day check.
  - ✅ `high_value_threshold`: Claim amount ₹7,500 below high-value threshold ₹25,000.
  - ✅ `document_alteration`: No document alteration detected.
  - ✅ `monthly_frequency`: No claims history — skipped monthly frequency check.
- **DecisionAgent**: `SUCCESS`
  - ✅ `member_eligibility`: Member is eligible.
  - ✅ `policy_exclusions`: No policy exclusions triggered.
  - ✅ `waiting_period`: Waiting period satisfied.
  - ✅ `pre_authorization`: Pre-authorization not required for this claim.
  - ❌ `per_claim_limit`: Claimed amount ₹7,500 exceeds the per-claim limit of ₹5,000.

---

## ✅ TC009 — Fraud Signal — Multiple Same-Day Claims
| Field | Value |
|-------|-------|
| Expected Decision | `MANUAL_REVIEW` |
| Actual Decision | `MANUAL_REVIEW` |
| Decision Matched | ✅ Yes |
| Confidence | 60% |
| Processing Time | 0ms |

**Approval Notes:**
- Claim routed to manual review due to fraud signals: Unusual pattern: 3 other claims already submitted on 2024-10-30 (limit: 2). Providers: Wellness Center, City Clinic A, City Clinic B.

**Agent Trace Summary:**
- **DocumentVerifierAgent**: `SUCCESS`
  - ✅ `required_documents_present`: Required: ['PRESCRIPTION', 'HOSPITAL_BILL']. Found: ['PRESCRIPTION', 'HOSPITAL_B
  - ✅ `cross_patient_name_validation`: All documents belong to the same patient.
- **ExtractionAgent**: `SUCCESS`
  - ✅ `extract_F017`: Extracted from pre-structured content for F017
  - ✅ `extract_F018`: Extracted from pre-structured content for F018
- **FraudDetectionAgent**: `SUCCESS`
  - ❌ `same_day_claims`: Unusual pattern: 3 other claims already submitted on 2024-10-30 (limit: 2). Prov
  - ✅ `high_value_threshold`: Claim amount ₹4,800 below high-value threshold ₹25,000.
  - ✅ `document_alteration`: No document alteration detected.
  - ✅ `monthly_frequency`: Monthly claims (3) within limit (6).
- **DecisionAgent**: `SUCCESS`
  - ✅ `member_eligibility`: Member is eligible.
  - ✅ `policy_exclusions`: No policy exclusions triggered.
  - ✅ `waiting_period`: Waiting period satisfied.
  - ✅ `pre_authorization`: Pre-authorization not required for this claim.
  - ✅ `per_claim_limit`: Claimed amount ₹4,800 is within per-claim limit of ₹5,000.
  - ❌ `fraud_screening`: Fraud score: 0.45. Routing to MANUAL_REVIEW.

---

## ✅ TC010 — Network Hospital — Discount Applied
| Field | Value |
|-------|-------|
| Expected Decision | `APPROVED` |
| Actual Decision | `APPROVED` |
| Decision Matched | ✅ Yes |
| Expected Amount | ₹3,240 |
| Actual Amount | ₹3,240 |
| Confidence | 95% |
| Processing Time | 0ms |

**Approval Notes:**
- Network hospital discount of 20% applied: ₹900.00 deducted from ₹4,500.00 → ₹3,600.00.
- Co-pay of 10% applied: ₹360.00 deducted → Final approved: ₹3,240.00.

**Agent Trace Summary:**
- **DocumentVerifierAgent**: `SUCCESS`
  - ✅ `required_documents_present`: Required: ['PRESCRIPTION', 'HOSPITAL_BILL']. Found: ['PRESCRIPTION', 'HOSPITAL_B
  - ✅ `cross_patient_name_validation`: All documents belong to the same patient.
- **ExtractionAgent**: `SUCCESS`
  - ✅ `extract_F019`: Extracted from pre-structured content for F019
  - ✅ `extract_F020`: Extracted from pre-structured content for F020
- **FraudDetectionAgent**: `SUCCESS`
  - ✅ `same_day_claims`: No claims history provided — skipped same-day check.
  - ✅ `high_value_threshold`: Claim amount ₹4,500 below high-value threshold ₹25,000.
  - ✅ `document_alteration`: No document alteration detected.
  - ✅ `monthly_frequency`: No claims history — skipped monthly frequency check.
- **DecisionAgent**: `SUCCESS`
  - ✅ `member_eligibility`: Member is eligible.
  - ✅ `policy_exclusions`: No policy exclusions triggered.
  - ✅ `waiting_period`: Waiting period satisfied.
  - ✅ `pre_authorization`: Pre-authorization not required for this claim.
  - ✅ `per_claim_limit`: Claimed amount ₹4,500 is within per-claim limit of ₹5,000.
  - ✅ `fraud_screening`: Fraud score: 0.00. Auto-processing allowed.
  - ✅ `financial_calculation`: Claimed: ₹4,500.00 | Network discount: ₹900.00 | Co-pay: ₹360.00 | Approved: ₹3,

---

## ✅ TC011 — Component Failure — Graceful Degradation
| Field | Value |
|-------|-------|
| Expected Decision | `APPROVED` |
| Actual Decision | `APPROVED` |
| Decision Matched | ✅ Yes |
| Confidence | 50% |
| Processing Time | 0ms |

**Approval Notes:**
- ⚠ One or more pipeline components failed during processing. Manual verification is recommended before disbursement.

**Agent Trace Summary:**
- **DocumentVerifierAgent**: `SUCCESS`
  - ✅ `required_documents_present`: Required: ['PRESCRIPTION', 'HOSPITAL_BILL']. Found: ['PRESCRIPTION', 'HOSPITAL_B
  - ✅ `cross_patient_name_validation`: All documents belong to the same patient.
- **ExtractionAgent**: `PARTIAL`
- **FraudDetectionAgent**: `SUCCESS`
  - ✅ `same_day_claims`: No claims history provided — skipped same-day check.
  - ✅ `high_value_threshold`: Claim amount ₹4,000 below high-value threshold ₹25,000.
  - ✅ `document_alteration`: No document alteration detected.
  - ✅ `monthly_frequency`: No claims history — skipped monthly frequency check.
- **DecisionAgent**: `SUCCESS`
  - ✅ `member_eligibility`: Member is eligible.
  - ✅ `policy_exclusions`: No policy exclusions triggered.
  - ✅ `waiting_period`: Waiting period satisfied.
  - ✅ `pre_authorization`: Pre-authorization not required for this claim.
  - ✅ `per_claim_limit`: Claimed amount ₹4,000 is within per-claim limit of ₹5,000.
  - ✅ `fraud_screening`: Fraud score: 0.00. Auto-processing allowed.
  - ✅ `financial_calculation`: Claimed: ₹4,000.00 | Network discount: ₹0.00 | Co-pay: ₹0.00 | Approved: ₹4,000.

---

## ✅ TC012 — Excluded Treatment
| Field | Value |
|-------|-------|
| Expected Decision | `REJECTED` |
| Actual Decision | `REJECTED` |
| Decision Matched | ✅ Yes |
| Confidence | 95% |
| Processing Time | 0ms |

**Rejection Reasons:**
- EXCLUDED_CONDITION: Treatment 'Morbid Obesity — BMI 37' falls under excluded category: Obesity and weight loss programs. This is explicitly excluded by the policy and cannot be covered.

**Agent Trace Summary:**
- **DocumentVerifierAgent**: `SUCCESS`
  - ✅ `required_documents_present`: Required: ['PRESCRIPTION', 'HOSPITAL_BILL']. Found: ['PRESCRIPTION', 'HOSPITAL_B
  - ✅ `cross_patient_name_validation`: All documents belong to the same patient.
- **ExtractionAgent**: `SUCCESS`
  - ✅ `extract_F023`: Extracted from pre-structured content for F023
  - ✅ `extract_F024`: Extracted from pre-structured content for F024
- **FraudDetectionAgent**: `SUCCESS`
  - ✅ `same_day_claims`: No claims history provided — skipped same-day check.
  - ✅ `high_value_threshold`: Claim amount ₹8,000 below high-value threshold ₹25,000.
  - ✅ `document_alteration`: No document alteration detected.
  - ✅ `monthly_frequency`: No claims history — skipped monthly frequency check.
- **DecisionAgent**: `SUCCESS`
  - ✅ `member_eligibility`: Member is eligible.
  - ❌ `policy_exclusions`: Excluded conditions/treatments matched: ['Obesity and weight loss programs']

---

