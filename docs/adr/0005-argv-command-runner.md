# ADR 0005: Argv-Only Governed Command Runner

- Status: Accepted
- Date: 2026-06-29

## Context

Code agents need to run tests, linters, and build commands. A free-form shell string adds shell
expansion, quoting, interpolation, platform grammar, and injection risk. Starting a process also
creates lifecycle obligations that asyncio cancellation alone does not satisfy.

## Decision

M2c supports only explicit argv execution through `asyncio.create_subprocess_exec`. There is no
`shell=True`, shell text, stdin, model-provided environment, background mode, or detached mode.

`RunCommandTool` is always `SideEffect.EXECUTE` and critical risk. Execute remains denied by
default. Approval previews show exact argv, relative cwd, and reason. Policy rules may narrow the
submitted executable with a deterministic glob.

`CommandRunner` uses a minimal environment, workspace-validated cwd, combined output budget,
monotonic timeout, concurrent pipe draining, and platform process-tree cleanup. Cancellation
attempts cleanup before propagation.

## Consequences

### Positive

- No second command language or implicit shell expansion.
- Windows and POSIX share one Tool contract.
- Secrets are not inherited through arbitrary environment variables.
- Output, time, and cleanup waits are bounded.
- Command failures remain structured and correlated with ToolCall IDs.

### Trade-offs

- Pipes, redirects, wildcard expansion, and compound commands require separate argv calls or a
  future explicitly governed shell adapter.
- Minimal environment can require callers to configure tools through files or argv.
- Process-tree cleanup is platform-specific and best effort.
- Executable glob matching describes submitted argv, not binary provenance.

## Non-claims

- Workspace cwd validation does not confine process filesystem access.
- Approval and executable globs do not make hostile commands safe.
- Process groups are not OS sandboxes.
- Descendants deliberately detached by hostile code may survive.
