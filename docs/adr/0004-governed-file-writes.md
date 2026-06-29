# ADR 0004: Governed and Conflict-Aware File Writes

- Status: Accepted
- Date: 2026-06-29

## Context

A coding agent must modify source files, but model output, repository instructions, and tool
arguments are untrusted. Prompt-only permission instructions cannot reliably prevent unintended
side effects. A read followed by a write also risks silently overwriting user or process changes.

## Decision

All side-effecting tools used by `AgentRuntime` must be composed behind
`GovernedToolExecutor`. The executor validates arguments, obtains a bounded action preview,
evaluates deterministic allow/ask/deny rules, obtains explicit interactive approval when needed,
and only then dispatches through `ToolRegistry`.

Default policy allows reads, asks for writes, and denies process execution and network access.
Non-interactive `ask` fails closed. The runtime rejects side-effect definitions from executors
that do not expose the literal governance marker.

Existing files use raw-byte SHA-256 optimistic concurrency. `read_file` returns the hash;
`write_file` and `edit_file` recheck it during preview and execution. New files use create-only
semantics. Edit replaces exactly one literal occurrence.

Writes use a same-directory temporary file and atomic publication. Public previews and results
contain only bounded data and workspace-relative paths.

## Consequences

### Positive

- Permission is enforced outside model text and is independently testable.
- Users approve the target, reason, risk, and concrete diff.
- Ordinary stale edits fail instead of overwriting newer content.
- Failed writes do not expose partial target files or raw host paths.
- Agent Runtime remains independent of paths, policies, and file mutation details.

### Trade-offs

- The governance marker is a trusted Python composition contract, not tamper-proof isolation.
- First-match rules are predictable but require deliberate ordering.
- Literal edit is less flexible than patch formats but has an unambiguous precondition.
- Full-file hashing and replacement are bounded but cost O(file size).
- Approval adds latency to every default write.

## Non-claims

- Approval does not prove generated code is safe or correct.
- Atomic replacement does not provide database transaction isolation or rollback.
- Hash revalidation does not eliminate a hostile external-writer race after the final check.
- Workspace and policy checks do not replace an OS sandbox.
