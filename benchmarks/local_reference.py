"""Repeated, trace-backed local inference benchmark.

This benchmark is deliberately separate from the GCP experiment. It produces
engineering evidence on the host where it runs: a fixed workload, repeated
trials, a batch-size tradeoff curve, bootstrap confidence intervals, SLO
pass-rate, and raw per-request rows. It never presents local numbers as L4
or Cloud Run measurements.
"""

from __future__ import annotations

import argparse
import json
import platform
import random
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from l4flow.workload import (
    WorkloadRow,
    generate_workload,
    load_workload,
    summarize_workload,
    write_workload,
)


DEFAULT_MODEL = "hf-internal-testing/tiny-random-gpt2"


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((p / 100) * (len(ordered) - 1)))
    return ordered[index]


def bootstrap_ci(values: list[float], seed: int, samples: int = 2000) -> list[float]:
    """95% percentile bootstrap CI for the mean of trial-level values."""
    if not values:
        return [0.0, 0.0]
    if len(values) == 1:
        value = round(values[0], 6)
        return [value, value]
    rng = random.Random(seed)
    means = []
    for _ in range(samples):
        sample = [rng.choice(values) for _ in values]
        means.append(statistics.mean(sample))
    return [round(percentile(means, 2.5), 6), round(percentile(means, 97.5), 6)]


def choose_device(torch: Any, requested: str) -> Any:
    if requested == "cpu":
        return torch.device("cpu")
    if requested == "mps":
        if not torch.backends.mps.is_available():
            raise RuntimeError("MPS was requested but is not available")
        return torch.device("mps")
    return torch.device("mps" if torch.backends.mps.is_available() else "cpu")


def synchronize(torch: Any, device: Any) -> None:
    if device.type == "mps":
        torch.mps.synchronize()


def load_model(model_id: str, device_name: str) -> tuple[Any, Any, Any, Any]:
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError as exc:  # pragma: no cover - optional benchmark dependency
        raise RuntimeError(
            "Install local benchmark dependencies with: "
            "python -m pip install '.[local-benchmark]'"
        ) from exc

    device = choose_device(torch, device_name)
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    tokenizer.padding_side = "left"
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(model_id, use_safetensors=True)
    model.to(device)
    model.eval()
    return torch, tokenizer, model, device


def generate_batch(
    model: Any,
    tokenizer: Any,
    torch: Any,
    device: Any,
    prompts: list[str],
    max_new_tokens: int,
) -> tuple[list[int], list[int]]:
    encoded = tokenizer(prompts, return_tensors="pt", padding=True, truncation=True)
    input_tokens = [int(value) for value in encoded["attention_mask"].sum(dim=1).tolist()]
    encoded = {key: value.to(device) for key, value in encoded.items()}
    with torch.inference_mode():
        output = model.generate(
            **encoded,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            pad_token_id=tokenizer.pad_token_id,
        )
    synchronize(torch, device)
    generated_each = max(0, int(output.shape[1] - encoded["input_ids"].shape[1]))
    return input_tokens, [generated_each] * len(prompts)


def run_strategy(
    model: Any,
    tokenizer: Any,
    torch: Any,
    device: Any,
    workload: list[WorkloadRow],
    batch_size: int,
    trial: int,
    strategy: str,
    model_id: str,
    output_token_cap: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    latencies: list[float] = []
    generated_tokens = 0
    trace_rows: list[dict[str, Any]] = []
    started_total = time.perf_counter()
    for offset in range(0, len(workload), batch_size):
        batch = workload[offset : offset + batch_size]
        prompts = [row.prompt for row in batch]
        max_new_tokens = min(output_token_cap, max(row.max_new_tokens for row in batch))
        started_wall = time.time()
        started = time.perf_counter()
        input_tokens, output_tokens = generate_batch(
            model, tokenizer, torch, device, prompts, max_new_tokens
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        latencies.extend([elapsed_ms] * len(batch))
        generated_tokens += sum(output_tokens)
        for row, prompt_tokens, completion_tokens in zip(batch, input_tokens, output_tokens):
            trace_rows.append(
                {
                    "trace_id": f"{strategy}-t{trial}-{row.request_id}",
                    "timestamp_s": started_wall,
                    "backend": "local-transformers",
                    "status": "ok",
                    "latency_ms": elapsed_ms,
                    "ttft_ms": None,
                    "input_tokens": prompt_tokens,
                    "output_tokens": completion_tokens,
                    "estimated_cost_usd": 0.0,
                    "trial": trial,
                    "strategy": strategy,
                    "batch_size": batch_size,
                    "workload_class": row.workload_class,
                    "prefix_id": row.prefix_id,
                    "model_id": model_id,
                    "evidence_scope": "local_reference_only",
                }
            )
    total_seconds = time.perf_counter() - started_total
    return (
        summarize_strategy(
            strategy,
            len(workload),
            batch_size,
            latencies,
            generated_tokens,
            total_seconds,
            trial,
        ),
        trace_rows,
    )


def summarize_strategy(
    name: str,
    requests: int,
    batch_size: int,
    latencies: list[float],
    generated_tokens: int,
    total_seconds: float,
    trial: int,
) -> dict[str, Any]:
    return {
        "strategy": name,
        "trial": trial,
        "requests": requests,
        "batch_size": batch_size,
        "total_seconds": round(total_seconds, 6),
        "latency_ms": {
            "p50": round(percentile(latencies, 50), 3),
            "p95": round(percentile(latencies, 95), 3),
            "p99": round(percentile(latencies, 99), 3),
            "mean": round(statistics.mean(latencies), 3) if latencies else 0.0,
        },
        "generated_tokens": generated_tokens,
        "requests_per_second": round(requests / total_seconds, 3) if total_seconds else 0.0,
        "tokens_per_second": round(generated_tokens / total_seconds, 3) if total_seconds else 0.0,
    }


def aggregate_strategy(
    name: str,
    trial_results: list[dict[str, Any]],
    trace_rows: list[dict[str, Any]],
    p95_slo_ms: float | None,
    seed: int,
) -> dict[str, Any]:
    latencies = [float(row["latency_ms"]) for row in trace_rows]
    total_seconds = sum(float(result["total_seconds"]) for result in trial_results)
    requests = sum(int(result["requests"]) for result in trial_results)
    generated_tokens = sum(int(result["generated_tokens"]) for result in trial_results)
    trial_throughput = [float(result["requests_per_second"]) for result in trial_results]
    trial_token_throughput = [float(result["tokens_per_second"]) for result in trial_results]
    aggregate = {
        "strategy": name,
        "trials": len(trial_results),
        "requests": requests,
        "batch_size": trial_results[0]["batch_size"],
        "total_seconds": round(total_seconds, 6),
        "latency_ms": {
            "p50": round(percentile(latencies, 50), 3),
            "p95": round(percentile(latencies, 95), 3),
            "p99": round(percentile(latencies, 99), 3),
            "mean": round(statistics.mean(latencies), 3) if latencies else 0.0,
        },
        "generated_tokens": generated_tokens,
        "requests_per_second": round(requests / total_seconds, 3) if total_seconds else 0.0,
        "tokens_per_second": round(generated_tokens / total_seconds, 3) if total_seconds else 0.0,
        "trial_throughput_ci95": bootstrap_ci(trial_throughput, seed),
        "trial_token_throughput_ci95": bootstrap_ci(trial_token_throughput, seed + 1),
        "trial_results": trial_results,
        "compute_seconds_per_1k_output_tokens": round(
            total_seconds / generated_tokens * 1000, 6
        ) if generated_tokens else 0.0,
    }
    if p95_slo_ms is not None:
        passing_trials = sum(
            result["latency_ms"]["p95"] <= p95_slo_ms for result in trial_results
        )
        passing_requests = sum(latency <= p95_slo_ms for latency in latencies)
        aggregate["slo"] = {
            "p95_ms": p95_slo_ms,
            "trial_pass_rate": round(passing_trials / len(trial_results), 4),
            "request_pass_rate": round(passing_requests / len(latencies), 4),
            "passing_trials": passing_trials,
            "total_trials": len(trial_results),
        }
    return aggregate


def write_trace(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def markdown(report: dict[str, Any]) -> str:
    lines = [
        "# L4Flow repeated local reference benchmark",
        "",
        f"- Model: `{report['model_id']}`",
        f"- Device: `{report['device']}`",
        f"- Workload: {report['workload']['requests']} requests × {report['trials']} trials per strategy",
        f"- Generated: {report['generated_at']}",
        "",
        "| Strategy | Batch | Requests | p50 ms | p95 ms | p99 ms | Requests/s | Tokens/s | 95% throughput CI | SLO pass |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|---:|",
    ]
    for name, result in report["results"].items():
        slo = result.get("slo", {}).get("trial_pass_rate")
        slo_text = f"{slo:.0%}" if slo is not None else "n/a"
        ci = result["trial_throughput_ci95"]
        lines.append(
            f"| {name} | {result['batch_size']} | {result['requests']} | "
            f"{result['latency_ms']['p50']:.3f} | {result['latency_ms']['p95']:.3f} | "
            f"{result['latency_ms']['p99']:.3f} | {result['requests_per_second']:.3f} | "
            f"{result['tokens_per_second']:.3f} | [{ci[0]:.3f}, {ci[1]:.3f}] | {slo_text} |"
        )
    improvement = report["improvements"]
    lines += [
        "",
        f"Recommended strategy: **{improvement['selected_strategy']}** under the declared SLO.",
        f"Throughput change: **{improvement['throughput_speedup']:.3f}x** "
        f"(95% CI for trial speedup [{improvement['throughput_speedup_ci95'][0]:.3f}, "
        f"{improvement['throughput_speedup_ci95'][1]:.3f}]).",
        f"Token-throughput change: **{improvement['token_throughput_improvement_percent']:.2f}%**.",
        f"P95 latency change: **{improvement['p95_latency_change_percent']:.2f}%** "
        "(positive means lower p95).",
        "",
        "The workload, raw request rows, repeated trials, and confidence interval inputs are committed with this report.",
        "These are local reference measurements, not Cloud Run L4 results or billing data.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run repeated local serial vs micro-batch inference experiments.")
    parser.add_argument("--model-id", default=DEFAULT_MODEL)
    parser.add_argument("--device", choices=["auto", "cpu", "mps"], default="auto")
    parser.add_argument("--requests", type=int, default=128)
    parser.add_argument("--trials", type=int, default=5)
    parser.add_argument("--batch-sizes", default="2,4,8")
    parser.add_argument("--batch-size", type=int, help="Compatibility shortcut for one batch size.")
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--max-new-tokens", type=int, default=16)
    parser.add_argument("--p95-slo-ms", type=float)
    parser.add_argument("--workload-jsonl", type=Path)
    parser.add_argument("--workload-output", type=Path)
    parser.add_argument("--trace-output", type=Path)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()
    if args.requests < 1 or args.trials < 1:
        raise SystemExit("--requests and --trials must be positive")
    if args.workload_jsonl:
        workload = load_workload(args.workload_jsonl)
        if len(workload) != args.requests:
            raise SystemExit("--requests must equal the number of rows in --workload-jsonl")
    else:
        workload = generate_workload(args.requests, args.seed)
    if args.workload_output:
        write_workload(args.workload_output, workload)
    batch_sizes = [args.batch_size] if args.batch_size else [
        int(value.strip()) for value in args.batch_sizes.split(",") if value.strip()
    ]
    if any(size < 1 for size in batch_sizes):
        raise SystemExit("batch sizes must be positive")
    if not any(size > 1 for size in batch_sizes):
        raise SystemExit("include at least one batch size greater than 1")
    if args.max_new_tokens < 1:
        raise SystemExit("--max-new-tokens must be positive")

    torch, tokenizer, model, device = load_model(args.model_id, args.device)
    warmup_prompts = [row.prompt for row in workload[: min(2, len(workload))]]
    generate_batch(model, tokenizer, torch, device, warmup_prompts, min(4, args.max_new_tokens))

    strategy_batches = [("serial_baseline", 1)] + [
        (f"micro_batch_{batch_size}", batch_size) for batch_size in batch_sizes if batch_size != 1
    ]
    trial_results: dict[str, list[dict[str, Any]]] = {name: [] for name, _ in strategy_batches}
    trace_rows: dict[str, list[dict[str, Any]]] = {name: [] for name, _ in strategy_batches}
    for trial in range(args.trials):
        for strategy, batch_size in strategy_batches:
            result, rows = run_strategy(
                model,
                tokenizer,
                torch,
                device,
                workload,
                batch_size,
                trial,
                strategy,
                args.model_id,
                args.max_new_tokens,
            )
            trial_results[strategy].append(result)
            trace_rows[strategy].extend(rows)

    results = {
        strategy: aggregate_strategy(
            strategy,
            trial_results[strategy],
            trace_rows[strategy],
            args.p95_slo_ms,
            args.seed + index * 100,
        )
        for index, (strategy, _) in enumerate(strategy_batches)
    }
    baseline = results["serial_baseline"]
    candidates = [result for name, result in results.items() if name != "serial_baseline"]
    if args.p95_slo_ms is not None:
        passing = [result for result in candidates if result["slo"]["trial_pass_rate"] == 1.0]
        selected = max(passing or candidates, key=lambda result: result["requests_per_second"])
    else:
        selected = max(candidates, key=lambda result: result["requests_per_second"])
    selected_trial_ratios = [
        selected_trial["requests_per_second"] / baseline_trial["requests_per_second"]
        for selected_trial, baseline_trial in zip(
            selected["trial_results"], baseline["trial_results"]
        )
        if baseline_trial["requests_per_second"]
    ]
    throughput_speedup = (
        selected["requests_per_second"] / baseline["requests_per_second"]
        if baseline["requests_per_second"]
        else 0.0
    )
    report = {
        "schema_version": "2.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model_id": args.model_id,
        "device": str(device),
        "host": platform.platform(),
        "torch_version": torch.__version__,
        "requests": args.requests,
        "trials": args.trials,
        "batch_sizes": batch_sizes,
        "max_new_tokens": args.max_new_tokens,
        "seed": args.seed,
        "workload": summarize_workload(workload),
        "results": results,
        "improvements": {
            "selected_strategy": selected["strategy"],
            "throughput_speedup": round(throughput_speedup, 4),
            "throughput_speedup_ci95": bootstrap_ci(selected_trial_ratios, args.seed + 900),
            "token_throughput_improvement_percent": round(
                (selected["tokens_per_second"] / baseline["tokens_per_second"] - 1) * 100,
                4,
            ) if baseline["tokens_per_second"] else 0.0,
            "p95_latency_change_percent": round(
                (baseline["latency_ms"]["p95"] - selected["latency_ms"]["p95"])
                / baseline["latency_ms"]["p95"]
                * 100,
                4,
            ) if baseline["latency_ms"]["p95"] else 0.0,
            "compute_seconds_per_1k_output_tokens_change_percent": round(
                (baseline["compute_seconds_per_1k_output_tokens"]
                 - selected["compute_seconds_per_1k_output_tokens"])
                / baseline["compute_seconds_per_1k_output_tokens"]
                * 100,
                4,
            ) if baseline["compute_seconds_per_1k_output_tokens"] else 0.0,
        },
        "evidence_scope": "local_reference_only",
        "cost_scope": "no_billing_data; compute_seconds_only",
    }
    if args.trace_output:
        all_rows = [row for rows in trace_rows.values() for row in rows]
        write_trace(args.trace_output, all_rows)
    rendered = json.dumps(report, indent=2) + "\n"
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(rendered, encoding="utf-8")
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(markdown(report), encoding="utf-8")
    print(rendered, end="")
    if args.markdown_output:
        print(markdown(report), end="")


if __name__ == "__main__":
    main()
