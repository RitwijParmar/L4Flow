from __future__ import annotations

import statistics
import threading
from collections import defaultdict
from typing import Any


class Metrics:
    def __init__(self, *, cpu_cost_per_second: float = 0.000018, gpu_cost_per_second: float = 0.0001867) -> None:
        self._lock = threading.Lock()
        self._counters: dict[tuple[str, str], int] = defaultdict(int)
        self._latency_ms: dict[str, list[float]] = defaultdict(list)
        self._reasons: dict[str, int] = defaultdict(int)
        self._tokens: dict[str, int] = defaultdict(int)
        self._route_seconds: dict[str, float] = defaultdict(float)
        self._fallbacks = 0
        self._cpu_cost_per_second = cpu_cost_per_second
        self._gpu_cost_per_second = gpu_cost_per_second

    def request(self, route: str, status: str, latency_ms: float, **kwargs: Any) -> None:
        self.record(route, status, latency_ms, **kwargs)

    def record(
        self,
        route: str,
        status: str,
        latency_ms: float,
        *,
        reason: str = "unknown",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        fallback: bool = False,
    ) -> None:
        with self._lock:
            self._counters[(route, status)] += 1
            self._latency_ms[route].append(latency_ms)
            self._reasons[reason] += 1
            self._tokens["prompt"] += max(0, prompt_tokens)
            self._tokens["completion"] += max(0, completion_tokens)
            self._route_seconds[route] += max(0.0, latency_ms / 1000)
            if fallback:
                self._fallbacks += 1

    @staticmethod
    def _latency_summary(values: list[float]) -> dict[str, float]:
        if not values:
            return {"p50": 0.0, "p95": 0.0, "mean": 0.0, "max": 0.0}
        ordered = sorted(values)
        p50 = ordered[min(len(ordered) - 1, round(0.50 * (len(ordered) - 1)))]
        p95 = ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))]
        return {
            "p50": round(p50, 3),
            "p95": round(p95, 3),
            "mean": round(statistics.mean(values), 3),
            "max": round(max(values), 3),
        }

    def summary(self) -> dict[str, Any]:
        with self._lock:
            total = sum(self._counters.values())
            errors = sum(count for (route, status), count in self._counters.items() if status == "error")
            estimated_cost = sum(
                seconds * (self._gpu_cost_per_second if route == "gpu" else self._cpu_cost_per_second)
                for route, seconds in self._route_seconds.items()
            )
            completion_tokens = self._tokens["completion"]
            return {
                "requests": total,
                "errors": errors,
                "success_rate": round((total - errors) / total, 6) if total else 0.0,
                "fallbacks": self._fallbacks,
                "fallback_rate": round(self._fallbacks / total, 6) if total else 0.0,
                "routes": {
                    route: sum(count for (label, _), count in self._counters.items() if label == route)
                    for route in sorted(self._latency_ms)
                },
                "reasons": dict(sorted(self._reasons.items())),
                "latency_ms": {
                    route: self._latency_summary(values)
                    for route, values in sorted(self._latency_ms.items())
                },
                "tokens": dict(self._tokens),
                "estimated_cost_usd": round(estimated_cost, 8),
                "estimated_cost_per_1k_completion_tokens": round(
                    estimated_cost / completion_tokens * 1000, 8
                ) if completion_tokens else 0.0,
                "cost_model": {
                    "cpu_usd_per_second": self._cpu_cost_per_second,
                    "gpu_usd_per_second": self._gpu_cost_per_second,
                    "note": "estimate from route service time; not a billing export",
                },
            }

    def render(self) -> str:
        lines = [
            "# HELP l4flow_requests_total Completed inference gateway requests.",
            "# TYPE l4flow_requests_total counter",
        ]
        with self._lock:
            for (route, status), count in sorted(self._counters.items()):
                lines.append(f'l4flow_requests_total{{route="{route}",status="{status}"}} {count}')
            lines += [
                "# HELP l4flow_fallbacks_total Requests served by a fallback backend.",
                "# TYPE l4flow_fallbacks_total counter",
                f"l4flow_fallbacks_total {self._fallbacks}",
                "# HELP l4flow_tokens_total Tokens observed by the gateway.",
                "# TYPE l4flow_tokens_total counter",
            ]
            for token_type, count in sorted(self._tokens.items()):
                lines.append(f'l4flow_tokens_total{{type="{token_type}"}} {count}')
            lines += [
                "# HELP l4flow_latency_ms_sum Sum of request latency in milliseconds.",
                "# TYPE l4flow_latency_ms_sum gauge",
            ]
            for route, values in sorted(self._latency_ms.items()):
                lines.append(f'l4flow_latency_ms_sum{{route="{route}"}} {sum(values):.3f}')
                lines.append(
                    f'l4flow_latency_ms_p95{{route="{route}"}} '
                    f'{self._latency_summary(values)["p95"]:.3f}'
                )
            estimated_cost = sum(
                seconds * (self._gpu_cost_per_second if route == "gpu" else self._cpu_cost_per_second)
                for route, seconds in self._route_seconds.items()
            )
            lines += [
                "# HELP l4flow_estimated_cost_usd Estimated route service cost.",
                "# TYPE l4flow_estimated_cost_usd gauge",
                f"l4flow_estimated_cost_usd {estimated_cost:.8f}",
            ]
        return "\n".join(lines) + "\n"
