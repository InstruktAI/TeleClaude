---
description: "How telec command declarations admit agent roles and person roles — each agent role's reach in one place, a person band per command."
visibility: 'public'
---

# CLI Authorization Matrix — Design

## Purpose

Who may run which `telec` command. Every command declares, in the CLI surface schema (`CLI_SURFACE`), the agent roles and the person roles it admits; the schema owns each command's exact declaration. This design owns how those declarations group roles, so an agent role's reach reads in one place instead of being scattered across per-command lists. The clearance boundary, including a named-target decision that completes inside its handler, is `project/design/architecture/cli-invocation-boundary`; its role rule is `project/spec/feature/identity/command-clearance`.

## Inputs/Outputs

- **Input:** the caller the identity context's shared caller resolution yields (`project/spec/identity-and-auth` §6) — a session's system role derived from its record, or a person's effective role for the object the command acts on (`project/design/architecture/scoped-roles`) — and the command's declaration.
- **Output:** admit or refuse, decided in the process that runs the command before any project operation or daemon request. The pre-dispatch gate completes commands whose target is known; a trusted-directory-named command completes its person band when its handler resolves the directory. The TUI applies the declaration of the command each of its actions performs.

## Invariants

1. An agent caller is judged by the agent roles a declaration admits, and a person caller by the command's person band at the person's effective role for the command's scope; neither falls through to the other. A session acting for a person must also pass the person band with that person's effective role — its agent role narrows and never widens the person's reach.
2. The worker is the one focused agent role: it reaches the commands its briefs run and nothing that reads or acts across the fleet.
3. Every other agent role reaches every agent command, starting sessions included, except the reservations in invariant 4. No agent role carries a band of its own beyond them. An agent command is one whose declaration admits agent roles at all; a person-only command declares none and is reached by no agent role, as `config wizard` is.
4. Only an orchestrator drives a todo state machine. The integrator alone holds integration and maintenance.
5. The daemon's own `system` credential grants no role-based command reach. Caller-independent commands pass without resolving that credential.
6. A command that does not depend on its caller admits a caller with no identity.
7. Customers reach only `version`, `docs`, `auth` and `sessions escalate`. Admins are the escalation target and do not escalate. Member, contributor and newcomer keep distinct reach.
8. Who may change machine, global, company or another person's configuration is decided by configuration target clearance (`project/spec/feature/identity/configuration-target-clearance`), by object and principal, never by a command's band.

Bands keep an agent inside its brief; they are focus, not integrity (`general/principle/trust-and-guardrails`), which is why every non-worker agent role shares one band and object rules stay with the object's owner.

## Primary flows

### Agent role reach

| Role         | Reach                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| ------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Worker       | The commands worker briefs run: documentation, todo and artifact reads, artifact writes and stamps, `todo create` (the deferral worker files follow-up work), the `code` quality and commit commands, reminders, bug reports and reads, `sessions send` (a reviewer talks to the builder it reviews directly), `sessions tail` (a reviewer reads the claimant session that dispatched it), results and files for its own session, and ending or restarting its own session through the self-acts in `command-clearance`. Never `sessions list`, `history search` or `history show`, never starting, reviving, restarting or ending another session, and none of the reservations below. |
| Orchestrator | Every agent command, and alone `todo prepare`, `todo work` and `todo design`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| Integrator   | Every agent command except the orchestrator's reservation, plus `todo integrate`, `code maintenance` and `code owners`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| Tasker       | Every agent command except the reservations.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| Job runner   | Every agent command except the reservations.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| Coordinator  | Every agent command except the reservations. It reads and talks to the fleet and may start a peer; which lifecycle roles a session may dispatch is the run-session dispatch privilege (`project/spec/feature/agent_runtime/run-session-with-command`), under which the coordinator dispatches none.                                                                                                                                                                                                                                                                                                                          |
| System       | No role-based command reach. Caller-independent commands pass without consulting this credential.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |

A role's reach is declared once, as a group, in the CLI surface schema; a command joins a role's reach by joining its group, never by naming the role in its own entry.

### Person role bands

Each command keeps a person band of its own in the CLI surface schema, evaluated against the person's effective role at the command's scope (`project/spec/feature/identity/command-clearance`). The tiers are:

- **Admin** — the system owner: every command except `sessions escalate`, whose target they are.
- **Member** — works on projects and manages sessions; no infrastructure acts such as reviving sessions, setting agent status, or reading and writing the machine environment.
- **Contributor** — works on specific projects; starts, sends to and runs no sessions.
- **Newcomer** — read-heavy, with very limited writes.
- **Customer** — reaches only the allow-list in invariant 7.

`todo sync` is a person-only command (invariant 3) at the admin band: an admin at a terminal, or a session an admin started without an agent role, is admitted, while every session carrying an agent role and every session acting for the platform's principal is refused. Replacing another computer's todo state is an act only the system owner decides, so no lifecycle or standing role reaches it.

### Commands that do not depend on the caller

`version`, `auth login`, `auth whoami`, `auth logout`, `events list`, `signals status`, `mcp list`, the local code-tooling commands `code lint`, `code test`, `code format`, `code add` and `code blueprint affected`, the hidden git-hook commands `code pre-commit`, `code post-commit` and `code post-merge`, and the hidden todo-state-transfer helper `todo sync-replica` admit a caller with no identity. Each either reads nothing that belongs to a caller or acts on an object already guarded by its own state (`general/principle/trust-and-guardrails`) — the code-tooling commands change only the invoking checkout and, when a session invokes them, that session's own path declarations, and those that narrow their scope to a session read the session marker, never the caller, and hook maintenance acts only on a canonical-main range and runs only main-only actions. The transfer helper runs on a receiving computer inside a non-interactive SSH session, which carries no login or session identity; it only reports where that computer keeps a project's todo state and whether that state is intact, facts any account able to run it can already read from disk, and it changes nothing.

## Failure modes

| Scenario                                         | Behavior                                                                                                                         |
| ------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------- |
| A command carries no declaration                 | Refused for every caller: an undeclared command fails closed.                                                                    |
| The caller resolves to no identity               | Refused before the handler runs, naming the missing login or session identity, unless the command does not depend on its caller. |
| A worker runs a command outside its reach        | Refused with the not-permitted failure naming `worker` and the command; the work belongs to the session that dispatched it.      |
| A person is removed from the registry or demoted | The change takes effect on that person's next command.                                                                           |
| A new agent role is introduced                   | It reaches nothing until it joins a group; no command admits it by default.                                                      |
