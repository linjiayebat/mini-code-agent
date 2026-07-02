# M7 CLI Provider Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add provider-backed `run` and `chat` commands that make the existing governed Agent runtime usable with SiliconFlow.

**Architecture:** Extend immutable settings with provider connection metadata, then add a small application composition root and terminal adapters. Keep Typer commands thin, preserve secure policy defaults, and inject fakes at module boundaries for deterministic tests.

**Tech Stack:** Python 3.12+, Pydantic Settings, Typer, Rich, httpx, pytest, pytest-asyncio

---

### Task 1: Provider Runtime Configuration

**Files:**
- Modify: `src/mini_code_agent/config.py`
- Modify: `tests/unit/test_config.py`

- [x] **Step 1: Write failing configuration tests**

Add tests that load `provider`, `model`, and `base_url` from TOML and override them with
`MINI_CODE_AGENT_PROVIDER`, `MINI_CODE_AGENT_MODEL`, and `MINI_CODE_AGENT_BASE_URL`. Assert that
`safe_dict` exposes only non-secret provider metadata.

- [x] **Step 2: Verify the tests fail**

Run: `python -m pytest tests/unit/test_config.py -q`

Expected: failure because `ProviderName` and the new settings fields do not exist.

- [x] **Step 3: Implement the minimal settings fields**

Add `ProviderName`, optional `model`, optional `base_url`, matching environment fields, bounded
validation, and secret-safe rendering.

- [x] **Step 4: Verify the tests pass**

Run: `python -m pytest tests/unit/test_config.py -q`

Expected: all configuration tests pass.

### Task 2: Application Composition Root

**Files:**
- Create: `src/mini_code_agent/application.py`
- Create: `tests/unit/test_application.py`

- [x] **Step 1: Write failing provider factory tests**

Specify `ApplicationConfigurationError`, `build_provider`, and `build_tool_executor`. Cover
SiliconFlow URL/model propagation through `httpx.MockTransport`, missing provider credentials,
the Anthropic selection, registered tool names, and the execute ask policy.

- [x] **Step 2: Verify the tests fail**

Run: `python -m pytest tests/unit/test_application.py -q`

Expected: import failure because `application.py` does not exist.

- [x] **Step 3: Implement provider and tool composition**

Create providers from `AppSettings`, build the bounded workspace tool registry, add an explicit
`ASK` policy rule for `run_command`, and return a governed executor.

- [x] **Step 4: Add and verify the async task runner tests**

Use `ScriptedProvider` and an injected provider factory to prove success, failure propagation, and
provider closure without network access.

- [x] **Step 5: Run the application tests**

Run: `python -m pytest tests/unit/test_application.py -q`

Expected: all application tests pass.

### Task 3: Terminal Adapters

**Files:**
- Create: `src/mini_code_agent/terminal.py`
- Create: `tests/unit/test_terminal.py`

- [x] **Step 1: Write failing approval and event rendering tests**

Specify a callback-injected `TerminalApprovalHandler` and `TerminalEventSink`. Assert that action
summaries, resources, argv, and diffs are shown, the callback decision is returned, and event
output contains no prompt or tool payload.

- [x] **Step 2: Verify the tests fail**

Run: `python -m pytest tests/unit/test_terminal.py -q`

Expected: import failure because `terminal.py` does not exist.

- [x] **Step 3: Implement bounded Rich terminal rendering**

Render approval previews and compact lifecycle status. Keep all model-controlled values bounded
by their existing Pydantic models.

- [x] **Step 4: Verify the tests pass**

Run: `python -m pytest tests/unit/test_terminal.py -q`

Expected: all terminal tests pass.

### Task 4: Run and Chat Commands

**Files:**
- Modify: `src/mini_code_agent/cli.py`
- Modify: `tests/cli/test_cli.py`

- [x] **Step 1: Write failing `run` command tests**

Patch the async application boundary, invoke Typer, and assert final text, summary, workspace
forwarding, non-interactive mode, configuration exit code two, and Agent failure exit code one.

- [x] **Step 2: Verify the run tests fail**

Run: `python -m pytest tests/cli/test_cli.py -q`

Expected: failure because the `run` command does not exist.

- [x] **Step 3: Implement `run`**

Load settings, configure logging, construct terminal adapters, execute the coroutine through
`asyncio.run`, render the result, and map errors to exit codes.

- [x] **Step 4: Write failing `chat` command tests**

Patch prompts with two tasks followed by `/exit`; assert two application calls and no call for an
empty prompt.

- [x] **Step 5: Verify the chat tests fail**

Run: `python -m pytest tests/cli/test_cli.py -q`

Expected: failure because the `chat` command does not exist.

- [x] **Step 6: Implement `chat`**

Reuse the same settings, workspace, system prompt, and rendering helpers for each independent
bounded run. Handle `/exit`, `/quit`, EOF, and Ctrl+C without a traceback.

- [x] **Step 7: Verify all CLI tests pass**

Run: `python -m pytest tests/cli/test_cli.py -q`

Expected: all CLI tests pass.

### Task 5: Documentation and Release Metadata

**Files:**
- Modify: `config.example.toml`
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `pyproject.toml`
- Modify: `src/mini_code_agent/__init__.py`
- Modify: `tests/cli/test_cli.py`

- [x] **Step 1: Document SiliconFlow configuration**

Add PowerShell environment setup, the exact base URL, model placeholder, `run`, `chat`, approval,
and live-smoke instructions. State that CI does not use live credentials.

- [x] **Step 2: Bump the alpha version**

Set the package and module version to `0.17.0a0`, update the CLI assertion, and add a changelog
entry.

- [x] **Step 3: Run focused checks**

Run: `python -m pytest tests/unit/test_config.py tests/unit/test_application.py tests/unit/test_terminal.py tests/cli/test_cli.py -q`

Expected: all focused tests pass.

### Task 6: Full Verification

**Files:**
- Verify only

- [x] **Step 1: Format and lint**

Run: `python -m ruff format --check .`

Expected: exit zero.

Run: `python -m ruff check .`

Expected: exit zero.

- [x] **Step 2: Type-check**

Run: `python -m pyright`

Expected: zero errors.

- [x] **Step 3: Run the full test suite**

Prepend `.venv/Scripts` to `PATH`, then run: `python -m pytest -q`

Expected: all runnable tests pass; Windows privilege-dependent symlink tests may skip.

- [x] **Step 4: Run CLI smoke checks**

Run: `mini-code-agent --version`

Expected: `0.17.0a0`.

Run: `mini-code-agent run "Inspect this project" --non-interactive` without a model/key.

Expected: exit two with an actionable configuration error and no traceback or secret.

- [x] **Step 5: Review the diff**

Run: `git diff --check` and `git status --short`.

Expected: no whitespace errors and only M7 files are changed.
