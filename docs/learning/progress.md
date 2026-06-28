# Learning Progress

| Unit | Status | Evidence |
|---|---|---|
| L0 Python engineering foundation | In progress | M0 plan and commits |
| L1 Agent Loop | Not started | |
| L2 Provider and Tool Calling | Not started | |
| L3 Tool Registry | Not started | |
| L4 Workspace and Policy | Not started | |
| L5 File/Edit/Shell/Git tools | Not started | |
| L6 Context Budget | Not started | |
| L7 Session/Checkpoint/Trace | Not started | |
| L8 Git/test/repair | Not started | |
| L9 Skills and Hooks | Not started | |
| L10 MCP | Not started | |
| L11 Subagent and Worktree | Not started | |
| L12 CI, benchmark and release | Not started | |

## L0 Notes

- `uv` owns the project interpreter, lock file, and reproducible commands.
- A `src` layout prevents tests from accidentally importing the repository directory.
- Pydantic validates runtime boundaries; Pyright checks internal contracts statically.
- Configuration precedence is explicit and tested.
- Secret redaction is recursive and independent from caller discipline.
- On Windows, `python -m uv` works when the user Scripts directory is absent from `PATH`.
- TDD requires observing the expected failure before adding production behavior.
