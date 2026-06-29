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
- M2a read-only tools pass Draft 2020-12 Schema validation and one WorkspaceBoundary.
- Model paths reject cross-platform traversal, link/junction, `.git`, ADS/device, type, size,
  binary, and encoding hazards.
- Workspace traversal and ToolResult content have explicit resource limits.

## Non-claims

- Regex command filtering is not a sandbox.
- Workspace path checks are not process isolation.
- Workspace checks do not eliminate TOCTOU when another process can mutate the tree.
- Human approval does not make malicious code safe.
- MCP connection does not establish trust.
