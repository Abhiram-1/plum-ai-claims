# Plum Claims Processing System

This repository contains a small claims-processing backend and a lightweight UI to submit claims, run the assignment test cases, and inspect traces end-to-end.

The pipeline is policy-driven (see `backend/data/policy_terms.json`) and is built around four steps:
document verification, extraction, fraud checks, and a final decision.

## Quick start

### Backend (FastAPI)

```bash
cd backend
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload --port 8000
```

Open:
- UI: `http://127.0.0.1:8000/ui/`
- API docs: `http://127.0.0.1:8000/docs`
- Health: `http://127.0.0.1:8000/health`

### Submit New Claim (UI)

The first tab in the UI is **Submit Claim**. It posts to `POST /claims/submit-with-files` (see `backend/main.py`). You fill the form, add one or more files, assign each file a document type, then submit.

**Form fields**

| Field | Notes |
|-------|--------|
| Member ID | Example: `EMP001` (must exist in policy roster). |
| Policy ID | Example: `PLUM_GHI_2024`. |
| Claim category | Drives which document types the UI expects (see table below). |
| Treatment date | `YYYY-MM-DD`. |
| Claimed amount | Number in INR. |
| Hospital name | Optional; used for network discount checks (e.g. `Apollo Hospitals`). |
| Documents | JPG, PNG, or PDF. After adding files, pick a type for each row. |

**Document types the UI offers**

`PRESCRIPTION`, `HOSPITAL_BILL`, `LAB_REPORT`, `PHARMACY_BILL`, `DENTAL_REPORT`, `DIAGNOSTIC_REPORT`, `DISCHARGE_SUMMARY`.

**What the UI requires before submit** (aligned with `backend/data/policy_terms.json` and enforced in `frontend/app.js`)

| Category | Required uploads (by type) |
|----------|----------------------------|
| CONSULTATION | `PRESCRIPTION` + `HOSPITAL_BILL` |
| PHARMACY | `PRESCRIPTION` + `PHARMACY_BILL` |
| DENTAL | `HOSPITAL_BILL` |
| VISION | `PRESCRIPTION` + `HOSPITAL_BILL` |
| ALTERNATIVE_MEDICINE | `PRESCRIPTION` + `HOSPITAL_BILL` |
| DIAGNOSTIC | `PRESCRIPTION` + `LAB_REPORT` + `HOSPITAL_BILL` |

The UI blocks submit if required types are missing or if any file has no type selected. It allows up to five files; the backend still validates policy rules.

**Structured JSON (no files)**

For API-only or scripted tests, use `POST /claims/submit` with a JSON body that matches the `ClaimSubmission` model in `backend/models.py` (includes optional embedded `DocumentContent` per document).

**LLM and file format**

Vision extraction for uploads uses `OPENAI_API_KEY` first (images only in that path); `ANTHROPIC_API_KEY` supports PDF as well in the extraction agent. Without keys, the pipeline still returns a decision but extraction is degraded.

### Run the 12 assignment scenarios

From the UI:
- Go to `http://127.0.0.1:8000/ui/` → Test Suite → Run Selected Case (TC001–TC012) or Run All 12 Cases.

From the API:

```bash
curl -s -X POST http://127.0.0.1:8000/claims/test/run-all | python -m json.tool
curl -s -X POST http://127.0.0.1:8000/claims/test/TC010 | python -m json.tool
```

From the CLI eval runner:

```bash
cd tests
python eval_runner.py --md --json
```

From pytest:

```bash
pytest tests/test_pipeline.py -v
```

## Real document uploads (optional)

The Test Suite does not require any LLM keys. Those cases use structured test inputs.

If you want to use the Submit Claim page with real PDFs/images and get OCR/vision extraction, set one of:

```bash
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
OPENAI_VISION_MODEL=gpt-4o-mini
```

Do not commit `.env`. If you want a template, create a local `.env` with the variables above.

## Project structure

```
backend/
  main.py                 FastAPI app (API + UI mount at /ui)
  agents/                 verifier, extraction, fraud, decision
  pipeline/orchestrator.py
  policy_engine.py        reads backend/data/policy_terms.json
  data/policy_terms.json
frontend/
  index.html
  app.js
  styles.css
tests/
  test_cases.json         12 assignment cases
  eval_runner.py
  test_pipeline.py
docs/
  architecture.md
  component_contracts.md
```

## Notes for reviewers

- The UI is served by the backend at `/ui/` if `frontend/` exists.
- The upload endpoint is `POST /claims/submit-with-files`. It accepts PDF/JPG/PNG.
- When LLM keys are not set, uploads degrade gracefully with warnings and lower confidence.





<img width="1210" height="596" alt="Screenshot 2026-04-29 at 10 48 02 AM" src="https://github.com/user-attachments/assets/65340314-bbfd-4fad-9749-12eba62f8550" />
<img width="1210" height="596" alt="Screenshot 2026-04-29 at 10 48 35 AM" src="https://github.com/user-attachments/assets/fb1f2595-843e-4925-901f-98f6e33ab7eb" />
<img width="1210" height="596" alt="Screenshot 2026-04-29 at 10 46 29 AM" src="https://github.com/user-attachments/assets/028e58fb-0d9c-4325-9467-fe43662dc290" />
