# ADR 0003: Read-only Workspace Boundary

- Status: Accepted
- Date: 2026-06-29

## Context

Model ToolCall arguments and repository contents are untrusted. A coding agent needs useful file
context without granting arbitrary host filesystem access or allowing one tool to invent its own
path rules.

Cross-platform behavior is part of the boundary. A path harmless on POSIX can identify a drive,
UNC share, alternate data stream, reserved device, or normalization alias on Windows.

## Decision

### One path authority

All model-supplied paths pass through `WorkspaceBoundary`. Read/Search tools never join paths or
open files directly.

The boundary uses two stages:

1. Lexical validation accepts only bounded POSIX-style relative paths and rejects absolute,
   drive-relative, UNC, backslash, percent-encoded, empty, dot, traversal, `.git`, NUL/control,
   colon/ADS, Windows device-name, and trailing-dot/space forms.
2. Physical validation walks existing components, rejects symlinks and Windows junctions,
   resolves strictly, and proves containment with `Path.relative_to(resolved_root)`.

String-prefix containment is forbidden because sibling roots and case behavior make it unsafe.

### Read policy

- Final targets must be regular files.
- Default file limit is 1 MiB; configuration is capped at 16 MiB.
- Size is checked before open and by reading at most `limit + 1`.
- Text uses strict UTF-8 with optional BOM removal.
- NUL-containing and malformed UTF-8 files are rejected.
- Original newline bytes are preserved.
- Public results contain workspace-relative POSIX paths only.

### Traversal policy

Traversal is deterministic and bounded by depth, file count, and cumulative file bytes. `.git`
is excluded case-insensitively. Links and special files fail closed. Hidden source files remain
visible because leading-dot does not imply unsafe content.

### Tool Registry

`ToolRegistry` snapshots each definition once, rejects duplicate names, validates Draft 2020-12
schemas at construction, validates ToolCall arguments before dispatch, preserves correlation IDs,
normalizes executor failures, and caps successful result content.

### Literal search

`search_text` does not accept regular expressions. Literal search avoids regex denial of service
and keeps query semantics predictable. Per-search budgets cap files, bytes, depth, results, line
length, and preview length. Unicode case-insensitive columns map folded positions back to original
text offsets.

## Security Non-claims

- Path validation is not an OS sandbox or process isolation.
- A path check followed by open has residual TOCTOU risk if another process can mutate the tree.
- M2a has no write, delete, shell, Git mutation, or network tools.
- Human approval and Policy Engine arrive in M2b; M2a remains read-only.
- File contents may still contain prompt injection and must be treated as untrusted model input.

OS-level containment for hostile concurrent writers requires descriptor-relative APIs or a
separate sandbox design. The current boundary fails closed on observed links and rechecks file
type on the opened descriptor, but does not claim race-free containment.

## Consequences

### Positive

- Read/Search share one testable cross-platform policy.
- Agent Runtime remains unchanged and receives only normal ToolResults.
- Model arguments cannot select host absolute paths or `.git` internals.
- Resource and output growth is deterministic.

### Trade-offs

- Valid POSIX filenames using `%`, `:`, trailing spaces/dots, or Windows device names are rejected
  for cross-platform consistency.
- Symlinks inside the workspace are rejected even when their current target is inside.
- Non-UTF-8 source files require a future explicit encoding policy.
- Literal search is less expressive than regex search.
