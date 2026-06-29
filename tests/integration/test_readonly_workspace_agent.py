import json
from pathlib import Path

import pytest

from mini_code_agent.agent.models import StopReason
from mini_code_agent.agent.runtime import AgentRuntime
from mini_code_agent.domain.content import ToolCall
from mini_code_agent.domain.messages import Message, MessageRole
from mini_code_agent.providers.base import FinishReason, ModelResponse
from mini_code_agent.providers.fake import ScriptedProvider
from mini_code_agent.tools.read_file import ReadFileTool
from mini_code_agent.tools.registry import ToolRegistry
from mini_code_agent.tools.search_text import SearchTextTool
from mini_code_agent.workspace.boundary import WorkspaceBoundary


@pytest.mark.asyncio
async def test_agent_reads_and_searches_inside_workspace(tmp_path: Path) -> None:
    source = tmp_path / "src" / "app.py"
    source.parent.mkdir()
    source.write_bytes(b"def run():\n    return 'needle'\n")
    workspace = WorkspaceBoundary(tmp_path)
    registry = ToolRegistry(
        [
            ReadFileTool(workspace),
            SearchTextTool(workspace),
        ]
    )
    provider = ScriptedProvider(
        [
            ModelResponse(
                message=Message(
                    role=MessageRole.ASSISTANT,
                    content=(
                        ToolCall(
                            id="read-1",
                            name="read_file",
                            arguments={"path": "src/app.py"},
                        ),
                    ),
                ),
                finish_reason=FinishReason.TOOL_CALL,
            ),
            ModelResponse(
                message=Message(
                    role=MessageRole.ASSISTANT,
                    content=(
                        ToolCall(
                            id="search-1",
                            name="search_text",
                            arguments={"query": "needle", "glob": "*.py"},
                        ),
                    ),
                ),
                finish_reason=FinishReason.TOOL_CALL,
            ),
            ModelResponse(
                message=Message.assistant_text("Workspace inspected."),
                finish_reason=FinishReason.STOP,
            ),
        ]
    )
    runtime = AgentRuntime(provider, registry)

    result = await runtime.run(
        user_prompt="Inspect the workspace.",
        system_prompt="Use read-only tools.",
        run_id="workspace-run",
    )

    assert result.stop_reason is StopReason.COMPLETED
    assert result.final_text == "Workspace inspected."
    assert result.turns == 3
    assert result.tool_calls == 2
    assert len(provider.requests) == 3

    read_result = provider.requests[1].messages[-1]
    search_result = provider.requests[2].messages[-1]
    assert read_result.role is MessageRole.USER
    assert search_result.role is MessageRole.USER
    assert read_result.tool_results[0].tool_call_id == "read-1"
    assert search_result.tool_results[0].tool_call_id == "search-1"
    assert json.loads(read_result.tool_results[0].content)["path"] == "src/app.py"
    matches = json.loads(search_result.tool_results[0].content)["matches"]
    assert matches[0]["path"] == "src/app.py"
    assert matches[0]["line"] == 2
