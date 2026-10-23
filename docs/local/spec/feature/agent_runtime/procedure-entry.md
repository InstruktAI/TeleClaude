---
description: Procedure assignments deliver a short loader with role, bound inputs and entry facts, and retrieve their instructions from the published procedure closure.
visibility: internal
---

# Procedure Entry — Spec

## Required reads

@docs/local/spec/domain/agent_runtime.md

## What it is

A procedure entry creates an agent session from a published procedure identified
by its domain-qualified snippet ID. The runtime resolves the procedure's declared
role, parameters and dispatch defaults, applies the caller's dispatch privilege,
and persists the resolved assignment before the agent starts. The role catalog
owns role resolution
(`local/projects/teleclaude/spec/feature/identity/agent-roles`).

The first message is a short loader carrying the role framing, bound parameters,
raw arguments and entry-specific facts, followed by an instruction to retrieve
the named procedure with `telec docs get <procedure-id> --closure` and follow it.
Additional assignment context is carried once. The procedure's instructions
remain in the documentation system; entry writes no per-session brief file.
Runtime references follow `general/policy/referencing-doc-snippets`.

Interactive procedure entry, lifecycle dispatch, scheduled jobs and activations
use the same loader shape. Entry kind supplies facts, not a separate list of
documentation dependencies. Each procedure declares its own required reads,
including the shared job or event-handling instructions its assignment needs.
Those shared instructions apply their duties to the actual invocation: reading a
procedure inline does not create a job-reporting or session-ending obligation.

Continuation preserves the assignment's role, arguments and entry facts and
reconstructs its loader from the persisted invocation. Existing stored invocations
remain continuable without relying on a temporary brief file. A procedure read
inside a running session changes neither its role nor its bound assignment.

## Canonical fields

### Assignment and display

The persisted invocation identifies the procedure, role, bound parameters, raw
arguments, entry kind and facts, and additional context. A scheduled run retains
its configured job identity; an activation retains its home, subject, attendance
and delivery settings. Those values remain available on continuation.

<!-- planned-change:issue-128 -->

The session's generated title is its role name followed by its work subject.
A direct invocation with a bound branch uses that branch as its subject;
other direct invocations use their supplied arguments. A scheduled run shows
its job name and an activation its home in that place. The full procedure ID
and complete arguments remain recorded and inspectable in session details.
Display abbreviation does not change dispatch, continuation or matching identity.
<!-- change:issue-128 -->

The session's generated title is its role name followed by its work subject.
A direct invocation with a bound branch uses that branch as its subject;
other direct invocations use their supplied arguments. A scheduled run shows
its job name. A subject-identity activation whose procedure declares parameters
uses the bound canonical subject identifier; other activations use their home.
The activation binding follows
`local/projects/teleclaude/design/architecture/procedure-activation`.
The full procedure ID and complete arguments remain recorded and inspectable
in session details. Display abbreviation does not change dispatch,
continuation or matching identity.
<!-- /planned-change:issue-128 -->

<!-- planned-change:issue-129 -->

A bound issue parameter identifies GitHub work when GitHub's issue lookup
resolves it in the assignment's project. Session snapshots carry its verified
number, URL, and bound work subject as an optional structured reference,
including for sessions started before the display was opened. Repository
selection follows the GitHub CLI used by the assignment. The reference is
independent of the session title and work-slug claim; an assignment without an
identified GitHub issue carries none. An unavailable optional lookup leaves
the session visible and eligible for a later lookup.
<!-- change:issue-129 -->

A bound issue parameter identifies GitHub work when the issue lookup resolves
it within the repository declared by the registered project. The owning
computer's session snapshot may carry the verified number, URL and bound work
subject as optional display metadata, including for sessions started before the
display opens. The stored invocation supplies the selector; the registered
project's `todos.repository` declaration supplies repository identity, even
when the selected todo backend is local. Cwd, command arguments, ambient Git
remotes and the developer's native CLI do not select a repository or credential.

The optional metadata read uses the existing role-to-App assignment owned by
`local/projects/teleclaude/spec/feature/identity/platform-github-identity`
and the GitHub adapter's existing `read_github_item_identity` issue-read path,
which requests only `issues:read` through GitHubKit. Its in-memory target scopes
that read; it is not persisted as the session's workflow target. The snapshot
uses the verified issue number and declared repository to form the display URL.
This is a display read only: it establishes no workflow binding or write
authority. Missing repository declaration, missing role/App mapping, unavailable
credential, an unreadable/non-issue selector, or provider failure leaves
metadata absent while the session remains visible. The lookup remains eligible
for later refresh under the existing bounded cache. A session without a
verified issue reference carries none. The TUI consumes this optional
structured reference under
`local/projects/teleclaude/spec/feature/tui/todo-session-cross-navigation`.
<!-- /planned-change:issue-129 -->

### Resolution

1. Resolve a published entry procedure. Unknown, pending or non-procedure IDs,
   missing role or dispatch declarations, and unusable required-read closures
   refuse before a session is created.
   Remote entry is refused with the missing capability named before any
   operation or session is created on either computer.
2. Bind declared parameters once under
   `general/spec/snippet-authoring-schema`, preserving raw arguments. Missing
   required arguments and surplus tokens refuse before session creation.
   Each refusal identifies its cause: an unresolved procedure names the
   procedure and gap, a missing required parameter is named, surplus arguments
   are identified, and a retired command name is refused as unknown.
3. Resolve the declared role and the caller's dispatch privilege through the
   catalog. Reading a dependency never adopts its declared role.
4. Resolve agent preference and thinking mode through the shared dispatch
   contract. An explicit mode and a scheduled job's effective dispatch settings
   retain their existing precedence over procedure defaults.
5. Compose the loader and create the session with its role, procedure identity,
   job identity where applicable, working slug and persisted invocation. Every
   assigned role can retrieve its procedure's closure through the docs surface.

### Use cases

#### UC-PE1: A session receives its assignment and procedure reference

#### UC-PE2: A scheduled job retains its run identity and duties

#### UC-PE3: An activation retains its event-handling context

#### UC-PE4: An unusable entry creates no session

#### UC-PE5: Missing required input refuses entry

#### UC-PE6: Dispatch privilege follows the declared role

#### UC-PE7: An orchestrator starts the integrator

#### UC-PE8: An inline read preserves the current assignment

#### UC-PE9: Continuation reconstructs the complete assignment

#### UC-PE10: Interactive procedure input uses the shared entry

#### UC-PE11: Lifecycle dispatch retains its procedure identity

#### UC-PE12: Unsupported remote entry refuses before side effects

#### UC-PE13: A retired command name is refused

## See Also

- docs/local/spec/feature/identity/agent-roles.md
- docs/local/spec/feature/agent_runtime/scheduled-agent-command-dispatch.md
- docs/local/spec/feature/agent_runtime/procedure-standing-agent.md
- docs/local/spec/feature/agent_runtime/procedure-event-delivery.md
