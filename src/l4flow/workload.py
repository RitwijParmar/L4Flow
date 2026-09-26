"""Deterministic, production-shaped workload data for inference experiments."""

from __future__ import annotations

import argparse
import json
import random
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class WorkloadRow:
    request_id: str
    workload_class: str
    prompt: str
    max_new_tokens: int
    prefix_id: str

    @classmethod
    def from_mapping(cls, value: dict[str, Any], *, line_number: int = 0) -> "WorkloadRow":
        required = ("request_id", "workload_class", "prompt", "max_new_tokens", "prefix_id")
        missing = [key for key in required if key not in value]
        if missing:
            raise ValueError(f"workload line {line_number} missing: {', '.join(missing)}")
        if value["workload_class"] not in {"short", "medium", "long"}:
            raise ValueError(f"workload line {line_number} has an unknown class")
        if not str(value["prompt"]).strip():
            raise ValueError(f"workload line {line_number} has an empty prompt")
        max_new_tokens = int(value["max_new_tokens"])
        if max_new_tokens < 1:
            raise ValueError(f"workload line {line_number} has invalid max_new_tokens")
        return cls(
            request_id=str(value["request_id"]),
            workload_class=str(value["workload_class"]),
            prompt=str(value["prompt"]),
            max_new_tokens=max_new_tokens,
            prefix_id=str(value["prefix_id"]),
        )


def generate_workload(count: int = 128, seed: int = 17) -> list[WorkloadRow]:
    """Generate a fixed-mixture workload without relying on an external dataset."""
    if count < 1:
        raise ValueError("count must be positive")
    rng = random.Random(seed)
    prefix = "You are an inference systems analyst. Give a precise, concise answer."
    templates = {
        "short": [
            "Explain why p95 latency matters for an interactive endpoint.",
            "Name one benefit of batching independent requests.",
            "Define time to first token in one sentence.",
        ],
        "medium": [
            "Compare queueing delay and model execution time in a serving system. "
            "Describe one measurement that separates them and one mitigation for each.",
            "Explain how a release gate can detect a serving regression without knowing "
            "which inference engine produced the trace.",
            "Design a small experiment that compares throughput, tail latency, and "
            "token efficiency under a fixed output-token budget.",
        ],
        "long": [
            "Write a detailed incident analysis for an inference service whose average "
            "latency improved while p95 and p99 latency regressed during a burst. "
            "Separate workload mix, queueing, cold start, model execution, and network "
            "effects, then propose measurements and a rollback criterion.",
            "Propose a reproducible benchmark methodology for comparing two OpenAI-compatible "
            "LLM endpoints. Include prompt parity, concurrency, warmup, streamed TTFT, "
            "completion-token accounting, error handling, cost evidence, confidence intervals, "
            "and the conditions under which a result is safe to put on a resume.",
        ],
    }
    classes = rng.choices(["short", "medium", "long"], weights=[0.55, 0.30, 0.15], k=count)
    rows: list[WorkloadRow] = []
    for index, workload_class in enumerate(classes):
        reuse_prefix = rng.random() < 0.72
        prefix_id = "shared-prefix-v1" if reuse_prefix else f"unique-prefix-{index:04d}"
        selected = rng.choice(templates[workload_class])
        prompt_prefix = prefix if reuse_prefix else f"{prefix} Request family {index % 11}."
        prompt = f"{prompt_prefix}\n\n{selected}"
        max_new_tokens = {"short": 8, "medium": 16, "long": 24}[workload_class]
        rows.append(
            WorkloadRow(
                request_id=f"req-{index:05d}",
                workload_class=workload_class,
                prompt=prompt,
                max_new_tokens=max_new_tokens,
                prefix_id=prefix_id,
            )
        )
    return rows


def load_workload(path: str | Path) -> list[WorkloadRow]:
    rows: list[WorkloadRow] = []
    seen: set[str] = set()
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = WorkloadRow.from_mapping(json.loads(line), line_number=line_number)
        if row.request_id in seen:
            raise ValueError(f"duplicate request_id: {row.request_id}")
        seen.add(row.request_id)
        rows.append(row)
    if not rows:
        raise ValueError(f"workload file {path} contains no rows")
    return rows


def write_workload(path: str | Path, rows: list[WorkloadRow]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(asdict(row), sort_keys=True) + "\n")


def summarize_workload(rows: list[WorkloadRow]) -> dict[str, Any]:
    prompt_lengths = [len(row.prompt) for row in rows]
    counts = {label: sum(row.workload_class == label for row in rows) for label in ("short", "medium", "long")}
    shared = sum(row.prefix_id == "shared-prefix-v1" for row in rows)
    ordered = sorted(prompt_lengths)
    p95_index = min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))
    return {
        "requests": len(rows),
        "class_counts": counts,
        "shared_prefix_rate": round(shared / len(rows), 4) if rows else 0.0,
        "prompt_chars": {
            "p50": statistics.median(prompt_lengths) if prompt_lengths else 0,
            "p95": ordered[p95_index] if ordered else 0,
            "max": max(prompt_lengths) if prompt_lengths else 0,
        },
        "output_budget_tokens": {
            "total": sum(row.max_new_tokens for row in rows),
            "mean": round(statistics.mean(row.max_new_tokens for row in rows), 2) if rows else 0.0,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a deterministic inference workload JSONL file.")
    parser.add_argument("--requests", type=int, default=128)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = generate_workload(args.requests, args.seed)
    write_workload(args.output, rows)
    print(json.dumps(summarize_workload(rows), indent=2))


if __name__ == "__main__":
    main()
