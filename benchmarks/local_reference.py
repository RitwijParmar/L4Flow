"""Real local reference benchmark for serial vs micro-batched generation.

This is intentionally separate from the GCP benchmark. It produces reproducible
engineering evidence on the host where it runs and never pretends that local
Apple-Metal numbers are Cloud Run L4 numbers.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_MODEL = "hf-internal-testing/tiny-random-gpt2"


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((p / 100) * (len(ordered) - 1)))
    return ordered[index]


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


def prompts_for(count: int) -> list[str]:
    templates = [
        "Explain why queue-aware inference routing matters.",
        "Summarize the purpose of continuous batching.",
        "Describe how p95 latency differs from average latency.",
        "Give one method for reducing inference cost.",
    ]
    return [templates[index % len(templates)] for index in range(count)]


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


def generate(model: Any, tokenizer: Any, torch: Any, device: Any, prompts: list[str], max_new_tokens: int) -> int:
    encoded = tokenizer(prompts, return_tensors="pt", padding=True, truncation=True)
    encoded = {key: value.to(device) for key, value in encoded.items()}
    with torch.inference_mode():
        output = model.generate(
            **encoded,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            pad_token_id=tokenizer.pad_token_id,
        )
    synchronize(torch, device)
    return max(0, int(output.shape[1] - encoded["input_ids"].shape[1])) * len(prompts)


def run_serial(
    model: Any,
    tokenizer: Any,
    torch: Any,
    device: Any,
    prompts: list[str],
    max_new_tokens: int,
) -> dict[str, Any]:
    latencies: list[float] = []
    generated_tokens = 0
    started_total = time.perf_counter()
    for prompt in prompts:
        started = time.perf_counter()
        generated_tokens += generate(model, tokenizer, torch, device, [prompt], max_new_tokens)
        latencies.append((time.perf_counter() - started) * 1000)
    total_seconds = time.perf_counter() - started_total
    return summarize("serial_baseline", len(prompts), 1, latencies, generated_tokens, total_seconds)


def run_batched(
    model: Any,
    tokenizer: Any,
    torch: Any,
    device: Any,
    prompts: list[str],
    batch_size: int,
    max_new_tokens: int,
) -> dict[str, Any]:
    latencies: list[float] = []
    generated_tokens = 0
    started_total = time.perf_counter()
    for offset in range(0, len(prompts), batch_size):
        batch = prompts[offset : offset + batch_size]
        started = time.perf_counter()
        generated_tokens += generate(model, tokenizer, torch, device, batch, max_new_tokens)
        elapsed_ms = (time.perf_counter() - started) * 1000
        latencies.extend([elapsed_ms] * len(batch))
    total_seconds = time.perf_counter() - started_total
    return summarize("micro_batch", len(prompts), batch_size, latencies, generated_tokens, total_seconds)


def summarize(
    name: str,
    requests: int,
    batch_size: int,
    latencies: list[float],
    generated_tokens: int,
    total_seconds: float,
) -> dict[str, Any]:
    return {
        "name": name,
        "requests": requests,
        "batch_size": batch_size,
        "total_seconds": round(total_seconds, 6),
        "latency_ms": {
            "p50": round(percentile(latencies, 50), 3),
            "p95": round(percentile(latencies, 95), 3),
            "mean": round(statistics.mean(latencies), 3) if latencies else 0.0,
        },
        "generated_tokens": generated_tokens,
        "requests_per_second": round(requests / total_seconds, 3) if total_seconds else 0.0,
        "tokens_per_second": round(generated_tokens / total_seconds, 3) if total_seconds else 0.0,
    }


def markdown(report: dict[str, Any]) -> str:
    baseline = report["results"]["serial_baseline"]
    optimized = report["results"]["micro_batch"]
    throughput_speedup = report["improvements"]["throughput_speedup"]
    p95_reduction = report["improvements"]["p95_latency_reduction_percent"]
    return "\n".join(
        [
            "# L4Flow local reference benchmark",
            "",
            f"- Model: {report['model_id']}",
            f"- Device: {report['device']}",
            f"- Requests: {report['requests']}",
            f"- Generated: {report['generated_at']}",
            "",
            "| Strategy | Batch | p50 ms | p95 ms | Requests/s | Tokens/s |",
            "|---|---:|---:|---:|---:|---:|",
            f"| Serial baseline | {baseline['batch_size']} | {baseline['latency_ms']['p50']:.3f} | "
            f"{baseline['latency_ms']['p95']:.3f} | {baseline['requests_per_second']:.3f} | "
            f"{baseline['tokens_per_second']:.3f} |",
            f"| Micro-batched | {optimized['batch_size']} | {optimized['latency_ms']['p50']:.3f} | "
            f"{optimized['latency_ms']['p95']:.3f} | {optimized['requests_per_second']:.3f} | "
            f"{optimized['tokens_per_second']:.3f} |",
            "",
            f"Measured throughput speedup: {throughput_speedup:.2f}x.",
            f"Measured p95 latency change: {p95_reduction:.2f}% (positive means lower p95).",
            *(
                [
                    f"p95 SLO: {report['slo']['p95_ms']:.3f} ms; "
                    f"serial={'PASS' if report['slo']['serial_passed'] else 'FAIL'}, "
                    f"micro_batch={'PASS' if report['slo']['micro_batch_passed'] else 'FAIL'}.",
                ]
                if "slo" in report
                else []
            ),
            "",
            "These are local reference measurements and must not be presented as Cloud Run L4 results.",
            "",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark serial vs micro-batched local generation.")
    parser.add_argument("--model-id", default=DEFAULT_MODEL)
    parser.add_argument("--device", choices=["auto", "cpu", "mps"], default="auto")
    parser.add_argument("--requests", type=int, default=24)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--max-new-tokens", type=int, default=16)
    parser.add_argument(
        "--p95-slo-ms",
        type=float,
        help="Optional p95 latency budget used to mark each strategy PASS/FAIL.",
    )
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()
    if args.requests < 1 or args.batch_size < 1:
        raise SystemExit("--requests and --batch-size must be positive")

    torch, tokenizer, model, device = load_model(args.model_id, args.device)
    warmup = prompts_for(2)
    generate(model, tokenizer, torch, device, warmup, min(4, args.max_new_tokens))
    prompts = prompts_for(args.requests)
    baseline = run_serial(model, tokenizer, torch, device, prompts, args.max_new_tokens)
    optimized = run_batched(model, tokenizer, torch, device, prompts, args.batch_size, args.max_new_tokens)
    throughput_speedup = (
        optimized["requests_per_second"] / baseline["requests_per_second"]
        if baseline["requests_per_second"]
        else 0.0
    )
    p95_reduction = (
        (baseline["latency_ms"]["p95"] - optimized["latency_ms"]["p95"])
        / baseline["latency_ms"]["p95"]
        * 100
        if baseline["latency_ms"]["p95"]
        else 0.0
    )
    report = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model_id": args.model_id,
        "device": str(device),
        "host": platform.platform(),
        "torch_version": torch.__version__,
        "requests": args.requests,
        "batch_size": args.batch_size,
        "max_new_tokens": args.max_new_tokens,
        "results": {
            "serial_baseline": baseline,
            "micro_batch": optimized,
        },
        "improvements": {
            "throughput_speedup": round(throughput_speedup, 4),
            "p95_latency_reduction_percent": round(p95_reduction, 4),
            "token_throughput_improvement_percent": round(
                (optimized["tokens_per_second"] / baseline["tokens_per_second"] - 1) * 100,
                4,
            ) if baseline["tokens_per_second"] else 0.0,
        },
        "evidence_scope": "local_reference_only",
    }
    if args.p95_slo_ms is not None:
        report["slo"] = {
            "p95_ms": args.p95_slo_ms,
            "serial_passed": baseline["latency_ms"]["p95"] <= args.p95_slo_ms,
            "micro_batch_passed": optimized["latency_ms"]["p95"] <= args.p95_slo_ms,
        }
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
