import json

import pytest

from l4flow.gate import GateConfig, compare_traces, render_markdown
from l4flow.trace import TraceRow, load_jsonl, summarize


def row(latency: float, *, ttft: float = 20, status: str = "ok", cost: float = 0.001) -> TraceRow:
    return TraceRow(
        trace_id=f"r-{latency}",
        timestamp_s=1.0,
        backend="test",
        status=status,
        latency_ms=latency,
        ttft_ms=ttft,
        input_tokens=10,
        output_tokens=10,
        estimated_cost_usd=cost,
    )


def test_trace_loader_accepts_common_benchmark_aliases(tmp_path):
    path = tmp_path / "trace.jsonl"
    path.write_text(
        json.dumps(
            {
                "request_id": "abc",
                "started_at_s": 3,
                "route": "gpu",
                "status": "200",
                "e2e_latency_ms": 90,
                "ttft_ms": 25,
                "prompt_tokens": 12,
                "completion_tokens": 8,
                "cost_usd": 0.0003,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    loaded = load_jsonl(path)
    assert loaded[0].trace_id == "abc"
    assert loaded[0].backend == "gpu"
    assert summarize(loaded)["tokens"] == {"input": 12, "output": 8}


def test_gate_passes_candidate_with_lower_latency_and_cost():
    report = compare_traces([row(100), row(120)], [row(90, ttft=18, cost=0.0008), row(110, ttft=19, cost=0.0008)])
    assert report["passed"] is True
    assert "ttft_ms.p95" in {check["metric"] for check in report["checks"]}
    assert "PASS" in render_markdown(report)


def test_gate_fails_large_tail_regression():
    report = compare_traces(
        [row(100), row(120)],
        [row(100), row(250)],
        GateConfig(max_p95_latency_regression_percent=10),
    )
    assert report["passed"] is False
    latency_check = next(check for check in report["checks"] if check["metric"] == "latency_ms.p95")
    assert latency_check["passed"] is False


def test_gate_fails_error_delta():
    report = compare_traces([row(100), row(120)], [row(100), row(120, status="error")])
    assert report["passed"] is False


def test_empty_ttft_is_optional():
    report = compare_traces([row(100, ttft=None)], [row(105, ttft=None)])
    assert "ttft_ms.p95" not in {check["metric"] for check in report["checks"]}
