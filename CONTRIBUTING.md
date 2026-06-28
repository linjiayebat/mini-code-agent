# Contributing

## Setup

```powershell
uv sync --all-groups
```

## Required Checks

```powershell
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest --cov
uv build
```

Changes to public behavior require tests. Security-sensitive behavior requires negative tests.
Architecture changes require an ADR.
