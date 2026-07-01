from __future__ import annotations

import os
from collections.abc import Mapping
from contextlib import AsyncExitStack
from datetime import timedelta
from typing import Protocol, cast

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from pydantic import JsonValue, ValidationError

from mini_code_agent import __version__
from mini_code_agent.domain.json import FrozenJsonValue, thaw_json_mapping
from mini_code_agent.mcp.models import (
    McpCallError,
    McpCallErrorCode,
    McpCallResult,
    McpConnectionError,
    McpConnectionErrorCode,
    McpInitializeSnapshot,
    McpRemoteTool,
    McpServerProfile,
    McpToolPage,
)


class McpSession(Protocol):
    async def initialize(self) -> McpInitializeSnapshot: ...

    async def list_tools(self) -> McpToolPage: ...

    async def call_tool(
        self,
        name: str,
        arguments: Mapping[str, JsonValue],
    ) -> McpCallResult: ...

    async def aclose(self) -> None: ...


class McpSessionFactory(Protocol):
    async def open(self, profile: McpServerProfile) -> McpSession: ...


def build_stdio_parameters(profile: McpServerProfile) -> StdioServerParameters:
    return StdioServerParameters(
        command=profile.command,
        args=list(profile.args),
        env={key: secret.get_secret_value() for key, secret in profile.environment.items()},
        cwd=profile.cwd,
        encoding="utf-8",
        encoding_error_handler="strict",
    )


def snapshot_initialize_result(
    result: types.InitializeResult,
) -> McpInitializeSnapshot:
    tools = result.capabilities.tools
    if not isinstance(result.protocolVersion, str):
        raise McpConnectionError(McpConnectionErrorCode.CONNECTION_FAILED)
    try:
        return McpInitializeSnapshot(
            protocol_version=result.protocolVersion,
            server_name=result.serverInfo.name,
            server_version=result.serverInfo.version,
            has_tools=tools is not None,
            tools_list_changed=bool(tools is not None and tools.listChanged is True),
        )
    except ValidationError:
        raise McpConnectionError(McpConnectionErrorCode.CONNECTION_FAILED) from None


def snapshot_tool_page(result: types.ListToolsResult) -> McpToolPage:
    try:
        return McpToolPage(
            tools=tuple(
                McpRemoteTool.model_validate(
                    {
                        "name": tool.name,
                        "input_schema": tool.inputSchema,
                        "output_schema": tool.outputSchema,
                        "task_support": (
                            tool.execution.taskSupport
                            if tool.execution is not None and tool.execution.taskSupport is not None
                            else "forbidden"
                        ),
                    }
                )
                for tool in result.tools
            ),
            next_cursor=result.nextCursor,
        )
    except ValidationError:
        raise McpConnectionError(McpConnectionErrorCode.TOOL_SCHEMA_INVALID) from None


def snapshot_call_result(result: types.CallToolResult) -> McpCallResult:
    text: list[str] = []
    for block in result.content:
        if not isinstance(block, types.TextContent):
            raise McpCallError(McpCallErrorCode.RESULT_UNSUPPORTED)
        text.append(block.text)
    try:
        return McpCallResult.model_validate(
            {
                "text": tuple(text),
                "structured_content": result.structuredContent,
                "is_error": result.isError,
            }
        )
    except (TypeError, ValidationError):
        raise McpCallError(McpCallErrorCode.RESULT_INVALID) from None


class OfficialStdioSessionFactory:
    async def open(self, profile: McpServerProfile) -> McpSession:
        stack = AsyncExitStack()
        try:
            errlog = stack.enter_context(
                open(os.devnull, "w", encoding="utf-8"),  # noqa: SIM115
            )
            read_stream, write_stream = await stack.enter_async_context(
                stdio_client(
                    build_stdio_parameters(profile),
                    errlog=errlog,
                )
            )
            session = await stack.enter_async_context(
                ClientSession(
                    read_stream,
                    write_stream,
                    read_timeout_seconds=timedelta(seconds=profile.limits.call_timeout_seconds),
                    client_info=types.Implementation(
                        name="mini-code-agent",
                        version=__version__,
                    ),
                )
            )
        except BaseException:
            await stack.aclose()
            raise
        return _OfficialStdioSession(
            stack,
            session,
            call_timeout_seconds=profile.limits.call_timeout_seconds,
        )


class _OfficialStdioSession:
    def __init__(
        self,
        stack: AsyncExitStack,
        session: ClientSession,
        *,
        call_timeout_seconds: float,
    ) -> None:
        self._stack = stack
        self._session = session
        self._call_timeout = timedelta(seconds=call_timeout_seconds)
        self._closed = False

    async def initialize(self) -> McpInitializeSnapshot:
        return snapshot_initialize_result(await self._session.initialize())

    async def list_tools(self) -> McpToolPage:
        return snapshot_tool_page(await self._session.list_tools())

    async def call_tool(
        self,
        name: str,
        arguments: Mapping[str, JsonValue],
    ) -> McpCallResult:
        frozen = cast(Mapping[str, FrozenJsonValue], arguments)
        result = await self._session.call_tool(
            name,
            arguments=thaw_json_mapping(frozen),
            read_timeout_seconds=self._call_timeout,
        )
        return snapshot_call_result(result)

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._stack.aclose()
