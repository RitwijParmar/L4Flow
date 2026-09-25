from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx


class BackendError(RuntimeError):
    """An inference backend could not complete a request."""


class Backend:
    name: str

    async def complete(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    async def ready(self) -> bool:
        return True


@dataclass
class MockBackend(Backend):
    name: str

    async def complete(self, payload: dict[str, Any]) -> dict[str, Any]:
        messages = payload.get("messages") or []
        last = messages[-1].get("content", "") if messages else ""
        prompt = str(last).replace("\n", " ").strip()
        answer = f"[{self.name}] routed {max(1, len(prompt) // 4)} estimated prompt tokens"
        return {
            "id": f"mock-{self.name}",
            "object": "chat.completion",
            "created": 0,
            "model": payload.get("model", "l4flow-mock"),
            "choices": [{"index": 0, "message": {"role": "assistant", "content": answer}, "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": max(1, len(prompt) // 4),
                "completion_tokens": max(1, len(answer) // 4),
                "total_tokens": max(2, (len(prompt) + len(answer)) // 4),
            },
        }


class HTTPBackend(Backend):
    def __init__(
        self,
        name: str,
        base_url: str,
        *,
        audience: str = "",
        auth_mode: str = "none",
        timeout_s: float = 120.0,
    ) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.audience = audience
        self.auth_mode = auth_mode
        self.timeout = httpx.Timeout(timeout_s, connect=10.0)

    async def _headers(self) -> dict[str, str]:
        if self.auth_mode != "id_token" or not self.audience:
            return {}
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.id_token import fetch_id_token

            token = await asyncio.to_thread(fetch_id_token, Request(), self.audience)
            return {"Authorization": f"Bearer {token}"}
        except Exception as exc:  # pragma: no cover - requires live GCP metadata
            raise BackendError(f"could not obtain Cloud Run identity token: {exc}") from exc

    async def complete(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.base_url:
            raise BackendError(f"{self.name} backend URL is not configured")
        headers = await self._headers()
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(f"{self.base_url}/v1/chat/completions", json=payload, headers=headers)
                response.raise_for_status()
                return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise BackendError(f"{self.name} backend request failed: {exc}") from exc

    async def ready(self) -> bool:
        if not self.base_url:
            return False
        try:
            headers = await self._headers()
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/health", headers=headers)
                return response.is_success
        except (BackendError, httpx.HTTPError):
            return False


def build_backends(settings: Any) -> tuple[Backend, Backend]:
    if settings.mode == "dry-run":
        return MockBackend("cpu"), MockBackend("gpu")
    return (
        HTTPBackend("cpu", settings.cpu_backend_url),
        HTTPBackend(
            "gpu",
            settings.gpu_backend_url,
            audience=settings.gpu_backend_audience,
            auth_mode=settings.gpu_backend_auth,
        ),
    )
