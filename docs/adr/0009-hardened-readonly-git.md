# ADR 0009: Parse Hardened Git CLI Machine Output

## Status

Accepted for M4a.

## Context

The Agent needs repository evidence before and after edits. Scraping human `git status` output is
locale-dependent. Treating Git as inherently safe because status/diff are read-only ignores
configured fsmonitor, external diff, textconv, paging, submodules, and optional index writes.

## Decision

Use the installed Git CLI as the domain engine, but expose only fixed status/diff command
templates. Parse porcelain v2 with NUL delimiters into strict models. Require the Workspace to be
the exact non-bare repository top-level.

Disable paging, optional locks, fsmonitor, external diff, textconv, and submodule recursion. Bound
time, output bytes, entry count, and patch characters. Fail rather than return partial evidence.

## Consequences

- Status parsing is versioned and locale-independent.
- Unusual path characters remain unambiguous.
- Existing user index state is preserved by read-only calls.
- Parent-repository context is unavailable when Workspace is only a nested folder.
- Git must be installed and new output record kinds require explicit parser support.
- Mutation and automatic commit remain separate future decisions.

## Alternatives Rejected

- **GitPython/libgit2:** adds a large dependency and may differ from the user's Git behavior.
- **Human status parsing:** unstable across locale, configuration, and Git versions.
- **Generic `run_command`:** lets model-controlled argv and policy obscure the narrower evidence
  contract.
- **Allow external diff/textconv:** repository configuration could execute code during inspection.
- **Return truncated patch:** can hide the part of a change relevant to review.

