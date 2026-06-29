# ADR 0007: SQLite Session and Append-Only Trace

- Status: Accepted
- Date: 2026-06-30

## Context

Agent runs need lifecycle evidence after process exit. Session metadata and Trace events must
agree across crashes and concurrent local access. The initial product sketch proposed SQLite
indexes plus JSONL payloads, but a database transaction cannot atomically commit a separate file
append. M3b events are bounded metadata and do not require large-object storage.

Observability also has two failure policies: UI/log sinks should not abort work, while explicitly
configured durable state must not fail silently.

## Decision

Use one SQLite schema for Session records, Run projections, and canonical typed Trace events.
Append one event and update projections in the same `BEGIN IMMEDIATE` transaction.

Use WAL, full synchronous writes, foreign keys, bounded busy timeout, parameterized SQL, explicit
schema version 1, event IDs for idempotency, and a per-Session SHA-256 chain.

Keep `EventSink` best effort. Add an infrastructure-neutral `EventJournal` protocol; when injected,
`AgentRuntime` writes it before observer publication and treats failure as
`PERSISTENCE_ERROR`.

Record `ModelStarted` before Provider I/O and `ToolStarted` before Tool execution. A started-only
Tool is indeterminate and cannot be assumed safe to replay.

## Consequences

### Positive

- Trace and projections commit or roll back together.
- Sessions and Runs are queryable without replaying every event.
- Required persistence cannot fail silently.
- Exact duplicate events are idempotent.
- Sequence/hash verification detects inconsistent or modified local data.
- Runtime remains independent of SQLite through a Protocol.

### Trade-offs

- SQLite writes synchronously block the event loop for a bounded local interval.
- WAL and `synchronous=FULL` favor durability over maximum write throughput.
- Hash chaining is not authenticated tamper protection.
- Active or started-only state after a crash needs M3c recovery policy.
- Large payloads require a later content-addressed artifact store.

## Rejected Alternatives

- **SQLite index plus JSONL:** creates a cross-file commit/reconciliation problem.
- **JSONL only:** weakens concurrent sequence allocation, bounded query, migration, and projection
  semantics.
- **Best-effort persistence through EventSink:** can silently lose the exact evidence needed for
  recovery.
- **Persist full prompts/results now:** expands Secret and storage risk before Checkpoint design.

## Non-claims

- No Checkpoint/Resume or exactly-once external action.
- No encryption, signature, replication, distributed transaction, or remote database.
- No guarantee against an attacker with database write access.
