# M1b Provider Adapters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add production-shaped Anthropic Messages and OpenAI-compatible Chat Completions adapters without leaking vendor wire types into Agent Core.

**Architecture:** Both adapters implement the existing `ModelProvider` protocol and translate at the provider boundary. A small shared HTTP module owns client lifecycle, bounded JSON/SSE decoding, request IDs, and normalized transport/status errors; each vendor module owns only message/tool/event conversion. Streaming parsers are explicit state machines that accumulate text and per-index tool arguments, emit normalized deltas, and build one validated `ResponseCompleted`.

**Tech Stack:** Python 3.12/3.13, `asyncio`, Pydantic v2, `httpx`, `httpx-sse`, Pytest, `pytest-asyncio`, `httpx.MockTransport`, Ruff, strict Pyright.

**Protocol references:**

- Anthropic [Messages API](https://platform.claude.com/docs/en/api/messages/create), [streaming](https://platform.claude.com/docs/en/build-with-claude/streaming), [tool results](https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls), and [errors](https://platform.claude.com/docs/en/api/errors).
- OpenAI [Chat Completions](https://platform.openai.com/docs/api-reference/chat/create), [function calling](https://platform.openai.com/docs/guides/function-calling?api-mode=chat), and [Chat Completions streaming](https://platform.openai.com/docs/api-reference/chat-streaming).

---

## File Map

- Create `src/mini_code_agent/providers/http.py`: HTTP client ownership, bounded response decoding, status/transport error normalization, and safe request ID extraction.
- Create `src/mini_code_agent/providers/anthropic.py`: Anthropic Messages request/response and SSE conversion.
- Create `src/mini_code_agent/providers/openai_compatible.py`: OpenAI-compatible Chat Completions request/response and SSE conversion.
- Modify `src/mini_code_agent/providers/base.py`: add protocol/config validation needed by concrete adapters without introducing vendor fields.
- Modify `src/mini_code_agent/providers/__init__.py`: export stable public provider types.
- Modify `pyproject.toml` and `uv.lock`: add bounded `httpx` and `httpx-sse` runtime dependencies.
- Create `tests/unit/providers/conftest.py`: shared request, tool, and response fixtures.
- Create `tests/unit/providers/test_http.py`: bounded decoding and normalized transport/status failures.
- Create `tests/unit/providers/test_anthropic.py`: Anthropic request, response, stream, malformed-data, and secret-safety contracts.
- Create `tests/unit/providers/test_openai_compatible.py`: OpenAI-compatible request, response, stream, malformed-data, and secret-safety contracts.
- Create `tests/integration/test_provider_contract.py`: parameterized domain-level contract shared by both adapters.
- Create `docs/adr/0002-provider-wire-protocols.md`: explain direct HTTP, Chat Completions compatibility, SSE, and retry ownership.
- Create `docs/architecture/provider-adapters.md`: conversion tables, state machines, limits, and failure semantics.
- Modify `docs/learning/knowledge-map.md` and `docs/learning/progress.md`: complete L2 with reproducible evidence.
- Modify `docs/resume/project-profile.md`, `README.md`, `CHANGELOG.md`, and package version: publish only measured M1b claims.

## Task 1: Freeze Shared HTTP Boundary

**Files:**
- Modify: `pyproject.toml`
- Create: `src/mini_code_agent/providers/http.py`
- Create: `tests/unit/providers/test_http.py`

- [ ] **Step 1: Add failing tests for bounded JSON and safe errors**

Cover these exact behaviors with `httpx.MockTransport`:

```python
@pytest.mark.asyncio
async def test_post_json_maps_401_without_echoing_secret() -> None:
    secret = "provider-secret-value"
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                401,
                json={"error": {"message": f"rejected {secret}"}},
                request=request,
            )
        )
    )
    transport = ProviderHttpTransport(client=client, max_response_bytes=1024)

    with pytest.raises(ProviderError) as captured:
        await transport.post_json(
            "/v1/messages",
            headers={"x-api-key": secret},
            payload={},
        )

    assert captured.value.code is ProviderErrorCode.AUTHENTICATION
    assert secret not in captured.value.public_message
    assert secret not in str(captured.value)


@pytest.mark.asyncio
async def test_post_json_rejects_oversized_body_before_json_decode() -> None:
    transport = mocked_transport(httpx.Response(200, content=b"x" * 33))
    with pytest.raises(ProviderError, match="response exceeded"):
        await transport.post_json("/v1/messages", headers={}, payload={})
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
python -m uv run pytest tests/unit/providers/test_http.py -q
```

Expected: collection fails because `ProviderHttpTransport` does not exist.

- [ ] **Step 3: Add runtime dependencies**

Run:

```powershell
python -m uv add "httpx>=0.28,<1" "httpx-sse>=0.4,<1"
```

Expected: `pyproject.toml` and `uv.lock` contain resolved, bounded dependencies.

- [ ] **Step 4: Implement the shared boundary**

Implement:

```python
class ProviderHttpTransport:
    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float,
        max_response_bytes: int = 4 * 1024 * 1024,
        client: httpx.AsyncClient | None = None,
    ) -> None: ...

    async def post_json(
        self,
        path: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, object],
    ) -> tuple[JsonObject, str | None]: ...

    def stream_sse(
        self,
        path: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, object],
    ) -> AsyncContextManager[AsyncIterator[ServerSentEvent]]: ...

    async def aclose(self) -> None: ...
```

Requirements:

- Own and close only internally created clients.
- Use HTTPX timeouts and convert connect/read/write/pool timeouts to retryable `TIMEOUT`.
- Convert 401/403 to non-retryable `AUTHENTICATION`, 429 to retryable `RATE_LIMIT`,
  408/504 to retryable `TIMEOUT`, 5xx to retryable `SERVER`, and remaining 4xx to
  non-retryable `INVALID_RESPONSE`.
- Never include response bodies, request payloads, API keys, URLs with query strings, or raw
  exception text in public errors.
- Bound non-streaming bytes before JSON decoding and validate that the top level is an object.
- Bound cumulative SSE data bytes and reject malformed JSON events.
- Preserve a bounded request ID from `request-id`, `x-request-id`, or JSON metadata.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run:

```powershell
python -m uv run pytest tests/unit/providers/test_http.py -q
python -m uv run pyright src/mini_code_agent/providers/http.py tests/unit/providers/test_http.py
```

Expected: all focused tests pass and Pyright reports zero errors.

- [ ] **Step 6: Commit**

```powershell
git add pyproject.toml uv.lock src/mini_code_agent/providers/http.py tests/unit/providers/test_http.py
git commit -m "feat: add bounded provider HTTP transport"
```

## Task 2: Implement Anthropic Non-streaming Adapter

**Files:**
- Create: `src/mini_code_agent/providers/anthropic.py`
- Create: `tests/unit/providers/conftest.py`
- Create: `tests/unit/providers/test_anthropic.py`

- [ ] **Step 1: Add failing request conversion tests**

Assert the posted request has:

```python
assert request.headers["x-api-key"] == "test-key"
assert request.headers["anthropic-version"] == "2023-06-01"
assert body == {
    "model": "claude-test",
    "max_tokens": 1024,
    "system": "Work carefully.",
    "messages": [
        {"role": "user", "content": [{"type": "text", "text": "Inspect."}]},
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "call-1",
                    "name": "runtime_info",
                    "input": {},
                }
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "call-1",
                    "content": "{}",
                    "is_error": False,
                }
            ],
        },
    ],
    "tools": [
        {
            "name": "runtime_info",
            "description": "Return runtime metadata.",
            "input_schema": {"type": "object", "properties": {}},
        }
    ],
}
```

Also prove tool results precede text in a mixed user message.

- [ ] **Step 2: Add failing response conversion tests**

Cover text-only, mixed text plus parallel `tool_use`, usage, request ID, all supported stop
reasons, unknown blocks, missing fields, invalid tool input, duplicate tool IDs, and unexpected
role. A valid tool response must normalize to:

```python
ModelResponse(
    message=Message(
        role=MessageRole.ASSISTANT,
        content=(
            TextBlock(text="Checking."),
            ToolCall(
                id="toolu_1",
                name="runtime_info",
                arguments={"verbose": True},
            ),
        ),
    ),
    finish_reason=FinishReason.TOOL_CALL,
    usage=TokenUsage(input_tokens=12, output_tokens=7),
    provider_request_id="req_1",
)
```

- [ ] **Step 3: Run Anthropic tests and verify RED**

Run:

```powershell
python -m uv run pytest tests/unit/providers/test_anthropic.py -q
```

Expected: import fails because `AnthropicProvider` does not exist.

- [ ] **Step 4: Implement configuration and non-streaming conversion**

Expose:

```python
class AnthropicProvider:
    def __init__(
        self,
        *,
        api_key: SecretStr,
        model: str,
        max_tokens: int = 4096,
        base_url: str = "https://api.anthropic.com",
        anthropic_version: str = "2023-06-01",
        timeout_seconds: float = 60.0,
        max_response_bytes: int = 4 * 1024 * 1024,
        client: httpx.AsyncClient | None = None,
    ) -> None: ...

    @property
    def capabilities(self) -> ProviderCapabilities: ...
    async def complete(self, request: ModelRequest) -> ModelResponse: ...
    async def stream(
        self, request: ModelRequest
    ) -> AsyncIterator[ProviderStreamEvent]: ...
    async def aclose(self) -> None: ...
```

Conversion rules:

- Send `system_prompt` in the top-level `system` field, not as a message.
- Preserve content block order except Anthropic's required `tool_result`-before-text order in user
  messages.
- Send tool schemas as `input_schema`.
- Accept only client `text` and `tool_use` output blocks in this milestone.
- Map `end_turn` and `stop_sequence` to `STOP`, `tool_use` to `TOOL_CALL`,
  `max_tokens` and `model_context_window_exceeded` to `MAX_TOKENS`, and `refusal` to
  `CONTENT_FILTER`; reject `pause_turn` because M1b does not preserve vendor-only continuation
  blocks.
- Reject a mismatch between stop reason and actual tool calls.
- Convert every parser/Pydantic failure to a non-retryable, secret-safe `INVALID_RESPONSE`.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run:

```powershell
python -m uv run pytest tests/unit/providers/test_anthropic.py -q
python -m uv run pyright src/mini_code_agent/providers/anthropic.py
```

Expected: all non-streaming Anthropic tests pass.

- [ ] **Step 6: Commit**

```powershell
git add src/mini_code_agent/providers/anthropic.py tests/unit/providers
git commit -m "feat: add Anthropic Messages adapter"
```

## Task 3: Implement Anthropic Streaming State Machine

**Files:**
- Modify: `src/mini_code_agent/providers/anthropic.py`
- Modify: `tests/unit/providers/test_anthropic.py`

- [ ] **Step 1: Add failing streaming tests**

Feed raw SSE events for:

- `message_start` with input usage and request ID.
- Interleaved text and two tool blocks.
- Multiple `input_json_delta` fragments.
- cumulative output usage in `message_delta`.
- `message_stop`.
- `ping` and unknown forward-compatible event types.
- in-stream `error`.
- duplicate indices, malformed JSON, incomplete tool blocks, missing terminal event, oversized
  stream, and disconnect.

Assert emitted events include metadata on every tool fragment:

```python
assert events == [
    TextDelta(text="Checking"),
    ToolCallDelta(
        index=1,
        tool_call_id="toolu_1",
        name="runtime_info",
        partial_json='{"verbose":',
    ),
    ToolCallDelta(
        index=1,
        tool_call_id="toolu_1",
        name="runtime_info",
        partial_json="true}",
    ),
    ResponseCompleted(response=expected_response),
]
```

- [ ] **Step 2: Run the streaming tests and verify RED**

Run:

```powershell
python -m uv run pytest tests/unit/providers/test_anthropic.py -k stream -q
```

Expected: failures show missing SSE implementation.

- [ ] **Step 3: Implement explicit stream state**

Maintain bounded state:

```python
@dataclass
class _AnthropicToolState:
    content_index: int
    tool_call_id: str
    name: str
    argument_fragments: list[str]
    byte_count: int
```

The parser must:

- require valid lifecycle ordering;
- cache `id/name` from `content_block_start`;
- repeat cached metadata in every normalized `ToolCallDelta`;
- parse accumulated tool JSON only at `content_block_stop`;
- build final content in provider content-index order;
- use cumulative usage from the latest message event;
- emit exactly one `ResponseCompleted`;
- normalize in-stream errors and never emit a partial completed response.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```powershell
python -m uv run pytest tests/unit/providers/test_anthropic.py -q
```

Expected: all Anthropic tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/mini_code_agent/providers/anthropic.py tests/unit/providers/test_anthropic.py
git commit -m "feat: stream Anthropic Messages responses"
```

## Task 4: Implement OpenAI-compatible Non-streaming Adapter

**Files:**
- Create: `src/mini_code_agent/providers/openai_compatible.py`
- Create: `tests/unit/providers/test_openai_compatible.py`

- [ ] **Step 1: Add failing request conversion tests**

Assert:

```python
assert request.headers["authorization"] == "Bearer test-key"
assert body["model"] == "compatible-test"
assert body["messages"] == [
    {"role": "system", "content": "Work carefully."},
    {"role": "user", "content": "Inspect."},
    {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call-1",
                "type": "function",
                "function": {"name": "runtime_info", "arguments": "{}"},
            }
        ],
    },
    {"role": "tool", "tool_call_id": "call-1", "content": "{}"},
]
assert body["tools"][0] == {
    "type": "function",
    "function": {
        "name": "runtime_info",
        "description": "Return runtime metadata.",
        "parameters": {"type": "object", "properties": {}},
    },
}
```

For mixed user text/tool results, assert the adapter emits tool messages followed by a user text
message while preserving semantic order.

- [ ] **Step 2: Add failing response tests**

Cover text-only, multiple `tool_calls`, JSON-string arguments, usage, HTTP request ID, empty
content with tools, invalid choices, multiple choices, invalid arguments, unknown finish reasons,
duplicate call IDs, and provider error envelopes.

- [ ] **Step 3: Run OpenAI-compatible tests and verify RED**

Run:

```powershell
python -m uv run pytest tests/unit/providers/test_openai_compatible.py -q
```

Expected: import fails because `OpenAICompatibleProvider` does not exist.

- [ ] **Step 4: Implement configuration and conversion**

Expose:

```python
class OpenAICompatibleProvider:
    def __init__(
        self,
        *,
        api_key: SecretStr,
        model: str,
        base_url: str = "https://api.openai.com",
        timeout_seconds: float = 60.0,
        max_response_bytes: int = 4 * 1024 * 1024,
        extra_headers: Mapping[str, str] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None: ...
```

Rules:

- Target `/v1/chat/completions`; this is a compatibility adapter, not an OpenAI Responses adapter.
- Use Bearer auth and reject caller-supplied headers that override authorization/content type.
- Encode tool arguments as compact deterministic JSON.
- Require exactly one choice.
- Map `stop` to `STOP`, `tool_calls` to `TOOL_CALL`, `length` to `MAX_TOKENS`, and
  `content_filter` to `CONTENT_FILTER`.
- Reject deprecated `function_call` responses and malformed/unknown wire shapes.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run:

```powershell
python -m uv run pytest tests/unit/providers/test_openai_compatible.py -q
python -m uv run pyright src/mini_code_agent/providers/openai_compatible.py
```

Expected: all non-streaming OpenAI-compatible tests pass.

- [ ] **Step 6: Commit**

```powershell
git add src/mini_code_agent/providers/openai_compatible.py tests/unit/providers/test_openai_compatible.py
git commit -m "feat: add OpenAI-compatible chat adapter"
```

## Task 5: Implement OpenAI-compatible Streaming State Machine

**Files:**
- Modify: `src/mini_code_agent/providers/openai_compatible.py`
- Modify: `tests/unit/providers/test_openai_compatible.py`

- [ ] **Step 1: Add failing stream tests**

Cover:

- text deltas;
- tool chunks where only the first fragment includes `id` and `name`;
- two interleaved tool-call indices;
- finish reason before final usage chunk;
- empty-choice usage chunk from `stream_options.include_usage`;
- `[DONE]`;
- malformed JSON, index gaps, metadata changes, incomplete tools, missing usage, missing `[DONE]`,
  oversized stream, and provider error events.

Assert the request includes:

```python
assert body["stream"] is True
assert body["stream_options"] == {"include_usage": True}
```

- [ ] **Step 2: Run stream tests and verify RED**

Run:

```powershell
python -m uv run pytest tests/unit/providers/test_openai_compatible.py -k stream -q
```

Expected: failures show missing stream aggregation.

- [ ] **Step 3: Implement stream aggregation**

Maintain state by `tool_calls[].index`; first chunks establish ID/name and later chunks append
arguments. Emit only tool argument fragments after metadata is known, require a terminal
`[DONE]`, allow the documented empty-choice usage chunk, and produce one validated final
response. If a compatibility server omits usage, return zero usage rather than fail because
`ProviderCapabilities.usage` describes support, not guaranteed delivery after interruption.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```powershell
python -m uv run pytest tests/unit/providers/test_openai_compatible.py -q
```

Expected: all OpenAI-compatible tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/mini_code_agent/providers/openai_compatible.py tests/unit/providers/test_openai_compatible.py
git commit -m "feat: stream OpenAI-compatible chat responses"
```

## Task 6: Prove the Shared Provider Contract

**Files:**
- Modify: `src/mini_code_agent/providers/__init__.py`
- Create: `tests/integration/test_provider_contract.py`

- [ ] **Step 1: Add parameterized contract tests**

For both adapters, use vendor-shaped mock responses to prove:

```python
@pytest.mark.parametrize("provider_factory", PROVIDER_FACTORIES)
@pytest.mark.asyncio
async def test_provider_contract_normalizes_tool_round_trip(provider_factory) -> None:
    provider = provider_factory()
    first = await provider.complete(tool_request())
    assert first.finish_reason is FinishReason.TOOL_CALL
    assert first.message.tool_calls[0].name == "runtime_info"

    second = await provider.complete(result_request(first.message.tool_calls[0]))
    assert second.finish_reason is FinishReason.STOP
    assert second.message.text == "done"
```

Also prove both stream APIs end with `ResponseCompleted`, use normalized usage, map 429
identically, satisfy the runtime-checkable shape of `ModelProvider`, and never expose API keys.

- [ ] **Step 2: Run contract tests and verify RED**

Run:

```powershell
python -m uv run pytest tests/integration/test_provider_contract.py -q
```

Expected: failures identify any remaining cross-adapter mismatch.

- [ ] **Step 3: Make only boundary fixes and export public types**

Export `AnthropicProvider` and `OpenAICompatibleProvider`; do not add provider-specific branches
to `AgentRuntime`.

- [ ] **Step 4: Run contract and Agent Loop integration tests**

Run:

```powershell
python -m uv run pytest tests/integration/test_provider_contract.py tests/integration/test_agent_loop.py -q
```

Expected: both adapters and existing Agent Core pass unchanged.

- [ ] **Step 5: Commit**

```powershell
git add src/mini_code_agent/providers tests/integration/test_provider_contract.py
git commit -m "test: enforce real provider contracts"
```

## Task 7: Document Design and Learning Evidence

**Files:**
- Create: `docs/adr/0002-provider-wire-protocols.md`
- Create: `docs/architecture/provider-adapters.md`
- Modify: `docs/learning/knowledge-map.md`
- Modify: `docs/learning/progress.md`
- Modify: `docs/resume/project-profile.md`
- Modify: `README.md`

- [ ] **Step 1: Write the ADR**

Record these decisions:

- direct HTTP keeps vendor SDK types out of the core while `httpx-sse` handles SSE framing;
- Chat Completions is used specifically for OpenAI-compatible ecosystem coverage;
- a separate Responses API adapter may be added later;
- adapters parse but do not retry, because retry budgets and idempotency belong to orchestration;
- public errors omit raw provider bodies and exceptions;
- vendor-only content types fail closed until the domain model can preserve them losslessly.

- [ ] **Step 2: Write architecture and learning material**

Include:

- side-by-side message/tool/finish/usage/error conversion tables;
- both stream state machines;
- Python concepts: async context managers, async generators, dependency injection, structural
  typing, dataclasses for parser state, Pydantic boundary validation;
- Java analogies: `Protocol` vs interface, async generator vs reactive stream, adapter vs anti-
  corruption layer, `MockTransport` vs mocked HTTP server;
- exercises that ask the learner to trace a two-tool stream and classify five HTTP failures.

- [ ] **Step 3: Update resume claims with measured evidence only**

For each highlight, state why it exists, implementation, delivered function, and solved problem.
Do not claim live-provider success unless a credentialed smoke test actually ran.

- [ ] **Step 4: Run doc checks**

Run:

```powershell
rg -n "TODO|TBD|待补充|待回填" docs README.md
rg -n "真实 Adapter 待|real adapters pending" docs README.md
```

Expected: no stale M1b placeholder or false claim remains; future milestone placeholders in the
resume metrics template remain explicitly labeled as unmeasured.

- [ ] **Step 5: Commit**

```powershell
git add docs README.md
git commit -m "docs: explain provider adapter architecture"
```

## Task 8: Quality, Security, Review, and Alpha Release

**Files:**
- Modify: `src/mini_code_agent/__init__.py`
- Modify: `pyproject.toml`
- Modify: `CHANGELOG.md`
- Modify tests only for concrete review findings.

- [ ] **Step 1: Run the complete local gate**

```powershell
python -m uv lock --check
python -m uv run ruff format --check .
python -m uv run ruff check .
python -m uv run pyright
python -m uv run pytest --cov
python -m uv build --build-constraint build-constraints.txt --require-hashes
python -m uv run --python 3.13 --isolated --no-project --with dist/*.whl tests/smoke_test.py
python -m uv run --python 3.13 --isolated --no-project --with dist/*.tar.gz tests/smoke_test.py
```

Expected: all commands succeed, coverage stays at or above 85%, and both artifacts install.

- [ ] **Step 2: Run security and dependency checks**

```powershell
python -m uv run --with bandit bandit -q -r src
python -m uv run --with pip-audit pip-audit
```

Expected: no high-confidence code finding and no known runtime dependency vulnerability. Record
tool versions and exact results in `docs/learning/progress.md`.

- [ ] **Step 3: Run adversarial self-review**

Inspect for:

- secret/raw-body leakage;
- unbounded response, event, tool-fragment, ID, model, base URL, and header inputs;
- lifecycle/client leaks;
- accepting redirects to an unintended host;
- ambiguous URL joining;
- malformed SSE completing successfully;
- incorrect retryability;
- changed Agent Core behavior;
- false resume or README claims.

Add a RED regression test before every code fix.

- [ ] **Step 4: Request independent code review**

Review the full M1b diff against this plan. Address each valid finding with a failing regression
test, implementation fix, focused verification, and full gate rerun.

- [ ] **Step 5: Bump and verify release version**

Write a failing package-version test for `0.3.0a0`, update both `pyproject.toml` and
`src/mini_code_agent/__init__.py`, move M1b changes from Unreleased to
`[0.3.0-alpha.0] - 2026-06-29`, rebuild, and verify artifact names:

```text
mini_code_agent-0.3.0a0-py3-none-any.whl
mini_code_agent-0.3.0a0.tar.gz
```

- [ ] **Step 6: Merge and tag**

After all evidence is green:

```powershell
git tag -a v0.3.0-alpha.0 -m "M1b provider adapters"
```

Expected: clean `main`, tag points to the reviewed release commit, and M2 is the next active
milestone.
