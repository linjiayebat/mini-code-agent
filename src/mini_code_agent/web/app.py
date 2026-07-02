from __future__ import annotations

import json
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from importlib import resources
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

from mini_code_agent import __version__
from mini_code_agent.agent.events import EventSink
from mini_code_agent.agent.models import AgentResult
from mini_code_agent.application import run_task
from mini_code_agent.config import AppSettings, ProviderName
from mini_code_agent.policy.approval import ApprovalHandler
from mini_code_agent.policy.models import SessionMode
from mini_code_agent.web.manager import (
    RunConflictError,
    RunNotFoundError,
    WebRunManager,
)
from mini_code_agent.web.models import (
    ApprovalDecisionRequest,
    RunDetail,
    RunSnapshot,
    StartRunRequest,
)

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_STATIC_ROOT = resources.files("mini_code_agent.web").joinpath("static")


def _is_loopback_origin(origin: str) -> bool:
    try:
        parsed = urlsplit(origin)
        return parsed.scheme in {"http", "https"} and parsed.hostname in _LOOPBACK_HOSTS
    except ValueError:
        return False


def create_web_app(
    settings: AppSettings,
    *,
    workspace: Path,
    manager: WebRunManager | None = None,
    csrf_token: str | None = None,
) -> FastAPI:
    workspace_root = workspace.resolve()
    if not workspace_root.is_dir():
        raise ValueError("Workspace must be an existing local directory.")
    token = csrf_token or secrets.token_urlsafe(32)

    async def task_runner(
        prompt: str,
        approval: ApprovalHandler,
        events: EventSink,
    ) -> AgentResult:
        return await run_task(
            settings,
            workspace=workspace_root,
            user_prompt=prompt,
            approval=approval,
            session_mode=SessionMode.INTERACTIVE,
            events=events,
        )

    run_manager = manager or WebRunManager(task_runner)
    app = FastAPI(
        title="Mini CodeAgent Web Console",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.run_manager = run_manager

    async def enforce_local_origin(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin is not None and not _is_loopback_origin(origin):
                return _forbidden_response()
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'"
        )
        return response

    app.middleware("http")(enforce_local_origin)

    def require_token(
        x_mini_code_agent_token: str | None = Header(default=None),
    ) -> None:
        if x_mini_code_agent_token is None or not secrets.compare_digest(
            x_mini_code_agent_token,
            token,
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid local request token.",
            )

    async def health() -> dict[str, str]:
        return {"status": "ok"}

    async def index() -> str:
        return _static_text("index.html")

    async def styles() -> Response:
        return Response(_static_text("styles.css"), media_type="text/css")

    async def javascript() -> Response:
        return Response(
            _static_text("app.js"),
            media_type="text/javascript",
        )

    async def bootstrap() -> dict[str, object]:
        key_configured = (
            settings.openai_api_key is not None
            if settings.provider is ProviderName.OPENAI_COMPATIBLE
            else settings.anthropic_api_key is not None
        )
        active = run_manager.active_snapshot()
        latest = run_manager.latest_snapshot()
        return {
            "version": __version__,
            "workspace": str(workspace_root),
            "provider": settings.provider.value,
            "model": settings.model,
            "api_key_configured": key_configured,
            "csrf_token": token,
            "active_run": active.model_dump(mode="json") if active else None,
            "latest_run": latest.model_dump(mode="json") if latest else None,
        }

    async def run_detail(run_id: str) -> RunDetail:
        try:
            return run_manager.detail(run_id)
        except RunNotFoundError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Run not found.",
            ) from None

    async def run_history() -> list[RunDetail]:
        return list(run_manager.details())

    async def start_run(payload: StartRunRequest) -> RunSnapshot:
        try:
            return await run_manager.start(payload.prompt)
        except RunConflictError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from None

    async def run_events(
        run_id: str,
        after: int = Query(default=0, ge=0),
    ) -> StreamingResponse:
        try:
            run_manager.snapshot(run_id)
        except RunNotFoundError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Run not found.",
            ) from None

        async def stream() -> AsyncIterator[str]:
            async for event in run_manager.subscribe(
                run_id,
                after_sequence=after,
            ):
                data = json.dumps(event.model_dump(mode="json"), separators=(",", ":"))
                yield f"id: {event.sequence}\nevent: {event.type}\ndata: {data}\n\n"

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-store",
                "X-Accel-Buffering": "no",
            },
        )

    async def decide_approval(
        run_id: str,
        tool_call_id: str,
        payload: ApprovalDecisionRequest,
    ) -> dict[str, bool]:
        accepted = await run_manager.decide_approval(
            run_id,
            tool_call_id,
            payload.approved,
        )
        if not accepted:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Approval is stale or no longer pending.",
            )
        return {"accepted": True}

    async def cancel_run(run_id: str) -> dict[str, bool]:
        cancelled = await run_manager.cancel(run_id)
        if not cancelled:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Run is not active.",
            )
        return {"cancelled": True}

    protected_dependencies = [Depends(require_token)]
    app.add_api_route("/healthz", health, methods=["GET"])
    app.add_api_route("/", index, methods=["GET"], response_class=HTMLResponse)
    app.add_api_route("/static/styles.css", styles, methods=["GET"])
    app.add_api_route("/static/app.js", javascript, methods=["GET"])
    app.add_api_route("/api/bootstrap", bootstrap, methods=["GET"])
    app.add_api_route(
        "/api/runs",
        start_run,
        methods=["POST"],
        response_model=RunSnapshot,
        status_code=status.HTTP_202_ACCEPTED,
        dependencies=protected_dependencies,
    )
    app.add_api_route(
        "/api/runs",
        run_history,
        methods=["GET"],
        response_model=list[RunDetail],
        dependencies=protected_dependencies,
    )
    app.add_api_route(
        "/api/runs/{run_id}",
        run_detail,
        methods=["GET"],
        response_model=RunDetail,
        dependencies=protected_dependencies,
    )
    app.add_api_route(
        "/api/runs/{run_id}/events",
        run_events,
        methods=["GET"],
    )
    app.add_api_route(
        "/api/runs/{run_id}/approvals/{tool_call_id}",
        decide_approval,
        methods=["POST"],
        dependencies=protected_dependencies,
    )
    app.add_api_route(
        "/api/runs/{run_id}/cancel",
        cancel_run,
        methods=["POST"],
        dependencies=protected_dependencies,
    )
    return app


def _forbidden_response() -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content={"detail": "Only loopback browser origins are allowed."},
    )


def _static_text(name: str) -> str:
    return _STATIC_ROOT.joinpath(name).read_text(encoding="utf-8")
