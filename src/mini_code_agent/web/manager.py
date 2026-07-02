from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from uuid import uuid4

from mini_code_agent.agent.events import AgentEvent, EventSink
from mini_code_agent.agent.models import AgentResult
from mini_code_agent.policy.approval import ApprovalHandler
from mini_code_agent.policy.models import ApprovalRequest
from mini_code_agent.web.models import RunDetail, RunSnapshot, WebEvent, WebRunStatus

type TaskRunner = Callable[
    [str, ApprovalHandler, EventSink],
    Awaitable[AgentResult],
]


class RunConflictError(RuntimeError):
    """Raised when a second run is started while one is active."""


class RunNotFoundError(KeyError):
    """Raised when a Web run ID is unknown."""


@dataclass
class _RunState:
    run_id: str
    prompt: str
    status: WebRunStatus = WebRunStatus.RUNNING
    final_text: str | None = None
    error: str | None = None
    events: deque[WebEvent] = field(default_factory=lambda: deque[WebEvent]())
    pending: dict[str, asyncio.Future[bool]] = field(
        default_factory=lambda: dict[str, asyncio.Future[bool]]()
    )
    subscribers: set[asyncio.Queue[None]] = field(
        default_factory=lambda: set[asyncio.Queue[None]]()
    )
    task: asyncio.Task[None] | None = None
    next_sequence: int = 1


class _WebEventSink:
    def __init__(self, manager: WebRunManager, run_id: str) -> None:
        self._manager = manager
        self._run_id = run_id

    def publish(self, event: AgentEvent) -> None:
        self._manager.publish_agent_event(self._run_id, event)


class _WebApprovalHandler:
    def __init__(self, manager: WebRunManager, run_id: str) -> None:
        self._manager = manager
        self._run_id = run_id

    async def approve(self, request: ApprovalRequest) -> bool:
        return await self._manager.request_approval(self._run_id, request)


class WebRunManager:
    def __init__(
        self,
        runner: TaskRunner,
        *,
        max_retained_events: int = 512,
        max_retained_runs: int = 20,
    ) -> None:
        if max_retained_events < 8:
            raise ValueError("max_retained_events must be at least 8")
        if not 1 <= max_retained_runs <= 100:
            raise ValueError("max_retained_runs must be between 1 and 100")
        self._runner = runner
        self._max_retained_events = max_retained_events
        self._max_retained_runs = max_retained_runs
        self._runs: dict[str, _RunState] = {}
        self._run_order: deque[str] = deque()
        self._active_run_id: str | None = None
        self._latest_run_id: str | None = None

    async def start(self, prompt: str) -> RunSnapshot:
        if self._active_run_id is not None:
            active = self._runs[self._active_run_id]
            if active.status is WebRunStatus.RUNNING:
                raise RunConflictError("A run is already active.")

        while len(self._run_order) >= self._max_retained_runs:
            expired_run_id = self._run_order.popleft()
            self._runs.pop(expired_run_id, None)

        run_id = uuid4().hex
        state = _RunState(
            run_id=run_id,
            prompt=prompt,
            events=deque(maxlen=self._max_retained_events),
        )
        self._runs[run_id] = state
        self._run_order.append(run_id)
        self._active_run_id = run_id
        self._latest_run_id = run_id
        self._publish(run_id, "web_run_started", {"status": "running"})
        state.task = asyncio.create_task(
            self._execute(run_id, prompt),
            name=f"mini-code-agent-web-{run_id}",
        )
        return self.snapshot(run_id)

    async def _execute(self, run_id: str, prompt: str) -> None:
        state = self._state(run_id)
        try:
            result = await self._runner(
                prompt,
                _WebApprovalHandler(self, run_id),
                _WebEventSink(self, run_id),
            )
        except asyncio.CancelledError:
            if state.status is WebRunStatus.RUNNING:
                state.status = WebRunStatus.CANCELLED
                self._publish(run_id, "web_run_cancelled", {"status": "cancelled"})
        except Exception:
            state.status = WebRunStatus.FAILED
            state.error = "The Agent run failed. Check the local server logs."
            self._publish(
                run_id,
                "web_run_failed",
                {
                    "status": "failed",
                    "message": state.error,
                },
            )
        else:
            state.status = WebRunStatus.COMPLETED
            state.final_text = result.final_text
            state.error = result.error
            self._publish(
                run_id,
                "web_run_completed",
                {
                    "status": "completed",
                    "stop_reason": result.stop_reason.value,
                    "turns": result.turns,
                    "tool_calls": result.tool_calls,
                    "usage": result.usage.model_dump(mode="json"),
                    "final_text": result.final_text,
                    "error": result.error,
                },
            )
        finally:
            self._reject_pending(state)
            if self._active_run_id == run_id:
                self._active_run_id = None

    async def decide_approval(
        self,
        run_id: str,
        tool_call_id: str,
        approved: bool,
    ) -> bool:
        state = self._runs.get(run_id)
        if state is None or state.status is not WebRunStatus.RUNNING:
            return False
        future = state.pending.pop(tool_call_id, None)
        if future is None or future.done():
            return False
        future.set_result(approved)
        self._publish(
            run_id,
            "approval_resolved",
            {"tool_call_id": tool_call_id, "approved": approved},
        )
        return True

    def publish_agent_event(self, run_id: str, event: AgentEvent) -> None:
        self._publish(
            run_id,
            "agent_event",
            {"event": event.model_dump(mode="json")},
        )

    async def request_approval(
        self,
        run_id: str,
        request: ApprovalRequest,
    ) -> bool:
        state = self._state(run_id)
        tool_call_id = request.preview.tool_call_id
        if tool_call_id in state.pending:
            return False

        future = asyncio.get_running_loop().create_future()
        state.pending[tool_call_id] = future
        self._publish(
            run_id,
            "approval_required",
            request.model_dump(mode="json"),
        )
        try:
            return await future
        finally:
            state.pending.pop(tool_call_id, None)

    async def cancel(self, run_id: str) -> bool:
        state = self._runs.get(run_id)
        if state is None or state.status is not WebRunStatus.RUNNING:
            return False
        state.status = WebRunStatus.CANCELLED
        self._reject_pending(state)
        if state.task is not None and not state.task.done():
            state.task.cancel()
            with suppress(asyncio.CancelledError):
                await state.task
        self._publish(run_id, "web_run_cancelled", {"status": "cancelled"})
        if self._active_run_id == run_id:
            self._active_run_id = None
        return True

    async def wait(self, run_id: str) -> RunSnapshot:
        state = self._state(run_id)
        if state.task is not None:
            with suppress(asyncio.CancelledError):
                await state.task
        return self.snapshot(run_id)

    def snapshot(self, run_id: str) -> RunSnapshot:
        state = self._state(run_id)
        return RunSnapshot(
            run_id=state.run_id,
            status=state.status,
            last_sequence=state.next_sequence - 1,
        )

    def active_snapshot(self) -> RunSnapshot | None:
        if self._active_run_id is None:
            return None
        return self.snapshot(self._active_run_id)

    def latest_snapshot(self) -> RunSnapshot | None:
        if self._latest_run_id is None:
            return None
        return self.snapshot(self._latest_run_id)

    def detail(self, run_id: str) -> RunDetail:
        state = self._state(run_id)
        return RunDetail(
            run_id=state.run_id,
            status=state.status,
            last_sequence=state.next_sequence - 1,
            prompt=state.prompt,
            final_text=state.final_text,
            error=state.error,
        )

    def details(self) -> tuple[RunDetail, ...]:
        return tuple(self.detail(run_id) for run_id in self._run_order)

    def events_after(
        self,
        run_id: str,
        sequence: int = 0,
    ) -> tuple[WebEvent, ...]:
        state = self._state(run_id)
        return tuple(event for event in state.events if event.sequence > sequence)

    async def subscribe(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
    ) -> AsyncIterator[WebEvent]:
        state = self._state(run_id)
        wakeup: asyncio.Queue[None] = asyncio.Queue(maxsize=1)
        state.subscribers.add(wakeup)
        sequence = after_sequence
        try:
            while True:
                pending = self.events_after(run_id, sequence)
                for event in pending:
                    sequence = event.sequence
                    yield event
                if state.status is not WebRunStatus.RUNNING:
                    return
                await wakeup.get()
        finally:
            state.subscribers.discard(wakeup)

    def _publish(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, object],
    ) -> None:
        state = self._state(run_id)
        event = WebEvent(
            sequence=state.next_sequence,
            type=event_type,
            payload=payload,
        )
        state.next_sequence += 1
        state.events.append(event)
        for subscriber in tuple(state.subscribers):
            if subscriber.empty():
                subscriber.put_nowait(None)

    def _state(self, run_id: str) -> _RunState:
        try:
            return self._runs[run_id]
        except KeyError:
            raise RunNotFoundError(run_id) from None

    @staticmethod
    def _reject_pending(state: _RunState) -> None:
        pending = tuple(state.pending.values())
        state.pending.clear()
        for future in pending:
            if not future.done():
                future.set_result(False)
