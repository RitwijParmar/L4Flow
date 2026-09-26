"""Release-quality gates for black-box inference traces."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .trace import TRACE_SCHEMA_VERSION, load_jsonl, summarize


@dataclass(frozen=True)
class GateConfig:
    max_p95_latency_regression_percent: float = 10.0
    max_p95_ttft_regression_percent: float = 10.0
    max_error_rate_delta: float = 0.01
    max_cost_regression_percent: float = 10.0


def _relative_change(baseline: float, candidate: float) -> float | None:
    if baseline == 0:
        return 0.0 if candidate == 0 else None
    return (candidate - baseline) / baseline * 100


def _check_relative(
    name: str,
    baseline: float,
    candidate: float,
    limit: float,
) -> dict[str, Any]:
    change = _relative_change(baseline, candidate)
    passed = change is not None and change <= limit
    return {
        "metric": name,
        "baseline": baseline,
        "candidate": candidate,
        "change_percent": round(change, 4) if change is not None else None,
        "limit": limit,
        "passed": passed,
        "reason": "baseline is zero; candidate is non-zero" if change is None else None,
    }


def _check_absolute(name: str, baseline: float, candidate: float, limit: float) -> dict[str, Any]:
    change = candidate - baseline
    return {
        "metric": name,
        "baseline": baseline,
        "candidate": candidate,
        "change": round(change, 6),
        "limit": limit,
        "passed": change <= limit,
    }


def compare_traces(
    baseline_rows: list[Any],
    candidate_rows: list[Any],
    config: GateConfig | None = None,
) -> dict[str, Any]:
    cfg = config or GateConfig()
    baseline = summarize(baseline_rows)
    candidate = summarize(candidate_rows)
    checks = [
        _check_relative(
            "latency_ms.p95",
            baseline["latency_ms"]["p95"],
            candidate["latency_ms"]["p95"],
            cfg.max_p95_latency_regression_percent,
        ),
        _check_absolute(
            "error_rate",
            baseline["error_rate"],
            candidate["error_rate"],
            cfg.max_error_rate_delta,
        ),
        _check_relative(
            "estimated_cost_per_1k_output_tokens",
            baseline["estimated_cost_per_1k_output_tokens"],
            candidate["estimated_cost_per_1k_output_tokens"],
            cfg.max_cost_regression_percent,
        ),
    ]
    if baseline["ttft_ms"]["observed"] and candidate["ttft_ms"]["observed"]:
        checks.append(
            _check_relative(
                "ttft_ms.p95",
                baseline["ttft_ms"]["p95"],
                candidate["ttft_ms"]["p95"],
                cfg.max_p95_ttft_regression_percent,
            )
        )
    return {
        "schema_version": TRACE_SCHEMA_VERSION,
        "gate_config": asdict(cfg),
        "baseline": baseline,
        "candidate": candidate,
        "checks": checks,
        "passed": all(check["passed"] for check in checks),
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# L4Flow inference release gate",
        "",
        f"**Decision:** {'PASS' if report['passed'] else 'FAIL'}",
        "",
        "| Check | Baseline | Candidate | Change | Limit | Result |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for check in report["checks"]:
        change = check.get("change_percent", check.get("change", 0.0))
        suffix = "%" if "change_percent" in check else " absolute"
        limit = check["limit"]
        limit_text = f"{limit:.2f}%" if "change_percent" in check else f"{limit:.4f}"
        lines.append(
            f"| {check['metric']} | {check['baseline']:.4f} | {check['candidate']:.4f} | "
            f"{change:.4f}{suffix} | {limit_text} | {'PASS' if check['passed'] else 'FAIL'} |"
        )
    lines += [
        "",
        "The gate compares equivalent trace sets; it does not control admission, batching, or model execution.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Gate a candidate inference trace against a baseline trace.")
    parser.add_argument("baseline", type=Path, help="Baseline JSONL trace")
    parser.add_argument("candidate", type=Path, help="Candidate JSONL trace")
    parser.add_argument("--max-p95-latency-regression-percent", type=float, default=10.0)
    parser.add_argument("--max-p95-ttft-regression-percent", type=float, default=10.0)
    parser.add_argument("--max-error-rate-delta", type=float, default=0.01)
    parser.add_argument("--max-cost-regression-percent", type=float, default=10.0)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()
    report = compare_traces(
        load_jsonl(args.baseline),
        load_jsonl(args.candidate),
        GateConfig(
            max_p95_latency_regression_percent=args.max_p95_latency_regression_percent,
            max_p95_ttft_regression_percent=args.max_p95_ttft_regression_percent,
            max_error_rate_delta=args.max_error_rate_delta,
            max_cost_regression_percent=args.max_cost_regression_percent,
        ),
    )
    rendered = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(render_markdown(report), encoding="utf-8")
    print(rendered, end="")
    if args.markdown_output:
        print(render_markdown(report), end="")
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
