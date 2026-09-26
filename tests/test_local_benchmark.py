from benchmarks.local_reference import aggregate_strategy, summarize_strategy


def test_repeated_benchmark_aggregates_ci_and_slo():
    trials = [
        summarize_strategy("micro_batch_4", 4, 4, [8, 8, 9, 9], 32, 0.04, 0),
        summarize_strategy("micro_batch_4", 4, 4, [9, 9, 10, 10], 32, 0.05, 1),
    ]
    rows = [
        {"latency_ms": latency}
        for latency in [8, 8, 9, 9, 9, 9, 10, 10]
    ]
    report = aggregate_strategy("micro_batch_4", trials, rows, 12, 19)
    assert report["requests"] == 8
    assert report["latency_ms"]["p95"] == 10
    assert report["slo"]["trial_pass_rate"] == 1.0
    assert report["trial_throughput_ci95"][0] <= report["trial_throughput_ci95"][1]
