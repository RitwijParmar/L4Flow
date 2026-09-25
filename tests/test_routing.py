from l4flow.routing import RoutingConfig, choose_route, estimate_tokens


def test_token_estimate_is_deterministic():
    assert estimate_tokens("12345678") == 2


def test_small_request_uses_cpu_first():
    decision = choose_route(
        {"messages": [{"role": "user", "content": "hello"}], "max_tokens": 64},
        config=RoutingConfig(),
    )
    assert decision.route == "cpu"
    assert decision.reason == "small_request_cpu_first"


def test_long_prompt_uses_gpu():
    decision = choose_route(
        {"messages": [{"role": "user", "content": "x" * 2000}], "max_tokens": 64},
        config=RoutingConfig(),
    )
    assert decision.route == "gpu"
    assert decision.reason == "prompt_over_cpu_budget"


def test_gpu_saturation_falls_back_for_small_request():
    decision = choose_route(
        {"messages": [{"role": "user", "content": "hello"}], "max_tokens": 64},
        config=RoutingConfig(gpu_max_inflight=2),
        gpu_inflight=2,
    )
    assert decision.route == "cpu"
    assert decision.reason == "gpu_inflight_limit"


def test_explicit_override_wins():
    decision = choose_route(
        {"messages": [{"role": "user", "content": "hello"}]},
        config=RoutingConfig(),
        override="gpu",
    )
    assert decision.route == "gpu"
    assert decision.reason == "explicit_override"


def test_configured_gpu_handles_requests_when_cpu_is_missing():
    decision = choose_route(
        {"messages": [{"role": "user", "content": "hello"}]},
        config=RoutingConfig(),
        cpu_ready=False,
        gpu_ready=True,
    )
    assert decision.route == "gpu"
    assert decision.reason == "cpu_not_configured"
