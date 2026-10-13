---
description: "How telec command declarations admit agent roles through command capabilities and person roles through a band per command — each capability's command reach in one place."
visibility: 'public'
---

# CLI Authorization Matrix — Design

## Purpose

Who may run which `telec` command. Every command declares, in the CLI surface schema (`CLI_SURFACE`), the command capabilities that admit agent roles and the person roles it admits; the schema owns each command's exact declaration. This design owns how those declarations group commands into capabilities, so a capability's reach reads in one place instead of being scattered across per-command lists. Which capabilities each agent role carries is the agent role catalog (`local/projects/teleclaude/spec/feature/identity/agent-roles`). The clearance boundary, including a named-target decision that completes inside its handler, is `local/projects/teleclaude/design/architecture/cli-invocation-boundary`; its role rule is `local/projects/teleclaude/spec/feature/identity/command-clearance`.

## Inputs/Outputs

- **Input:** the caller the identity context's shared caller resolution yields (`local/projects/teleclaude/spec/identity-and-auth` §6) — a session's system role derived from its record, or a person's effective role for the object the command acts on (`local/projects/teleclaude/design/architecture/scoped-roles`) — and the command's declaration.
- **Output:** admit or refuse on the computer that executes the command. A request addressed to another computer authenticates its caller at the edge and is relayed for authorization there (`local/projects/teleclaude/spec/feature/identity/cross-computer-authorization`). For local execution, the pre-dispatch gate completes commands whose target is known; a trusted-directory-named command completes its person band when its handler resolves the directory. The TUI applies the same boundary to each action.

## Invariants

1. An agent caller with an assigned system role is judged by the command capabilities a declaration names, and a person caller by the command's person band at the person's effective role for the command's scope; neither falls through to the other. An agent caller is admitted when its role carries at least one capability the declaration names. A session acting for a person must also pass the person band with that person's effective role — its agent role narrows and never widens the person's reach. A roleless platform caller follows the exception in `local/projects/teleclaude/spec/feature/identity/command-clearance`.
2. `worker-commands` is the one focused capability: it reaches the commands worker briefs run and nothing that reads or acts across the fleet.
3. `agent-commands` reaches every agent command, starting sessions included, except the reserved commands in invariant 4. An agent command is one whose declaration names a command capability at all; a person-only command names none and is reached by no agent role, as `config wizard` is.
4. A reserved command is declared with its reserving capability alone: driving a todo state machine with `todo-orchestration`, integration and the dirty-path ownership read with `integration`, maintenance inspection and recovery with `maintenance-recovery`, and memory curation with `memory-curation`.
5. The daemon's own `system` credential grants no role-based command reach. Caller-independent commands pass without resolving that credential.
6. A command that does not depend on its caller admits a caller with no identity.

7. Customers reach only the desk commands: `version`, `docs index`, `docs get`, `auth whoami` and `sessions escalate`. `sessions escalate` is admitted to every person band below admin, and it succeeds only from a session running in a help desk (`local/projects/teleclaude/spec/feature/agent_runtime/help-desk-escalation`). Everyone in the desk's scope is the escalation's target, the admins among them, and admins do not escalate.

8. Who may change machine, global, company or another person's configuration is decided by configuration target clearance (`local/projects/teleclaude/spec/feature/identity/configuration-target-clearance`), by object and principal, never by a command's band.

Capabilities keep an agent inside its brief; they are focus, not integrity (`general/principle/trust-and-guardrails`), which is why one capability covers every ordinary agent command and object rules stay with the object's owner.

## Primary flows

### Command capability reach

| Capability             | Commands                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| ---------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `worker-commands`      | The commands worker briefs run: documentation, todo and artifact reads, artifact writes and stamps, `todo create` (the deferral worker files follow-up work), the `code` quality and commit commands, reminders, bug reports and reads, `sessions send` (a reviewer talks to the builder it reviews directly), `sessions tail` (a reviewer reads the claimant session that dispatched it), results and files for its own session, and ending or restarting its own session through the self-acts in `command-clearance`. Never `sessions list`, `history search` or `history show`, never starting, reviving, restarting or ending another session, and none of the reserved commands. |
| `agent-commands`       | Every agent command except the reserved commands.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `todo-orchestration`   | `todo prepare`, `todo work` and `todo design`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `integration`          | `todo integrate` and `code owners`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `maintenance-recovery` | `code maintenance status`, `code maintenance drain` and `code maintenance retry`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `memory-curation`      | The `memories` curation, prospect, extraction and read-point commands.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |

A command joins a capability's reach by naming that capability in its declaration, never by naming a role. A role reaches a command by carrying a capability the command names; which role carries which capability is the agent role catalog's.

Clearance reads the acting session's resolved principal and system role. A
role-carrying session still passes its own start-session band when it creates a
peer. A peer carrying the platform principal without a system role receives
the roleless platform exception; its creator's role does not supply a role to
the peer. Object ownership and valid operation targets retain their existing
contracts (`general/principle/trust-and-guardrails`).

### Person role bands

Each command keeps a person band of its own in the CLI surface schema, evaluated against the person's effective role at the command's scope (`local/projects/teleclaude/spec/feature/identity/command-clearance`). The tiers are:

- **Admin** — the system owner: every command except `sessions escalate`, whose target they are.
- **Member** — works on projects and manages sessions; no infrastructure acts such as reviving sessions, setting agent status, or reading and writing the machine environment.

- **Customer** — reaches only the allow-list in invariant 7.

`todo sync` names no command capability (invariant 3) and has the admin person band: an admin at a terminal, or a session an admin started without an agent role, is admitted, while every session carrying an assigned system role is refused. A caller with the platform principal and no resolved system role is admitted by the roleless platform exception in `local/projects/teleclaude/spec/feature/identity/command-clearance`.

### Commands that do not depend on the caller

`version`, `auth login`, `auth whoami`, `auth logout`, `events list`, `signals status`, `mcp list`, the local code-tooling commands `code lint`, `code test`, `code format`, `code add` and `code blueprint affected`, the hidden git-hook commands `code pre-commit`, `code post-commit` and `code post-merge`, and the hidden todo-state-transfer helper `todo sync-replica` admit a caller with no identity. Each either reads nothing that belongs to a caller or acts on an object already guarded by its own state (`general/principle/trust-and-guardrails`) — the code-tooling commands change only the invoking checkout and, when a session invokes them, that session's own path declarations, and those that narrow their scope to a session read the session marker, never the caller, and hook maintenance acts only on a canonical-main range and runs only main-only actions. The transfer helper runs on a receiving computer inside a non-interactive SSH session, which carries no login or session identity; it only reports where that computer keeps a project's todo state and whether that state is intact, facts any account able to run it can already read from disk, and it changes nothing.

## Failure modes

| Scenario                                         | Behavior                                                                                                                                  |
| ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------- |
| A command carries no declaration                 | Refused for every caller: an undeclared command fails closed.                                                                             |
| The caller resolves to no identity               | Refused before the handler runs, naming the missing login or session identity, unless the command does not depend on its caller.          |
| A role carries no capability a command names     | Refused with the not-permitted failure naming the role and the command; for a worker, the work belongs to the session that dispatched it. |
| A person is removed from the registry or demoted | The change takes effect on that person's next command.                                                                                    |
| A new agent role is introduced                   | It reaches exactly the commands its composed capabilities name, and no command admits it by name.                                         |
