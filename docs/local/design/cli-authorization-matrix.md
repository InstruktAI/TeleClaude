---
description: "How telec command declarations admit agent roles through named command capabilities and person roles through a band per command — each capability's command membership in one place."
visibility: 'public'
---

# CLI Authorization Matrix — Design

## Purpose

Who may run which `telec` command. Every command declares, in the CLI surface schema (`CLI_SURFACE`), the one command capability that admits agent callers and the person roles it admits; the schema owns each command's exact declaration. This design owns which commands each capability names, so a capability's reach reads in one place instead of being scattered across per-command lists. Which capabilities each agent role carries, and which roles are full-reach, is the agent role catalog (`local/projects/teleclaude/spec/feature/identity/agent-roles`). The clearance boundary, including a named-target decision that completes inside its handler, is `local/projects/teleclaude/design/architecture/cli-invocation-boundary`; its role rule is `local/projects/teleclaude/spec/feature/identity/command-clearance`.

## Inputs/Outputs

- **Input:** the caller the identity context's shared caller resolution yields (`local/projects/teleclaude/spec/identity-and-auth` §6) — a session's role resolved through the catalog, or a person's effective role for the object the command acts on (`local/projects/teleclaude/design/architecture/scoped-roles`) — and the command's declaration.
- **Output:** admit or refuse on the computer that executes the command. A request addressed to another computer authenticates its caller at the edge and is relayed for authorization there (`local/projects/teleclaude/spec/feature/identity/cross-computer-authorization`). For local execution, the pre-dispatch gate completes commands whose target is known; a trusted-directory-named command completes its person band when its handler resolves the directory. The TUI applies the same boundary to each action.

## Invariants

1. An agent caller with a role is admitted when its catalog entry is full-reach, its explicit set contains the capability the command declares, or the catalog gives that capability to every role; a person caller is judged by the command's person band at the person's effective role for the command's scope; neither falls through to the other. A session acting for a person must also pass the person band with that person's effective role — its agent role narrows and never widens the person's reach. A roleless platform caller follows the exception in `local/projects/teleclaude/spec/feature/identity/command-clearance`.
2. Every agent command declares exactly one command capability; a person-only command declares none and is reached by no agent role, as `config wizard` is.
3. A capability's membership is the complete set of commands declaring it. A command joins a capability by declaring it, never by naming a role; a role reaches a command only through the catalog.
4. The daemon's own `system` credential grants no role-based command reach. Caller-independent commands pass without resolving that credential.
5. A command that does not depend on its caller admits a caller with no identity.
6. Customers reach only the desk commands: `version`, `docs index`, `docs get`, `auth whoami` and `sessions escalate`. `sessions escalate` is admitted to every person band below admin, and it succeeds only from a session running in a help desk (`local/projects/teleclaude/spec/feature/agent_runtime/help-desk-escalation`). Everyone in the desk's scope is the escalation's target, the admins among them, and admins do not escalate.
7. Who may change machine, global, company or another person's configuration is decided by configuration target clearance (`local/projects/teleclaude/spec/feature/identity/configuration-target-clearance`), by object and principal, never by a command's band.

Capabilities keep an agent inside its brief; they are focus, not integrity (`general/principle/trust-and-guardrails`). Whether a caller may act on a particular object stays with the object's owner: a todo's claim, the driver-start dedup, the integrator's lease, an extraction's scope.

## Primary flows

### Command capability membership

| Capability             | Commands                                                                                                                                                                                                |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `docs-read`            | `docs index`, `docs get`                                                                                                                                                                                |
| `todo-read`            | `todo list`, `todo show`, `bugs list`, `bugs suppressions`                                                                                                                                              |
| `todo-write`           | `todo create`, `todo freeze`, `todo unfreeze`, `todo remove`, `todo reactivate`, `todo deliver`, `todo update`, `todo board repair`, `bugs report`, `bugs suppress`, `bugs unsuppress`, `content dump`  |
| `artifact-read`        | `todo artifacts list`, `todo artifacts read`, `todo artifacts diff`                                                                                                                                     |
| `artifact-write`       | `todo artifacts write`, `todo artifacts remove`                                                                                                                                                         |
| `stamp`                | `todo stamp`, `repo stamp`                                                                                                                                                                              |
| `todo-orchestration`   | `todo prepare`, `todo work`, `todo design`                                                                                                                                                              |
| `integration`          | `todo integrate`, `repo owners`                                                                                                                                                                         |
| `maintenance-recovery` | `repo maintenance status`, `repo maintenance drain`, `repo maintenance retry`                                                                                                                           |
| `memory-curation`      | `memories scope`, `memories add`, `memories update`, `memories retire`, `memories prospect`, `memories extraction read`, `memories extraction complete`, `memories extraction fail`, `memories advance` |
| `session-observe`      | `sessions list`, `sessions show`, `history search`, `computers list`, `projects list`, `agents availability`, `sessions coordinate`                                                                     |
| `transcript-read`      | `history show`                                                                                                                                                                                          |
| `operation-read`       | `operations get`                                                                                                                                                                                        |
| `session-act`          | `sessions start`, `sessions run`, `sessions run-pa`, `sessions revive`, `sessions restart`, `sessions end`, `agents status`                                                                             |
| `peer-talk`            | `sessions send`, `sessions tail`                                                                                                                                                                        |
| `self-acts`            | `sessions result`, `sessions file`, `sessions escalate`, `sessions unsubscribe`, and a session's own end and restart through the self-acts in `command-clearance`                                       |
| `messaging`            | `message`                                                                                                                                                                                               |
| `audio`                | `audio stt`                                                                                                                                                                                             |
| `jobs`                 | `jobs enable`, `jobs disable`, `jobs run`                                                                                                                                                               |
| `jobs-read`            | `jobs list`, `jobs status`                                                                                                                                                                              |
| `job-report`           | `jobs report`                                                                                                                                                                                           |
| `config`               | every `config` command except `config wizard` and the `config-read` commands                                                                                                                            |
| `config-read`          | `config computer list`, `config computer get`, `config global list`, `config global get`, `config project list`, `config project get`, `config validate`                                                |
| `reminders`            | `reminders set`, `reminders list`, `reminders cancel`                                                                                                                                                   |
| `code-check`           | `repo blueprint affected`, `repo lint`, `repo test`                                                                                                                                                     |
| `code`                 | `repo format`, `repo add`, `repo commit`, `sync`                                                                                                                                                        |
| `mcp`                  | `mcp list-tools`, `mcp call`                                                                                                                                                                            |
| `memories-read`        | `memories list`, `memories search`, `memories timeline`, `memories delete`                                                                                                                              |
| `memories-save`        | `memories save`                                                                                                                                                                                         |

The schema's declaration is the authority for every command's exact capability; this table is its grouped reading and is corrected to the schema, never the reverse.

### Person role bands

Each command keeps a person band of its own in the CLI surface schema, evaluated against the person's effective role at the command's scope (`local/projects/teleclaude/spec/feature/identity/command-clearance`). The tiers are:

- **Admin** — the system owner: every command except `sessions escalate`, whose target they are.
- **Member** — works on projects and manages sessions; no infrastructure acts such as reviving sessions, setting agent status, or reading and writing the machine environment.
- **Customer** — reaches only the allow-list in invariant 6.

`todo sync` and `todo switch-to-github` declare no command capability (invariant 2) and have the admin person band: an admin at a terminal, or a session an admin started without an agent role, is admitted, while every session carrying a role is refused. A caller with the platform principal and no resolved role is admitted by the roleless platform exception in `local/projects/teleclaude/spec/feature/identity/command-clearance`.

### Commands that do not depend on the caller

`version`, `auth login`, `auth whoami`, `auth logout`, `events list`, `events schema`, `signals status`, `mcp list`, the local repository commands `repo lint`, `repo test`, `repo format`, `repo add` and `repo blueprint affected`, the hidden git-hook commands `repo pre-commit`, `repo post-commit` and `repo post-merge`, and the hidden todo-state-transfer helper `todo sync-replica` admit a caller with no identity. Each either reads nothing that belongs to a caller or acts on an object already guarded by its own state (`general/principle/trust-and-guardrails`) — the repository commands change only the invoking checkout and, when a session invokes them, that session's own path declarations, and those that narrow their scope to a session read the session marker, never the caller, and hook maintenance acts only on a canonical-main range and runs only main-only actions. The transfer helper runs on a receiving computer inside a non-interactive SSH session, which carries no login or session identity; it only reports where that computer keeps a project's todo state and whether that state is intact, facts any account able to run it can already read from disk, and it changes nothing.

## Failure modes

| Scenario                                                                                   | Behavior                                                                                                                                               |
| ------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| A command carries no declaration                                                           | Refused for every caller: an undeclared command fails closed.                                                                                          |
| The caller resolves to no identity                                                         | Refused before the handler runs, naming the missing login or session identity, unless the command does not depend on its caller.                       |
| A role's set lacks the command's capability and the catalog does not give it to every role | Refused with the not-permitted failure naming the role and the command; for a worker, the work belongs to the session that dispatched it.              |
| A recorded role the catalog does not name                                                  | Refused with the not-permitted failure naming the role; the refusal is logged as a platform defect.                                                    |
| A person is removed from the registry or demoted                                           | The change takes effect on that person's next command.                                                                                                 |
| A new agent role is introduced                                                             | It reaches exactly the commands its catalog entry composes plus those whose capability the catalog gives every role, and no command admits it by name. |
