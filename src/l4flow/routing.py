from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

Route = Literal["cpu", "gpu"]


@dataclass(frozen=True)
class RoutingConfig:
    cpu_prompt_token_limit: int = 350
    cpu_output_token_limit: int = 256
    gpu_max_inflight: int = 4


@dataclass(frozen=True)
class RouteDecision:
    route: Route
    reason: str
    estimated_prompt_tokens: int
    requested_output_tokens: int
    gpu_inflight: int


def estimate_tokens(value: Any) -> int:
    """Cheap, deterministic token estimate used before model tokenization."""
    if value is None:
        return 0
    if isinstance(value, str):
        return max(1, math.ceil(len(value) / 4))
    if isinstance(value, dict):
        return sum(estimate_tokens(k) + estimate_tokens(v) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return sum(estimate_tokens(item) for item in value)
    return estimate_tokens(str(value))


def prompt_tokens(payload: dict[str, Any]) -> int:
    return estimate_tokens(payload.get("messages", []))


def choose_route(
    payload: dict[str, Any],
    *,
    config: RoutingConfig,
    cpu_ready: bool = True,
    gpu_ready: bool = True,
    gpu_inflight: int = 0,
    override: str | None = None,
) -> RouteDecision:
    estimated = prompt_tokens(payload)
    requested_output = int(payload.get("max_tokens") or payload.get("max_completion_tokens") or 256)

    if override in {"cpu", "gpu"}:
        route = override
        reason = "explicit_override"
    elif not cpu_ready and gpu_ready:
        route = "gpu"
        reason = "cpu_not_configured"
    elif not gpu_ready:
        route = "cpu"
        reason = "gpu_not_ready"
    elif estimated > config.cpu_prompt_token_limit:
        route = "gpu"
        reason = "prompt_over_cpu_budget"
    elif requested_output > config.cpu_output_token_limit:
        route = "gpu"
        reason = "output_over_cpu_budget"
    elif gpu_inflight >= config.gpu_max_inflight:
        route = "cpu"
        reason = "gpu_inflight_limit"
    else:
        route = "cpu"
        reason = "small_request_cpu_first"

    return RouteDecision(
        route=route,
        reason=reason,
        estimated_prompt_tokens=estimated,
        requested_output_tokens=requested_output,
        gpu_inflight=gpu_inflight,
    )
