# Mini CodeAgent

A framework-light, provider-neutral coding agent built from first principles.

> Status: pre-alpha. M1b provides a provider-neutral, bounded Agent Core plus programmatic
> Anthropic Messages and OpenAI-compatible Chat Completions adapters. File tools, interactive
> permissions, persistence, and live-provider CI are not implemented yet.

## Requirements

- Python 3.12 or 3.13
- uv 0.11.25

## Development

```powershell
uv sync --all-groups
uv run mini-code-agent --version
uv run mini-code-agent doctor
uv run pytest
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv build --build-constraint build-constraints.txt --require-hashes
```

If `uv` was installed by `pip` but is not available on the Windows `PATH`, use
`python -m uv` in the commands above.

## Configuration

Precedence is:

```text
defaults < TOML file < MINI_CODE_AGENT_* environment variables < CLI overrides
```

Default config paths follow the operating system conventions provided by Platformdirs.
Secrets are accepted from environment variables but are never printed by `doctor`.
See `config.example.toml` for supported inputs.

## Provider Adapters

Both adapters implement the same `ModelProvider` protocol:

```python
from pydantic import SecretStr

from mini_code_agent.providers import (
    AnthropicProvider,
    OpenAICompatibleProvider,
)

anthropic = AnthropicProvider(
    api_key=SecretStr("..."),
    model="your-claude-model",
)

compatible = OpenAICompatibleProvider(
    api_key=SecretStr("..."),
    model="your-model",
    base_url="https://your-provider.example/v1",
)
```

Applications must call `await provider.aclose()` for internally created clients. Injected
`httpx.AsyncClient` instances remain caller-owned. M1b tests use `httpx.MockTransport`; no live
API success is claimed without a separate credentialed smoke test.

## Documentation

- Product design: `docs/superpowers/specs/2026-06-29-mini-code-agent-design.md`
- Learning map: `docs/learning/knowledge-map.md`
- Learning evidence: `docs/learning/progress.md`
- Resume evidence: `docs/resume/project-profile.md`
- Agent Core: `docs/architecture/agent-core.md`
- Provider adapters: `docs/architecture/provider-adapters.md`
- Threat model: `docs/architecture/threat-model.md`
- Provider protocol ADR: `docs/adr/0002-provider-wire-protocols.md`

## License

Apache-2.0
