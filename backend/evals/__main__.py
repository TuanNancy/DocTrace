"""CLI: python -m evals [--mode smoke|live]."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from evals import baseline as baseline_store
from evals.dataset import DEFAULT_PATH
from evals.runner import (
    EvaluationError, resolve_dataset, run_live, run_smoke, write_artifact,
)
from evals.schema import GoldenSet

RESULT_DIR = Path(__file__).resolve().parent / "results"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the DocTrace RAG golden set.")
    parser.add_argument("--mode", choices=("smoke", "live"), default="smoke")
    parser.add_argument("--dataset", default=str(DEFAULT_PATH))
    parser.add_argument("--baseline", default=str(Path(__file__).resolve().parent / "baseline.json"))
    parser.add_argument("--output", default=None)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--plan", choices=("free", "pro"), default="pro")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--budget-micros", type=int,
        default=int(os.environ.get("EVAL_BUDGET_MICROS", "0") or 0),
        help="Total known-cost cap for live evaluation (integer micro-USD).",
    )
    parser.add_argument("--request-cap-micros", type=int, default=None)
    parser.add_argument("--no-baseline", action="store_true")
    parser.add_argument("--allow-dataset-change", action="store_true")
    parser.add_argument("--write-baseline", action="store_true")
    return parser


def _print_summary(artifact: dict, artifact_path: Path, check: dict | None) -> None:
    summary = artifact["summary"]
    values = " ".join(
        f"{key}={summary[key]:.4f}" if isinstance(summary[key], float) else f"{key}={summary[key]}"
        for key in (
            "total_cases", "pass_rate", "answer_accuracy", "refusal_accuracy",
            "retrieval_recall", "mrr", "citation_precision", "citation_recall",
            "latency_p50_ms", "first_token_p50_ms", "cost_known_micros", "unknown_cost_calls",
        )
        if summary.get(key) is not None
    )
    print(f"{artifact['mode']} eval: {values}")
    print(f"artifact: {artifact_path}")
    if check is not None:
        print(f"baseline: {check['status']}")
        for failure in check["failures"]:
            print(f"- {failure}")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.limit is not None and args.limit <= 0:
        print("--limit must be positive.", file=sys.stderr)
        return 2
    if args.write_baseline and args.limit is not None:
        print("--write-baseline cannot be combined with --limit.", file=sys.stderr)
        return 2

    try:
        dataset, dataset_path = resolve_dataset(args.dataset)
    except (OSError, ValueError) as exc:
        print(f"Cannot load golden set: {exc}", file=sys.stderr)
        return 2
    cases = dataset.cases if args.limit is None else dataset.cases[:args.limit]
    limited = len(cases) < len(dataset.cases)
    run_dataset = GoldenSet(dataset.version, dataset.documents, cases)

    try:
        if args.mode == "smoke":
            artifact = run_smoke(run_dataset, dataset_path, top_k=args.top_k, plan=args.plan)
        else:
            from app.core.config import get_config

            config = get_config()
            artifact = run_live(
                run_dataset, dataset_path, config, top_k=args.top_k, plan=args.plan,
                budget_micros=args.budget_micros,
                request_cap_micros=args.request_cap_micros,
            )
    except EvaluationError as exc:
        print(f"Evaluation failed: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"Cannot start evaluation: {exc}", file=sys.stderr)
        return 2

    artifact["limited"] = limited
    check = None
    if args.write_baseline:
        baseline_store.update(args.baseline, artifact, mode=args.mode)
        print(f"baseline updated: {args.baseline}")
    if not args.no_baseline:
        if limited:
            check = {"status": "skipped", "failures": [], "reason": "limited run"}
        else:
            try:
                baseline = baseline_store.load(args.baseline)
                check = baseline_store.check(
                    baseline, args.mode, artifact,
                    allow_dataset_change=args.allow_dataset_change,
                )
            except ValueError as exc:
                check = {"status": "fail", "failures": [str(exc)]}
    artifact["baseline"] = check

    output = Path(args.output) if args.output else RESULT_DIR / f"{args.mode}.json"
    artifact_path = write_artifact(artifact, output)
    _print_summary(artifact, artifact_path, check)
    return 1 if check and check["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
