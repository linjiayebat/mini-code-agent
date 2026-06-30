# M5a Governed Skills and Hooks Design

## Goal

Add two bounded extension surfaces without allowing repository content to become executable
authority:

1. discover and lazily load source-qualified `SKILL.md` instructions as untrusted data;
2. run deterministic, host-registered Tool lifecycle Hooks that may reduce authority but never
   grant authority or rewrite execution facts.

M5a is a library API and two read-only Agent tools. It does not add arbitrary command Hooks,
dynamic Python imports, HTTP Hooks, MCP Hooks, project configuration execution, automatic prompt
injection, a Skill marketplace, or OS-level isolation.

## Approaches Considered

### Reproduce the full Claude Code extension surface immediately

This would discover Skills, execute command/HTTP/prompt Hooks, load plugins, and connect MCP
servers in one release. It offers broad compatibility but combines four different trust and
process-lifecycle boundaries before any one of them has independent tests or audit semantics.
Rejected for M5a.

### Treat Skills as plugins and import their Python implementation

Python entry points or repository-local imports could make Skills executable. This is convenient
for trusted application plugins, but importing a project Skill gives repository content the
Agent process authority before Tool Policy is evaluated. Rejected.

### Use inert Skills and host-registered Hooks

The selected design treats a Skill as bounded Markdown plus strict metadata. Discovery exposes
metadata; an explicit read-only Tool loads the body on demand. Hooks are typed async objects
provided by the trusted application composition root. Pre-Tool Hooks can only continue or block;
ordinary ActionGuard, Policy, approval, and Tool execution remain authoritative. This produces a
useful extension contract while preserving the existing security model.

## Security Invariants

1. A Skill never registers a Tool, Hook, Provider, Policy rule, or Python module.
2. Skill discovery accepts only direct child directories containing one regular `SKILL.md`.
   Roots, Skill directories, and files that are symlinks, junctions, or other reparse points are
   rejected.
3. Skill files are bounded UTF-8 text with strict YAML frontmatter. Duplicate YAML keys, aliases,
   custom tags, unknown fields, non-string keys, and malformed documents are rejected.
4. Every Skill has a source-qualified identity: `managed:<name>`, `user:<name>`, or
   `project:<name>`. Cross-source names never silently override one another.
5. The metadata `name` must equal the Skill directory name. Names, descriptions, versions, file
   sizes, root counts, Skill counts, and body sizes have hard limits.
6. Discovery records a SHA-256 fingerprint. Loading reopens and revalidates the same regular file;
   identity or content drift returns a typed error and no body.
7. Disabled Skills cannot be listed for model use or loaded. Non-model-invocable Skills are not
   exposed by the Agent tools.
8. Skill bodies are returned as explicitly labelled untrusted content. They are never appended to
   the system prompt automatically.
9. Hook handlers are supplied by host composition. M5a never imports or executes Hook code named
   by a Skill, repository file, YAML document, environment variable, or model output.
10. Pre-Tool Hooks run after schema validation, preview creation, and the existing ActionGuard,
    but before Policy and approval. A Hook `continue` result only proceeds to normal Policy; it
    cannot convert `ask` or `deny` to `allow`.
11. A pre-Hook block, timeout, exception, malformed result, or required audit failure fails closed
    before Policy, approval, or Tool execution.
12. Post-Tool Hooks run only after Tool execution produced a `ToolResult`. Their failures are
    isolated and cannot change, hide, or replace that result.
13. Hook ordering is stable by `(priority, hook_id)`. Duplicate IDs are rejected at construction.
14. Hook count, timeout, IDs, public reasons, and audit records are bounded. Raw exceptions,
    Skill bodies, Tool arguments, Tool results, and secrets do not enter Hook audit records.
15. `asyncio.CancelledError` propagates. If cancellation arrives after Tool execution, the caller
    must treat the side effect as potentially completed, matching the existing Agent semantics.

## Skill File Contract

The first release accepts this exact shape:

```markdown
---
name: review-python
description: Review Python changes against the repository conventions.
version: 1.0.0
model_invocable: true
---

Read the changed files, inspect tests, and report evidence-backed findings.
```

Frontmatter fields:

- `name`: required, lowercase kebab case, 1-64 characters;
- `description`: required, one bounded non-empty string;
- `version`: required semantic version without build metadata;
- `model_invocable`: optional boolean, default `true`.

The parser uses a restricted `yaml.SafeLoader` subclass that rejects duplicate keys and YAML
aliases. Pydantic rejects unknown fields. The Markdown body must be non-empty after trimming but
is otherwise preserved as data. Syntax such as `!command`, embedded code blocks, links, and
instructions has no execution semantics in M5a.

Supporting files are not loaded in M5a. This avoids recursive traversal and gives the initial
contract one auditable content object. A later release may add bounded supporting-file reads
through the same filesystem and Policy boundaries.

## Skill Sources and Identity

`SkillRoot` is host configuration with:

- an existing absolute root path;
- `SkillSource.MANAGED`, `USER`, or `PROJECT`;
- a stable root ID for diagnostics.

The host chooses roots explicitly. The library does not search the whole home directory or
workspace. A source-qualified `SkillId` is `<source>:<name>`. Multiple roots with the same source
may be configured, but duplicate qualified IDs are conflicts and neither candidate is admitted.

There is no precedence lookup in M5a. Callers and the model use qualified IDs. This intentionally
differs from systems that silently choose enterprise, user, or project precedence: an untrusted
project Skill cannot shadow a user or managed Skill, and a deployment cannot change behavior only
by reordering roots.

`SkillTrust` is derived, never declared by the Skill:

- managed: `managed`;
- user: `user`;
- project: `untrusted_project`.

The trust label is included in metadata and loaded Tool output. It is descriptive provenance, not
a permission token.

## Package Boundaries

### `mini_code_agent.skills.models`

Immutable Pydantic models define:

- `SkillSource`;
- `SkillTrust`;
- `SkillRoot`;
- `SkillMetadata`;
- `SkillDescriptor`;
- `LoadedSkill`;
- `SkillIssueCode` and `SkillIssue`;
- `SkillDiscoveryReport`.

Descriptors contain qualified ID, source, derived trust, description, version, model visibility,
relative display path, byte count, and SHA-256. They do not contain the body or an absolute path.

Issues contain only bounded root IDs, optional qualified IDs, stable codes, and static public
messages. Filesystem exceptions and absolute paths are not exposed.

### `mini_code_agent.skills.parser`

The parser:

1. enforces the total byte limit before decoding;
2. decodes strict UTF-8 without BOM;
3. requires opening and closing `---` delimiter lines;
4. bounds frontmatter bytes;
5. loads YAML through the restricted safe loader;
6. validates exact Pydantic metadata;
7. bounds and requires the Markdown body;
8. computes canonical file SHA-256.

It returns an internal parsed value. All parser failures become stable `SkillIssueCode` values.

### `mini_code_agent.skills.catalog`

`SkillCatalog.discover(...)` validates configured roots and direct Skill children, builds
descriptors, reports quarantined invalid entries, rejects conflicts, applies a host-provided
disabled-ID set, and returns an immutable catalog plus discovery report.

`catalog.load(skill_id, expected_sha256)` requires an admitted, enabled, model-invocable Skill and
the descriptor fingerprint observed by the caller. It revalidates the path chain, file identity,
metadata, and hash. Drift returns `skill_changed`; callers must rediscover instead of consuming
new instructions under stale metadata.

### `mini_code_agent.skills.tools`

Two ordinary `SideEffect.READ_ONLY` tools expose Skills:

- `list_skills`: returns bounded model-invocable descriptors and discovery issues;
- `load_skill`: requires qualified `skill_id` and `expected_sha256`, then returns provenance,
  metadata, and the bounded Markdown body.

Tool failures use static codes such as `unknown_skill`, `skill_disabled`, `skill_changed`, and
`skill_unavailable`. Both tools still use the existing JSON Schema and Tool Registry contracts.
Loading a Skill does not alter the current Tool definitions or Policy engine.

### `mini_code_agent.hooks.models`

Immutable models define:

- `HookSource`: `managed`, `user`, or `project`;
- `HookPhase`: `pre_tool` or `post_tool`;
- `HookDecision`: `continue` or `block`;
- `PreToolHookResult`;
- `ToolHookContext`;
- `PostToolHookContext`;
- `HookOutcome`;
- `HookAuditRecord`.

Contexts contain the validated `ToolCall`, immutable `ToolDefinition`, trusted `ActionPreview`,
session mode, and execution trust source. Post context also contains the actual `ToolResult`.
Audit records contain identifiers, phase, source, outcome, elapsed milliseconds, Tool identity,
and a static failure code, but not raw content.

### `mini_code_agent.hooks.runner`

`PreToolHook` and `PostToolHook` are async structural protocols. `HookRegistration` is a frozen
host-side object containing ID, source, priority, phase, and handler.

`ToolHookRunner`:

- validates registration count, IDs, phases, and duplicates;
- sorts registrations deterministically;
- applies an individual timeout to every invocation;
- requires an exact `PreToolHookResult` from pre-Hooks;
- stops at the first block or pre-Hook failure;
- invokes every post-Hook independently after execution;
- emits one bounded audit record per invocation.

M5a does not run pre-Hooks concurrently because ordering and first-block semantics must be
deterministic. Post-Hooks also run sequentially so audit order is stable.

### `mini_code_agent.policy.executor`

`GovernedToolExecutor` gains an optional `ToolHookRunner`. Its order becomes:

```text
JSON Schema validation
  -> ActionPreview
  -> existing ActionGuard
  -> pre-Tool Hooks
  -> PolicyEngine
  -> explicit approval when required
  -> ToolRegistry execution
  -> post-Tool Hooks
  -> original ToolResult
```

Omitting Hooks preserves current behavior. Side-effecting Tools still require
`GovernedToolExecutor`; read-only Skill tools can also be placed behind it when a deployment wants
uniform Policy observation.

## Failure and Audit Semantics

Skill discovery quarantines an invalid entry and reports a bounded issue so one malformed Skill
does not hide unrelated valid Skills. An unsafe or unreadable configured root is reported and
contributes no Skills. Exceeding a global root or candidate limit stops discovery with a typed
configuration error rather than returning a partial, order-dependent catalog.

Conflicting qualified IDs are all excluded and reported. Disabled IDs are represented in the
catalog but omitted from model-facing listing and rejected on load. Unknown disabled IDs are
reported as configuration issues.

For Hooks:

- explicit pre-Hook `block` maps to the existing generic `permission_denied` Tool result;
- pre-Hook exception, timeout, invalid result, or audit failure also maps to
  `permission_denied`;
- post-Hook exception, timeout, invalid return, or audit failure is recorded when possible and the
  original Tool result is returned unchanged;
- raw Hook error text is never returned to the model;
- cancellation is never converted to a block or observer failure.

The first release supplies `NullHookAuditSink` and `RecordingHookAuditSink`. Durable Hook records
are deferred until execution context carries stable `run_id` and `turn` into the Tool boundary;
M5a does not claim durable Hook audit. Existing Agent Trace still records Tool start/completion and
the final denied or completed Tool result.

## Testing Strategy

### Skill parser and filesystem tests

- valid LF and CRLF documents;
- strict UTF-8, delimiter, metadata, body, semantic-version, and byte limits;
- duplicate keys, aliases, custom tags, unknown fields, and non-string keys;
- missing, linked, junction/reparse, directory, device-like, and changed files;
- direct-child-only discovery and ignored nested content;
- deterministic descriptors and fingerprints;
- source-qualified coexistence, same-source conflicts, disable behavior, and root/candidate limits;
- no absolute path or exception leak in issues.

### Skill Tool tests

- list returns metadata without bodies or absolute paths;
- load requires qualified ID plus expected fingerprint;
- changed content or metadata fails until rediscovery;
- disabled, non-model-invocable, unknown, and quarantined Skills cannot load;
- loaded output carries source and derived trust;
- Tool schema validation and result limits remain active.

### Hook model and runner tests

- deterministic priority/ID ordering and duplicate rejection;
- continue chain, first block, timeout, exception, malformed result, and audit failure;
- pre-Hook failures stop before later Hooks and Tool work;
- post-Hook failures do not alter results and later observers continue;
- cancellation propagation in both phases;
- bounded audit records contain no arguments, result body, exception text, or secret.

### Executor and integration tests

- execution order is guard, pre-Hooks, Policy, approval, Tool, post-Hooks;
- Hook continue cannot bypass Policy deny or approval;
- Hook block happens before Policy approval and mutation;
- omitted Hook runner preserves all existing tests;
- Fake Provider lists and loads a project Skill, then completes;
- a malicious Skill instruction asking for an out-of-policy write remains denied;
- a pre-Hook blocks a real governed write and a post-Hook observes a permitted read.

### Release gates

- Python 3.12 and 3.13 full suites on Windows and Ubuntu;
- Ruff format/check and strict Pyright;
- branch-aware package coverage at least 85%;
- Bandit and locked runtime dependency audit;
- wheel/sdist isolated smoke tests;
- `v0.13.0-alpha.0` prerelease with verified artifact hashes.

## Documentation and Learning Deliverables

M5a adds:

- an architecture guide for discovery, lazy loading, Hook ordering, and threat boundaries;
- an ADR explaining why project Skills remain inert and command Hooks are deferred;
- L9 prerequisite and implementation notes with Java SPI/Interceptor and Flink operator lifecycle
  comparisons;
- exercises tracing Skill provenance, TOCTOU drift, Policy non-bypass, Hook timeout, and post-side
  effect uncertainty;
- a resume highlight covering provenance-aware extension loading and monotonic authorization.

## Non-Claims

- Skill Markdown is not trusted because it parsed successfully.
- SHA-256 identifies observed content; it does not establish authorship or safety.
- A managed source label is host configuration, not a cryptographic signature.
- Lazy loading reduces context use; it does not prevent prompt injection after the body is loaded.
- In-process Hooks have the Agent process authority and are trusted composition code.
- M5a does not safely execute repository-provided Hook code.
- Hook timeout does not stop arbitrary work already delegated to another thread or process.
- Post-Hook isolation preserves the Tool result but cannot undo an already completed side effect.
- Existing Tool Policy constrains registered Tool actions, not arbitrary behavior inside a trusted
  in-process Hook.
- M5a does not implement MCP, command Hooks, HTTP Hooks, prompt Hooks, plugin installation, Skill
  supporting-file traversal, or durable Hook audit.

## Source Alignment

The design borrows the public concepts of a `SKILL.md` file with YAML frontmatter and lazily loaded
Markdown, plus lifecycle Hook events, from the official Claude Code documentation:

- <https://code.claude.com/docs/en/slash-commands>
- <https://code.claude.com/docs/en/hooks>
- <https://code.claude.com/docs/en/hooks-guide>
- <https://code.claude.com/docs/en/features-overview>

It intentionally narrows those concepts. Compatibility with every Claude Code frontmatter field,
Hook type, setting scope, and precedence rule is not an M5a goal.
