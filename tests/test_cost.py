from l4flow.cost import RateCard, analyze_trace, summarize_cost


def rate_card() -> RateCard:
    return RateCard.from_mapping(
        {
            "name": "test-card",
            "source_url": "https://example.test/rates",
            "region": "test",
            "currency": "USD",
            "billing_model": "request-based",
            "billing_quantum_seconds": 0.1,
            "free_tier_enabled": False,
            "rates": {
                "cpu_vcpu_second_usd": 1.0,
                "memory_gib_second_usd": 0.0,
                "l4_gpu_second_usd": 10.0,
            },
            "profiles": {"cpu": {"vcpus": 1, "memory_gib": 0, "l4_gpus": 0}},
            "backend_profiles": {"local-transformers": "cpu"},
        }
    )


def test_shared_resource_group_is_charged_once():
    rows = [
        {
            "trace_id": "a",
            "strategy": "batch2",
            "resource_group": "batch-1",
            "backend": "local-transformers",
            "status": "ok",
            "latency_ms": 8,
            "output_tokens": 8,
        },
        {
            "trace_id": "b",
            "strategy": "batch2",
            "resource_group": "batch-1",
            "backend": "local-transformers",
            "status": "ok",
            "latency_ms": 8,
            "output_tokens": 8,
        },
    ]
    summary = summarize_cost(rows, rate_card())
    assert summary["resource_groups"] == 1
    assert summary["resource_seconds"]["cpu_vcpu_seconds"] == 0.1
    assert summary["gross_cost_usd"] == 0.1


def test_cost_analyzer_recommends_cheapest_slo_passing_strategy():
    rows = []
    for strategy, group_count, latency in (("batch2", 1, 8), ("batch8", 2, 30)):
        for index in range(group_count):
            rows.append(
                {
                    "trace_id": f"{strategy}-{index}",
                    "strategy": strategy,
                    "resource_group": f"{strategy}-group-{index}",
                    "backend": "local-transformers",
                    "status": "ok",
                    "latency_ms": latency,
                    "output_tokens": 8,
                }
            )
    report = analyze_trace(rows, rate_card(), p95_slo_ms=20, requests_per_day=100, budget_usd=1)
    assert report["recommendation"]["strategy"] == "batch2"
    assert report["strategies"]["batch8"]["slo"]["passed"] is False
    assert report["strategies"]["batch2"]["forecast"]["status"] == "over_budget"
