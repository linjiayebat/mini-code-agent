# M8 Local Web Console Design

## Goal

Add a local, single-user Web console that makes the existing Mini CodeAgent runtime observable
and controllable without weakening its Workspace, Policy, approval, or Provider boundaries.

## Product Scope

The first screen is the working Agent console, not a landing page. It provides:

- fixed startup Workspace and Provider status;
- a task transcript and prompt composer;
- live Agent lifecycle and Tool activity;
- explicit write/command approval with resources, argv, reason, risk, and diff;
- run cancellation;
- bounded run summaries and public errors;
- responsive desktop and mobile layouts.

M8 does not add account management, cloud hosting, multi-user access, browser-side API-key
storage, durable conversation memory, image generation, arbitrary Workspace selection, or remote
network binding.

## Visual Direction

The console uses the recommended three-pane engineering workbench:

- compact top bar for product, Workspace, Provider, model, connection state, and token usage;
- left rail for local sessions and Workspace context;
- center transcript for tasks, Agent output, progress, and prompt composition;
- right inspector for Activity and Changes, including approval actions and bounded diffs.

The visual system is quiet and operational: neutral surfaces, charcoal text, teal active state,
amber pending state, green additions, and red deletions. It avoids gradients, decorative cards,
oversized typography, nested cards, and marketing composition. Corners are at most 6px. Dense
panels use 13-15px text and stable responsive tracks.

## Architecture

### Backend

FastAPI is an explicit runtime dependency. `mini-code-agent web` starts Uvicorn on
`127.0.0.1` only and serves package-owned static assets.

`WebRunManager` owns at most one active run. It creates:

- a `WebApprovalHandler` that publishes a typed approval event and waits on a Future;
- a `WebEventSink` that serializes existing `AgentEvent` values;
- one background task that invokes the existing `run_task`;
- a bounded subscriber queue for Server-Sent Events.

The manager publishes normalized envelopes:

```json
{
  "sequence": 1,
  "type": "run_started",
  "payload": {}
}
```

It never publishes prompts, Tool arguments/results, API keys, or raw exception text through
lifecycle events. The explicit approval payload contains only the already bounded
`ApprovalRequest` preview needed for user authorization.

### API

- `GET /api/bootstrap`: product version, Workspace display path, Provider, model, key-configured
  flag, and CSRF token.
- `POST /api/runs`: validate and start one task.
- `GET /api/runs/{run_id}/events`: replay retained events, then stream new SSE events.
- `POST /api/runs/{run_id}/approvals/{tool_call_id}`: approve or reject one pending action.
- `POST /api/runs/{run_id}/cancel`: cancel and join the active Agent task.
- `GET /healthz`: local process health.

Requests that mutate state require an `X-Mini-Code-Agent-Token` header matching the random token
embedded into the bootstrap payload.

### Frontend

The frontend is package-owned HTML, CSS, and browser-native JavaScript. It has no CDN or remote
asset dependency and uses a small set of local Lucide-compatible SVG icons.

The browser:

- fetches bootstrap state;
- starts a run;
- subscribes to SSE;
- renders lifecycle rows and final output;
- opens approval content in the right inspector;
- posts approve/reject/cancel decisions with the CSRF token;
- reconnects with the last received sequence;
- disables incompatible controls while a run is active.

## Security

- `web` rejects non-loopback hosts instead of exposing the Agent over LAN.
- The Workspace is fixed by the CLI process and never accepted from browser input.
- API keys remain server-side settings. The browser receives only `api_key_configured`.
- Mutating routes require the process-random token.
- CORS is not enabled. Origin checks accept only the current loopback origin.
- Static files are selected from a fixed resource map, not user paths.
- Browser rendering uses `textContent`; model text, paths, reasons, commands, and diffs are never
  inserted as HTML.
- Approvals are single-use and bound to run ID plus ToolCall ID.
- Disconnecting the browser does not approve anything. Pending approvals remain blocked until
  explicit rejection, approval, cancellation, or process shutdown.
- The Web console remains local process governance, not an OS sandbox.

## Error Handling

Configuration failures are returned before a run starts. Concurrent start attempts return
HTTP 409. Unknown/stale approval IDs return 404 or 409 without executing a Tool. Queue overflow
cancels the run and emits a bounded terminal error. Client disconnects do not cancel the run;
the user can reconnect and replay retained events.

## Testing

- Unit tests cover manager lifecycle, approval, rejection, cancellation, stale decisions, event
  redaction, and queue bounds with `ScriptedProvider`.
- ASGI tests cover bootstrap, CSRF, loopback origin checks, start/conflict, SSE replay, approval,
  cancellation, health, and static assets.
- CLI tests cover loopback enforcement, option forwarding, and no-browser mode.
- Browser verification checks 1440x1024, 1024x768, and 390x844 for nonblank rendering,
  stable layout, no overlap, working tabs, run state, approval state, and responsive collapse.
- No live Provider credential is required in CI.

## SiliconFlow Compatibility

The Web console reuses the M7 `OpenAICompatibleProvider`. SiliconFlow documents
`POST /v1/chat/completions`, Bearer authentication, SSE streaming, and function tools. M8 does
not call `POST /v1/images/generations`; that API is reserved for a later governed image Tool.

The user-provided key is never committed. A live smoke requires
`MINI_CODE_AGENT_OPENAI_API_KEY` to be set in the process environment before launching the Web
console.
