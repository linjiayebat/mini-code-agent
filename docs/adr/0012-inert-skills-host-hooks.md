# ADR 0012: Keep Project Skills Inert and Register Hooks in Host Code

- Status: Accepted
- Date: 2026-07-01

## Context

Skills and Hooks improve an Agent harness only if they do not become an alternate authority path.
Repository files are controlled by the same untrusted project the Agent inspects. Dynamically
importing Python or executing a command named by that repository would happen before ordinary Tool
Policy and approval.

The full public Claude Code surface includes Skill frontmatter, supporting files, and several Hook
handler types. Reproducing all of it together would combine prompt provenance, filesystem
traversal, process execution, network access, lifecycle ordering, and audit correlation in one
change.

## Decision

M5a uses two narrower contracts:

1. Skills are bounded `SKILL.md` data. Strict discovery returns source-qualified metadata and a
   content fingerprint. Explicit loading revalidates identity and returns labelled untrusted
   Markdown. Skills cannot register executable capabilities.
2. Hooks are typed async handlers supplied directly by the trusted application composition root.
   Pre-Hooks may only continue or veto. Policy and approval still decide authority. Post-Hooks are
   isolated observers and cannot replace Tool results.

Project/user/managed source is derived from host-selected roots or registrations. It is never
accepted from extension content. Cross-source Skill names coexist; same qualified IDs fail instead
of using precedence.

Command, HTTP, prompt, MCP, dynamic-import, and repository-configured Hooks are deferred.

## Consequences

Positive:

- project instructions cannot directly execute code or register Tools;
- source qualification removes silent shadowing;
- lazy load saves context and supports content drift detection;
- Hook authorization is monotonic: extensions can reduce but not increase authority;
- failures have deterministic pre/post semantics and bounded audit metadata.

Negative:

- the first release is not drop-in compatible with every Claude Code Skill or Hook field;
- supporting Skill files are unavailable;
- in-process Hooks are still trusted code with process authority;
- Hook audit is in-memory until run/turn context reaches the Tool boundary.

## Alternatives Rejected

- **Dynamic project imports:** grants repository code process authority.
- **Arbitrary command Hooks:** requires a separate governed process profile, environment, output,
  timeout, and approval design.
- **Silent source precedence:** lets configuration order change which instructions execute.
- **Automatic system-prompt injection:** spends context on every Skill and hides provenance from
  the model/tool transcript.
