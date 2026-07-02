from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from mini_code_agent.agent.models import AgentResult, StopReason
from mini_code_agent.config import AppSettings
from mini_code_agent.providers.base import TokenUsage
from mini_code_agent.web.app import create_web_app
from mini_code_agent.web.manager import WebRunManager


def settings(tmp_path: Path) -> AppSettings:
    return AppSettings.model_validate(
        {
            "data_dir": tmp_path / "data",
            "provider": "openai_compatible",
            "model": "Pro/zai-org/GLM-4.7",
            "base_url": "https://api.siliconflow.cn/v1",
            "openai_api_key": "server-only-secret",
        }
    )


def result() -> AgentResult:
    return AgentResult(
        run_id="agent-run",
        messages=(),
        stop_reason=StopReason.COMPLETED,
        turns=1,
        tool_calls=0,
        usage=TokenUsage(input_tokens=4, output_tokens=2),
        final_text="Finished.",
    )


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.asyncio
async def test_health_and_bootstrap_expose_status_but_not_secret(tmp_path: Path) -> None:
    async def runner(prompt: str, approval: object, events: object) -> AgentResult:
        del prompt, approval, events
        return result()

    app = create_web_app(
        settings(tmp_path),
        workspace=tmp_path,
        manager=WebRunManager(runner),
        csrf_token="fixed-token",
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1:8765",
    ) as client:
        health = await client.get("/healthz")
        bootstrap = await client.get("/api/bootstrap")

    assert health.json() == {"status": "ok"}
    payload = bootstrap.json()
    assert payload["workspace"] == str(tmp_path.resolve())
    assert payload["provider"] == "openai_compatible"
    assert payload["model"] == "Pro/zai-org/GLM-4.7"
    assert payload["api_key_configured"] is True
    assert payload["csrf_token"] == "fixed-token"
    assert "server-only-secret" not in bootstrap.text


@pytest.mark.asyncio
async def test_mutations_require_token_and_loopback_origin(tmp_path: Path) -> None:
    async def runner(prompt: str, approval: object, events: object) -> AgentResult:
        del prompt, approval, events
        return result()

    app = create_web_app(
        settings(tmp_path),
        workspace=tmp_path,
        manager=WebRunManager(runner),
        csrf_token="fixed-token",
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1:8765",
    ) as client:
        missing = await client.post("/api/runs", json={"prompt": "Inspect"})
        foreign = await client.post(
            "/api/runs",
            json={"prompt": "Inspect"},
            headers={
                "X-Mini-Code-Agent-Token": "fixed-token",
                "Origin": "https://attacker.example",
            },
        )
        accepted = await client.post(
            "/api/runs",
            json={"prompt": "Inspect"},
            headers={
                "X-Mini-Code-Agent-Token": "fixed-token",
                "Origin": "http://localhost:8765",
            },
        )

    assert missing.status_code == 403
    assert foreign.status_code == 403
    assert accepted.status_code == 202


@pytest.mark.asyncio
async def test_start_conflict_cancel_and_sse_replay(tmp_path: Path) -> None:
    release = asyncio.Event()

    async def runner(prompt: str, approval: object, events: object) -> AgentResult:
        del prompt, approval, events
        await release.wait()
        return result()

    manager = WebRunManager(runner)
    app = create_web_app(
        settings(tmp_path),
        workspace=tmp_path,
        manager=manager,
        csrf_token="fixed-token",
    )
    headers = {"X-Mini-Code-Agent-Token": "fixed-token"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1:8765",
    ) as client:
        started = await client.post(
            "/api/runs",
            json={"prompt": "Inspect"},
            headers=headers,
        )
        run_id = started.json()["run_id"]
        conflict = await client.post(
            "/api/runs",
            json={"prompt": "Second"},
            headers=headers,
        )
        cancelled = await client.post(
            f"/api/runs/{run_id}/cancel",
            headers=headers,
        )
        stream = await client.get(f"/api/runs/{run_id}/events?after=0")

    assert started.status_code == 202
    assert conflict.status_code == 409
    assert cancelled.status_code == 200
    assert stream.headers["content-type"].startswith("text/event-stream")
    data_lines = [
        line.removeprefix("data: ")
        for line in stream.text.splitlines()
        if line.startswith("data: ")
    ]
    events = [json.loads(line) for line in data_lines]
    assert [event["type"] for event in events] == [
        "web_run_started",
        "web_run_cancelled",
    ]


@pytest.mark.asyncio
async def test_approval_route_returns_not_found_for_stale_decision(
    tmp_path: Path,
) -> None:
    async def runner(prompt: str, approval: object, events: object) -> AgentResult:
        del prompt, approval, events
        return result()

    manager = WebRunManager(runner)
    app = create_web_app(
        settings(tmp_path),
        workspace=tmp_path,
        manager=manager,
        csrf_token="fixed-token",
    )
    headers = {"X-Mini-Code-Agent-Token": "fixed-token"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1:8765",
    ) as client:
        started = await client.post(
            "/api/runs",
            json={"prompt": "Inspect"},
            headers=headers,
        )
        run_id = started.json()["run_id"]
        await manager.wait(run_id)
        response = await client.post(
            f"/api/runs/{run_id}/approvals/stale",
            json={"approved": True},
            headers=headers,
        )

    assert response.status_code == 409
