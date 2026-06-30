# M4c Bounded Repair Loop Design

## Goal

Add a host-controlled, bounded repair workflow that combines one existing Agent repair attempt,
hardened Git evidence, and governed Pytest diagnostics without turning the ordinary
`AgentRuntime` into a repair-specific state machine.

M4c completes this sequence:

```text
approve session
  -> validate clean repository and exact edit scope
  -> run baseline tests
  -> ask one Agent worker for one repair attempt
  -> validate the resulting Git state and diff budget
  -> rerun the same host-owned tests
  -> succeed, stop safely, or repeat within fixed budgets
```

The implementation is a library API. It does not add a production CLI command, live-provider CI,
automatic commit, rollback, new-file creation, dirty-tree repair, shell-string execution, or an OS
sandbox.

## Approaches Considered

### Extend `AgentRuntime` with repair state

The existing runtime already owns model turns and ToolCalls, so it could count `run_tests` calls
and writes. This couples every normal Agent run to Pytest-specific semantics, lets the model choose
when verification occurs, and makes deterministic stopping depend on parsing model-selected tool
history. Rejected.

### Wrap the Tool executor only

A middleware can restrict write resources and count actions, but it cannot guarantee a baseline
test, compare pre-test and post-test repository state, or terminate the outer model loop when a
failure fingerprint repeats. Useful as one control, but insufficient as the workflow owner.

### Add an outer `RepairRuntime`

The selected design keeps `AgentRuntime` as one repair worker and adds a separate deterministic
coordinator. The coordinator owns approval, test timing, Git validation, attempt budgets, failure
fingerprints, and terminal status. A policy action guard prevents the worker from writing outside
the approved exact paths or executing commands. This preserves existing boundaries and gives each
unit one responsibility.

## Security Invariants

1. The Repair session receives one explicit approval before Provider or test execution.
2. The repository must be clean at admission. Staged, unstaged, untracked, renamed, deleted,
   unmerged, or submodule changes reject the session.
3. Every editable path is an existing Git-tracked regular workspace file, is unique after
   normalization, and is listed explicitly. Directory scopes and wildcard scopes are not accepted.
4. The Repair worker's governed executor has a `RepairActionGuard` with the same scope
   fingerprint as the coordinator.
5. The guard permits read-only actions, permits writes only when every preview resource is one
   exact editable path, and denies execute and network actions. The coordinator alone invokes the
   fixed Pytest runner.
6. Agent-produced repository state may contain only ordinary unstaged modifications to approved
   files. New files, staging, renames, deletion, conflicts, submodules, or out-of-scope paths stop
   the loop.
7. Combined unstaged patch bytes are bounded after every worker attempt.
8. Tests must not alter the observed Git status or unstaged diff. The coordinator compares both
   fingerprints before and after every test run.
9. Test success requires process status `passed` and report status `complete`. Model text never
   decides success.
10. The loop is bounded independently by attempts, elapsed time, Agent limits, Pytest limits, and
    patch bytes.
11. Cancellation propagates. The coordinator does not convert cancellation into an ordinary
    result.
12. The coordinator never stages, commits, resets, checks out, cleans, stashes, or automatically
    reverts files.

## Package Boundaries

### `mini_code_agent.repair.models`

Immutable Pydantic models define the public contract:

- `RepairLimits`
  - `max_attempts`: default 3, hard maximum 10;
  - `max_elapsed_seconds`: default 900, hard maximum 3600;
  - `max_patch_bytes`: default 256 KiB, hard maximum 8 MiB;
  - `max_same_failure`: default 2, hard maximum 5;
  - `max_prompt_chars`: default 64 KiB, hard maximum 256 KiB.
- `RepairRequest`
  - bounded user goal;
  - optional bounded system prompt;
  - fixed Pytest targets;
  - one to 32 exact editable paths;
  - bounded approval reason;
  - caller-selected repair ID or generated UUID.
- `RepairStopReason`
  - `already_passing`;
  - `repaired`;
  - `not_approved`;
  - `invalid_scope`;
  - `dirty_repository`;
  - `test_infrastructure_error`;
  - `test_mutated_repository`;
  - `worker_failed`;
  - `no_progress`;
  - `scope_violation`;
  - `patch_limit`;
  - `repeated_failure`;
  - `max_attempts`;
  - `time_limit`;
  - `persistence_error`.
- `RepairAttemptRecord`
  - attempt number;
  - worker run ID and stop reason;
  - pre-test patch hash and byte count;
  - test execution/report statuses and counts;
  - failure fingerprint;
  - elapsed milliseconds.
- `RepairResult`
  - repair ID;
  - terminal reason;
  - normalized scope and scope fingerprint;
  - baseline and final test summaries;
  - immutable attempt records;
  - final Git status/diff fingerprints;
  - bounded public error.

`RepairResult.succeeded` is true only for `already_passing` or `repaired`.

### `mini_code_agent.repair.scope`

`RepairScope` validates exact editable files through `WorkspaceBoundary`, canonicalizes their
workspace-relative display paths, sorts them, and computes a canonical SHA-256 fingerprint.

`ActionGuard` is a small policy protocol evaluated by `GovernedToolExecutor` after preview
creation and before ordinary policy evaluation or approval:

```python
class ActionGuard(Protocol):
    def evaluate(self, preview: ActionPreview) -> ActionGuardResult: ...
```

`ActionGuardResult` contains `allowed: bool` and a bounded static public message. The default
executor guard allows existing behavior. `RepairActionGuard` applies the invariants above.

The guard sees trusted Tool preview resources rather than parsing arbitrary ToolCall JSON. Guard
denial returns the existing generic `permission_denied` ToolResult so resource policy details are
not exposed to the model.

### `mini_code_agent.git` tracked-path evidence

`GitService.tracked_paths(paths)` adds one fixed read-only query for exact, already
Workspace-validated paths. `GitClient` invokes:

```text
git <hardened-prefix> ls-files --error-unmatch -z -- <exact-path>...
```

The query has the existing timeout and output budgets, rejects malformed UTF-8/NUL output, and
requires the returned normalized set to equal the requested set exactly. Model-controlled
wildcards and directories never reach Git. This closes the ignored-file gap: a clean status does
not reveal edits to an ignored file, so ignored or otherwise untracked paths cannot enter a Repair
scope.

### `mini_code_agent.repair.fingerprint`

Failure identity is canonical SHA-256 over:

- Pytest execution status;
- report status;
- recomputed counts;
- sorted diagnostic outcome, test name, class name, file, line, and message.

It excludes duration, stdout, stderr, diagnostic detail bodies, and ordering. Those fields often
contain unstable paths, timestamps, or stack formatting and would defeat stall detection.

### `mini_code_agent.repair.worker`

`RepairWorker` is a host-trusted protocol:

```python
class RepairWorker(Protocol):
    @property
    def scope_sha256(self) -> str: ...

    async def run(self, request: RepairWorkerRequest) -> AgentResult: ...
```

`RepairWorkerRequest` contains the repair ID, attempt number, original goal, exact editable paths,
last structured test summary, failure fingerprint, and remaining budgets.

`AgentRepairWorker` adapts an `AgentRuntime`. It serializes the request as bounded canonical JSON
inside a fixed host instruction that says:

- inspect evidence before editing;
- modify only the listed existing files;
- do not execute tests or commands;
- make the smallest defensible repair;
- stop after one repair attempt.

Each attempt uses a unique deterministic run ID derived from the repair ID and attempt number.
The wrapped `AgentRuntime` still applies its own Provider, ToolCall, timeout, context, checkpoint,
Trace, policy, and approval controls.

The worker is host-trusted composition code. A custom worker can lie about its scope marker, so
the coordinator also validates Git state after every attempt. The marker catches accidental
misconfiguration; it is not an authentication boundary.

### `mini_code_agent.repair.runtime`

`RepairRuntime` receives:

- `WorkspaceBoundary`;
- hardened `GitService`;
- fixed `PytestRunner`;
- `RepairWorker`;
- `RepairApprovalHandler`;
- `RepairJournal`;
- immutable `RepairLimits`;
- monotonic clock dependency for deterministic tests.

The constructor requires the Workspace, Git, and Pytest roots to be identical.

## Admission and Approval

The coordinator performs only request and read-only Workspace scope validation before approval. It
creates a bounded `RepairPreview` containing normalized targets, exact editable paths, maximum
attempts, maximum elapsed time, maximum patch bytes, and the caller's reason.

Approval failure, rejection, or a malformed handler result stops before Git, Provider, or Pytest
work. There is no implicit approval in non-interactive use. Automation must inject an explicit
host-owned approval handler.

After approval:

1. read Git status;
2. require a clean repository and no submodule state;
3. revalidate every editable path through the Workspace to catch approval-time drift;
4. require the hardened tracked-path query to return every exact editable path;
5. verify the worker scope fingerprint;
6. record a required `RepairStarted` journal event;
7. run baseline tests and compare pre/post Git evidence.

Persistence failure is fail-closed. Best-effort UI event publication is separate from the
required journal, matching the existing Agent runtime pattern.

## Test Classification

A test result is:

- **passing** only when execution is `passed` and report is `complete`;
- **repairable** only when execution is `failed`, report is `complete`, and at least one failed or
  errored case exists;
- **infrastructure failure** for timeout, output overflow, interruption, internal error, usage
  error, no tests, unknown exit, or any incomplete report.

The coordinator does not repair an infrastructure failure because changing product code is not a
sound response to an untrusted or incomplete diagnostic channel.

## Attempt State Machine

For each attempt:

1. Check elapsed time before Provider work.
2. Persist `RepairAttemptStarted` with attempt number and current failure fingerprint.
3. Call the worker once.
4. Require worker stop reason `completed`; otherwise stop `worker_failed`.
5. Read Git status and unstaged diff.
6. Require only ordinary unstaged `M` entries for exact approved paths.
7. Require a non-empty diff, a new diff fingerprint, and patch bytes within the total limit.
8. Check elapsed time before test execution.
9. Persist `RepairVerificationStarted`.
10. Run the exact original Pytest targets.
11. Re-read Git status and diff; require exact pre-test fingerprints.
12. Build and persist one `RepairAttemptCompleted` record.
13. Return `repaired` on trusted pass.
14. Stop on infrastructure failure.
15. Count the canonical failure fingerprint. Stop `repeated_failure` when its count reaches
    `max_same_failure`.
16. Continue with the new diagnostics until `max_attempts`.

Time is checked at deterministic boundaries. An already-running Provider or Pytest call uses its
own tighter timeout and is not forcefully interrupted by the outer elapsed budget.

## Journal and Events

Repair orchestration has a separate typed event family because Agent `RunStarted`/`RunStopped`
events drive the existing Session/Run projection and cannot represent a nested coordinator.

The first implementation provides:

- `RepairStarted`;
- `RepairAttemptStarted`;
- `RepairVerificationStarted`;
- `RepairAttemptCompleted`;
- `RepairStopped`;
- `RepairJournal` protocol;
- `NullRepairJournal` for explicitly non-durable unit composition;
- `RecordingRepairJournal` for tests.

Production `RepairRuntime` requires a journal unless `allow_volatile=True` is explicitly set at
construction. The SQLite schema v3 adapter is included in M4c so ordinary durable composition does
not silently lose coordinator state. Stored events contain hashes, counts, statuses, IDs, and
bounded errors, but not prompts, patches, stdout, stderr, or diagnostic bodies.

The coordinator does not support automatic crash Resume in M4c. A started event without a terminal
event is evidence of an indeterminate Repair session. The caller must inspect the working tree and
start a new approved session. This is fail-closed and avoids replaying writes.

## Error Handling

- Expected admission, scope, Git, test, worker, budget, and persistence outcomes become typed
  terminal reasons.
- Unexpected dependency exceptions become bounded static errors and stop the loop.
- Raw exception text, absolute paths, patches, test output, and Provider content do not enter
  Repair lifecycle events.
- A journal failure stops before any later Provider, test, or write action.
- Event sink failures are ignored after required journal persistence succeeds.
- Cancellation propagates after the active dependency performs its own cleanup.
- No failure path automatically rewrites the working tree.

## Testing Strategy

### Model and fingerprint tests

- bounds and cross-field validation;
- canonical scope ordering and duplicate rejection;
- exact tracked-path parsing and ignored/untracked path rejection;
- stable fingerprint under diagnostic reordering and unstable detail changes;
- different execution/report/count/message inputs produce different fingerprints.

### Policy guard tests

- read-only allow;
- exact approved write allow;
- out-of-scope, missing-resource, multi-resource, execute, and network deny;
- existing `GovernedToolExecutor` behavior remains unchanged without a guard;
- guard denial occurs before policy approval and Tool execution.

### Runtime unit tests

- approval rejection performs zero Git, Provider, and Pytest calls;
- dirty/staged/untracked/rename/conflict/submodule admission rejection;
- invalid, duplicate, linked, directory, and missing scope rejection;
- baseline already passing;
- every infrastructure test classification;
- one-attempt repair success;
- worker failure;
- no Git progress;
- scope violation and staged/new/deleted/renamed changes;
- patch budget;
- test mutation detected by status or diff fingerprint;
- repeated failure;
- maximum attempts;
- elapsed budget before worker and before test;
- required journal failure at every event boundary;
- cancellation propagation.

### Integration tests

- real Git repository, Workspace, governed Write/Edit, Fake Provider, Agent runtime, fixed Pytest,
  and Repair runtime repair one deterministic defect;
- write outside exact scope is denied before mutation;
- baseline dirty file blocks the session without Provider or Pytest execution;
- a test that mutates a tracked file is detected and stops the loop;
- SQLite repair journal reopens, verifies its hash chain, and exposes an incomplete started-only
  session without replay.

### Regression and release gates

- Python 3.12 and 3.13 full suites;
- Ubuntu and Windows GitHub Actions matrix;
- Ruff format/check and strict Pyright;
- branch-aware package coverage at least 85%;
- Bandit and locked runtime dependency audit;
- hashed wheel/sdist build and isolated smoke tests;
- `v0.12.0-alpha.0` prerelease with verified artifacts.

## Non-Claims

- Repair approval is not process isolation.
- Pytest still executes arbitrary repository code with the Agent user's authority.
- Git observations and post-action checks do not prevent all concurrent or transient mutations.
- Exact path scope limits governed Agent write tools; malicious test code or other host processes
  can bypass Tool governance.
- The coordinator detects final-state drift but cannot prove that a test never changed and restored
  a file.
- A clean working tree does not prove repository content is trustworthy.
- Failure fingerprints identify normalized diagnostics; they do not prove two failures have the
  same root cause.
- M4c does not automatically revert a bad repair, preserve it in a worktree, commit it, or merge
  it. Worktree isolation remains M6.
- M4c does not resume an interrupted repair session automatically.
