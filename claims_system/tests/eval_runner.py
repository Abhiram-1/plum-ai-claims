"""
Eval Runner
===========
Runs all 12 test cases through the live pipeline and produces a full eval report.
Usage: python eval_runner.py [--json] [--md]
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import json
import argparse
from datetime import date

from models import ClaimSubmission, ClaimCategory, DocumentSubmission, DocumentContent
from pipeline.orchestrator import ClaimsPipeline


def load_test_cases():
    tc_path = os.path.join(os.path.dirname(__file__), "test_cases.json")
    with open(tc_path) as f:
        return json.load(f)


def parse_test_case(tc: dict) -> ClaimSubmission:
    inp = tc["input"]
    docs = []
    for d in inp.get("documents", []):
        cr = d.get("content")
        content = None
        if cr:
            content = DocumentContent(
                doctor_name=cr.get("doctor_name"),
                doctor_registration=cr.get("doctor_registration"),
                patient_name=cr.get("patient_name"),
                date=cr.get("date"),
                diagnosis=cr.get("diagnosis"),
                treatment=cr.get("treatment"),
                medicines=cr.get("medicines", []),
                hospital_name=cr.get("hospital_name"),
                line_items=cr.get("line_items", []),
                total=cr.get("total"),
            )
        docs.append(DocumentSubmission(
            file_id=d["file_id"],
            file_name=d.get("file_name"),
            actual_type=d.get("actual_type"),
            content=content,
            quality=d.get("quality", "GOOD"),
            patient_name_on_doc=d.get("patient_name_on_doc"),
        ))

    return ClaimSubmission(
        claim_id=f"EVAL-{tc['case_id']}",
        member_id=inp["member_id"],
        policy_id=inp["policy_id"],
        claim_category=ClaimCategory(inp["claim_category"]),
        treatment_date=date.fromisoformat(inp["treatment_date"]),
        claimed_amount=float(inp["claimed_amount"]),
        hospital_name=inp.get("hospital_name"),
        ytd_claims_amount=float(inp.get("ytd_claims_amount", 0)),
        claims_history=inp.get("claims_history", []),
        documents=docs,
        simulate_component_failure=inp.get("simulate_component_failure", False),
    )


def run_eval(output_md=False, output_json=False):
    data = load_test_cases()
    pipeline = ClaimsPipeline()
    results = []

    print(f"\n{'='*70}")
    print("  PLUM CLAIMS AI — EVALUATION REPORT")
    print(f"{'='*70}\n")

    for tc in data["test_cases"]:
        claim = parse_test_case(tc)
        decision = pipeline.process(claim)

        expected = tc.get("expected", {})
        expected_dec = expected.get("decision")
        expected_amt = expected.get("approved_amount")

        decision_matched = expected_dec is None or decision.decision.value == expected_dec
        amount_matched = expected_amt is None or decision.approved_amount == expected_amt

        result = {
            "case_id": tc["case_id"],
            "case_name": tc["case_name"],
            "expected_decision": expected_dec or "STOP (doc issue)",
            "actual_decision": decision.decision.value,
            "decision_matched": decision_matched,
            "expected_amount": expected_amt,
            "actual_amount": decision.approved_amount,
            "amount_matched": amount_matched,
            "confidence_score": decision.confidence_score,
            "rejection_reasons": decision.rejection_reasons,
            "approval_notes": decision.approval_notes,
            "fraud_signals": decision.fraud_signals,
            "component_failures": decision.component_failures,
            "processing_ms": decision.processing_time_ms,
            "agent_traces": [
                {
                    "agent": t.agent_name,
                    "status": t.status.value if hasattr(t.status, 'value') else t.status,
                    "checks": [
                        {
                            "name": c.check_name,
                            "passed": c.passed,
                            "detail": c.detail
                        }
                        for c in (t.checks or [])
                    ],
                    "warnings": t.warnings or [],
                }
                for t in (decision.agent_traces or [])
            ],
        }
        results.append(result)

        icon = "✅" if decision_matched else "❌"
        print(f"{icon} {tc['case_id']} | {tc['case_name'][:40]:<42}")
        print(f"   Expected: {expected_dec or 'STOP':<16} Got: {decision.decision.value:<16} Match: {'YES' if decision_matched else 'NO'}")
        if expected_amt:
            print(f"   Expected Amount: ₹{expected_amt:,} | Got: {'₹'+f'{decision.approved_amount:,}' if decision.approved_amount else 'None'} | {'OK' if amount_matched else 'MISMATCH'}")
        if decision.rejection_reasons:
            for r in decision.rejection_reasons[:1]:
                print(f"   Reason: {r[:70]}...")
        if decision.approval_notes:
            for n in decision.approval_notes[:1]:
                print(f"   Note: {n[:70]}...")
        if decision.component_failures:
            print(f"   ⚠ Component failure: {decision.component_failures[0][:60]}")
        print()

    passed = sum(1 for r in results if r["decision_matched"])
    total = len(results)

    print(f"{'='*70}")
    print(f"  FINAL SCORE: {passed}/{total} PASSED ({passed/total:.0%})")
    print(f"{'='*70}\n")

    if output_json:
        out_path = os.path.join(os.path.dirname(__file__), "eval_report.json")
        with open(out_path, "w") as f:
            json.dump(results, f, indent=2, default=str)
        print(f"JSON report saved to: {out_path}")

    if output_md:
        _write_md_report(results, passed, total)

    return results


def _write_md_report(results, passed, total):
    lines = [
        "# Eval Report — Plum Claims AI\n",
        f"**Result: {passed}/{total} test cases passed ({passed/total:.0%})**\n",
        "---\n",
    ]

    for r in results:
        match_icon = "✅" if r["decision_matched"] else "❌"
        lines.append(f"## {match_icon} {r['case_id']} — {r['case_name']}\n")
        lines.append(f"| Field | Value |\n|-------|-------|\n")
        lines.append(f"| Expected Decision | `{r['expected_decision']}` |\n")
        lines.append(f"| Actual Decision | `{r['actual_decision']}` |\n")
        lines.append(f"| Decision Matched | {'✅ Yes' if r['decision_matched'] else '❌ No'} |\n")
        if r['expected_amount']:
            lines.append(f"| Expected Amount | ₹{r['expected_amount']:,} |\n")
            aa = r["actual_amount"]
            amt_cell = f"₹{aa:,.0f}" if aa else "None"
            lines.append(f"| Actual Amount | {amt_cell} |\n")
        lines.append(f"| Confidence | {r['confidence_score']:.0%} |\n")
        lines.append(f"| Processing Time | {r['processing_ms']:.0f}ms |\n\n")

        if r["rejection_reasons"]:
            lines.append("**Rejection Reasons:**\n")
            for reason in r["rejection_reasons"]:
                lines.append(f"- {reason}\n")
            lines.append("\n")

        if r["approval_notes"]:
            lines.append("**Approval Notes:**\n")
            for note in r["approval_notes"]:
                lines.append(f"- {note}\n")
            lines.append("\n")

        lines.append("**Agent Trace Summary:**\n")
        for trace in r["agent_traces"]:
            status = trace["status"]
            lines.append(f"- **{trace['agent']}**: `{status}`\n")
            for check in trace.get("checks", []):
                icon = "✅" if check["passed"] else "❌"
                lines.append(f"  - {icon} `{check['name']}`: {check['detail'][:80]}\n")
        lines.append("\n---\n\n")

    out_path = os.path.join(os.path.dirname(__file__), "eval_report.md")
    with open(out_path, "w") as f:
        f.writelines(lines)
    print(f"Markdown report saved to: {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="Save JSON report")
    parser.add_argument("--md", action="store_true", help="Save Markdown report")
    args = parser.parse_args()
    run_eval(output_md=args.md, output_json=args.json)
