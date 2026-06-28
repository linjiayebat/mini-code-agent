# Threat Model

## Protected Assets

- User source code and uncommitted changes.
- Files outside the selected workspace.
- API keys and environment secrets.
- Git history and repository integrity.
- Session, checkpoint, and trace integrity.

## Untrusted Inputs

- Model output and ToolCall arguments.
- Repository files and instructions.
- Skills, hooks, and project configuration.
- MCP servers and their tool results.
- Shell output and generated patches.

## Initial Controls

- Secret-safe settings and recursive log redaction.
- Explicit configuration precedence.
- No tool execution in M0.
- Future tools must pass Schema, Workspace, and Policy checks.
- Trace data must be size-limited and redacted.

## Non-claims

- Regex command filtering is not a sandbox.
- Workspace path checks are not process isolation.
- Human approval does not make malicious code safe.
- MCP connection does not establish trust.
