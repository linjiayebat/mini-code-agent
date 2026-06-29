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
- Command output and generated patches.

## Initial Controls

- Secret-safe settings and recursive log redaction.
- Explicit configuration precedence.
- No tool execution in M0.
- Side-effecting tools must pass Schema, Workspace, Policy, preview, and approval checks.
- Trace data must be size-limited and redacted.
- M2a read-only tools pass Draft 2020-12 Schema validation and one WorkspaceBoundary.
- Model paths reject cross-platform traversal, link/junction, `.git`, ADS/device, type, size,
  binary, and encoding hazards.
- Workspace traversal and ToolResult content have explicit resource limits.
- M2b write tools use bounded previews, interactive-only approval for `ask`, SHA-256
  preconditions, create-only publication, and same-directory atomic replacement.
- Non-interactive `ask` decisions fail closed without invoking an approval handler.
- M2c commands use argv-only execution, workspace cwd validation, a minimal inherited
  environment, bounded output/time, and process-tree cleanup.
- Execute remains denied by default and requires an explicit tool/executable policy rule.

## Non-claims

- Regex command filtering is not a sandbox.
- Workspace path checks are not process isolation.
- Workspace checks do not eliminate TOCTOU when another process can mutate the tree.
- Hash revalidation narrows but does not eliminate the race between final check and replacement.
- Human approval does not make malicious code safe.
- An approved local process can access host files, network, credentials in files, and other
  resources available to the current OS identity.
- Process groups and tree termination are lifecycle controls, not security isolation; hostile
  detached descendants require an OS sandbox.
- MCP connection does not establish trust.
