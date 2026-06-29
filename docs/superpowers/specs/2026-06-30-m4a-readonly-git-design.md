# M4a Hardened Read-only Git Evidence Design

**Date:** 2026-06-30  
**Target:** `v0.10.0-alpha.0`

## Scope

M4a adds two model-callable read-only tools:

- `git_status`: typed branch and working-tree state from porcelain v2;
- `git_diff`: bounded staged or unstaged patch text.

No add, commit, reset, checkout, clean, stash, merge, rebase, push, fetch, or automatic commit is
included. Test execution and Repair Loop remain M4b/M4c.

## Invariants

1. Git is invoked only through explicit argv; no shell parsing.
2. The configured Workspace root must equal `git rev-parse --show-toplevel`.
3. Every command disables optional locks, paging, fsmonitor, external diff, textconv, and submodule
   recursion where applicable.
4. Machine-readable status uses `--porcelain=v2 -z`; human-localized output is never parsed.
5. Status entry count, process time, and combined output bytes are bounded.
6. Output overflow, timeout, malformed records, invalid UTF-8 replacement, non-repository state,
   and non-zero Git exits become stable public errors without stderr/path leakage.
7. Diff pathspec options are not model-controlled in M4a. `--` always terminates options.
8. Read-only classification does not mean arbitrary Git configuration is trusted. Hardened flags
   disable known execution extension points used by these commands.
9. Git evidence can contain source code and secrets. It is returned to the model but is not added
   to the bounded lifecycle Trace.
10. Git status/diff are observations, not proof that concurrent files did not change afterward.

## Hardened Command Prefix

Every invocation starts with:

```text
git --no-pager --no-optional-locks
    -c core.fsmonitor=false
    -c diff.external=
```

Status adds:

```text
-C <workspace> status --porcelain=v2 -z --branch
--untracked-files=all --ignore-submodules=all
```

Diff adds:

```text
-C <workspace> diff --no-ext-diff --no-textconv
--ignore-submodules=all --unified=3 [--cached] --
```

The client first runs hardened `rev-parse --show-toplevel --is-bare-repository`. It rejects bare
repositories and any top-level path different from the resolved Workspace root. Worktrees are
allowed when their reported top-level is the configured root.

## Models

`GitLimits` bounds:

- 10-second command timeout;
- 2 MiB combined output;
- 10,000 status entries;
- 2 MiB patch characters.

`GitStatusEntry` contains:

- record kind: ordinary, renamed/copied, unmerged, or untracked;
- index/worktree status characters;
- current path and optional original path;
- optional submodule state.

`GitStatusSnapshot` contains branch OID/head/upstream, ahead/behind counts, ordered entries, and a
SHA-256 over canonical typed content. It does not include ignored files.

`GitDiffResult` contains mode (`staged` or `unstaged`), patch, byte/character counts, and SHA-256.
Overflow fails rather than returning a misleading partial patch.

## Parsing

The parser consumes NUL-separated records. Branch headers are newline-prefixed `#` records before
the first NUL status entry. Record types:

- `1`: ordinary changed entry;
- `2`: rename/copy plus a second NUL original-path field;
- `u`: unmerged entry;
- `?`: untracked entry;
- `!`: ignored entry, rejected because M4a does not request ignored records.

Unknown, incomplete, duplicate branch metadata, invalid XY fields, impossible ahead/behind values,
and entry overflow fail closed.

Ordering is Git's machine-output order. The snapshot hash uses canonical JSON, not raw localized
text.

## Tool Boundary

Both tools have `SideEffect.READ_ONLY` and can use the default allow policy. They return compact
canonical JSON through the existing Tool Registry result-size boundary.

`git_diff` accepts only:

```json
{"staged": false}
```

This avoids pathspec ambiguity in the first release. Repository-wide output remains bounded.

## Tests

- parser fixtures for branch metadata and every porcelain-v2 record kind;
- spaces, tabs, newlines, leading dashes, rename original path, conflict state, and empty repo;
- malformed/truncated/unknown records and entry N-1/N/N+1 limits;
- exact top-level, nested parent-repo rejection, bare repo rejection, and non-repo;
- staged versus unstaged diff, binary file summary, empty diff, output overflow, timeout, and
  static errors;
- command argv assertions proving hardening flags and `--`;
- real Git integration through Tool Registry and AgentRuntime;
- existing user changes remain unchanged byte-for-byte after every operation.

## Learning Mapping

- Porcelain v2 is analogous to consuming a versioned wire protocol instead of scraping logs.
- A status snapshot is evidence like a Flink source offset; it can become stale immediately.
- Git index and working tree are separate state layers, similar to staged versus in-flight data.
- `--` is an input-boundary primitive comparable to prepared-statement parameter separation.
- Disabling extension points demonstrates that a nominally read-only command can still execute
  configured code unless the host process narrows behavior.

