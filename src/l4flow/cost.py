"""Cost allocation and budget analysis for inference traces.

This module intentionally models billing outside the serving path. It can
attribute a shared resource group (for example, one micro-batch) once instead
of charging every request independently, then compares cost against an SLO.
The rate card is explicit and versioned so modeled cost is never confused with
an exported GCP invoice.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .trace import percentile


@dataclass(frozen=True)
class ResourceProfile:
    vcpus: float
    memory_gib: float
    l4_gpus: float = 0.0


@dataclass(frozen=True)
class RateCard:
    name: str
    source_url: str
    region: str
    currency: str
    billing_model: str
    billing_quantum_seconds: float
    cpu_vcpu_second_usd: float
    memory_gib_second_usd: float
    l4_gpu_second_usd: float
    profiles: dict[str, ResourceProfile]
    backend_profiles: dict[str, str]
    free_tier_enabled: bool = False

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "RateCard":
        rates = value["rates"]
        profiles = {
            name: ResourceProfile(
                vcpus=float(profile.get("vcpus", 0)),
                memory_gib=float(profile.get("memory_gib", 0)),
                l4_gpus=float(profile.get("l4_gpus", 0)),
            )
            for name, profile in value["profiles"].items()
        }
        return cls(
            name=str(value["name"]),
            source_url=str(value.get("source_url", "")),
            region=str(value.get("region", "unknown")),
            currency=str(value.get("currency", "USD")),
            billing_model=str(value.get("billing_model", "request-based")),
            billing_quantum_seconds=float(value.get("billing_quantum_seconds", 0.1)),
            cpu_vcpu_second_usd=float(rates["cpu_vcpu_second_usd"]),
            memory_gib_second_usd=float(rates["memory_gib_second_usd"]),
            l4_gpu_second_usd=float(rates["l4_gpu_second_usd"]),
            profiles=profiles,
            backend_profiles={str(key): str(name) for key, name in value["backend_profiles"].items()},
            free_tier_enabled=bool(value.get("free_tier_enabled", False)),
        )

    def profile_for(self, backend: str) -> ResourceProfile:
        profile_name = self.backend_profiles.get(backend, backend)
        if profile_name not in self.profiles:
            raise ValueError(f"no resource profile for backend {backend!r}")
        return self.profiles[profile_name]


def load_rate_card(path: str | Path) -> RateCard:
    return RateCard.from_mapping(json.loads(Path(path).read_text(encoding="utf-8")))


def load_raw_trace(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"trace line {line_number} must be a JSON object")
        rows.append(value)
    if not rows:
        raise ValueError(f"trace file {path} contains no rows")
    return rows


def _billed_seconds(duration_ms: float, quantum_seconds: float) -> float:
    duration_seconds = max(0.0, duration_ms / 1000)
    if duration_seconds == 0:
        return 0.0
    return math.ceil(duration_seconds / quantum_seconds) * quantum_seconds


def _group_key(row: dict[str, Any]) -> str:
    return str(row.get("resource_group") or row.get("trace_id") or id(row))


def _status_ok(row: dict[str, Any]) -> bool:
    return str(row.get("status", "ok")).lower() in {"ok", "success", "200"}


def summarize_cost(
    rows: list[dict[str, Any]],
    rate_card: RateCard,
    *,
    p95_slo_ms: float | None = None,
    requests_per_day: float | None = None,
    days: int = 30,
    budget_usd: float | None = None,
) -> dict[str, Any]:
    if not rows:
        raise ValueError("cannot summarize an empty trace")
    profiles = {backend: rate_card.profile_for(backend) for backend in {str(row.get("backend", "unknown")) for row in rows}}
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(_group_key(row), []).append(row)

    cpu_seconds = 0.0
    memory_seconds = 0.0
    gpu_seconds = 0.0
    gross_cost = 0.0
    for group_rows in groups.values():
        representative = group_rows[0]
        profile = profiles[str(representative.get("backend", "unknown"))]
        billable_seconds = _billed_seconds(
            max(float(row.get("latency_ms", 0.0)) for row in group_rows),
            rate_card.billing_quantum_seconds,
        )
        cpu_seconds += billable_seconds * profile.vcpus
        memory_seconds += billable_seconds * profile.memory_gib
        gpu_seconds += billable_seconds * profile.l4_gpus
        gross_cost += billable_seconds * (
            profile.vcpus * rate_card.cpu_vcpu_second_usd
            + profile.memory_gib * rate_card.memory_gib_second_usd
            + profile.l4_gpus * rate_card.l4_gpu_second_usd
        )

    successful = [row for row in rows if _status_ok(row)]
    latencies = [float(row.get("latency_ms", 0.0)) for row in successful]
    output_tokens = sum(max(0, int(row.get("output_tokens", row.get("completion_tokens", 0)))) for row in successful)
    requests = len(rows)
    request_cost = gross_cost / requests if requests else 0.0
    cost_per_1k = gross_cost / output_tokens * 1000 if output_tokens else 0.0
    result: dict[str, Any] = {
        "requests": requests,
        "successful": len(successful),
        "error_rate": round((requests - len(successful)) / requests, 6) if requests else 0.0,
        "resource_groups": len(groups),
        "latency_ms": {
            "p50": round(percentile(latencies, 50), 3),
            "p95": round(percentile(latencies, 95), 3),
            "p99": round(percentile(latencies, 99), 3),
        },
        "output_tokens": output_tokens,
        "resource_seconds": {
            "cpu_vcpu_seconds": round(cpu_seconds, 6),
            "memory_gib_seconds": round(memory_seconds, 6),
            "l4_gpu_seconds": round(gpu_seconds, 6),
        },
        "gross_cost_usd": round(gross_cost, 8),
        "cost_per_request_usd": round(request_cost, 8),
        "cost_per_1k_output_tokens_usd": round(cost_per_1k, 8),
        "free_tier_applied": rate_card.free_tier_enabled,
        "rate_card": rate_card.name,
        "region": rate_card.region,
    }
    if p95_slo_ms is not None:
        result["slo"] = {
            "p95_ms": p95_slo_ms,
            "passed": result["latency_ms"]["p95"] <= p95_slo_ms,
        }
    if requests_per_day is not None:
        forecast_requests = requests_per_day * days
        forecast_cost = request_cost * forecast_requests
        result["forecast"] = {
            "requests_per_day": requests_per_day,
            "days": days,
            "requests": round(forecast_requests, 3),
            "cost_usd": round(forecast_cost, 6),
            "budget_usd": budget_usd,
            "budget_utilization": round(forecast_cost / budget_usd, 6)
            if budget_usd and budget_usd > 0
            else None,
            "status": "over_budget"
            if budget_usd and forecast_cost > budget_usd
            else "within_budget"
            if budget_usd
            else "unbudgeted",
        }
    return result


def analyze_trace(
    rows: list[dict[str, Any]],
    rate_card: RateCard,
    *,
    p95_slo_ms: float | None = None,
    requests_per_day: float | None = None,
    days: int = 30,
    budget_usd: float | None = None,
) -> dict[str, Any]:
    strategies = sorted({str(row.get("strategy", "all")) for row in rows})
    by_strategy = {
        strategy: summarize_cost(
            [row for row in rows if str(row.get("strategy", "all")) == strategy],
            rate_card,
            p95_slo_ms=p95_slo_ms,
            requests_per_day=requests_per_day,
            days=days,
            budget_usd=budget_usd,
        )
        for strategy in strategies
    }
    eligible = [
        (strategy, summary)
        for strategy, summary in by_strategy.items()
        if p95_slo_ms is None or summary["slo"]["passed"]
    ]
    recommendation = None
    if eligible:
        strategy, summary = min(eligible, key=lambda item: item[1]["cost_per_1k_output_tokens_usd"])
        recommendation = {
            "strategy": strategy,
            "reason": "lowest modeled cost per 1K output tokens among SLO-passing strategies",
            "cost_per_1k_output_tokens_usd": summary["cost_per_1k_output_tokens_usd"],
        }
    return {
        "schema_version": "1.0",
        "rate_card": {
            "name": rate_card.name,
            "source_url": rate_card.source_url,
            "region": rate_card.region,
            "billing_model": rate_card.billing_model,
            "billing_quantum_seconds": rate_card.billing_quantum_seconds,
            "free_tier_applied": rate_card.free_tier_enabled,
        },
        "strategies": by_strategy,
        "recommendation": recommendation,
        "evidence_scope": "modeled_cost_from_trace_and_rate_card",
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# L4Flow inference FinOps report",
        "",
        f"- Rate card: `{report['rate_card']['name']}`",
        f"- Region: `{report['rate_card']['region']}`",
        f"- Billing model: `{report['rate_card']['billing_model']}`",
        f"- Billing quantum: `{report['rate_card']['billing_quantum_seconds']:.3f}s`",
        f"- Evidence scope: `{report['evidence_scope']}`",
        "",
        "| Strategy | Resource groups | p95 ms | Output tokens | Gross cost | Cost / 1K output tok | SLO |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for strategy, summary in report["strategies"].items():
        slo = summary.get("slo", {}).get("passed", "n/a")
        slo_text = "PASS" if slo is True else "FAIL" if slo is False else "n/a"
        lines.append(
            f"| {strategy} | {summary['resource_groups']} | {summary['latency_ms']['p95']:.3f} | "
            f"{summary['output_tokens']} | ${summary['gross_cost_usd']:.8f} | "
            f"${summary['cost_per_1k_output_tokens_usd']:.6f} | {slo_text} |"
        )
    if report["recommendation"]:
        recommendation = report["recommendation"]
        lines += [
            "",
            f"Recommendation: **{recommendation['strategy']}** at "
            f"${recommendation['cost_per_1k_output_tokens_usd']:.6f}/1K output tokens "
            "among SLO-passing strategies.",
        ]
    lines += [
        "",
        "Modeled cost is not a billing export. Reconcile with Cloud Billing export or Cloud Monitoring before reporting spend.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze inference trace cost and SLO tradeoffs.")
    parser.add_argument("trace", type=Path)
    parser.add_argument("--rate-card", type=Path, required=True)
    parser.add_argument("--p95-slo-ms", type=float)
    parser.add_argument("--requests-per-day", type=float)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--budget-usd", type=float)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    parser.add_argument("--fail-on-budget", action="store_true")
    args = parser.parse_args()
    report = analyze_trace(
        load_raw_trace(args.trace),
        load_rate_card(args.rate_card),
        p95_slo_ms=args.p95_slo_ms,
        requests_per_day=args.requests_per_day,
        days=args.days,
        budget_usd=args.budget_usd,
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
    if args.fail_on_budget:
        over_budget = any(
            summary.get("forecast", {}).get("status") == "over_budget"
            for summary in report["strategies"].values()
        )
        if over_budget:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
