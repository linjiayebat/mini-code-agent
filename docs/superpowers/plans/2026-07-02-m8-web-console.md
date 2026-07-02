# M8 Local Web Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a secure loopback-only Web console for running, observing, approving, and cancelling Mini CodeAgent tasks.

**Architecture:** Add a FastAPI adapter around the existing `run_task`, bridge Agent events and approvals through a bounded in-memory run manager, and serve a dependency-free three-pane frontend from package resources. Keep Provider secrets and Workspace selection exclusively server-side.

**Tech Stack:** Python 3.12/3.13, FastAPI, Uvicorn, asyncio, Pydantic, SSE, HTML, CSS, browser-native JavaScript, pytest, httpx ASGITransport

---

### Task 1: Web Contracts and Run Manager

**Files:**
- Create: `src/mini_code_agent/web/__init__.py`
- Create: `src/mini_code_agent/web/models.py`
- Create: `src/mini_code_agent/web/manager.py`
- Create: `tests/unit/web/__init__.py`
- Create: `tests/unit/web/test_models.py`
- Create: `tests/unit/web/test_manager.py`

- [ ] **Step 1: Write failing model and lifecycle tests**

Specify bounded `StartRunRequest`, `ApprovalDecisionRequest`, `WebEvent`, `RunSnapshot`, and
`WebRunManager`. Tests assert one active run, monotonic sequence values, terminal result events,
and no prompt or API-key values in lifecycle payloads.

- [ ] **Step 2: Verify RED**

Run:

```powershell
python -m pytest tests/unit/web/test_models.py tests/unit/web/test_manager.py -q
```

Expected: collection fails because `mini_code_agent.web` does not exist.

- [ ] **Step 3: Implement models and basic run lifecycle**

Use frozen Pydantic models with bounded strings. The manager accepts an injected async runner:

```python
type TaskRunner = Callable[
    [str, ApprovalHandler, EventSink],
    Awaitable[AgentResult],
]
```

Publish `web_run_started`, normalized `agent_event`, and `web_run_completed` envelopes into a
bounded retained deque and subscriber queues.

- [ ] **Step 4: Verify GREEN**

Run the Task 1 tests and expect all to pass.

### Task 2: Browser Approval and Cancellation

**Files:**
- Modify: `src/mini_code_agent/web/manager.py`
- Modify: `tests/unit/web/test_manager.py`

- [ ] **Step 1: Write failing approval tests**

Start a runner that calls `approval.approve()`. Assert the manager publishes a bounded
`approval_required` event, ignores unknown decisions, resolves approve/reject once, and rejects a
second decision.

- [ ] **Step 2: Verify RED**

Run the approval tests and expect missing `decide_approval`.

- [ ] **Step 3: Implement pending approval ownership**

Store one Future per `(run_id, tool_call_id)`. Remove it before resolving. Cancellation resolves
pending approvals as rejected, cancels the task, awaits task completion, and emits one terminal
event.

- [ ] **Step 4: Verify GREEN**

Run manager tests and expect all to pass.

### Task 3: FastAPI Application and Security

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Create: `src/mini_code_agent/web/app.py`
- Create: `tests/unit/web/test_app.py`

- [ ] **Step 1: Add FastAPI runtime dependency**

Add:

```toml
"fastapi>=0.116,<1",
"uvicorn>=0.34,<1",
```

Run `uv lock` and `uv sync --locked --all-groups`.

- [ ] **Step 2: Write failing ASGI tests**

Using `httpx.ASGITransport`, assert bootstrap redacts keys, health works, mutating requests require
the token, non-loopback Origin is rejected, one run starts, a second conflicts, SSE replays, and
approval/cancel routes delegate to the manager.

- [ ] **Step 3: Verify RED**

Run `python -m pytest tests/unit/web/test_app.py -q`.

Expected: import failure because `web.app` does not exist.

- [ ] **Step 4: Implement the application factory**

Create:

```python
def create_web_app(
    settings: AppSettings,
    *,
    workspace: Path,
    manager: WebRunManager | None = None,
    csrf_token: str | None = None,
) -> FastAPI:
    ...
```

Use fixed static resource routes and `StreamingResponse` with `text/event-stream`.

- [ ] **Step 5: Verify GREEN**

Run all Web unit tests.

### Task 4: Three-Pane Frontend

**Files:**
- Create: `src/mini_code_agent/web/static/index.html`
- Create: `src/mini_code_agent/web/static/styles.css`
- Create: `src/mini_code_agent/web/static/app.js`
- Create: `tests/unit/web/test_static.py`

- [ ] **Step 1: Write failing static contract tests**

Assert the package contains the three files, no external CDN references, no inline API key field,
required landmarks and controls exist, and JavaScript uses `textContent` rather than dynamic
`innerHTML`.

- [ ] **Step 2: Verify RED**

Run static tests and expect missing resources.

- [ ] **Step 3: Implement semantic HTML and stable layout**

Create the top bar, session rail, transcript, composer, inspector tabs, activity timeline,
approval panel, diff viewer, empty/error/running states, and mobile inspector drawer.

- [ ] **Step 4: Implement browser behavior**

Fetch bootstrap, start tasks, consume SSE, render events, submit approval decisions, cancel the
active run, reconnect by sequence, and update stable control states.

- [ ] **Step 5: Verify GREEN**

Run static and ASGI tests.

### Task 5: Web CLI

**Files:**
- Modify: `src/mini_code_agent/cli.py`
- Modify: `tests/cli/test_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Patch `uvicorn.run` and `webbrowser.open`. Assert `web` forwards the app, host, port, and log level;
rejects non-loopback hosts; supports `--no-open`; and maps configuration errors to exit code 2.

- [ ] **Step 2: Verify RED**

Run CLI tests and expect no `web` command.

- [ ] **Step 3: Implement `mini-code-agent web`**

Load settings, create the Web app, optionally open the loopback URL, and run Uvicorn. Permit only
`127.0.0.1`, `localhost`, and `::1`.

- [ ] **Step 4: Verify GREEN**

Run CLI and Web tests.

### Task 6: Documentation and Release Metadata

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `config.example.toml`
- Create: `docs/learning/m8-web-console.md`
- Create: `docs/resume/m8-web-console-profile.md`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: version assertions under `tests/`

- [ ] **Step 1: Document local launch**

Document environment-only API key setup, `mini-code-agent web --workspace .`, loopback boundary,
approval flow, cancellation, and current limitations.

- [ ] **Step 2: Add learning and interview material**

Explain SSE, Future-based approval, CSRF, loopback binding, server/browser trust boundaries, and
Java/Spring mappings. Add resume-safe highlights with code/test evidence and no invented metrics.

- [ ] **Step 3: Bump version**

Set package version and assertions to `0.18.0a0`.

- [ ] **Step 4: Verify focused suite**

Run all Web, CLI, package, and runtime-info tests.

### Task 7: Browser and Full Verification

**Files:**
- Verify only

- [ ] **Step 1: Run quality gates**

```powershell
python -m ruff format --check .
python -m ruff check .
pyright --pythonpath .\.venv\Scripts\python.exe
python -m pytest --cov -q
```

Expected: zero format/lint/type errors, all runnable tests pass, coverage remains above 85%.

- [ ] **Step 2: Start the local server**

Launch `mini-code-agent web --workspace . --config config.example.toml --no-open` in a hidden
background process on a free loopback port.

- [ ] **Step 3: Browser QA**

Use the in-app browser at 1440x1024, 1024x768, and 390x844. Verify nonblank pixels, fixed layout,
no overlap, responsive collapse, tabs, composer, simulated run events, approval state, and diff.

- [ ] **Step 4: Final safety review**

Confirm no API key in Git diff, no remote bind, no CORS, no dynamic HTML injection, no browser
Workspace input, bounded queues, single-use approvals, and clean shutdown.
