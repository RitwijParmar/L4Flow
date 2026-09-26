"""Engine-agnostic inference trace records and summary statistics.

L4Flow deliberately observes a serving system from the outside.  The trace
schema is small enough to emit from an OpenAI-compatible client, while the
aliases in ``TraceRow.from_mapping`` make it easy to normalize rows exported
by different benchmark tools.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


TRACE_SCHEMA_VERSION = "1.0"


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((p / 100) * (len(ordered) - 1))))
    return ordered[index]


def _number(mapping: dict[str, Any], *names: str, default: float = 0.0) -> float:
    for name in names:
        if mapping.get(name) is not None:
            return float(mapping[name])
    return default


def _integer(mapping: dict[str, Any], *names: str, default: int = 0) -> int:
    return int(_number(mapping, *names, default=default))


@dataclass(frozen=True)
class TraceRow:
    """One completed request observed at an inference endpoint."""

    trace_id: str
    timestamp_s: float
    backend: str
    status: str
    latency_ms: float
    ttft_ms: float | None
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float = 0.0
    cache_hit: bool | None = None
    cold_start: bool | None = None

    @classmethod
    def from_mapping(cls, value: dict[str, Any], *, line_number: int = 0) -> "TraceRow":
        if not isinstance(value, dict):
            raise ValueError(f"trace line {line_number} must be a JSON object")
        trace_id = str(value.get("trace_id") or value.get("request_id") or f"line-{line_number}")
        backend = str(value.get("backend") or value.get("route") or "unknown")
        status = str(value.get("status") or "ok")
        latency = _number(value, "latency_ms", "e2e_latency_ms", "e2e_ms")
        if latency < 0:
            raise ValueError(f"trace line {line_number} has negative latency")
        raw_ttft = value.get("ttft_ms")
        ttft = None if raw_ttft is None else float(raw_ttft)
        if ttft is not None and ttft < 0:
            raise ValueError(f"trace line {line_number} has negative TTFT")
        return cls(
            trace_id=trace_id,
            timestamp_s=_number(value, "timestamp_s", "started_at_s", default=0.0),
            backend=backend,
            status=status,
            latency_ms=latency,
            ttft_ms=ttft,
            input_tokens=_integer(value, "input_tokens", "prompt_tokens"),
            output_tokens=_integer(value, "output_tokens", "completion_tokens"),
            estimated_cost_usd=_number(value, "estimated_cost_usd", "cost_usd"),
            cache_hit=value.get("cache_hit"),
            cold_start=value.get("cold_start"),
        )

    def to_mapping(self) -> dict[str, Any]:
        return asdict(self)


def load_jsonl(path: str | Path) -> list[TraceRow]:
    rows: list[TraceRow] = []
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"trace line {line_number} is not valid JSON: {exc}") from exc
        rows.append(TraceRow.from_mapping(value, line_number=line_number))
    if not rows:
        raise ValueError(f"trace file {path} contains no rows")
    return rows


def write_jsonl(path: str | Path, rows: Iterable[TraceRow]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row.to_mapping(), sort_keys=True) + "\n")


def summarize(rows: Iterable[TraceRow]) -> dict[str, Any]:
    materialized = list(rows)
    successful = [row for row in materialized if row.status.lower() in {"ok", "success", "200"}]
    latencies = [row.latency_ms for row in successful]
    ttfts = [row.ttft_ms for row in successful if row.ttft_ms is not None]
    output_tokens = sum(max(0, row.output_tokens) for row in successful)
    cost = sum(max(0.0, row.estimated_cost_usd) for row in successful)
    return {
        "requests": len(materialized),
        "successful": len(successful),
        "errors": len(materialized) - len(successful),
        "error_rate": round((len(materialized) - len(successful)) / len(materialized), 6)
        if materialized
        else 0.0,
        "latency_ms": {
            "p50": round(percentile(latencies, 50), 3),
            "p95": round(percentile(latencies, 95), 3),
            "mean": round(statistics.mean(latencies), 3) if latencies else 0.0,
        },
        "ttft_ms": {
            "observed": bool(ttfts),
            "p50": round(percentile(ttfts, 50), 3),
            "p95": round(percentile(ttfts, 95), 3),
        },
        "tokens": {"input": sum(max(0, row.input_tokens) for row in successful), "output": output_tokens},
        "estimated_cost_usd": round(cost, 8),
        "estimated_cost_per_1k_output_tokens": round(cost / output_tokens * 1000, 8)
        if output_tokens
        else 0.0,
        "backends": {
            backend: sum(1 for row in successful if row.backend == backend)
            for backend in sorted({row.backend for row in successful})
        },
    }
