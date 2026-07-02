# M7 CLI Provider Runtime Design

## Goal

Turn the existing Agent SDK into a usable terminal product that can execute one task or an
interactive sequence of tasks against an OpenAI-compatible provider such as SiliconFlow.

## Scope

M7 adds:

- provider, model, and base URL configuration;
- `mini-code-agent run TASK`;
- `mini-code-agent chat`;
- a composition root that connects providers, the workspace, governed tools, and `AgentRuntime`;
- terminal approval previews for writes and command execution;
- deterministic tests that never call a live model API;
- SiliconFlow setup and usage documentation.

M7 does not add a Web UI, full-screen TUI, streaming model output, durable chat continuity, or
automatic command approval. Each `chat` prompt starts a new bounded Agent run while sharing the
same workspace.

## Architecture

`config.py` remains the only source of configuration precedence. It adds a provider selector,
model identifier, and optional base URL. Secrets continue to come from the existing environment
key fields and are never rendered by `safe_dict`.

`application.py` is the composition root. It validates runtime-specific settings, creates the
selected provider, constructs a `WorkspaceBoundary`, registers built-in tools, wraps them in
`GovernedToolExecutor`, executes `AgentRuntime`, and closes the provider-owned HTTP client.

`terminal.py` owns terminal-specific behavior. Its approval handler renders the model's proposed
action, affected resources, argv, and bounded diff before obtaining a yes/no decision. Its event
sink renders bounded progress without exposing prompts, arguments, tool results, or secrets.

`cli.py` remains a thin Typer adapter. It loads configuration, selects interactive or
non-interactive policy mode, calls the application service, renders the final result, and maps
configuration or runtime failures to stable exit codes.

## Provider Configuration

The supported provider values are:

- `openai_compatible`: uses `openai_api_key`; defaults to `https://api.openai.com/v1`.
- `anthropic`: uses `anthropic_api_key`; defaults to `https://api.anthropic.com`.

For SiliconFlow:

```toml
[mini_code_agent]
provider = "openai_compatible"
model = "MODEL_FROM_SILICONFLOW_ACCOUNT"
base_url = "https://api.siliconflow.cn/v1"
```

The API key is supplied as `MINI_CODE_AGENT_OPENAI_API_KEY`. A missing model, missing matching
key, or invalid provider construction is reported before any Agent work begins.

## Tool Governance

The CLI registers `read_file`, `search_text`, `write_file`, `edit_file`, `git_status`,
`git_diff`, and `run_command`.

- Read-only tools use the existing default allow rule.
- Writes use the existing default ask rule.
- `run_command` receives an explicit ask rule because execute is denied by default.
- Interactive sessions call the terminal approval handler.
- Non-interactive sessions deny all ask decisions without prompting.

The workspace boundary and argv-only command runner remain the enforcement points. M7 does not
claim OS sandboxing.

## Command Behavior

`run TASK` executes one bounded Agent run. It prints the final model text, then a compact run
summary. A completed run exits zero; configuration errors exit two; incomplete Agent runs exit
one.

`chat` prompts until `/exit`, `/quit`, EOF, or Ctrl+C. Every non-empty prompt invokes the same
single-run application flow and shares filesystem changes through the selected workspace. It does
not silently claim conversational memory.

## Error Handling

Public errors are bounded and omit secret values. Provider failures use the existing normalized
`AgentResult.error`. Configuration errors are caught at the CLI boundary. Provider clients are
closed in `finally`, including interrupted and failed runs.

## Testing

Tests follow red-green-refactor and cover:

- configuration precedence and secret-safe diagnostics;
- provider selection, SiliconFlow base URL propagation, and missing-key errors;
- built-in tool and policy composition;
- approval rendering and decisions;
- `run` success/failure exit behavior;
- `chat` prompt loop and exit commands;
- a mocked OpenAI-compatible end-to-end CLI flow without network access.

Live SiliconFlow verification is an explicit local smoke test and is not part of CI.
