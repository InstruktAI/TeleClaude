---
description: "Gate every protected operation on the CLI verb's role allowlist via the command-clearance capability."
visibility: 'public'
---

# Command Clearance — Spec

## Required reads

- @docs/local/spec/domain/identity.md
- @docs/local/spec/identity-and-auth.md

## What it is

Command clearance is v1's authorization gate, evaluated in the client process that serves the caller before any request reaches the daemon (`local/projects/teleclaude/spec/identity-and-auth` §6). The client resolves its caller through the identity context's shared caller resolution, consults the CLI surface schema for the verb it performs (e.g. `"telec sessions start"`), and checks the caller against that verb's `CommandAuth(system=..., human=...)` allowlist at the command's scope (Person role at the command's scope). A person caller is evaluated against the human band with their effective role at that scope (`local/projects/teleclaude/design/architecture/scoped-roles`); an agent session acting for a person is evaluated against the system band and, with that person's effective role, the human band; an agent session acting for a system principal is evaluated against the system band alone. Unknown verb paths fail closed. The verb→Role table lives declaratively in the CLI surface schema, so adding a new operation means adding a `CommandAuth` to the schema and clearing its verb where the operation is performed.

For a CLI command whose `--project` value names a machine-configured trusted
directory, the gate resolves the caller and enforces any agent band. The handler
resolves the name through typed configuration, then completes that command's
person-band clearance on the exact directory it will use before any project
action or daemon request. The name is never treated as a project slug.

For a cleared session-start command, the client carries its resolved caller to
agent_runtime; session-lifecycle owns the child's stored initiator and principal
(`local/projects/teleclaude/spec/feature/agent_runtime/session-lifecycle`).

## Canonical fields

### Roleless platform caller

<!-- planned-change:local-operator-identity -->

A caller whose resolved principal is `system:daemon` and whose resolved system
role is absent is admitted to every declared command. A caller with a system
role retains that role's existing command restrictions, including when its
principal is `system:daemon`. Person callers and unidentified callers retain
their existing clearance rules. Object ownership and valid operation targets
remain with their owning contracts (`general/principle/trust-and-guardrails`).

<!-- change:local-operator-identity -->

A caller whose resolved principal is `system:daemon` or `system:operator` and
whose resolved system role is absent is admitted to every declared command, by
the computer that executes it: locally, and on a computer that receives the
command relayed with that principal. `system:operator` is the computer's
operator: a local caller for which no session, terminal login or carried identity
resolves, and a session kept for an agent the platform did not launch when no
person resolves for it (`local/projects/teleclaude/spec/identity-and-auth` §2,
§3). A caller with a system role retains that role's existing command
restrictions, including when its principal is a system principal. Person callers
retain their existing clearance rules. A caller whose session identity document
names no admissible session is not the operator and is refused. Object ownership
and valid operation targets remain with their owning contracts, and a
person-bound service acts for no system principal
(`general/principle/trust-and-guardrails`).

<!-- /planned-change:local-operator-identity -->

#### UC-CCRD1: Platform authority without a system role

<!-- planned:local-operator-identity -->

#### UC-CCRD2: The computer's operator works without a login

```gherkin
Given an agent another application started on a computer with several registered people
And no session, terminal login or carried identity names a person for it
When the agent runs a telec command on this computer or addressed to another computer
Then the command is cleared as the computer's operator
And a caller whose session identity names no admissible session is refused
```

<!-- /planned:local-operator-identity -->

### Use cases

#### UC-CCS1: A company administrator works as an administrator in their company's projects

```
Given a person holding no platform role and the admin role in one company
When the person revives a session that ran in a project that company owns
Then the session is revived, as it is for a platform administrator
And a person holding the member role in that company is refused the same revive
```

#### UC-CCS2: The same person is an outsider in another company's project

#### UC-CCS3: A person's agent reaches no further than that person

#### UC-CCS4: A session acting for the platform is not bounded by any person

#### UC-CCS5: A command naming a session is judged at that session's project

#### UC-CCS6: Platform-scope commands need a platform role

#### UC-CCS7: A command naming another computer that acts on nothing held there is refused locally

#### UC-CCS8: A trusted-directory name reaches its selected project

#### UC-CCS9: A named project outside the person's scope is refused

#### UC-CCS10: An unknown trusted-directory name reveals no project list to an outsider

#### UC-CCS11: Enabling a help desk is judged at the home it opens

### Cross-context references

- The verb→Role allowlist data lives in the CLI surface schema, owned by the `config`/CLI-shape concern. The identity context owns only the gate logic.
- Consumed by every client path that asks the daemon to act and by the CLI's local commands. Each clears the verb it performs, where it performs it.
- The self-agent-restart carve-out adds a self-restart bypass on top of the standard rule — see `feature/identity/self-restart-authorization-bypass`.
- The self-end carve-out adds a self-end bypass on top of the standard rule, allowing a parentless session (`initiator_session_id is None`) to end itself — see `feature/identity/self-end-authorization-bypass`.

- The `telec todo update` gate replaces role privilege with object state for every agent caller uniformly — see the Claim-scoped todo update section below.

- In v2 this responsibility moves out of identity: each bounded context defines its own authorization rules against the resolved `Principal`'s Role. Identity returns the Principal; the bounded context decides which operations require which roles.

### Claim-scoped todo update

`telec todo update` replaces role privilege with object state. The verb admits every agent role whose set composes `todo-write`, focused roles included; a roleless agent session is admitted through the verb's human band. Every admitted caller other than a direct human identity — focused roles, dispatch-capable roles and roleless sessions included — is then checked against the todo's claim. No role holds unrestricted access to this verb.

The claim gate is the claiming-group predicate governing artifact writes (`feature/workflow/artifact-versioning`, Write authority). A todo whose `active_runner` names a live session is claimed; its claiming group is the holding session plus every session it dispatched, transitively through `initiator_session_id`. The gate admits a caller inside the claiming group, and admits any caller on an unclaimed todo — no `active_runner`, or one naming a session that is no longer live. It refuses a caller outside a live claim's group with the claim-conflict shape naming the holding session: the caller's door is that session. The todo state is unchanged by a refused update.

A direct human-identity caller — a login-resolved human principal carrying no agent session id and no system role — is not a session, is not gated by the claim, and is evaluated against the verb's human band; it is the caller class the artifact-write claim gate exempts (`feature/workflow/artifact-versioning`, UC-WAV16, UC-WAV23). Any other caller carrying no agent session id, such as the daemon's own credential, belongs to no claiming group and is refused on a live claim.

The `--unclaim` leg releases only the caller's own claim or the caller's own binding to the todo; it never clears another session's claim. A claiming-group member other than the holder passes the gate, and `--unclaim` then releases at most its own binding, leaving the holder's claim in place. The build-started freeze on slug/kind mutation is a phase invariant owned by the todo-management contract, orthogonal to this gate.

#### UC-CSU1: Tasker updates the todo it holds the claim on

```
Given a tasker agent session with system_role=`tasker` and session_id=`t-1`
And a todo whose active_runner is `t-1`
When the session calls `telec todo update` on that todo
Then the claim gate accepts (the caller holds the live claim)
And the requested mutation is applied to the todo state
```

#### UC-CSU2: Tasker updates an unclaimed todo

```
Given a tasker agent session with system_role=`tasker` and session_id=`t-1`
And a todo whose active_runner is absent
When the session calls `telec todo update` on that todo
Then the claim gate accepts (the todo is unclaimed)
And the requested mutation is applied to the todo state
```

#### UC-CSU3: Tasker outside the claiming group is refused

```
Given a tasker agent session with system_role=`tasker` and session_id=`t-1`
And a todo whose active_runner names a different live session whose claiming group does not include `t-1`
When the session calls `telec todo update` on that todo
Then the claim gate refuses with a claim conflict naming the holding session
And the todo state is unchanged
```

#### UC-CSU4: Job runner updates an unclaimed todo

```
Given a job-runner agent session with system_role=`job_runner` and session_id=`j-1`
And a todo whose active_runner is absent
When the session calls `telec todo update` on that todo
Then the claim gate accepts (the todo is unclaimed)
And the requested mutation is applied to the todo state
```

#### UC-CSU5: A focused role is claim-gated like every agent caller

```
Given a builder session `w-1` dispatched by the live session `t-1` that holds the claim on a todo
And a second todo whose active_runner names a different live session whose claiming group does not include `w-1`
When `w-1` calls `telec todo update` on each todo
Then the claim gate accepts the update to the first todo
And refuses the second with a claim conflict naming the holding session
```

#### UC-CSU6: Orchestrator outside the claiming group is refused

```
Given an orchestrator agent session with system_role=`orchestrator`
And a todo whose active_runner names a different live session whose claiming group does not include the caller
When the session calls `telec todo update` on that todo
Then the claim gate refuses with a claim conflict naming the holding session
And the todo state is unchanged
```

#### UC-CSU7: A direct human-identity caller is not claim-gated

```
Given a login-resolved human caller with human_role=`member` and no agent session id
And a todo whose active_runner names a live agent session
When the caller invokes `telec todo update` on that todo
Then the human band accepts the caller
And no claim gate applies
And the requested mutation is applied to the todo state
```

#### UC-CSU8: A dead holder's claim counts as unclaimed

```
Given a tasker agent session with system_role=`tasker` and session_id=`t-1`
And a todo whose active_runner names a session that is no longer live
When the session calls `telec todo update` on that todo
Then the claim gate accepts (no live claim exists)
And the requested mutation is applied to the todo state
```

#### UC-CSU9

#### UC-CSU10

#### UC-CSU11: A session dispatched by the claim holder updates the todo

```
Given a live session `t-1` holding the claim on a todo
And an agent session `c-1` outside the focused class whose initiator_session_id chain reaches `t-1`
When `c-1` calls `telec todo update` on that todo
Then the claim gate accepts (the caller is inside the claiming group)
And the requested mutation is applied to the todo state
```

### Role reach

Each command's declaration names the command capability that admits agent callers, so a capability's reach reads in one place (`local/projects/teleclaude/design/cli-authorization-matrix`), and an agent caller is admitted when the agent role catalog composes its role with that capability or marks the role full-reach (`local/projects/teleclaude/spec/feature/identity/agent-roles`); person roles keep a band per command. A role that is not full-reach is admitted to a capability-gated command only when its explicit set composes that command's capability or the catalog gives that capability to every role, and its class adds none; a caller-independent command admits it as it admits every caller. No focused role's set lists sessions, searches history or reads the fleet's computers, projects or agents, and a focused session starts, revives, restarts or ends no session but its own through the self-acts above. A recorded role the catalog does not name is refused every command that depends on its caller and reported as a platform defect; it is never admitted as a caller without a role, and caller-independent commands pass without resolving it. The daemon's own `system` credential grants no role-based command reach; caller-independent commands pass without resolving that credential. A command that does not depend on its caller — `version`, `auth login|whoami|logout`, `events list`, `signals status`, `mcp list`, the local repository commands `repo lint|test|format|add|blueprint affected`, and the git-hook commands — admits a caller with no identity and passes the gate with no caller resolution. `todo update` is governed by the claim-scoped rule instead of a role.

The installation verbs are declared for the machine's own account (`local/projects/teleclaude/design/cli-authorization-matrix`): a caller outside any session is admitted to them with or without a terminal login, and a session is admitted only through its role's installation capability and, when it acts for a person, that person's band.

#### UC-CCB1: A full-reach role starts a session

#### UC-CCB2: A full-reach role revives a session

#### UC-CCB3: A full-reach role ends a session

#### UC-CCB4: A focused role is refused the state-machine-driving verbs

#### UC-CCR1: A command that does not depend on its caller runs without an identity

#### UC-CCR2: A focused role reads nothing across the fleet

#### UC-CCR3: A job's session reaches an ordinary agent command

#### UC-CCR4: Clearance admits a full-reach role to every agent command

#### UC-CCR5: A coordinator is admitted everywhere and drives no work by its procedure's discipline

### Local read clearance

<!-- planned-change:local-operator-identity -->

The read commands `telec todo list`, `telec todo show`, `telec todo artifacts list`, `telec todo artifacts read`, `telec todo artifacts diff`, `telec bugs list`, and `telec bugs suppressions`, and a `telec history search` or `telec history show` that reads this computer's mirrors, are cleared in the process that runs them, against the same verb allowlist. The caller is the one the identity context's shared caller resolution yields (`local/projects/teleclaude/spec/identity-and-auth` §6): inside a session, the session record its identity document names; outside any session, the person the terminal's login names. The caller's system role is derived from that record by the identity context's system-role derivation, and its person role is the role the people registry holds for its principal when the command runs. A caller that resolves to no person and no system principal is refused before any content is read. A role outside the verb's band is refused with the not-permitted failure naming the role and verb. The gate sends no request to the daemon, so these reads answer while the daemon is not running.

<!-- change:local-operator-identity -->

The read commands `telec todo list`, `telec todo show`, `telec todo artifacts list`, `telec todo artifacts read`, `telec todo artifacts diff`, `telec bugs list`, and `telec bugs suppressions`, and a `telec history search` or `telec history show` that reads this computer's mirrors, are cleared in the process that runs them, against the same verb allowlist. The caller is the one the identity context's shared caller resolution yields (`local/projects/teleclaude/spec/identity-and-auth` §6): inside a session, the session record its identity document names; outside any session, the person the terminal's login names, or the computer's operator, `system:operator`, when nothing resolves an identity (`local/projects/teleclaude/spec/identity-and-auth` §2). The caller's system role is derived from that record by the identity context's system-role derivation, and its person role is the role the people registry holds for its principal when the command runs. The operator is cleared as the roleless platform caller above. A caller whose session identity document names no admissible session is refused before any content is read. A role outside the verb's band is refused with the not-permitted failure naming the role and verb. The gate sends no request to the daemon, so these reads answer while the daemon is not running.

<!-- /planned-change:local-operator-identity -->

#### UC-CCL1: A project maintainer reads their todo list while the daemon is unavailable

```gherkin
Given a project maintainer's agent is in a project checkout
And the daemon's local service is unavailable
When the agent requests the project's todo list
Then the project's current todo list is displayed
```

#### UC-CCL2: A caller with no usable identity reads nothing

#### UC-CCL3: A session is cleared by the role derived from its record

#### UC-CCL4: A role outside the verb's band is refused locally

### Clearance of commands that ask the daemon to act

<!-- planned-change:local-operator-identity -->

For a command that runs locally, the CLI gate preceding its handler applies the command's verb allowlist with the caller the shared identity resolution yields (`local/projects/teleclaude/spec/identity-and-auth` §6). The same gate authenticates a caller addressing another computer and relays the request without applying a sender-side role band. The owning computer authorizes the command from the relayed principal and its own records (`local/projects/teleclaude/spec/feature/identity/cross-computer-authorization`). This applies equally to terminal callers, roleless sessions, and sessions carrying any system role. A protected command with no usable caller identity is refused before any request is sent. Explicit local targets and commands naming no computer retain local clearance.

<!-- change:local-operator-identity -->

For a command that runs locally, the CLI gate preceding its handler applies the command's verb allowlist with the caller the shared identity resolution yields (`local/projects/teleclaude/spec/identity-and-auth` §6). The same gate authenticates a caller addressing another computer and relays the request without applying a sender-side role band. The owning computer authorizes the command from the relayed principal and its own records (`local/projects/teleclaude/spec/feature/identity/cross-computer-authorization`). This applies equally to terminal callers, roleless sessions, and sessions carrying any system role. A local caller for which nothing resolves an identity is the computer's operator and is cleared as the roleless platform caller above, here and on a computer its command is relayed to. A protected command whose caller's session identity document names no admissible session is refused before any request is sent. Explicit local targets and commands naming no computer retain local clearance.

<!-- /planned-change:local-operator-identity -->

The TUI clears each action it performs before sending it, against the verb of the command that action performs, with the identity it was launched with; an action on an object another computer holds is cleared as that command is. An action that performs no `telec` command, or one whose command no gate clears, is not cleared.

The preceding pre-handler clearance rule has one named-target exception:
`telec bugs --project` naming a trusted directory completes person-band
clearance inside its handler (`local/projects/teleclaude/design/architecture/cli-invocation-boundary`
invariant 5).

`telec sessions end` and `telec sessions restart` each admit one act outside their band, decided in the same clearance from the caller's own session record and the command's target: a session may end itself when its record names no orchestrating parent (`feature/identity/self-end-authorization-bypass`), and a session may restart itself (`feature/identity/self-restart-authorization-bypass`). A focused session is refused a restart of any session other than its own, whatever the band says.

#### UC-CCA1: An out-of-band agent is refused before the daemon is asked

#### UC-CCA2: A caller with no usable identity asks the daemon nothing

#### UC-CCA3: A cleared command's request carries the caller the client resolved

#### UC-CCA4: A command naming another computer is authorized there

#### UC-CCA5: The TUI refuses an out-of-band action without asking the daemon

### Person role at the command's scope

A person is cleared by their effective role at the command's scope
(`local/projects/teleclaude/design/architecture/scoped-roles`): the object the command acts on, read
from the invocation and the object itself, never from a scope or role the caller
supplies.

- A command that addresses a configuration subject is judged at that subject: a
  company at that company, a project at that project, a person at that person.
  Machine and global configuration, and the listing, creation and management of
  people and companies, are judged at platform scope.

- Creating a project is judged at the home it lands in: the caller's own person
  scope, the company scope `--company` names, or platform scope for `--path`.
  Adopting a project is judged at the caller's own person scope wherever the
  folder is, so any registered person adopts a folder they can reach, including
  a project they created, to converge it; which
  folders a session can reach is not decided here. These bands admit every role
  but customer, so a registered person without a platform role creates in their
  own home and adopts.

- A command that names a target session is judged at the project that session runs
  in.
- A command that names a directory to act in is judged at the project containing
  that directory.
- A `telec bugs` command whose `--project` value names a trusted directory is
  judged at the project containing the directory that name resolves to
  (`local/projects/teleclaude/design/architecture/cli-invocation-boundary` invariant 5).
- A command that names another computer is decided by that computer, at the scope
  of the object it addresses there, read by these same rules from the request it sends
  (`local/projects/teleclaude/spec/feature/identity/cross-computer-authorization`). Here it needs an identified caller; authorization belongs to the addressed computer. A `telec sessions send` that opens or closes a direct
  conversation with a session on another computer is judged at platform scope.
- Every other command is judged at the project the invocation runs in — the project
  of its working directory's checkout — and at platform scope where it runs in no
  registered project.
- The TUI judges each action at the scope of the object that action targets, and
  at platform scope when the action targets no project or session.

A person caller is admitted when the command's person band admits their effective
role at that scope. A session acting for a person is admitted only when the
command's agent band admits the session's system role and its person band admits
that person's effective role at the command's scope; a system role narrows what a
person's session may run and never widens it. A session acting for a system
principal carries no person and is judged by the agent band alone. A command that
reads across many objects, such as a history search, is cleared at its scope, and
the objects' owners then narrow what it returns.

## Known caveats

- The refusal names the caller's role: `"role '<role>' is not permitted to call <tool>"`.
- Admin is NOT implicit. The "all human roles" band lists `admin` explicitly alongside the other human roles. A future band that forgets to include `admin` will lock admins out of that verb — there is no automatic override.
- An agent caller never falls through to the person band as an alternative: an agent band that refuses the session's system role refuses the command, whatever role the person holds. The person band applies to an agent caller only as the further bound on a session acting for a person.
- Unknown verb paths return False. A typo in a binding's verb argument silently locks out every caller — there is no startup-time check that every verb identifier resolves to a real entry in the CLI surface.
- The verb resolver normalizes `"telec sessions start"`, `"sessions.start"`, and `"sessions start"` to the same path. Mixed forms across operation bindings do not cause divergence, but the dot form is undocumented.

- The `telec todo update` claim check reads the todo's claim once, when the request is handled. A claim recorded while a request is in flight — including before a deferred slug rename executes — is not seen by that request.

## See Also

- docs/local/adr/0067-authorization-reads-the-object-not-the-caller-role.md — why `telec todo update` authorizes on the todo's claim rather than the caller's role.
- docs/local/adr/0096-claimed-todo-artifacts-are-writable-only-by-the-claiming-group.md — the claiming-group boundary and the direct human-identity exemption this gate shares.
