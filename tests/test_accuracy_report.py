"""
Accuracy report generator for all agents.

Runs all real documents through the system and generates accuracy_report.json.

Usage: pytest tests/test_accuracy_report.py -m e2e -v
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests

from tests.fixtures.real_procurement_docs import REAL_DOCS_REGISTRY

API_BASE = os.getenv("TEST_API_BASE", "http://localhost:8000")
API_KEY = os.getenv("TEST_API_KEY", "sandbox-test-api-key-12345")
HEADERS = {"x-api-key": API_KEY}


def _b64(text: str) -> str:
    import base64
    return base64.b64encode(text.encode("utf-8")).decode()


def _submit_job(agent: str, subject: str, body: str, doc_text: str, filename: str) -> str:
    payload = {
        "sender": f"accuracy_test_{agent}@example.com",
        "subject": subject,
        "body_text": body,
        "attachments": [
            {
                "filename": filename,
                "content_base64": _b64(doc_text),
                "mime_type": "text/plain",
            }
        ],
    }
    r = requests.post(
        f"{API_BASE}/api/v1/process/{agent}",
        headers=HEADERS,
        json=payload,
        timeout=15,
    )
    r.raise_for_status()
    return r.json()["job"]["job_id"]


def _wait_for_job(job_id: str, max_wait: int = 120) -> dict:
    for _ in range(max_wait):
        r = requests.get(f"{API_BASE}/api/v1/jobs/{job_id}", headers=HEADERS, timeout=5)
        r.raise_for_status()
        d = r.json()
        if d["status"] in ("success", "error", "failed"):
            return d
        time.sleep(1)
    raise TimeoutError(f"Job {job_id} did not complete in {max_wait}s")


_server_available = False
try:
    import socket as _s
    _c = _s.create_connection(("localhost", 8000), timeout=1)
    _c.close()
    _server_available = True
except OSError:
    pass


@pytest.mark.e2e
@pytest.mark.skipif(
    not os.getenv("LLM_BACKEND") or not _server_available,
    reason="LLM_BACKEND not set or server not running",
)
class TestAccuracyReport:
    """Generate accuracy_report.json with metrics across all agents."""

    def test_generate_accuracy_report(self):
        results = {}
        correct = 0
        total = 0
        false_positives = []
        false_negatives = []
        per_agent = {}

        for doc_key, doc in REAL_DOCS_REGISTRY.items():
            if doc["agent"] not in ("tz", "dzo", "tender"):
                continue

            total += 1
            agent = doc["agent"]
            expected = doc["expected"]
            expected_decision = expected.get("expert_decision", "")

            try:
                job_id = _submit_job(
                    agent=agent,
                    subject=f"Accuracy: {doc['subject'][:60]}",
                    body=f"Accuracy test: {doc['filename']}",
                    doc_text=doc["text"],
                    filename=doc["filename"],
                )
                d = _wait_for_job(job_id, max_wait=120)

                if d["status"] != "success":
                    results[doc_key] = {
                        "status": "error",
                        "expected_decision": expected_decision,
                        "actual_decision": None,
                        "match": False,
                    }
                    continue

                result_str = json.dumps(d.get("result", {}), ensure_ascii=False).lower()

                # Check decision match
                decision_match = expected_decision.lower() in result_str

                # Check key_missing detection
                missing_detected = 0
                missing_total = len(expected.get("key_missing", []))
                for gap in expected.get("key_missing", []):
                    if gap.lower() in result_str:
                        missing_detected += 1

                if decision_match:
                    correct += 1
                elif "принять" in result_str and "доработк" in expected_decision.lower():
                    false_positives.append(doc_key)
                elif "доработк" in result_str and "принять" in expected_decision.lower():
                    false_negatives.append(doc_key)

                results[doc_key] = {
                    "status": "success",
                    "expected_decision": expected_decision,
                    "decision_match": decision_match,
                    "missing_detected": missing_detected,
                    "missing_total": missing_total,
                    "agent": agent,
                }

                # Per-agent stats
                if agent not in per_agent:
                    per_agent[agent] = {"total": 0, "correct": 0}
                per_agent[agent]["total"] += 1
                if decision_match:
                    per_agent[agent]["correct"] += 1

            except Exception as e:
                results[doc_key] = {
                    "status": "exception",
                    "error": str(e),
                    "expected_decision": expected_decision,
                }

        overall_accuracy = correct / total if total > 0 else 0

        accuracy_report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "overall_accuracy": round(overall_accuracy, 3),
            "total_documents": total,
            "correct_decisions": correct,
            "per_agent": {
                k: {
                    "total": v["total"],
                    "correct": v["correct"],
                    "accuracy": round(v["correct"] / v["total"], 3) if v["total"] > 0 else 0,
                }
                for k, v in per_agent.items()
            },
            "false_positives": false_positives,
            "false_negatives": false_negatives,
            "details": results,
        }

        report_path = Path("accuracy_report.json")
        report_path.write_text(json.dumps(accuracy_report, ensure_ascii=False, indent=2))

        # Target: >= 85% overall accuracy
        assert overall_accuracy >= 0.85, (
            f"Overall accuracy {overall_accuracy:.1%} < 85% target. "
            f"Details: {json.dumps(per_agent, indent=2)}"
        )
