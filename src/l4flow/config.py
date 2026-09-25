from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    mode: str = "dry-run"
    cpu_backend_url: str = ""
    gpu_backend_url: str = ""
    gpu_backend_audience: str = ""
    gpu_backend_auth: str = "none"
    cpu_prompt_token_limit: int = 350
    cpu_output_token_limit: int = 256
    gpu_max_inflight: int = 4
    fallback_to_cpu: bool = True

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            mode=os.getenv("L4FLOW_MODE", "dry-run"),
            cpu_backend_url=os.getenv("CPU_BACKEND_URL", "").rstrip("/"),
            gpu_backend_url=os.getenv("GPU_BACKEND_URL", "").rstrip("/"),
            gpu_backend_audience=os.getenv("GPU_BACKEND_AUDIENCE", "").rstrip("/"),
            gpu_backend_auth=os.getenv("GPU_BACKEND_AUTH", "none"),
            cpu_prompt_token_limit=int(os.getenv("CPU_PROMPT_TOKEN_LIMIT", "350")),
            cpu_output_token_limit=int(os.getenv("CPU_OUTPUT_TOKEN_LIMIT", "256")),
            gpu_max_inflight=max(1, int(os.getenv("GPU_MAX_INFLIGHT", "4"))),
            fallback_to_cpu=_bool("FALLBACK_TO_CPU", True),
        )
