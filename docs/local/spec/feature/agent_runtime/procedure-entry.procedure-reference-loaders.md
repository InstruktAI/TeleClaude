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

The session's generated title is its role name followed by its supplied
arguments. The full procedure ID remains recorded and inspectable in session
details. Display abbreviation does not change dispatch, continuation or matching
identity.

### Resolution

1. Resolve a published entry procedure. Unknown, pending or non-procedure IDs,
   missing role or dispatch declarations, and unusable required-read closures
   refuse before a session is created.
2. Bind declared parameters once under
   `general/spec/snippet-authoring-schema`, preserving raw arguments. Missing
   required arguments and surplus tokens refuse before session creation.
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

```gherkin
Given an agent is dispatched to a published entry procedure
When its session starts
Then its first instruction names its role and bound assignment inputs
And directs it to retrieve that procedure's complete instructions
And reading those instructions requires no temporary session brief file
```

#### UC-PE2: A scheduled job retains its run identity and duties

```gherkin
Given a configured agent job whose procedure declares its job-handling reads
When the job runner dispatches the agent
Then the loader identifies the scheduled invocation and its configured job
And the procedure's reads supply the applicable reporting and close-out duties
And the job declaration supplies the run's agent preferences and thinking mode
```

#### UC-PE3: An activation retains its event-handling context

```gherkin
Given a subscribed procedure declaring its applicable event-handling reads
When its activation starts an agent
Then the loader carries the activation home and applicable subject and delivery facts
And the procedure's reads supply its event-handling instructions
```

#### UC-PE4: An unusable entry creates no session

```gherkin
Given an agent requests an unknown, pending or unusable entry procedure
When entry resolution runs
Then the request fails with the specific cause
And no session is created
```

#### UC-PE5: Missing required input refuses entry

```gherkin
Given an agent requests an entry procedure without one of its required inputs
When entry resolution binds the arguments
Then the request fails naming the missing input
And no session is created
```

#### UC-PE6: Dispatch privilege follows the declared role

```gherkin
Given an agent caller permitted to dispatch only worker-class sessions
When it requests a procedure declaring another role class
Then entry refuses for the missing dispatch privilege
And a caller with full dispatch reach can start that procedure
```

#### UC-PE7: An orchestrator starts the integrator

```gherkin
Given an agent session carrying the work-orchestrator role
When it requests the integration procedure
Then entry creates a session carrying the integrator role
And the integrator's singleton ownership is decided by its owning contract
```

#### UC-PE8: An inline read preserves the current assignment

```gherkin
Given an agent reads another procedure inside its existing session
When that procedure declares a launch role and job-handling reads
Then the session retains its current role and assignment
And the read alone creates no scheduled-job close-out obligation
```

#### UC-PE9: Continuation reconstructs the complete assignment

```gherkin
Given an agent session with a persisted procedure assignment
When it restarts, revives or hands off to another agent
Then its loader retains the procedure, role, bound inputs and entry facts
And its instructions are retrievable without the former temporary brief file
```

#### UC-PE10: Interactive procedure input uses the shared entry

```gherkin
Given an operator submits a published procedure ID and arguments
When the input surface starts that assignment
Then it uses the procedure's declared role and shared loader
And unrecognized procedure input retains the surface's ordinary conversation behavior
```

#### UC-PE11: Lifecycle dispatch retains its procedure identity

```gherkin
Given a lifecycle agent dispatches a build procedure
When the session is created
Then its recorded command remains the full procedure ID
And its generated title displays the role and arguments
```

#### UC-PE12: Unsupported remote entry refuses before side effects

```gherkin
Given an agent requests procedure entry on a computer without that capability
When the request is routed
Then it fails naming the missing capability
And no session or operation is created on either computer
```

#### UC-PE13: A retired command name is refused

```gherkin
Given an agent supplies a retired command name instead of a procedure ID
When entry resolves the request
Then it refuses naming the unknown command
And no session is created
```

## See Also

- docs/local/spec/feature/identity/agent-roles.md
- docs/local/spec/feature/agent_runtime/scheduled-agent-command-dispatch.md
- docs/local/spec/feature/agent_runtime/procedure-standing-agent.md
- docs/local/spec/feature/agent_runtime/procedure-event-delivery.md
