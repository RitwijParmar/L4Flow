from l4flow.benchmark import make_payload, render_markdown


def test_workload_contains_short_medium_and_long_classes():
    payloads = [make_payload(index) for index in range(3)]
    assert [payload["_l4flow_workload_class"] for payload in payloads] == ["short", "medium", "long"]
    assert payloads[0]["max_tokens"] < payloads[2]["max_tokens"]


def test_markdown_report_contains_resume_metrics():
    report = {
        "generated_at": "2026-09-25T00:00:00+00:00",
        "url": "https://example.test",
        "requests": 10,
        "concurrency": 2,
        "policies": {
            "auto": {
                "failure_rate": 0.0,
                "latency_ms": {"p50": 10.0, "p95": 20.0},
                "completion_tokens_per_second": 30.0,
                "route_mix": {"gpu": 0.5},
                "estimated_cost_per_1k_completion_tokens": 0.001,
            }
        },
    }
    rendered = render_markdown(report)
    assert "p95 ms" in rendered
    assert "GPU share" in rendered
    assert "50.0%" in rendered
