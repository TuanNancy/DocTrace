"""Versioned evaluation gates and baseline comparison."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

# Smoke is deterministic; it should stay near 1.0. Live thresholds are
# deliberately conservative until the first budgeted real-provider run is
# reviewed. The provider project hard budget remains the final cost guard.
THRESHOLDS = {
    "smoke": {
        "min_pass_rate": 0.9,
        "min_answer_accuracy": 0.9,
        "min_refusal_accuracy": 0.9,
        "min_retrieval_recall": 0.9,
        "min_mrr": 0.8,
        "min_citation_precision": 0.9,
        "min_citation_recall": 0.9,
    },
    "live": {
        "min_pass_rate": 0.6,
        "min_answer_accuracy": 0.65,
        "min_refusal_accuracy": 2 / 3,
        "min_retrieval_recall": 0.75,
        "min_mrr": 0.6,
        "min_citation_precision": 0.5,
        "min_citation_recall": 0.6,
    },
}


def load(path: str | Path) -> dict:
    resolved = Path(path)
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Cannot read baseline: {resolved}") from exc
    except ValueError as exc:
        raise ValueError(f"Baseline is not valid JSON: {resolved}") from exc
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ValueError("Baseline must be a version 1 JSON object.")
    return payload


def check(
    baseline: dict, mode: str, artifact: dict, *, allow_dataset_change: bool = False,
) -> dict:
    from evals.evaluator import threshold_failures

    failures = []
    expected = baseline.get("dataset_sha256")
    actual = artifact.get("dataset", {}).get("sha256")
    dataset_matches = expected == actual
    if not dataset_matches and not allow_dataset_change:
        failures.append("Golden dataset changed without a baseline update.")
    section = baseline.get(mode)
    if not isinstance(section, dict):
        failures.append(f"Baseline has no {mode} section.")
        thresholds = {}
    else:
        thresholds = section.get("thresholds") or {}
        failures.extend(threshold_failures(artifact["summary"], thresholds))
    return {
        "status": "fail" if failures else "pass",
        "failures": failures,
        "dataset_matches": dataset_matches,
        "thresholds": thresholds,
    }


def update(path: str | Path, artifact: dict, *, mode: Optional[str] = None) -> dict:
    resolved = Path(path)
    try:
        payload = load(resolved)
    except (OSError, ValueError):
        payload = {"version": 1, "dataset_sha256": artifact["dataset"]["sha256"]}
    mode = mode or artifact["mode"]
    payload["version"] = 1
    payload["dataset_sha256"] = artifact["dataset"]["sha256"]
    payload["updated_at"] = artifact["generated_at"]
    payload[mode] = {
        "generated_at": artifact["generated_at"],
        "metrics": artifact["summary"],
        "thresholds": THRESHOLDS[mode],
    }
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return payload
