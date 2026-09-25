from __future__ import annotations

import time
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from .backends import Backend, BackendError, build_backends
from .config import Settings
from .metrics import Metrics
from .routing import RoutingConfig, choose_route


def _validate_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("request body must be a JSON object")
    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages must be a non-empty list")
    for message in messages:
        if not isinstance(message, dict) or "role" not in message or "content" not in message:
            raise ValueError("each message requires role and content")
    return payload


def create_app(
    settings: Settings | None = None,
    *,
    cpu_backend: Backend | None = None,
    gpu_backend: Backend | None = None,
) -> FastAPI:
    cfg = settings or Settings.from_env()
    default_cpu, default_gpu = build_backends(cfg)
    cpu = cpu_backend or default_cpu
    gpu = gpu_backend or default_gpu
    metrics = Metrics()
    routing_config = RoutingConfig(
        cpu_prompt_token_limit=cfg.cpu_prompt_token_limit,
        cpu_output_token_limit=cfg.cpu_output_token_limit,
        gpu_max_inflight=cfg.gpu_max_inflight,
    )
    state = {"gpu_inflight": 0}
    app = FastAPI(title="L4Flow Inference Gateway", version="0.1.0")

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        cpu_ready = await cpu.ready()
        gpu_ready = await gpu.ready()
        return {
            "status": "ok",
            "mode": cfg.mode,
            "cpu_ready": cpu_ready,
            "gpu_ready": gpu_ready,
            "gpu_inflight": state["gpu_inflight"],
        }

    @app.get("/metrics")
    async def metrics_endpoint() -> PlainTextResponse:
        return PlainTextResponse(metrics.render(), media_type="text/plain; version=0.0.4")

    @app.get("/metrics/summary")
    async def metrics_summary() -> dict[str, Any]:
        return metrics.summary()

    @app.get("/v1/models")
    async def models() -> dict[str, Any]:
        return {"object": "list", "data": [{"id": "l4flow-router", "object": "model", "owned_by": "l4flow"}]}

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request) -> JSONResponse:
        started = time.perf_counter()
        request_id = request.headers.get("x-request-id", uuid4().hex)
        try:
            payload = _validate_payload(await request.json())
        except (ValueError, TypeError) as exc:
            return JSONResponse(
                {"error": {"message": str(exc), "type": "invalid_request_error"}},
                headers={"x-request-id": request_id},
                status_code=400,
            )

        override = request.headers.get("x-l4flow-route", "auto").lower()
        # Do not probe the GPU service on every request: a probe can itself wake a
        # scale-to-zero GPU instance. Backend failures are handled below.
        cpu_ready = cfg.mode == "dry-run" or bool(getattr(cpu, "base_url", ""))
        gpu_ready = cfg.mode == "dry-run" or bool(getattr(gpu, "base_url", ""))
        decision = choose_route(
            payload,
            config=routing_config,
            cpu_ready=cpu_ready,
            gpu_ready=gpu_ready,
            gpu_inflight=state["gpu_inflight"],
            override=None if override == "auto" else override,
        )
        backend = gpu if decision.route == "gpu" else cpu
        actual_route = decision.route
        fallback = False

        if decision.route == "gpu":
            state["gpu_inflight"] += 1
        try:
            try:
                result = await backend.complete(payload)
            except BackendError as exc:
                if decision.route != "gpu" or not cfg.fallback_to_cpu:
                    latency = (time.perf_counter() - started) * 1000
                    metrics.record(
                        decision.route,
                        "error",
                        latency,
                        reason=decision.reason,
                        prompt_tokens=decision.estimated_prompt_tokens,
                    )
                    return JSONResponse(
                        {"error": {"message": str(exc), "type": "backend_error"}},
                        headers={"x-request-id": request_id},
                        status_code=503,
                    )
                try:
                    result = await cpu.complete(payload)
                except BackendError as fallback_exc:
                    latency = (time.perf_counter() - started) * 1000
                    metrics.record(
                        "cpu",
                        "error",
                        latency,
                        reason=f"{decision.reason}:fallback_failed",
                        prompt_tokens=decision.estimated_prompt_tokens,
                        fallback=True,
                    )
                    return JSONResponse(
                        {
                            "error": {
                                "message": f"GPU backend failed: {exc}; CPU fallback failed: {fallback_exc}",
                                "type": "backend_error",
                            }
                        },
                        headers={"x-request-id": request_id, "x-l4flow-fallback": "true"},
                        status_code=503,
                    )
                actual_route = "cpu"
                fallback = True
        finally:
            if decision.route == "gpu":
                state["gpu_inflight"] -= 1

        latency = (time.perf_counter() - started) * 1000
        usage = result.get("usage") or {}
        metrics.record(
            actual_route,
            "ok",
            latency,
            reason=decision.reason,
            prompt_tokens=int(usage.get("prompt_tokens") or decision.estimated_prompt_tokens),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            fallback=fallback,
        )
        headers = {
            "x-request-id": request_id,
            "x-l4flow-route": actual_route,
            "x-l4flow-reason": decision.reason,
            "x-l4flow-estimated-prompt-tokens": str(decision.estimated_prompt_tokens),
            "x-l4flow-latency-ms": f"{latency:.2f}",
        }
        if fallback:
            headers["x-l4flow-fallback"] = "true"
        return JSONResponse(result, headers=headers)

    return app


app = create_app()
