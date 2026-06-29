# ADR 0002: Provider Wire Protocols

- Status: Accepted
- Date: 2026-06-29

## Context

Agent Core uses provider-neutral `Message`, `ToolCall`, `ToolResult`, usage, finish reason, and
stream event types. Anthropic Messages and OpenAI-compatible Chat Completions represent the same
concepts differently:

- Anthropic uses ordered content blocks and places `tool_use` in assistant messages and
  `tool_result` in user messages.
- Chat Completions places function calls in `assistant.tool_calls` and returns each result as a
  separate `tool` role message.
- Both stream JSON arguments incrementally, but their event lifecycle and metadata placement
  differ.
- Provider errors may contain request data or sensitive service details and cannot cross the
  public boundary unchanged.

The adapters must preserve the existing Agent Core contract without introducing vendor SDK
objects or provider branches into the runtime.

## Decision

### Direct HTTP boundary

Use `httpx.AsyncClient` for HTTP and `httpx-sse` for standards-compliant SSE framing. Keep all
vendor request/response models private to each adapter.

This is not a rejection of mature SDKs. Direct HTTP is appropriate here because the project's
learning and architecture goals require the wire conversion to remain visible, small, and
testable. HTTP client injection plus `httpx.MockTransport` also makes every protocol test
deterministic and credential-free.

### Two explicit protocols

Implement:

- Anthropic Messages at `/v1/messages`.
- OpenAI-compatible Chat Completions at `/v1/chat/completions`.

OpenAI recommends the Responses API for new OpenAI-only applications, especially for semantic
streaming events. This adapter deliberately targets Chat Completions because it is the shared
compatibility surface implemented by many gateways and third-party model servers. A future
Responses adapter must be a separate implementation rather than conditional behavior hidden
inside `OpenAICompatibleProvider`.

### Streaming state machines

Do not expose raw SSE or parse tool calls with regular expressions.

- Anthropic validates `message_start`, each content block start/delta/stop sequence,
  `message_delta`, and terminal `message_stop`.
- OpenAI-compatible processing caches tool metadata by `tool_calls[].index`, accepts a final
  empty-choice usage chunk, and requires `[DONE]`.
- Tool argument fragments are emitted as normalized deltas and parsed as one strict JSON object
  only when the stream is complete.
- `ResponseCompleted` is emitted exactly once and only after lifecycle, usage, finish reason, and
  accumulated content validate.

### Failure and retry ownership

Adapters classify errors but do not retry:

| Condition | Normalized code | Retryable |
|---|---|---|
| 401/403 | `authentication` | No |
| 429 | `rate_limit` | Yes |
| 408/504 or client timeout | `timeout` | Yes |
| Other 5xx/network failure | `server` | Yes |
| Malformed, oversized, lossy, or unsupported response | `invalid_response` | No |

Retry count, backoff, jitter, idempotency, and total time budget belong to orchestration. Hiding
retries in an adapter would make model cost and latency invisible to Agent Runtime.

### Fail closed on lossy content

M1b supports text and client-side tool calls. It rejects vendor-only response blocks and
continuation states such as Anthropic `pause_turn` because the current domain model cannot
round-trip them losslessly. New content types require an explicit domain-model extension,
contract tests, and a versioned decision.

### Security limits

- Non-streaming bodies and cumulative SSE data have a configurable limit capped at 16 MiB.
- Timeout is bounded to 600 seconds.
- Base URLs reject credentials, query strings, fragments, and non-HTTP schemes.
- Provider endpoint paths reject traversal, query strings, fragments, and absolute URLs.
- Extra compatibility headers cannot replace authorization or content type.
- Public exceptions never include raw provider bodies, request payloads, API keys, or raw
  transport exception messages.
- Internally created HTTP clients disable redirects and are closed by the adapter; injected
  clients remain caller-owned.

## Consequences

### Positive

- Agent Core remains provider-neutral.
- Protocol behavior is testable without network access or secrets.
- Sparse and interleaved tool-call streams become deterministic domain events.
- Error handling has one public vocabulary across providers.
- Adding a provider requires a boundary adapter and contract tests, not runtime changes.

### Trade-offs

- The project owns wire-schema maintenance.
- Vendor-only features are unavailable until the domain contract can represent them.
- Live API compatibility still requires optional credentialed smoke tests; MockTransport tests
  prove conversion logic, not external service availability.
- Chat Completions compatibility does not expose Responses-only capabilities.

## References

- [Anthropic Messages API](https://platform.claude.com/docs/en/api/messages/create)
- [Anthropic streaming](https://platform.claude.com/docs/en/build-with-claude/streaming)
- [Anthropic tool results](https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls)
- [Anthropic errors](https://platform.claude.com/docs/en/api/errors)
- [OpenAI Chat Completions](https://platform.openai.com/docs/api-reference/chat/create)
- [OpenAI function calling](https://platform.openai.com/docs/guides/function-calling?api-mode=chat)
- [OpenAI Chat Completions streaming](https://platform.openai.com/docs/api-reference/chat-streaming)
