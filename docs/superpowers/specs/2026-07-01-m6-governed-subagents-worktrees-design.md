# M6 Governed Subagents and Worktree Candidates Design

**Status:** Approved by the user's standing delegation to continue without additional confirmation.

**Decision:** Deliver M6 in two independently releasable slices. M6a adds bounded, non-recursive
analysis Subagents with structured concurrency. M6b adds host-managed Worktree execution,
immutable candidate snapshots, and separately governed adoption into the parent Workspace.

## 1. Goals

M6 must:

1. let a parent Agent delegate one to four independent analysis tasks without copying the parent
   transcript into each child;
2. give every child a host-owned prompt, exact Tool set, independent Agent limits, timeout, and
   result budget;
3. prevent recursive delegation and distinguish child ToolCalls from parent model ToolCalls in
   Policy;
4. preserve cancellation and return one ordered, typed result for every requested child;
5. let one approved implementation Subagent edit an isolated Git Worktree without touching the
   parent checkout;
6. snapshot add/modify text changes into an integrity-checked candidate after the child exits;
7. remove the temporary Worktree after a valid snapshot, even though it is dirty;
8. require a second Policy/approval decision before candidate adoption;
9. reject stale/conflicting adoption before any parent file changes;
10. return bounded evidence rather than treating a child's natural-language summary as proof.

## 2. Non-Goals

M6 does not add:

- recursive Subagents, agent teams, mailboxes, task boards, peer messaging, or autonomous claims;
- child access to arbitrary shell, Git mutation, MCP, project Hooks, credentials, or network by
  default;
- parent transcript forks, prompt-cache sharing, background UI, steering, or resume;
- automatic commit, stage, push, merge, cherry-pick, rebase, reset, stash, or branch creation;
- repository-controlled Worktree hooks, checkout filters, `.worktreeinclude`, ignored-file or
  secret copying;
- binary, symlink, submodule, rename, deletion, or file-mode candidate changes in the first
  Worktree release;
- an OS sandbox, process isolation, crash-atomic multi-file transactions, or exactly-once external
  side effects.

The parent remains responsible for reviewing adopted files, running final verification, and
creating Git history.

## 3. Source Alignment

The design follows, but does not copy, these external patterns:

- Claude Code named Subagents start with separate context, fixed prompts/Tools, bounded turns, and
  can use Worktree isolation:
  <https://code.claude.com/docs/en/sub-agents>.
- Claude Code distinguishes Subagents from parallel sessions and keeps intermediate child work out
  of the parent context:
  <https://code.claude.com/docs/en/agents>.
- Claude Code removes clean temporary Worktrees automatically but keeps changed Worktrees for
  review:
  <https://code.claude.com/docs/en/worktrees>.
- Python `asyncio.TaskGroup` provides structured sibling lifetime and propagating cancellation;
  `CancelledError` must be re-raised:
  <https://docs.python.org/3.13/library/asyncio-task.html>.
- Git recommends `worktree list --porcelain -z`, supports detached and locked Worktrees, and
  refuses dirty removal unless explicitly forced:
  <https://git-scm.com/docs/git-worktree>.
- `learn-claude-code` s06 demonstrates fresh child messages and no recursive task Tool, while s18
  demonstrates per-task Worktree directories:
  <https://github.com/shareAI-lab/learn-claude-code>.

The teaching implementation is reference material only. Its `shell=True`, global mutable state,
model-chosen Worktree names, daemon threads, force removal, and direct write access do not meet this
project's trust boundaries.

## 4. Approaches Considered

### 4.1 Generic threaded agent team

Spawn named daemon threads, share a task board and inbox, and let agents call shell/file handlers.
This is compact and visually similar to educational implementations, but it has weak cancellation,
shared mutable state, no exact Policy provenance, and no reliable cleanup. Rejected.

### 4.2 One CLI subprocess per child

Launch a full `mini-code-agent` process with serialized profile, credentials, and an IPC result
protocol. This gives stronger interpreter/process isolation, but immediately requires secret
transport, provider lifecycle, process authentication, durable recovery, and child log governance.
Deferred until the in-process contracts and evidence format are stable.

### 4.3 Host-profiled in-process children plus candidate Worktrees

Reuse `AgentRuntime` with fresh messages, exact child Tools, `TrustSource.SUBAGENT`, independent
limits, and `TaskGroup`. Implementation children run against a host-materialized Worktree; the host
then snapshots bounded text changes and destroys the temporary tree. Adoption is a separate
governed Tool. Selected because it extends existing tested boundaries without inventing a second
Agent protocol.

## 5. Delivery Slices

### M6a: bounded analysis Subagents

- Add immutable profiles, child/result/evidence models, supervisor, analysis-batch Tool, events,
  docs, and release `0.15.0-alpha.0`.
- Only read-only child Tool definitions are admitted.
- One parent ToolCall can run one to four children concurrently.

### M6b: Worktree candidates

- Add Worktree lease management, clean tracked-file materialization, implementation child mode,
  candidate store, adoption/discard Tools, docs, and release `0.16.0-alpha.0`.
- Child write/execute Tools remain exact and governed.
- Candidate adoption supports UTF-8 regular-file additions and modifications only.

The slices share `SubagentProfile`, supervisor result contracts, and `TrustSource.SUBAGENT`, but
M6a has no Git mutation path.

## 6. Trust Model

### Trusted host inputs

- profile IDs, local Tool names and descriptions;
- child system prompts;
- exact child Tool names and side-effect ceiling;
- provider and governed Tool factories;
- repository root, Worktree state root, candidate state root, and Git executable;
- all limits, allowed path scopes, Policy, Hooks, and approval handlers.

### Untrusted inputs

- parent-model task text and task ordering;
- every child model response and ToolCall;
- child final summaries;
- repository files and attributes;
- files produced inside a Worktree;
- candidate IDs when presented by a model;
- Git stdout/stderr and filesystem state after every race boundary.

No untrusted source can select an executable, filesystem root, Worktree path, Git branch, Tool set,
Policy mode, timeout, or result limit.

## 7. M6a Host Profile

`SubagentProfile` is an immutable Pydantic model with:

- `profile_id`: 1-64 lowercase ASCII letters, digits, `_` or `-`;
- `local_name`: exact parent Tool name;
- `description`: host-authored, 1-500 characters;
- `system_prompt`: host-authored, 1-20,000 characters;
- `tool_names`: one to 16 unique exact child Tool names;
- `mode`: `analysis` or, in M6b, `worktree`;
- `agent_limits`: bounded existing `AgentLimits`;
- `max_tasks`: 1-4, fixed by the host;
- `max_task_chars`: default 4,000, hard maximum 20,000;
- `max_concurrency`: 1-4 and no greater than `max_tasks`;
- `child_timeout_seconds`: default 120, hard maximum 600;
- `batch_timeout_seconds`: default 300, hard maximum 900;
- `max_summary_chars`: default 8,000, hard maximum 32,000;
- `max_evidence_items`: default 64, hard maximum 256;
- `max_result_bytes`: default 128 KiB, hard maximum 1 MiB.

Analysis profiles reject any child Tool whose `SideEffect` is not `READ_ONLY`.

## 8. Child Composition Contracts

The supervisor receives trusted factories:

```python
class SubagentProviderFactory(Protocol):
    def create(
        self,
        profile: SubagentProfile,
        child_id: str,
    ) -> ModelProvider: ...


class SubagentToolFactory(Protocol):
    def create(
        self,
        profile: SubagentProfile,
        workspace_root: Path,
    ) -> ToolExecutor: ...
```

For each child, the supervisor requires:

- a distinct provider object and distinct Tool executor object within the batch;
- `governance_enforced is True`;
- Tool names exactly equal `profile.tool_names`, with no extra or missing definition;
- `trust_source_for(name) is TrustSource.SUBAGENT` for every Tool;
- side effects no stronger than the profile mode allows;
- no registered Subagent delegation or candidate-adoption Tool.

Construction mismatch fails the whole batch before any Provider call.

The parent transcript is never passed to a child. Every child receives only:

- its host system prompt;
- one user message containing the bounded task;
- its exact Tool definitions;
- an independent run ID, Agent limits, context budget, and in-memory message list.

## 9. Policy and Approval

Add `TrustSource.SUBAGENT`. Parent delegation remains a normal ToolCall from
`TrustSource.MODEL`. Child ToolCalls use `SUBAGENT`, allowing stricter rules than parent calls.

M6a analysis delegation is `READ_ONLY` and low risk, but still traverses Registry, Preview, Hooks,
Policy, and Tool execution. A Policy rule may deny delegation entirely.

M6b implementation delegation is a separate Tool with the highest configured side effect:

- `WRITE` when only Read/Search/Write/Edit are granted;
- `EXECUTE` when fixed Pytest is also granted.

Its preview lists repository identity, base revision, profile, child Tool names, task count, and a
bounded task summary. Worktree creation occurs only after the parent Tool is allowed.

Child session mode is always `NON_INTERACTIVE`. Child `ASK` decisions auto-deny; a background child
can never open a nested approval prompt. Connection approval, parent delegation approval, child
Tool Policy, and candidate adoption approval are separate decisions.

## 10. Structured Concurrency

`SubagentSupervisor.run_batch()`:

1. validates all tasks before creating any child;
2. allocates host-generated child IDs and ordered result slots;
3. creates at most `max_concurrency` child tasks inside one `asyncio.TaskGroup`;
4. wraps each child in its own `asyncio.timeout`;
5. converts ordinary child timeout/failure into that child's typed result so siblings continue;
6. keeps result order equal to input order, not completion order;
7. enforces one outer batch timeout;
8. on parent cancellation, re-raises `CancelledError` and lets `TaskGroup` cancel all children.

No detached `asyncio.create_task`, daemon thread, background process, or orphan Agent survives the
parent ToolCall.

## 11. Results and Evidence

`SubagentChildResult` contains:

- child ID, ordinal, profile ID, and status;
- `StopReason`, turns, ToolCall count, and token usage when available;
- bounded final summary labelled `untrusted_summary`;
- zero or more `SubagentEvidenceItem` records;
- static public error code/message for timeout or infrastructure failure.

Evidence items are derived by the host from the child transcript and contain:

- ToolCall ID and exact Tool name;
- whether the correlated ToolResult was an error;
- result character count and SHA-256;
- no raw arguments, file contents, exception text, prompt, or ToolResult content.

The batch result also includes elapsed time, completed/timed-out/failed counts, and a canonical
SHA-256 over the ordered child result projection. Serialization is deterministic, ASCII-safe, and
bounded before it becomes the parent ToolResult.

A natural-language child summary is useful output, not execution proof. Tool evidence and, in M6b,
the candidate manifest are the auditable facts.

## 12. Subagent Events

Add metadata-only events:

- `SubagentBatchStarted`;
- `SubagentStarted`;
- `SubagentCompleted`;
- `SubagentBatchCompleted`.

They include parent ToolCall ID, child ID/ordinal, profile ID, status, duration, counts, usage, and
result hash. They never include task text, system prompt, summary, Tool arguments/results, file
content, or exception text.

The supervisor accepts an `EventSink`. Event delivery follows existing best-effort semantics.
Durable parent-run linkage is not claimed because the current `ToolExecutor` contract does not
carry run/turn context.

## 13. M6b Worktree Profile

`WorktreeProfile` is host-owned and pins:

- absolute existing clean repository root;
- absolute existing state root outside the repository;
- absolute existing unlinked Git executable, revalidated before every command;
- maximum active leases: default 2, hard maximum 4;
- tracked-file count/byte/depth limits;
- candidate changed-file count: default 32, hard maximum 128;
- candidate total after-content bytes: default 2 MiB, hard maximum 8 MiB;
- per-file bytes, path length, diff characters, and cleanup timeout;
- allowed literal path prefixes;
- exact implementation `SubagentProfile`.

The model supplies only task text. Lease IDs, directory names, candidate IDs, and base revisions are
host-generated.

## 14. Worktree Creation Without Repository Execution

Before creation, the manager verifies:

- repository top-level equals the pinned root and is not bare;
- `HEAD` is a full 40-character commit ID;
- index and parent Worktree are clean, including untracked files;
- no active lease already uses the generated path;
- the state root and all ancestors are existing unlinked directories; POSIX mode must exclude
  group/other access, while Windows rejects reparse points and relies on the host-created
  current-user state directory ACL.

It then runs fixed argv equivalent to:

```text
git --no-pager --no-optional-locks
  -c core.fsmonitor=false
  -c core.hooksPath=<host-empty-hooks-dir>
  -C <repo>
  worktree add --detach --no-checkout --lock
  --reason mini-code-agent:<lease-id>
  <host-generated-path> <base-sha>
```

`--no-checkout` is mandatory. It prevents repository checkout hooks and smudge filters from being
used to populate the child directory.

The host reads the clean parent's tracked index entries with stable NUL-delimited Git output.
Regular `100644` and `100755` files are copied byte-for-byte into the Worktree with path, link,
file-type, file-count, and total-byte checks. Symlinks, gitlinks/submodules, sparse or unresolved
entries, special files, duplicate/case-colliding paths, and output truncation fail creation.

Ignored/untracked files, `.env`, credentials, caches, `.venv`, and repository-local Worktree include
rules are never copied.

## 15. Worktree Child Execution

The child Tool factory receives a new `WorkspaceBoundary` rooted at the lease path. The parent
Workspace is never exposed.

The first implementation profile permits only:

- Read/Search;
- CAS Write/Edit;
- optionally the fixed governed Pytest Tool.

It excludes arbitrary Command, Git mutation, MCP, Skills loaded from the repository, project Hooks,
candidate adoption, and Subagent delegation. Host in-process Hooks may still observe or veto child
Tools.

The child cannot delete files, create missing parent directories, change file modes, or traverse
links. This deliberately narrows the first candidate format to regular UTF-8 additions and
modifications.

The supervisor maintains an internal mutation ledger from successful host-generated Write/Edit
ToolResults. For each path it records the ordered before/after SHA-256 chain. The ledger is not
derived from child prose and is not editable by the child.

## 16. Candidate Snapshot

After child completion or ordinary failure, the manager scans the Worktree independently of the
child:

1. reject links, reparse points, special files, case collisions, `.git` traversal, and budget
   excess;
2. compare every materialized base path by raw SHA-256;
3. identify new regular files and changed base files;
4. reject missing base files, binary/invalid UTF-8 content, mode changes, and paths outside allowed
   prefixes;
5. require the exact changed-path set to equal the mutation ledger, every repeated-write hash
   chain to be contiguous, and every final filesystem hash to equal the ledger's final hash;
6. generate deterministic bounded unified diffs for display;
7. store after-content separately from a canonical immutable manifest;
8. hash each content blob and the canonical manifest;
9. atomically rename the complete candidate directory from `building` to `ready`.

This check prevents test code or another process from smuggling unapproved Worktree changes into a
candidate. If extra regular-file mutations fit the evidence budget, they are persisted as a
non-adoptable `rejected` forensic manifest before cleanup. If links, special files, or budget excess
prevent a trustworthy snapshot, the locked Worktree is retained with `cleanup_required`; it is not
force-removed as though its contents had been preserved.

The candidate manifest contains repository identity, base SHA, profile/child IDs, path operation,
before/after SHA-256, byte/line counts, bounded diff, child status, evidence hash, and manifest hash.
It does not contain prompts, Tool arguments, credentials, or raw child messages.

If there are no changes, no candidate is created.

## 17. Worktree Cleanup

Once a candidate is safely in `ready`, or when a child leaves the tree clean, the manager:

1. verifies the lease path and `.git` administrative identity against the in-memory lease;
2. unlocks the exact Worktree;
3. removes it with `git worktree remove --force`;
4. runs bounded `git worktree prune`;
5. verifies the path and lease no longer exist.

`--force` is allowed only for a manager-created lease after candidate persistence. The model cannot
call remove, provide the path, request double force, or discard an unsnapshotted dirty tree.

If cleanup fails, the result reports a static `cleanup_required` status and exact lease ID. It does
not claim isolation was removed.

## 18. Candidate Adoption

`adopt_subagent_candidate` is a separate native `WRITE` Tool with high risk.

Preview:

- loads the candidate by validated opaque ID;
- verifies directory state, manifest hash, and every content hash;
- shows repository/base identity, paths, byte counts, and bounded diffs;
- never performs Git or Workspace mutation.

Execution after Policy/approval:

1. atomically claims `ready/<id>` by renaming it to `applying/<id>`;
2. verifies repository top-level, clean status, and exact `HEAD == candidate.base_sha`;
3. preflights every path through the parent `WorkspaceBoundary`;
4. requires every existing file SHA-256 to equal `before_sha256` and every addition to be absent;
5. stages all after-content in same-directory temporary regular files;
6. revalidates every precondition immediately before the first replacement;
7. applies paths in canonical order;
8. verifies every final SHA-256 and exact changed-path set;
9. moves the candidate to `applied/<id>` and returns bounded evidence.

Any conflict found through step 6 produces zero parent writes and moves the candidate back to
`ready`.

An I/O failure after the first replacement triggers reverse-order rollback using the captured
before bytes and after hashes. Successful rollback returns `apply_failed_rolled_back`. Failed
rollback returns `apply_uncertain`, preserves the claimed candidate and recovery evidence, and
never reports success.

The operation is process-serialized and rollback-aware, but not crash-atomic against power loss or
an external writer. Recovery classifies an abandoned `applying` candidate as:

- all before hashes: return to `ready`;
- all after hashes: mark `applied`;
- mixed/unknown hashes: `apply_uncertain`, manual recovery required.

Adoption leaves changes unstaged and uncommitted in the parent Worktree.

## 19. Candidate Discard

`discard_subagent_candidate` is a separate governed `WRITE` Tool. It accepts only a ready candidate
ID, previews repository/base/path metadata, atomically claims the directory, and removes only the
host-owned candidate path after containment and link checks.

Applied or uncertain candidates cannot be discarded through the Tool.

## 20. Failure Semantics

Static public error codes cover:

- invalid profile/task/batch;
- child composition mismatch;
- provider/tool factory failure;
- child timeout or failure;
- batch timeout;
- repository dirty/not supported;
- Worktree create/materialize/snapshot/cleanup failure;
- no candidate changes;
- candidate corrupt/stale/conflict;
- adoption failed and rolled back;
- adoption completion uncertain.

Raw Git output, filesystem exceptions, provider exceptions, and child exception text stay out of
model-facing errors and events.

Child cancellation always propagates. Timeouts of read-only M6a children are final. For M6b, a
timeout does not imply rollback; the supervisor still snapshots the Worktree before cleanup.
Parent cancellation enters a bounded shielded snapshot/cleanup section, then re-raises
`CancelledError`. If the shielded cleanup budget expires, the exact lease remains locked and is
reported through host diagnostics on the next startup.

## 21. Resource Limits

Hard maxima:

| Resource | Hard maximum |
|---|---:|
| Children per batch | 4 |
| Concurrent children | 4 |
| Child turns | 32 |
| Child ToolCalls | 128 |
| Child timeout | 600 seconds |
| Batch timeout | 900 seconds |
| Task text | 20,000 characters |
| Summary | 32,000 characters |
| Evidence items | 256 |
| Parent ToolResult | 1 MiB |
| Active Worktree leases | 4 |
| Materialized tracked files | 20,000 |
| Materialized bytes | 512 MiB |
| Candidate changed files | 128 |
| Candidate after-content | 8 MiB |
| Candidate file | 2 MiB |
| Candidate displayed diff | 64 KiB per file |

Defaults are lower and all limits are immutable host configuration.

## 22. Test Strategy

### M6a unit tests

- profile immutability, uniqueness, bounds, exact Tool sets, and analysis side-effect ceiling;
- child IDs, fresh message context, no recursive Tool, independent limits, and SUBAGENT provenance;
- ordered results under out-of-order completion;
- sibling timeout/failure isolation;
- parent cancellation cancels every child and re-raises;
- malformed factory/runtime/result handling;
- evidence extraction, secret omission, deterministic hashes, and result-size limits;
- parent Registry/Hook/Policy deny/allow behavior.

### M6a integration tests

- two real scripted child Agents analyze independent files concurrently;
- one child times out while its sibling completes;
- a child attempts an unregistered delegation Tool and receives `unknown_tool`;
- child read calls traverse the governed executor with `TrustSource.SUBAGENT`;
- parent Agent receives one bounded batch ToolResult and completes.

### M6b unit tests

- repository/worktree/state-root identity and link/reparse rejection;
- fixed argv, `--detach --no-checkout --lock`, no shell, no model-selected path;
- clean-status/base-SHA requirements and stable NUL parsing;
- tracked file materialization, mode/count/byte/case-collision checks;
- snapshot add/modify success and deletion/binary/link/submodule rejection;
- mutation-ledger chain validation and rejection of test-created or out-of-band file changes;
- candidate canonical hashes, atomic publish, corruption detection, and replay claim;
- exact-path cleanup and refusal to delete foreign/unsnapshotted trees;
- adoption preview, clean/base/hash conflict with zero writes;
- multi-file success, injected apply failure with successful rollback, and uncertain rollback;
- abandoned-claim recovery classification.

### M6b integration tests

- real Git repository creates a detached no-checkout Worktree without running a malicious
  post-checkout hook or smudge filter;
- implementation child changes one file and adds one file only in the Worktree;
- candidate survives Worktree removal and parent remains byte-identical;
- denied adoption produces no parent writes;
- approved adoption applies exact files and leaves them unstaged;
- parent drift causes conflict and zero writes;
- cancellation/timeout snapshots dirty child work before cleanup.
- cancelled cleanup timeout retains a locked lease instead of force-deleting unpreserved changes.

All existing Python 3.12/3.13, Windows/Linux, coverage, Ruff, strict Pyright, Bandit, dependency
audit, deterministic build, archive-member, and artifact smoke gates remain required.

## 23. Documentation and Resume Evidence

M6a adds L11 prerequisites for structured concurrency, context isolation, capability profiles,
fan-out/fan-in, cancellation, and evidence aggregation. M6b adds Git Worktree internals, clean base
snapshots, candidate manifests, optimistic concurrency, rollback uncertainty, and conflict
handling.

Resume material must state:

- why Subagents reduce parent context pressure but increase permission/cancellation complexity;
- why exact profiles and `TrustSource.SUBAGENT` are required;
- why Worktree isolation prevents file collision but is not an OS sandbox;
- how candidate snapshots and separate adoption approval prevent child writes from directly
  touching the parent;
- what remains unsupported and which measurements are test evidence rather than performance
  claims.

## 24. Release Plan

- M6a bumps the package to `0.15.0a0` and publishes `v0.15.0-alpha.0`.
- M6b bumps the package to `0.16.0a0` and publishes `v0.16.0-alpha.0`.
- Each release requires a PR, five-job CI, merged-main CI, deterministic wheel/sdist hashes,
  Python 3.12/3.13 isolated artifact smoke, annotated tag verification, non-draft prerelease, and
  exact evidence updates.

## 25. Explicit Security Claims

M6 can claim bounded child context, exact capabilities, non-recursion, structured cancellation,
separate child provenance, parent-file isolation before adoption, integrity-checked candidate
storage, conflict-before-write behavior, and rollback-aware adoption.

M6 cannot claim that in-process children are memory/process isolated, that Worktrees restrict OS
authority, that tests are safe, that candidate storage is encrypted, that multi-file adoption is
power-loss atomic, or that external side effects are exactly once.
