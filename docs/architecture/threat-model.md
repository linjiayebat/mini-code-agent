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
- M3a applies deterministic request admission before every provider call, keeps ToolCall and
  ToolResult batches atomic, and fails before provider I/O when required context cannot fit.
- Completed write/execute/network and unknown-tool exchanges remain pinned during compaction so
  the model does not lose in-memory evidence of an action and repeat it under a new call ID.
- Compaction markers/events contain bounded counts and a transcript fingerprint, not raw omitted
  content.

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
- Context fingerprints are not encryption, authentication, redaction, or durable storage.
- M3a pinning reduces in-process repeat-action risk but does not provide crash-safe replay
  prevention or exactly-once side effects; those require M3b/M3c persistence and recovery.
- A provider-neutral UTF-8 estimator is not an exact vendor tokenizer and cannot guarantee
  provider acceptance.
- MCP connection does not establish trust.
