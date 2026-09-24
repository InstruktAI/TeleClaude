---
description: 'Per-command authorization matrix for telec CLI across all system and human roles.'
visibility: 'public'
---

# CLI Authorization Matrix — Design

## Purpose

Per-command authorization matrix for `telec` CLI. Both system role (worker/orchestrator) and human role (admin/member/contributor/newcomer/customer) must allow a command for it to execute. Composition: `allowed(cmd) = system_allows(cmd) AND human_allows(cmd)`.

## Inputs/Outputs

- **Input:** Caller session identity (system role derivation) and person identity (human role lookup from `people` config).
- **Output:** Allow/deny decision for each `telec` command invocation.

## Invariants

1. Both the system gate and human gate must pass for a command to execute.
2. Workers cannot spawn sessions, orchestrate, or drive the todo state machine.
3. Customers use an allow-list model (only: `version`, `docs *`, `auth *`, `sessions escalate`).
4. Admins are the escalation target and must not be able to escalate themselves.
5. Per-role exclusion sets must be distinct: member, contributor, and newcomer have meaningfully different access levels.
6. Tasker (task-preparer/task-runner sessions) may dispatch worker-lane sessions via `sessions run`, unlike Worker, but — like Worker — cannot drive the todo state machine (`todo prepare`/`todo work`) or dispatch an orchestrator/integrator session.
<!-- planned:cli-authorization-config-via-daemon -->
7. The daemon decides this matrix for the commands the CLI serves
   (`project/spec/identity-and-auth` §6). A command reaches the data or effect it
   governs through the daemon API, which resolves the caller from the identity it
   carries, or, for a configuration operation the CLI executes in its own process,
   only on the daemon's allow. Validation alone also proceeds while no daemon is
   listening and records that no authority was available
   (`project/spec/feature/identity/command-clearance`). The CLI makes no allow/deny
   decision and resolves no role. A caller the daemon
   cannot identify receives the unauthorized allow-list. `telec config wizard` opens
   the TUI's configuration editor, which runs in the operator's own process and is
   listed under Still Open 3.
<!-- /planned:cli-authorization-config-via-daemon -->

## Primary flows

### Role Definitions

**System roles** (session type):

- **Worker**: dispatched agent doing scoped task work. Cannot spawn sessions, cannot orchestrate, cannot drive the todo state machine.
- **Tasker**: dispatched `/next-prepare-task` or `/next-run-task` session. Otherwise a Worker, but additionally may dispatch worker-lane sessions via `sessions run` (e.g. a review) when its task-plan calls for it. Still cannot drive the todo state machine or dispatch an orchestrator/integrator session.
- **Orchestrator**: personal assistant, help desk agent, any session a human interacts with. No system-level restrictions.

**Human roles** (person identity -- NOT a linear hierarchy):

- **Admin**: system owner, full access, escalation target.
- **Member**: team member, works on projects, manages own sessions. Cannot manage infrastructure.
- **Contributor**: external contributor, can work on specific projects, more restricted on session management.
- **Newcomer**: onboarding person, read-heavy, very limited write.
- **Customer**: external user via help desk. Can interact with own session, can escalate. No access to internal tooling.

### Authorization Table

Legend: R = read, W = write. Worker and Orchestrator columns show system-role gate. Admin through Customer columns show human-role gate.

### Sessions

| Command                      | Type | Worker | Orch | Admin | Member | Contributor | Newcomer | Customer | Reasoning                                                                                                                                                                                     |
| ---------------------------- | ---- | ------ | ---- | ----- | ------ | ----------- | -------- | -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `telec sessions list`        | R    | ✅     | ✅   | ✅    | ✅     | ✅          | ✅       | ❌       | Workers need to discover peer sessions for collaboration (e.g., reviewer finding fixer). Customers should not see internal session inventory.                                                 |
| `telec sessions start`       | W    | ❌     | ✅   | ✅    | ✅     | ❌          | ❌       | ❌       | Starting sessions is orchestration. Workers cannot spawn. Contributors, newcomers, and customers cannot create sessions -- only admins and members can.                                       |
| `telec sessions send`        | W    | ✅     | ✅   | ✅    | ✅     | ❌          | ❌       | ❌       | Workers need to message each other (reviewer ↔ fixer collaboration); a worker reports upward by completing its turn, and messaging a session above it is refused at the API layer. Contributors, newcomers, and customers cannot message arbitrary sessions. |
| `telec sessions tail`        | R    | ✅     | ✅   | ✅    | ✅     | ✅          | ✅       | ❌       | Workers may read peer transcripts for collaboration context. Customers should not see internal transcripts.                                                                                   |
| `telec sessions run`         | W    | ❌     | ✅   | ✅    | ✅     | ❌          | ❌       | ❌       | Running slash commands on new sessions is orchestration. Same restrictions as `sessions start`.                                                                                               |
| `telec sessions revive`      | W    | ❌     | ✅   | ✅    | ❌     | ❌          | ❌       | ❌       | Reviving a dead session is admin infrastructure. Admin only.                                                                                                                                  |
| `telec sessions end`         | W    | ❌     | ✅   | ✅    | ✅     | ❌          | ❌       | ❌       | Members can end their own sessions (self-scoped enforcement at API layer). Workers, contributors, newcomers, and customers cannot.                                                            |
| `telec sessions unsubscribe` | W    | ✅     | ✅   | ✅    | ✅     | ❌          | ❌       | ❌       | Workers manage their own notification subscriptions. Matches send restrictions for non-admin human roles.                                                                                     |
| `telec sessions restart`     | W    | ✅     | ✅   | ✅    | ❌     | ❌          | ❌       | ❌       | Workers may restart only their own session for artifact reloads; arbitrary session restart remains admin infrastructure enforced at the API layer.                                            |
| `telec sessions result`      | W    | ✅     | ✅   | ✅    | ✅     | ✅          | ❌       | ❌       | Workers send results back to their orchestrator -- this is their primary output mechanism. Newcomers and customers have no reason to send results.                                            |
| `telec sessions file`        | W    | ✅     | ✅   | ✅    | ✅     | ✅          | ❌       | ❌       | Workers send files back to their user. Same as result.                                                                                                                                        |
| `telec sessions escalate`    | W    | ✅     | ✅   | ❌    | ✅     | ✅          | ✅       | ✅       | Escalation is how non-admins ask for help. Admins ARE the escalation target, so they don't escalate. Workers CAN escalate (a stuck worker needs to ask for help). Everyone else can escalate. |

This table's system-role columns predate Integrator and System (see the code's `_SYS_ORCH`/`_SYS_ALL`, which already include both) and now also predate Tasker — none of the three have a column here. For the one row where Tasker diverges from Worker, `telec sessions run`, Tasker is ✅ (dispatch worker-lane sessions only — see Role Definitions above); every other row in this table treats Tasker the same as Worker.

### Infrastructure

| Command                     | Type | Worker | Orch | Admin | Member | Contributor | Newcomer | Customer | Reasoning                                                                                                                    |
| --------------------------- | ---- | ------ | ---- | ----- | ------ | ----------- | -------- | -------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `telec computers list`      | R    | ✅     | ✅   | ✅    | ✅     | ❌          | ❌       | ❌       | Read-only context. Workers may need environment awareness. Only team members see the computer inventory.                     |
| `telec projects list`       | R    | ✅     | ✅   | ✅    | ✅     | ✅          | ✅       | ❌       | Read-only context. Workers may need project awareness. Customers should not see the project inventory.                       |
| `telec agents availability` | R    | ✅     | ✅   | ✅    | ✅     | ✅          | ✅       | ❌       | Read-only agent status. Workers may check availability before requesting help. Customers don't interact with agent dispatch. |
| `telec agents status`       | W    | ❌     | ✅   | ✅    | ❌     | ❌          | ❌       | ❌       | Setting agent dispatch status is infrastructure management. Admin only.                                                      |
| `telec channels list`       | R    | ✅     | ✅   | ✅    | ✅     | ❌          | ❌       | ❌       | Workers need channel awareness for status publishing. Only team members see channels.                                        |
| `telec channels publish`    | W    | ✅     | ✅   | ✅    | ✅     | ❌          | ❌       | ❌       | Workers publish status updates to channels. Only team members can publish.                                                   |

### System

| Command               | Type | Worker | Orch | Admin | Member | Contributor | Newcomer | Customer | Reasoning                                                                                                                           |
| --------------------- | ---- | ------ | ---- | ----- | ------ | ----------- | -------- | -------- | ----------------------------------------------------------------------------------------------------------------------------------- |
<!-- planned-change:align-config-cli-ownership -->
| `telec projects init` | W    | ❌     | ✅   | ✅    | ✅     | ❌          | ❌       | ❌       | Project initialization modifies the workspace. Workers don't initialize. Only admins and members should initialize projects.        |
<!-- change:align-config-cli-ownership -->
<!-- /planned-change:align-config-cli-ownership -->
| `telec version`       | R    | ✅     | ✅   | ✅    | ✅     | ✅          | ✅       | ✅       | Version is a health check. Everyone can see it.                                                                                     |

### Documentation

| Command            | Type | Worker | Orch | Admin | Member | Contributor | Newcomer | Customer | Reasoning                                                                       |
| ------------------ | ---- | ------ | ---- | ----- | ------ | ----------- | -------- | -------- | ------------------------------------------------------------------------------- |
| `telec docs index` | R    | ✅     | ✅   | ✅    | ✅     | ✅          | ✅       | ✅       | Documentation is universally readable. Workers need docs for context retrieval. |
| `telec docs get`   | R    | ✅     | ✅   | ✅    | ✅     | ✅          | ✅       | ✅       | Same as docs index -- universal read access.                                    |

### Todo Management

| Command                       | Type | Worker | Orch | Admin | Member | Contributor | Newcomer | Customer | Reasoning                                                                                                                                                                                                    |
| ----------------------------- | ---- | ------ | ---- | ----- | ------ | ----------- | -------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `telec todo create`           | W    | ❌     | ✅   | ✅    | ✅     | ✅          | ❌       | ❌       | Creating a todo with substantive content is work planning. Contributors can scaffold work items.                                                                                                             |
| `telec todo design`           | W    | ❌     | ✅   | ✅    | ✅     | ❌          | ❌       | ❌       | Driving the creative state machine is orchestration. Same boundary as prepare/work.                                                                                                                          |
| `telec todo remove`           | W    | ❌     | ✅   | ✅    | ✅     | ❌          | ❌       | ❌       | Removing a todo is destructive planning. Only admins and members.                                                                                                                                            |
| `telec todo reactivate`       | W    | ❌     | ✅   | ✅    | ✅     | ❌          | ❌       | ❌       | Restoring a soft-removed todo is the inverse of `telec todo remove`; same audience and trust shape (operator/member restoring a recoverable state on a todo they own). delivered_by roadmap-trash-reveal-ui. |
| `telec todo prepare`          | W    | ❌     | ✅   | ✅    | ✅     | ❌          | ❌       | ❌       | Driving the prepare state machine is orchestration. Workers cannot drive the state machine. Only admins and members.                                                                                         |
| `telec todo work`             | W    | ❌     | ✅   | ✅    | ✅     | ❌          | ❌       | ❌       | Driving the work state machine is orchestration. Same as prepare.                                                                                                                                            |
| `telec todo stamp`            | W    | ❌     | ✅   | ✅    | ✅     | ❌          | ❌       | ❌       | Stamping verdicts and finalize-ready is state machine management.                                                                                                                                            |
| `telec todo set-deps`         | W    | ❌     | ✅   | ✅    | ✅     | ❌          | ❌       | ❌       | Setting dependencies is work planning. Same as prepare/work.                                                                                                                                                 |
| `telec todo verify-artifacts` | R    | ✅     | ✅   | ✅    | ✅     | ✅          | ✅       | ❌       | Mechanical verification is a read/check operation. Workers can verify their own artifacts.                                                                                                                   |
<!-- planned:cli-authorization-config-via-daemon -->
| `telec todo show`             | R    | ✅     | ✅   | ✅    | ✅     | ✅          | ✅       | ❌       | Reading one todo's state is a read operation. Workers read the todo they are working on. Customers should not see internal planning.                                                                         |
| `telec todo artifacts read`   | R    | ✅     | ✅   | ✅    | ✅     | ✅          | ✅       | ❌       | Workers read their todo's artifacts to do the work. Customers should not see internal planning.                                                                                                              |
<!-- /planned:cli-authorization-config-via-daemon -->

### Todo List Management

| Command               | Type | Worker | Orch | Admin | Member | Contributor | Newcomer | Customer | Reasoning                                                                                                                          |
| --------------------- | ---- | ------ | ---- | ----- | ------ | ----------- | -------- | -------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `telec todo list`     | R    | ✅     | ✅   | ✅    | ✅     | ✅          | ✅       | ❌       | Reading the todo list is useful for orientation. Workers read it too: reviewers and diagnosers check it for overlapping and duplicate work. Customers should not see internal planning. |
| `telec todo freeze`   | W    | ❌     | ✅   | ✅    | ✅     | ❌          | ❌       | ❌       | Freezing an entry is planning management. Only admins and members.                                                                 |
| `telec todo unfreeze` | W    | ❌     | ✅   | ✅    | ✅     | ❌          | ❌       | ❌       | Restoring an iceboxed entry is planning management. Only admins and members.                                                       |
| `telec todo deliver`  | W    | ❌     | ✅   | ✅    | ✅     | ❌          | ❌       | ❌       | Delivering is planning management. Only admins and members.                                                                        |

### Bug Management

| Command             | Type | Worker | Orch | Admin | Member | Contributor | Newcomer | Customer | Reasoning                                                                                                          |
| ------------------- | ---- | ------ | ---- | ----- | ------ | ----------- | -------- | -------- | ------------------------------------------------------------------------------------------------------------------ |
| `telec bugs report` | W    | ✅     | ✅   | ✅    | ✅     | ✅          | ✅       | ❌       | Workers CAN report bugs (explicitly stated). Anyone on the team can report. Customers should use escalate instead. |
| `telec bugs list`   | R    | ✅     | ✅   | ✅    | ✅     | ✅          | ✅       | ❌       | Listing bugs is a read operation. Workers can see bug status. Customers should not see internal bug tracking.      |

Job-runner sessions, which have no column here, are admitted to `telec todo list`,
`telec todo artifacts read`, and `telec bugs list`: a scheduled job that files bugs reads
the todo and bug landscape before filing, so it does not file a defect that is already
reported or being fixed.


### Content Pipeline

| Command              | Type | Worker | Orch | Admin | Member | Contributor | Newcomer | Customer | Reasoning                                                                                                                         |
| -------------------- | ---- | ------ | ---- | ----- | ------ | ----------- | -------- | -------- | --------------------------------------------------------------------------------------------------------------------------------- |
| `telec content dump` | W    | ✅     | ✅   | ✅    | ✅     | ✅          | ❌       | ❌       | Fire-and-forget content dump. Workers can dump content observations. Contributors can dump. Newcomers should not produce content. |

### Events

| Command             | Type | Worker | Orch | Admin | Member | Contributor | Newcomer | Customer | Reasoning                                                                                                            |
| ------------------- | ---- | ------ | ---- | ----- | ------ | ----------- | -------- | -------- | -------------------------------------------------------------------------------------------------------------------- |
| `telec events list` | R    | ✅     | ✅   | ✅    | ✅     | ✅          | ✅       | ❌       | Listing event schemas is a read operation. Workers may need event context. Customers should not see internal events. |

### Authentication

| Command             | Type | Worker | Orch | Admin | Member | Contributor | Newcomer | Customer | Reasoning                                                    |
| ------------------- | ---- | ------ | ---- | ----- | ------ | ----------- | -------- | -------- | ------------------------------------------------------------ |
| `telec auth login`  | W    | ✅     | ✅   | ✅    | ✅     | ✅          | ✅       | ✅       | Identity establishment. Everyone needs to be able to log in. |
| `telec auth whoami` | R    | ✅     | ✅   | ✅    | ✅     | ✅          | ✅       | ✅       | Identity check. Everyone can see who they are.               |
| `telec auth logout` | W    | ✅     | ✅   | ✅    | ✅     | ✅          | ✅       | ✅       | Identity clearing. Everyone can log out.                     |

### Configuration

| Command                      | Type | Worker | Orch | Admin | Member | Contributor | Newcomer | Customer | Reasoning                                                                                                           |
| ---------------------------- | ---- | ------ | ---- | ----- | ------ | ----------- | -------- | -------- | ------------------------------------------------------------------------------------------------------------------- |
| `telec config wizard`        | W    | ❌     | ❌   | ✅    | ❌     | ❌          | ❌       | ❌       | Human-only interactive config wizard; hidden from command discovery and reserved for direct invocation by an admin. |
<!-- planned-change:align-config-cli-ownership -->
| `telec config get`           | R    | ✅     | ✅   | ✅    | ✅     | ✅          | ✅       | ❌       | Reading config values is a read operation. Workers may need config context. Customers should not see system config. |
| `telec config patch`         | W    | ❌     | ✅   | ✅    | ❌     | ❌          | ❌       | ❌       | Patching config is system modification. Admin only.                                                                 |
<!-- change:align-config-cli-ownership -->
| `telec config computer list` | R | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | Reading machine configuration is a read operation. Workers may need config context. Customers should not see system config. |
| `telec config computer get` | R | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | Same as `config computer list`. |
| `telec config computer init` | W | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | Machine configuration is system modification. Target clearance requires platform-administrator standing. |
| `telec config computer patch` | W | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | Same as `config computer init`. |
| `telec config global list` | R | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | The global view excludes the people registry, which belongs to person subjects. |
| `telec config global get` | R | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | Same as `config global list`. |
| `telec config global init` | W | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | Global configuration is fleet-wide modification. Target clearance requires platform-administrator standing. |
| `telec config global patch` | W | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | Same as `config global init`. |
| `telec config person list` | R | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | Listing people exposes identity info. Target clearance requires platform-administrator standing. |
| `telec config person get` | R | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | Registered people read their own configuration; target clearance limits a non-administrator to their own instance. |
| `telec config person patch` | W | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | Registered people change their own settings; identity fields, other instances, and removal require platform-administrator standing. |
| `telec config person init` | W | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | Registering people is admin infrastructure. |
| `telec config person invite` | W | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | Generating invite links is admin infrastructure. |
| `telec config person discord-voice-bot` | W | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | Binding the machine Discord credential into a person's environment is admin infrastructure. |
| `telec config company list` | R | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | A company's configuration carries its roster, which names people. Target clearance requires platform-administrator standing. |
| `telec config company get` | R | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | Same as `config company list`. |
| `telec config company patch` | W | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | Company configuration and its roster are changed by a platform administrator. |
| `telec config company init` | W | ❌ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | Company initialization scaffolds the company tree without touching a roster. |
| `telec config project list` | R | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | Project configuration is read-only context committed in its repository. |
| `telec config project get` | R | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | Same as `config project list`. |
| `telec config project init` | W | ❌ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | Project initialization modifies the caller's workspace. Workers don't initialize. Only admins and members should initialize projects. |
| `telec config project patch` | W | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | Naming a project by slug reaches any registered checkout. Target clearance requires platform-administrator standing. |
<!-- /planned-change:align-config-cli-ownership -->
| `telec config validate`      | R    | ✅     | ✅   | ✅    | ✅     | ✅          | ✅       | ❌       | Validation is a read/check operation. Same as config get.                                                           |
<!-- planned-change:align-config-cli-ownership -->
| `telec config people list`   | R    | ❌     | ✅   | ✅    | ❌     | ❌          | ❌       | ❌       | People management is admin infrastructure. Listing people exposes identity info.                                    |
| `telec config people add`    | W    | ❌     | ✅   | ✅    | ❌     | ❌          | ❌       | ❌       | Adding people is admin infrastructure.                                                                              |
| `telec config people edit`   | W    | ❌     | ✅   | ✅    | ❌     | ❌          | ❌       | ❌       | Editing people is admin infrastructure.                                                                             |
| `telec config people remove` | W    | ❌     | ✅   | ✅    | ❌     | ❌          | ❌       | ❌       | Removing people is admin infrastructure.                                                                            |
<!-- change:align-config-cli-ownership -->
<!-- /planned-change:align-config-cli-ownership -->
| `telec config env list`      | R    | ❌     | ✅   | ✅    | ❌     | ❌          | ❌       | ❌       | Environment variables may contain secrets. Admin only.                                                              |
| `telec config env set`       | W    | ❌     | ✅   | ✅    | ❌     | ❌          | ❌       | ❌       | Setting env vars is system modification. Admin only.                                                                |
| `telec config notify`        | W    | ❌     | ✅   | ✅    | ✅     | ❌          | ❌       | ❌       | Toggling notifications is personal config. Members can manage their own notifications.                              |

<!-- planned-change:align-config-cli-ownership -->
| `telec config people invite` | W | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | Generating invite links is admin infrastructure. |
<!-- change:align-config-cli-ownership -->
<!-- /planned-change:align-config-cli-ownership -->

### Disagreements with Current `tool_access.py`

Workers now use a **whitelist** (`WORKER_ALLOWED_TOOLS`): only explicitly listed tools pass; all others are denied by default. This means new clearance-gated tools are automatically blocked for workers until whitelisted. Human roles still use exclusion sets (deny-lists).

### Resolved

- **Worker escalate bug** — `telec sessions escalate` is in `WORKER_ALLOWED_TOOLS`. Workers can escalate when stuck.
- **Worker send bug** — `telec sessions send` is in `WORKER_ALLOWED_TOOLS`. Workers can message each other (reviewer ↔ fixer collaboration).
- **Worker default-deny** — New clearance-gated tools are denied by default for workers (whitelist model).

### Still Open

### 1. `telec sessions escalate` — Member gate

**Current code**: `MEMBER_EXCLUDED_TOOLS` contains `telec sessions escalate` (members CANNOT escalate).
**Matrix**: Members SHOULD be able to escalate. Escalation is for all non-admins. Admins are the target, not the source.
**Action**: Remove `telec sessions escalate` from `MEMBER_EXCLUDED_TOOLS`. Add `telec sessions escalate` to a new admin-excluded set (since admins don't escalate to themselves).

### 2. `telec sessions escalate` — Admin gate

**Current code**: Admins have no exclusions, so admins CAN escalate.
**Matrix**: Admins SHOULD NOT escalate. They are the escalation target. Allowing admin escalation is a logical error.
**Action**: Create an `ADMIN_EXCLUDED_TOOLS` set containing `telec sessions escalate`.

### 3. Missing commands — no enforcement at all

Many commands have no clearance gate (no `CLEARANCE_*` dependency on their API endpoint) and therefore bypass the tool-access layer entirely. These need enforcement:

| Command                       | Should be restricted for                    |
| ----------------------------- | ------------------------------------------- |
| `telec sessions revive`       | Contributors, newcomers, customers          |
| `telec sessions result`       | Newcomers, customers                        |
<!-- planned-change:align-config-cli-ownership -->
| `telec projects init`         | Contributors, newcomers, customers          |
<!-- change:align-config-cli-ownership -->
<!-- /planned-change:align-config-cli-ownership -->
| `telec todo create`           | Newcomers, customers                        |
| `telec todo design`           | Contributors, newcomers, customers          |
| `telec todo remove`           | Contributors, newcomers, customers          |
| `telec todo reactivate`       | Contributors, newcomers, customers          |
| `telec todo verify-artifacts` | Customers                                   |
| `telec todo freeze`           | Contributors, newcomers, customers          |
| `telec todo unfreeze`         | Contributors, newcomers, customers          |
| `telec todo deliver`          | Contributors, newcomers, customers          |
| `telec bugs report`           | Customers                                   |
| `telec content dump`          | Newcomers, customers                        |
| `telec events list`           | Customers                                   |
| `telec config wizard`         | Members, contributors, newcomers, customers |
<!-- planned-change:align-config-cli-ownership -->
| `telec config get`            | Customers                                   |
| `telec config patch`          | Members, contributors, newcomers, customers |
<!-- change:align-config-cli-ownership -->
<!-- /planned-change:align-config-cli-ownership -->
<!-- planned-change:cli-authorization-config-via-daemon -->
| `telec config validate`       | Customers                                   |
<!-- change:cli-authorization-config-via-daemon -->
<!-- /planned-change:cli-authorization-config-via-daemon -->
<!-- planned-change:align-config-cli-ownership -->
| `telec config people *`       | Members, contributors, newcomers, customers |
<!-- change:align-config-cli-ownership -->
<!-- /planned-change:align-config-cli-ownership -->
<!-- planned-change:cli-authorization-config-via-daemon -->
| `telec config env *`          | Members, contributors, newcomers, customers |
| `telec config notify`         | Contributors, newcomers, customers          |
<!-- change:cli-authorization-config-via-daemon -->
<!-- /planned-change:cli-authorization-config-via-daemon -->

### 4. `MEMBER_EXCLUDED_TOOLS` applied too broadly

**Current code**: The `MEMBER_EXCLUDED_TOOLS` set is applied to members, contributors, AND newcomers equally (all three share the same exclusion set).
**Matrix**: These three roles have meaningfully different access levels. Contributors should not start/send/run sessions. Newcomers should be even more restricted (read-heavy). The current code under-restricts contributors and newcomers.
**Action**: Create separate `CONTRIBUTOR_EXCLUDED_TOOLS` and `NEWCOMER_EXCLUDED_TOOLS` sets.

### 5. `CUSTOMER_EXCLUDED_TOOLS` — missing many commands

**Current code**: Customer exclusions are built from `UNAUTHORIZED_EXCLUDED_TOOLS` plus `sessions list`, `todo list`, `channels publish`, and `channels list`, minus `sessions escalate`.
**Matrix**: Customers should also be excluded from: `sessions tail`, `sessions revive`, `sessions restart`, `sessions result`, `computers list`, `projects list`, `agents availability`, `agents status`, all `todo *` (including list), all `bugs *`, `content dump`, `events list`, all `config *` commands (except auth is universal).
**Action**: Switch to an allow-list approach for customers (simpler: allow only `version`, `docs *`, `auth *`, `sessions escalate`).

### 6. `UNAUTHORIZED_EXCLUDED_TOOLS` — inconsistent with newcomer

**Current code**: `UNAUTHORIZED_EXCLUDED_TOOLS` is used as the fallback for unknown/unauthenticated users AND is the base for customer exclusions.
**Matrix**: Unauthorized (no identity) should have the most restrictive access -- essentially the same as customer or even less. The current set misses many commands that should be restricted.

### Implementation Recommendations

1. **Extend whitelist model to customers and unauthorized.** Workers already use a whitelist. Customers and unauthorized roles are equally restricted — switch them to allow-lists too.

2. **Create per-role exclusion sets.** Replace the current shared `MEMBER_EXCLUDED_TOOLS` with distinct sets for member, contributor, and newcomer.

3. **Add admin exclusions.** Create `ADMIN_EXCLUDED_TOOLS = {"telec sessions escalate"}` -- admins are the escalation target.

4. **Enumerate all leaf commands in enforcement.** The current code only covers ~20 commands with clearance gates. This matrix covers 65+ leaf commands. Every command needs a gate, or the system must default-deny unknown commands.

## Failure modes

| Scenario                                       | Behavior                                                                                          |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| New clearance-gated tool added for workers     | Denied by default (whitelist model). Must be added to `WORKER_ALLOWED_TOOLS` to permit.           |
| Command not in any exclusion set (human roles) | Defaults to allowed; must default-deny unknown commands or add clearance gates to close this gap. |
| Shared exclusion set applied to multiple roles | Under-restricts contributors and newcomers; requires distinct per-role sets.                      |
| Admin attempts to escalate                     | Currently allowed; must create `ADMIN_EXCLUDED_TOOLS = {"telec sessions escalate"}` to block it.  |
| Customer bypasses via non-enumerated command   | Deny-list approach misses new commands; switch to allow-list for customer role to close the gap.  |
