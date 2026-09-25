from l4flow.metrics import Metrics


def test_summary_tracks_routes_fallbacks_tokens_and_cost():
    metrics = Metrics(cpu_cost_per_second=1.0, gpu_cost_per_second=2.0)
    metrics.record(
        "gpu",
        "ok",
        100,
        reason="prompt_over_cpu_budget",
        prompt_tokens=40,
        completion_tokens=20,
    )
    metrics.record(
        "cpu",
        "ok",
        50,
        reason="gpu_inflight_limit",
        prompt_tokens=10,
        completion_tokens=10,
        fallback=True,
    )
    summary = metrics.summary()
    assert summary["requests"] == 2
    assert summary["fallback_rate"] == 0.5
    assert summary["tokens"] == {"prompt": 50, "completion": 30}
    assert summary["estimated_cost_usd"] == 0.25
    assert summary["latency_ms"]["gpu"]["p95"] == 100.0


def test_prometheus_render_does_not_deadlock_or_drop_cost():
    metrics = Metrics()
    metrics.record("gpu", "ok", 10, completion_tokens=4)
    rendered = metrics.render()
    assert "l4flow_requests_total" in rendered
    assert "l4flow_latency_ms_p95{route=\"gpu\"}" in rendered
    assert "l4flow_estimated_cost_usd" in rendered
