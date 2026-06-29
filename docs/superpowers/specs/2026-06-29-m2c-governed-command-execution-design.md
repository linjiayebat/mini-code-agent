# M2c Governed Command Execution Design

## Goal

Add a cross-platform, policy-governed `run_command` tool for bounded local development commands
without introducing shell-string parsing or claiming OS sandbox isolation.

## Approaches Considered

### 1. Argv-only local runner (selected)

The model supplies a non-empty executable/argument array. Python uses
`asyncio.create_subprocess_exec`, never `shell=True`. This avoids a second shell grammar,
cross-platform quoting differences, and common interpolation injection. It remains capable of
arbitrary host actions after policy permission, so execution is critical risk and denied by
default.

### 2. PowerShell/POSIX shell adapters

Shell strings are convenient for pipes, redirects, and compound commands, but require separate
grammars, escaping rules, and injection tests. This is deferred until there is a concrete
workflow that cannot be represented as argv calls.

### 3. Container or OS sandbox

Containers, Windows Job Objects/AppContainer, namespaces, seccomp, and restricted tokens offer
stronger isolation but add platform-specific deployment and privilege requirements. They remain
an optional execution backend after the local runner contract is stable.

## Architecture

```text
ToolCall
  -> ToolRegistry Schema validation
  -> RunCommandTool.preview
  -> PolicyEngine (execute defaults to deny)
  -> explicit custom allow/ask rule
  -> interactive approval when ask
  -> CommandRunner
       -> Workspace cwd resolution
       -> minimal inherited environment
       -> subprocess_exec(argv)
       -> concurrent bounded stdout/stderr drain
       -> timeout/output-limit/cancellation process-tree cleanup
  -> correlated structured ToolResult
```

`AgentRuntime` and `GovernedToolExecutor` remain unchanged. The runner owns process lifecycle;
the tool owns model arguments, preview metadata, and JSON results; `WorkspaceBoundary` remains
the only cwd path authority.

## Public Contract

`run_command` arguments:

- `argv`: 1 to 64 strings; executable is non-empty; each value is at most 4,096 characters;
- `cwd`: optional workspace-relative directory, default workspace root;
- `timeout_seconds`: integer from 1 to 300, default 30;
- `reason`: 1 to 500 characters.

There is no shell mode, stdin content, model-provided environment, background execution, or
detached process mode.

The preview has `SideEffect.EXECUTE`, `RiskLevel.CRITICAL`, workspace-relative cwd, bounded reason,
and the exact argv tuple. Execute policy remains `deny` by default. Applications must provide an
explicit rule to ask or allow this tool.

The result contains:

- argv and relative cwd;
- exit code or `null` if unavailable;
- decoded stdout and stderr;
- `timed_out`, `output_limit_exceeded`, and truncation flags;
- bounded duration in milliseconds.

A non-zero process exit code is a successful tool invocation with a failing command result, not
an infrastructure exception. Spawn/path failures return static structured tool errors.

## Resource and Process Controls

- stdin is `DEVNULL`;
- stdout and stderr are always pipes and are drained concurrently;
- total captured output defaults to 1 MiB and has an 8 MiB hard configuration maximum;
- reaching the output budget terminates the process tree instead of draining unbounded output;
- timeout uses monotonic time and terminates the process tree;
- cancellation first cleans the process tree, then re-raises `CancelledError`;
- POSIX starts a new session and signals its process group;
- Windows starts a new process group without a visible console and uses `taskkill /T /F`;
- cleanup has a bounded 5-second default grace period and escalates where supported.

The runner inherits only a small platform allowlist needed to locate and start tools: PATH,
temporary-directory, locale, home, and Windows system variables. API keys and arbitrary project
environment variables are not inherited. No model-supplied environment override is accepted.

## Security Boundary

This is governed process execution, not process isolation. An approved executable can:

- read or write outside the workspace;
- access the network;
- start grandchildren that escape best-effort cleanup;
- inspect host state available to its OS identity;
- print sensitive file content.

Policy, approval, minimal environment, cwd validation, limits, and process-tree cleanup reduce
accidental risk. Hostile code requires a sandbox backend. Command allow/deny decisions cannot be
made safely with a regex blacklist.

## Error Handling

Public errors are static and contain no absolute cwd, environment, raw exception, or secret:

- `invalid_arguments`;
- `invalid_path`, `outside_workspace`, `link_traversal`, `not_found`;
- `command_not_found`;
- `command_start_failed`;
- `command_cleanup_failed`.

Timeout and output-limit termination are structured command outcomes so the model can choose a
smaller command or a larger user-approved timeout without parsing exception text.

## Test Strategy

Unit tests cover schema, preview, cwd policy, environment filtering, normal/non-zero exit,
stdout/stderr, Unicode replacement decoding, timeout, output limit, spawn failure, cancellation,
and static error leakage.

Process-tree tests start a Python child that starts a sleeping grandchild, then verify timeout or
cancellation ends both where the platform permits reliable PID observation. Integration tests
prove default deny, explicit ask plus approval, non-interactive denial, and a full Agent
ToolCall/ToolResult/final response.

Release gates remain Python 3.12/3.13, Ruff, strict Pyright, coverage, Bandit, pip-audit, hashed
build, and wheel/sdist console-script smoke.

## Learning Mapping

- Java `ProcessBuilder(List<String>)` maps to argv-only `create_subprocess_exec`.
- `CompletableFuture` cancellation does not automatically kill an OS process; explicit lifecycle
  ownership is required.
- Flink task timeout/restart policy is analogous to classifying timeout separately from command
  exit failure.
- Backpressure is approximated by bounded pipe draining and termination at the output budget.
- A process group is a lifecycle boundary, not a security principal or sandbox.
