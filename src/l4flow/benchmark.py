from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from .trace import TraceRow, write_jsonl


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((p / 100) * (len(ordered) - 1))))
    return ordered[index]


async def run_benchmark(url: str, requests: int, concurrency: int, route: str) -> dict[str, Any]:
    return await run_policy(url, requests, concurrency, route)


def make_payload(index: int) -> dict[str, Any]:
    workload_class = index % 3
    if workload_class == 0:
        content = "Summarize dynamic batching in one sentence."
        max_tokens = 64
        label = "short"
    elif workload_class == 1:
        content = "Explain dynamic batching, queue pressure, and time-to-first-token. " * 30
        max_tokens = 128
        label = "medium"
    else:
        content = "Design an inference benchmark covering scheduling, cold starts, and cost. " * 100
        max_tokens = 512
        label = "long"
    return {
        "model": "l4flow-router",
        "messages": [{"role": "user", "content": content}],
        "max_tokens": max_tokens,
        "_l4flow_workload_class": label,
    }


async def run_policy(
    url: str,
    requests: int,
    concurrency: int,
    route: str,
    *,
    trace_output: Path | None = None,
) -> dict[str, Any]:
    semaphore = asyncio.Semaphore(concurrency)
    latencies: list[float] = []
    routes: dict[str, int] = {}
    route_seconds: dict[str, float] = {}
    workload_classes: dict[str, int] = {}
    prompt_tokens = 0
    completion_tokens = 0
    failures = 0
    trace_rows: list[TraceRow] = []
    cpu_cost = 0.000018
    gpu_cost = 0.0001867

    async with httpx.AsyncClient(timeout=180.0) as client:
        async def one() -> None:
            nonlocal failures, prompt_tokens, completion_tokens
            async with semaphore:
                payload = make_payload(one.index)
                one.index += 1
                workload_class = payload.pop("_l4flow_workload_class")
                workload_classes[workload_class] = workload_classes.get(workload_class, 0) + 1
                started_wall = time.time()
                started = time.perf_counter()
                try:
                    response = await client.post(
                        f"{url.rstrip('/')}/v1/chat/completions",
                        json=payload,
                        headers={"x-l4flow-route": route},
                    )
                    latency = (time.perf_counter() - started) * 1000
                    latencies.append(latency)
                    backend = response.headers.get("x-l4flow-route", "unknown")
                    routes[backend] = routes.get(backend, 0) + 1
                    route_seconds[backend] = route_seconds.get(backend, 0.0) + latency / 1000
                    usage = response.json().get("usage") or {}
                    prompt_tokens += int(usage.get("prompt_tokens") or 0)
                    completion_tokens += int(usage.get("completion_tokens") or 0)
                    if response.status_code >= 400:
                        failures += 1
                    trace_rows.append(
                        TraceRow(
                            trace_id=response.headers.get("x-request-id", uuid4().hex),
                            timestamp_s=started_wall,
                            backend=backend,
                            status="error" if response.status_code >= 400 else "ok",
                            latency_ms=latency,
                            ttft_ms=None,
                            input_tokens=int(usage.get("prompt_tokens") or 0),
                            output_tokens=int(usage.get("completion_tokens") or 0),
                            estimated_cost_usd=latency / 1000 * (
                                gpu_cost if backend == "gpu" else cpu_cost
                            ),
                        )
                    )
                except httpx.HTTPError:
                    failures += 1
                    latency = (time.perf_counter() - started) * 1000
                    trace_rows.append(
                        TraceRow(
                            trace_id=uuid4().hex,
                            timestamp_s=started_wall,
                            backend="unknown",
                            status="error",
                            latency_ms=latency,
                            ttft_ms=None,
                            input_tokens=0,
                            output_tokens=0,
                        )
                    )

        one.index = 0
        await asyncio.gather(*(one() for _ in range(requests)))

    estimated_cost = sum(
        seconds * (gpu_cost if backend == "gpu" else cpu_cost)
        for backend, seconds in route_seconds.items()
    )
    total_time_s = sum(latencies) / 1000
    report = {
        "url": url,
        "requests": requests,
        "concurrency": concurrency,
        "requested_route": route,
        "completed": len(latencies),
        "failures": failures,
        "failure_rate": round(failures / requests, 6) if requests else 0.0,
        "workload_classes": workload_classes,
        "latency_ms": {
            "p50": round(percentile(latencies, 50), 2),
            "p95": round(percentile(latencies, 95), 2),
            "mean": round(statistics.mean(latencies), 2) if latencies else 0.0,
        },
        "actual_routes": routes,
        "route_seconds": {key: round(value, 4) for key, value in sorted(route_seconds.items())},
        "route_mix": {
            key: round(value / len(latencies), 6)
            for key, value in sorted(routes.items())
        } if latencies else {},
        "tokens": {"prompt": prompt_tokens, "completion": completion_tokens},
        "completion_tokens_per_second": round(completion_tokens / total_time_s, 3) if total_time_s else 0.0,
        "estimated_cost_usd": round(estimated_cost, 8),
        "estimated_cost_per_1k_completion_tokens": round(
            estimated_cost / completion_tokens * 1000, 8
        ) if completion_tokens else 0.0,
        "cost_model": {
            "cpu_usd_per_second": cpu_cost,
            "gpu_usd_per_second": gpu_cost,
            "note": "estimate from client-observed route time; not a billing export",
        },
    }
    if trace_output:
        write_jsonl(trace_output, trace_rows)
    return report


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# L4Flow benchmark report",
        "",
        f"Generated: {report['generated_at']}",
        f"Endpoint: {report['url']}",
        f"Requests/policy: {report['requests']}; concurrency: {report['concurrency']}",
        "",
        "| Policy | Success | p50 ms | p95 ms | Completion tok/s | GPU share | Est. $/1k output tok |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for policy, result in report["policies"].items():
        success = 1 - result["failure_rate"]
        gpu_share = result.get("route_mix", {}).get("gpu", 0.0)
        lines.append(
            f"| {policy} | {success:.1%} | {result['latency_ms']['p50']:.2f} | "
            f"{result['latency_ms']['p95']:.2f} | {result['completion_tokens_per_second']:.2f} | "
            f"{gpu_share:.1%} | {result['estimated_cost_per_1k_completion_tokens']:.8f} |"
        )
    lines += [
        "",
        "All policies must use the same region, model, prompt set, output budget, and concurrency "
        "before performance or cost claims are used on a resume.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark an L4Flow endpoint.")
    parser.add_argument("--url", default="http://127.0.0.1:8080")
    parser.add_argument("--requests", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--route", choices=["auto", "cpu", "gpu"], help="Run one policy only.")
    parser.add_argument(
        "--policies",
        default="auto,cpu,gpu",
        help="Comma-separated policies when --route is omitted.",
    )
    parser.add_argument("--output", type=Path, help="Write JSON report to this path.")
    parser.add_argument("--markdown-output", type=Path, help="Write a Markdown comparison report.")
    parser.add_argument(
        "--trace-dir",
        type=Path,
        help="Write one normalized JSONL trace per policy under this directory.",
    )
    args = parser.parse_args()
    policies = [args.route] if args.route else [item.strip() for item in args.policies.split(",") if item.strip()]
    policy_results = {
        policy: asyncio.run(
            run_policy(
                args.url,
                args.requests,
                args.concurrency,
                policy,
                trace_output=(args.trace_dir / f"{policy}.jsonl") if args.trace_dir else None,
            )
        )
        for policy in policies
    }
    result = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "url": args.url,
        "requests": args.requests,
        "concurrency": args.concurrency,
        "policies": policy_results,
    }
    rendered = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(render_markdown(result), encoding="utf-8")
    print(rendered, end="")
    if args.markdown_output:
        print(render_markdown(result), end="")


if __name__ == "__main__":
    main()
