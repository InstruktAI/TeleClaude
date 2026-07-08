---
delivered_by:
  - move-discord-reflection-state-to-db
description: DB-backed Discord admin reflection state for categories, channels, project forums, and launcher messages, with restart-safe reconciliation and no provider IDs written to config.yml.
visibility: internal
---

# Discord Admin Reflection State — Spec

## Required reads

- @docs/project/policy/adapter-boundaries.md
- @docs/project/policy/config-public-surface.md
- @docs/project/design/architecture/database.md
- @docs/project/spec/domain/integration.md
- @docs/project/spec/teleclaude-config.md

## What it is

Discord admin reflection state is the durable record of Discord provider artifacts
that TeleClaude creates or adopts to reflect its operational structure: admin
categories, shared channels, help-desk forums, per-machine project forums, team
channels, and session-launcher forum threads/messages.

The desired operational shape comes from configuration and project discovery:
machine identity, master/non-master role, enabled agents, registered project
roots, project display names, and configured people. Discord provider IDs are
not desired-state configuration. They are observed external state returned by
the Discord adapter boundary, and the database stores them as reflection records.

Startup and restart reconcile Discord toward the desired shape through one
DB-backed reflection-state seam. A reconciler first reads any stored provider
ID, verifies it against Discord, and reuses it when it still represents the
expected artifact. It creates or adopts an artifact only when the database has no
usable record or Discord conclusively reports that the recorded artifact no
longer exists. An inconclusive provider lookup never creates, deletes, or clears
state.

Session-launcher buttons are part of this reflection state. Their forum
thread/message IDs live in the database, and the running bot process reattaches
the persistent button view to the stored message after restart. Reattachment is
runtime callback wiring only; it does not create a Discord artifact and does not
change stored state.

## Canonical fields

### Reflection record

- `provider`: `discord`.
- `artifact_kind`: the Discord artifact class in TeleClaude terms, such as
  `category`, `text_channel`, `forum`, `forum_thread`, or `message`.
- `logical_key`: stable TeleClaude identity for the artifact, such as
  `operations.category`, `help_desk.customer_sessions`, `project_forum:<project_slug>`,
  or `session_launcher:<forum_id>`.
- `scope`: ownership scope, such as `shared`, `machine:<computer_name>`,
  `project:<project_slug>`, or `person:<person_slug>`.
- `provider_id`: Discord's returned ID for the reflected artifact.
- `parent_provider_id`: optional Discord parent ID for artifacts whose validity
  depends on a category or forum parent.
- `metadata`: small adapter-owned details needed to verify shape or reattach
  runtime behavior, such as launcher thread ID plus starter message ID.
- `verified_at`: last time the reconciler conclusively verified the artifact.

The exact table shape is implementation-owned. The contract is the seam: every
Discord admin artifact read, write, migration, reset, and reconciliation goes
through one database-backed reflection-state repository. Adapter code does not
write provider IDs to `config.yml` and does not introduce one-off stores for
special cases.

### Use cases

#### UC-DARS-1: Discord provider IDs are persisted only as database reflection state

```gherkin
Given the Discord adapter resolves or creates an admin category, shared channel,
help-desk forum, project forum, team channel, launcher thread, or launcher message
When the provider returns a Discord ID
Then the ID is written to the database reflection-state repository
And no Discord category, channel, forum, thread, or message ID is written to config.yml
And the runtime config remains limited to desired machine/project/operator inputs
```

#### UC-DARS-2: Legacy config.yml Discord IDs are migrated into reflection state

```gherkin
Given config.yml contains legacy Discord provider IDs such as category IDs,
shared channel IDs, help-desk forum IDs, all-sessions forum IDs, or
trusted_dirs[].discord_forum
When the Discord reflection-state migration runs
Then each valid legacy ID is copied into the database under a stable logical key
And subsequent reconciliation reads the database record, not the YAML field
And subsequent provisioning writes do not restore those provider IDs into config.yml
```

#### UC-DARS-3: Startup reuses a verified reflected artifact

```gherkin
Given the database contains a reflection record for logical key "project_forum:teleclaude"
And the stored provider_id resolves in Discord
And the artifact is a forum under the expected "Projects - <computer>" category
When the Discord reconciler starts
Then it reuses the stored forum
And records the verification time
And does not create another forum
And project-session routing uses the database-backed project-forum binding
```

#### UC-DARS-4: Conclusive provider absence clears or replaces stale reflection state

```gherkin
Given the database contains a reflection record for a Discord artifact
And Discord conclusively returns not-found for the stored provider_id
When the reconciler verifies the record
Then the record is treated as stale reflection state
And the reconciler searches by the artifact's stable Discord identity when such identity exists
And exactly one matching artifact is adopted by replacing the stored provider_id
And no matching artifact causes the reconciler to create a replacement and store its provider_id
And multiple matching artifacts are handled by the artifact-specific convergence rule before one survivor is stored
```

#### UC-DARS-5: Inconclusive provider lookup preserves state and prevents duplicates

```gherkin
Given the database contains a reflection record for a Discord artifact
And Discord lookup fails due to timeout, missing cache population, rate limit, or another recoverable provider error
When the reconciler evaluates the artifact
Then the lookup is inconclusive
And the database record is retained unchanged
And no replacement artifact is created
And no existing artifact is deleted
And the reconciler logs the inconclusive state for retry on a later pass
```

#### UC-DARS-6: Missing reflection record creates or adopts exactly one project forum

```gherkin
Given a registered project has no database reflection record for its project forum
When the Discord reconciler evaluates the project's desired forum
Then it searches the machine's "Projects - <computer>" category for the project's stable forum name
And if exactly one matching forum exists, it adopts that forum and stores the provider_id
And if no matching forum exists, it creates the forum and stores the returned provider_id
And if lookup is inconclusive, it does not create or adopt a forum
And config.yml is not updated with a discord_forum field
```

#### UC-DARS-7: Launcher state is governed by its forum's reflection record

```gherkin
Given a reflected project forum exists
And the database has no launcher record for that forum
When the launcher reconciler evaluates the forum
Then it discovers existing launcher threads by the durable launch-button marker
And adopts exactly one launcher when one valid candidate exists
And creates a launcher thread/message only when no valid candidate exists
And stores the launcher thread ID and starter message ID in database reflection state
And does not write launcher IDs to config.yml
```

#### UC-DARS-8: Restart reattaches button views to stored launcher messages

```gherkin
Given the database contains a launcher thread ID and starter message ID for a project forum
And Discord verifies that the starter message exists and still carries launch buttons
When the daemon restarts
Then the bot reattaches the persistent launcher view to the stored message ID
And no launcher thread or message is created
And button clicks on the existing message route to the current daemon process
```

#### UC-DARS-9: Launcher click routing resolves project context from reflection state

```gherkin
Given a user clicks a launcher button in a reflected project forum
And the forum's database reflection record maps to a project root
When the Discord adapter handles the interaction
Then it creates a session command with explicit project_path, origin=discord,
  the selected agent, and the user's Discord identity metadata
And the session is provisioned into the correct Discord forum thread
And the project context is not read from config.yml discord_forum fields
```

#### UC-DARS-10: Launchers are not exposed where no launch context exists

```gherkin
Given a Discord forum is shared, unknown, help-desk, or otherwise not bound to a project root
And no explicit database reflection record defines a launch target for that forum
When launcher reconciliation runs
Then no session-launcher message is created there
And any existing launcher in that forum is not treated as a valid project launcher
And a button click without a launch target returns user-safe feedback without creating a session
```

#### UC-DARS-11: Shared artifacts obey master ownership without config writes

```gherkin
Given a Discord artifact is shared across the fleet, such as Operations,
Help Desk, Customer Sessions, Escalations, announcements, general, or operator-chat
When a master computer reconciles that shared artifact
Then it may create or adopt the artifact and store the provider_id in database reflection state
When a non-master computer reconciles that shared artifact
Then it may verify and use existing reflection state
And it does not create the shared artifact when no usable record exists
And neither computer writes the shared provider ID to config.yml
```

#### UC-DARS-12: Explicit reset is a database operation

```gherkin
Given an operator or agent determines that a reflected Discord artifact should be recreated
When the reflection record for that logical key is removed from the database
Then the next reconciliation pass treats the artifact as missing reflection state
And it follows the normal adopt-or-create path
And no config.yml edit is required to force recreation
```

#### UC-DARS-13: Reflection-state store failure fails closed before provider mutation

```gherkin
Given the database reflection-state repository is unavailable
When Discord admin reconciliation starts
Then reconciliation does not create, delete, or mutate Discord provider artifacts
And startup surfaces an operator-visible failure or degraded state
```

### Cross-context references

- The `integration` context owns the Discord provider boundary and the
  provider-ID anti-corruption layer. Discord IDs enter TeleClaude only as
  reflection records or session origin metadata.
- The `config` context owns desired setup inputs. It does not own provider-returned
  Discord IDs.
- The main runtime database owns durable reflection records because the records
  are operational state that must survive daemon restart.
- `agent_runtime` consumes project/forum routing by receiving explicit
  session-create commands after the Discord adapter has resolved project context.

## Allowed values

- `provider`: `discord`.
- `artifact_kind`: `category`, `text_channel`, `forum`, `forum_thread`, `message`.
- `scope`: `shared`, `machine:<computer_name>`, `project:<project_slug>`,
  `person:<person_slug>`.
- Reconciliation result: `verified`, `adopted`, `created`, `stale-replaced`,
  `inconclusive`, `skipped`, `failed-closed`.

## Known caveats

- Discord permissions can prevent cleanup of duplicate or stale provider
  artifacts. In that case the reconciler records the failure, preserves durable
  state for the survivor it can verify, and leaves manual provider cleanup to an
  operator.
- Discord cache state is not proof of absence. Only conclusive provider lookup
  may clear or replace a database reflection record.
- A launcher view reattachment is process-local runtime wiring. The durable
  artifact remains the Discord message plus the database reflection record.
