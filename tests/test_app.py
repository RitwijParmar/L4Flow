from fastapi.testclient import TestClient

from l4flow.app import create_app
from l4flow.backends import MockBackend
from l4flow.config import Settings


def test_chat_completion_returns_routing_headers():
    app = create_app(
        Settings(mode="dry-run"),
        cpu_backend=MockBackend("cpu"),
        gpu_backend=MockBackend("gpu"),
    )
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hello"}], "max_tokens": 32},
        )
    assert response.status_code == 200
    assert response.headers["x-l4flow-route"] == "cpu"
    assert response.headers["x-request-id"]
    assert response.json()["choices"][0]["message"]["role"] == "assistant"


def test_long_request_uses_gpu():
    app = create_app(Settings(mode="dry-run"), cpu_backend=MockBackend("cpu"), gpu_backend=MockBackend("gpu"))
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "x" * 2000}], "max_tokens": 32},
        )
    assert response.status_code == 200
    assert response.headers["x-l4flow-route"] == "gpu"


def test_metrics_summary_exposes_machine_readable_cost_and_latency():
    app = create_app(Settings(mode="dry-run"), cpu_backend=MockBackend("cpu"), gpu_backend=MockBackend("gpu"))
    with TestClient(app) as client:
        client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hello"}], "max_tokens": 32},
        )
        summary = client.get("/metrics/summary").json()
    assert summary["requests"] == 1
    assert summary["success_rate"] == 1.0
    assert "estimated_cost_per_1k_completion_tokens" in summary
