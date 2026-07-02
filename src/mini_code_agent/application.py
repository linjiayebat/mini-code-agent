from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Protocol, cast

import httpx

from mini_code_agent.agent.events import EventSink
from mini_code_agent.agent.models import AgentResult
from mini_code_agent.agent.runtime import AgentRuntime
from mini_code_agent.command.runner import CommandRunner
from mini_code_agent.config import AppSettings, ProviderName
from mini_code_agent.git.client import GitClient
from mini_code_agent.policy.approval import ApprovalHandler
from mini_code_agent.policy.engine import PolicyEngine
from mini_code_agent.policy.executor import GovernedToolExecutor
from mini_code_agent.policy.models import (
    PolicyDecision,
    PolicyRule,
    SessionMode,
    TrustSource,
)
from mini_code_agent.providers.anthropic import AnthropicProvider
from mini_code_agent.providers.base import ModelProvider
from mini_code_agent.providers.openai_compatible import OpenAICompatibleProvider
from mini_code_agent.tools.base import SideEffect
from mini_code_agent.tools.edit_file import EditFileTool
from mini_code_agent.tools.git_diff import GitDiffTool
from mini_code_agent.tools.git_status import GitStatusTool
from mini_code_agent.tools.read_file import ReadFileTool
from mini_code_agent.tools.registry import ToolRegistry
from mini_code_agent.tools.run_command import RunCommandTool
from mini_code_agent.tools.search_text import SearchTextTool
from mini_code_agent.tools.write_file import WriteFileTool
from mini_code_agent.workspace.boundary import WorkspaceBoundary

DEFAULT_SYSTEM_PROMPT = """\
You are a coding agent working inside a bounded local workspace.
Inspect relevant files before changing them. Use workspace-relative paths.
Explain the completed work concisely and report any verification you could not run.
"""

type HttpProvider = AnthropicProvider | OpenAICompatibleProvider


class ApplicationConfigurationError(ValueError):
    """Raised when the CLI runtime cannot be composed from trusted settings."""


class ProviderFactory(Protocol):
    def __call__(self, settings: AppSettings) -> ModelProvider: ...


def build_provider(
    settings: AppSettings,
    *,
    client: httpx.AsyncClient | None = None,
) -> HttpProvider:
    if settings.model is None:
        raise ApplicationConfigurationError(
            "A model is required. Set MINI_CODE_AGENT_MODEL or model in config.toml."
        )
    try:
        if settings.provider is ProviderName.OPENAI_COMPATIBLE:
            if settings.openai_api_key is None:
                raise ApplicationConfigurationError(
                    "Set MINI_CODE_AGENT_OPENAI_API_KEY for the openai_compatible provider."
                )
            return OpenAICompatibleProvider(
                api_key=settings.openai_api_key,
                model=settings.model,
                base_url=settings.base_url or "https://api.openai.com/v1",
                client=client,
            )
        if settings.anthropic_api_key is None:
            raise ApplicationConfigurationError(
                "Set MINI_CODE_AGENT_ANTHROPIC_API_KEY for the anthropic provider."
            )
        return AnthropicProvider(
            api_key=settings.anthropic_api_key,
            model=settings.model,
            base_url=settings.base_url or "https://api.anthropic.com",
            client=client,
        )
    except ApplicationConfigurationError:
        raise
    except ValueError:
        raise ApplicationConfigurationError(
            "Provider model or base URL configuration is invalid."
        ) from None


def build_tool_executor(
    workspace_root: Path,
    *,
    approval: ApprovalHandler,
    session_mode: SessionMode,
) -> GovernedToolExecutor:
    try:
        workspace = WorkspaceBoundary(workspace_root)
        git = GitClient(workspace.root)
    except ValueError:
        raise ApplicationConfigurationError(
            "Workspace must be an existing local directory."
        ) from None
    registry = ToolRegistry(
        (
            ReadFileTool(workspace),
            SearchTextTool(workspace),
            WriteFileTool(workspace),
            EditFileTool(workspace),
            GitStatusTool(git),
            GitDiffTool(git),
            RunCommandTool(workspace, CommandRunner()),
        )
    )
    policy = PolicyEngine(
        (
            PolicyRule(
                id="cli-ask-execute",
                decision=PolicyDecision.ASK,
                rationale="Local command execution requires explicit terminal approval.",
                tool_glob="run_command",
                side_effect=SideEffect.EXECUTE,
            ),
        )
    )
    return GovernedToolExecutor(
        registry,
        policy=policy,
        approval=approval,
        session_mode=session_mode,
        trust_source=TrustSource.MODEL,
    )


async def run_task(
    settings: AppSettings,
    *,
    workspace: Path,
    user_prompt: str,
    approval: ApprovalHandler,
    session_mode: SessionMode,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    events: EventSink | None = None,
    provider_factory: ProviderFactory | None = None,
) -> AgentResult:
    factory = provider_factory or build_provider
    provider = factory(settings)
    try:
        tools = build_tool_executor(
            workspace,
            approval=approval,
            session_mode=session_mode,
        )
        return await AgentRuntime(provider, tools, events=events).run(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
        )
    finally:
        close_candidate = getattr(provider, "aclose", None)
        if close_candidate is not None:
            close = cast(Callable[[], Awaitable[None]], close_candidate)
            await close()
