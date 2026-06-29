# ADR 0006: Deterministic Context Budget

- Status: Accepted
- Date: 2026-06-29

## Context

Long Agent runs accumulate prompts, tool schemas, ToolCalls, and ToolResults. Sending the complete
history can exceed a provider context window. Blind truncation can split correlated calls/results,
erase the original goal, or hide a completed side effect and cause it to be repeated.

Provider tokenizers differ and are not universally available for OpenAI-compatible endpoints.
LLM-generated summaries add cost, provenance, prompt-injection, and hallucination concerns before
durable Trace storage exists.

## Decision

Every provider request is prepared by an injected `ContextManager`.

The default manager uses deterministic canonical-JSON UTF-8 estimation, reserves output capacity,
and returns the full transcript unchanged when it fits. Otherwise it:

- pins the original user goal and newest completed unit;
- groups ToolCall and ToolResult batches atomically;
- pins completed side-effecting, mixed, and unknown-tool exchanges;
- retains a newest contiguous suffix of optional read-only/standalone units;
- records bounded omitted counts and a full-transcript SHA-256 marker;
- fails closed if fixed, latest, or pinned history cannot fit.

The runtime retains the full transcript and emits a typed `ContextCompacted` event. Provider
adapters remain unaware of selection.

## Consequences

### Positive

- Request construction is bounded, deterministic, provider-neutral, and testable offline.
- ToolCall/ToolResult correlation cannot be split by compaction.
- Evidence of completed side effects is not silently removed.
- Context failures stop before provider I/O with static public errors.
- Exact vendor estimators can be injected later without changing Agent Runtime.

### Trade-offs

- UTF-8 bytes are a conservative heuristic, not exact vendor tokens.
- Omitting read-only history can lose facts; the marker cannot reconstruct them.
- Pinning side effects may stop a long run earlier when required history fills the budget.
- The in-memory full transcript still grows until M3c persists checkpoint/message state.

## Rejected Alternatives

- **Blind oldest-message truncation:** can split tool exchanges and erase side-effect evidence.
- **Mandatory provider tokenizer:** couples Core to vendor/model versions and excludes some
  compatible endpoints.
- **LLM rolling summary in M3a:** adds an untrusted model call and unverifiable semantic loss
  before durable provenance exists.

## Non-claims

- The transcript fingerprint is not secret protection or authentication.
- M3a is not durable memory, checkpoint/resume, or exactly-once side-effect execution.
- Context admission does not guarantee provider acceptance.
