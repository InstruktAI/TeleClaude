---
description: DB-backed Discord admin reflection state for categories, channels, project
  forums, and launcher messages, with restart-safe reconciliation and no provider
  IDs written to config.yml.
visibility: internal
---

# Discord Admin Reflection State — Spec

## Required reads

- @docs/local/policy/adapter-boundaries.md
- @docs/local/policy/config-public-surface.md
- @docs/local/design/architecture/database.md
- @docs/local/spec/domain/integration.md
- @docs/local/spec/teleclaude-config.md

## What it is

Discord admin reflection state is the durable record of Discord provider artifacts
that TeleClaude creates or adopts to reflect its operational structure: admin
categories, shared channels, help-desk forums, per-machine project forums, team
channels, and session-launcher forum threads/messages.

Every help desk the master hosts has its own category in the guild, named
`Help Desk - <kind>-<slug>` after the desk's entry identifier, created and
reconciled by the master alone. It holds three channels:

<!-- planned-change:help-desk-escalation-in-desk -->

| Channel                     | People in the desk's scope                | The bot                                               |
| --------------------------- | ----------------------------------------- | ----------------------------------------------------- |
| `customer-sessions` (forum) | read every thread; post nothing           | mirrors each session of that desk into its own thread |
| `escalations` (forum)       | read threads and reply in them; open none | holds the forum for the desk's escalation threads     |
| `team-chat` (text channel)  | read and post                             | grants access only; reads and answers nothing         |

<!-- change:help-desk-escalation-in-desk -->

| Channel                     | People in the desk's scope                | The bot                                                               |
| --------------------------- | ----------------------------------------- | --------------------------------------------------------------------- |
| `customer-sessions` (forum) | read every thread; post nothing           | mirrors each session of that desk into its own thread                 |
| `escalations` (forum)       | read threads and reply in them; open none | opens one thread per escalation and relays between it and the visitor |
| `team-chat` (text channel)  | read and post                             | grants access only; reads and answers nothing                         |

<!-- /planned-change:help-desk-escalation-in-desk -->

A desk's category is visible only to the people in its scope, as identity
resolves it (`local/projects/teleclaude/spec/domain/identity`), through
per-person permission overwrites, never through Discord roles. For a company
desk the scope is the company's members and admins. For a project desk it is
the owning company's members and admins, or the person who owns it. Every
desk's scope includes the platform's admins. A person is in Discord scope only
through a bound Discord account. The master keeps every overwrite in step with
the desk's scope, and re-syncs them when a declaration the scope or a Discord
binding derives from changes: a desk's grants are exactly its scope's people
who have a bound account and are in the guild, and every other person's grant
is removed. A desk that stops being hosted loses its category; hosting is the
endpoint registry's hosted-desk answer
(`local/projects/teleclaude/spec/domain/agent_runtime`). No session at a
desk is reflected into any other forum of the guild — not the all-sessions
forum and not a project's own forum — so no desk's customer conversation is
visible outside its scope, and the guild holds no shared help-desk category. A
desk's forums are no entry point: a post that Discord lets through into a
customer-sessions thread reaches no session.

The guild is the members' surface and never a customer's: every desk session
reaches its desk through an adapter other than Discord
(`local/projects/teleclaude/spec/feature/agent_runtime/conversation-entry`), so
its thread in the desk's customer-sessions forum is the only place Discord shows
it.

The desired operational shape comes from configuration and the project
registry: machine identity, master/non-master role, enabled agents, every entry
on the machine's project registry — projects and person or company homes alike —
with its identity, display name, and registry order, and configured people
(`local/projects/teleclaude/spec/feature/config/project-registry`). A project forum is keyed by its
entry's identity, and the forums in a machine's project category follow registry
order. A machine's project category holds exactly its registry entries' forums
and its catch-all forum for sessions outside every entry; any other forum there,
and every project-forum reflection record no registry entry backs, is removed.
Removal runs only in a pass where every present registry folder's configuration
loads, every registry entry holds its forum, and Discord conclusively lists the
category's forums. A stored forum whose lookup was inconclusive keeps its
reflection record and is never replaced in that pass. Discord provider IDs are not
desired-state configuration. They are
observed external state returned by the Discord adapter boundary, and the
database stores them as reflection records.

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
  `operations.category`, `help_desk:<entry_identifier>.customer_sessions`,
  `project_forum:<project_slug>`, or `session_launcher:<forum_id>`.

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
Given a registered project has no recorded forum
When Discord reconciliation examines forums with the project's display name in the machine's project category
Then if exactly one matching forum is unclaimed by another registry identity, that forum is assigned to the project
And if no unclaimed matching forum exists, a distinct forum is created for that identity, even when another forum has the same name
And if more than one unclaimed match remains, no forum is created or assigned
And a session started from an assigned forum is placed in that project's folder
And the machine configuration is not updated with a Discord forum field
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

#### UC-DARS-11: Shared containers are provisioned by the master alone

```gherkin
Given a Discord category, forum, or channel is a singleton shared container across the fleet
When the fleet reconciles that container
Then only the master computer may create or adopt it
And every non-master may verify and use the existing container without creating a duplicate
And no computer writes its provider identity to configuration
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

#### UC-DARS-14: A forum keyed by a retired trusted-directory name moves to its entry's identity

```gherkin
Given the database holds a project-forum reflection record keyed by a retired trusted-directory name
And the configuration hand-off binds that name to a folder that is now on the project registry
When the Discord reconciler runs
Then the stored forum is recorded under that registry entry's identity
And no forum is created for that entry
And a session started from a thread in that forum is placed in the entry's folder
```

#### UC-DARS-15: A newly adopted registry entry gets its forum without a restart

```gherkin
Given the daemon is running with Discord enabled
When an operator adopts a folder onto the machine's project registry
Then the operator sees that entry's forum in the machine's project category in Discord within seconds
And the daemon did not restart
```

#### UC-DARS-16: Project forums follow registry order

```gherkin
Given the machine's project registry lists its entries in a given order
And each entry has a reflected forum in the machine's project category
When the Discord reconciler runs at startup or after the registry changes
Then an operator reading Discord sees those forums in registry order
```

#### UC-DARS-17: The project category shows only forums the registry backs

```gherkin
Given the machine's project category in Discord holds a forum that no entry on the machine's project registry is assigned
And every registry entry holds its forum in that category
When the Discord reconciler runs at startup or after the registry changes
Then an operator reading Discord no longer sees that forum
And the database holds no reflection record for it
And the operator still sees every registry entry's forum and the machine's catch-all forum
```

#### UC-DARS-18: Removal waits until every registry entry holds its forum

```gherkin
Given a registry entry whose forum could not be assigned in a reconciliation pass
And the machine's project category holds a forum that no registry entry is assigned
When that reconciliation pass completes
Then an operator reading Discord still sees that forum
```

#### UC-DARS-19: A registry folder whose configuration fails to load keeps its forum

```gherkin
Given a registry folder is present on the machine but its configuration fails to load
And that folder's forum is in the machine's project category
When the Discord reconciler runs
Then an operator reading Discord still sees that folder's forum
```

#### UC-DARS-20: A desk's sessions are reflected only in its own category

```gherkin
Given a customer session at a project's help desk
When the master reflects sessions into the guild
Then the session has a thread in that desk's customer-sessions forum
And it appears in no other forum of the guild, the all-sessions forum and the project's own forum included
```

#### UC-DARS-21: Every hosted desk has its own category on the master

```gherkin
Given the master hosts a company desk and a project desk
When the master reconciles the guild
Then each desk has a category named after its entry identifier
And each category holds a customer-sessions forum, an escalations forum and a team-chat channel
And the guild holds no shared help-desk category
And a computer that is not the master creates no desk category
```

#### UC-DARS-22: Only the people in a desk's scope see its category

```gherkin
Scenario Outline: <person>
  Given a company desk and a project the company owns with its own desk
  And <person> with a bound Discord account
  When they look at the guild
  Then <outcome>

  Examples:
    | person                                  | outcome                                              |
    | a member of the company                 | they see both desks' categories                      |
    | an admin of the company                 | they see both desks' categories                      |
    | a platform admin                        | they see both desks' categories and every other desk |
    | a member of another company             | they see neither category                            |
    | the owner of a person-owned project     | they see that project's desk category only           |
```

#### UC-DARS-23: People in scope read customer sessions but cannot post there

```gherkin
Given a member in a desk's scope
When they open the desk's customer-sessions forum
Then they can read every session thread
And they cannot post in any thread or open a new one
```

#### UC-DARS-24: Scope follows the roster

```gherkin
Scenario Outline: <change>
  Given a desk whose category is visible to its scope
  When <change>
  Then <outcome>

  Examples:
    | change                                                | outcome                                         |
    | a person becomes a member of the desk's company       | they see the desk's category                    |
    | a person leaves the desk's company                    | they no longer see the desk's category          |
    | a member in scope binds their Discord account         | they see the desk's category                    |
    | a desk is no longer enabled                           | its category is removed                         |
```

#### UC-DARS-25: Team chat is for people only

```gherkin
Given a desk's team-chat channel
When a person in scope posts there
Then everyone in the desk's scope reads it
And the bot neither answers nor routes the message anywhere
```

#### UC-DARS-26: A post in a desk's customer-sessions thread reaches no customer

```gherkin
Given a person whom Discord lets post in a desk's customer-sessions thread
When they post there
Then the message reaches no session and no customer
And the customer's conversation continues as before
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

- `identity` owns a desk's scope. The desk surface turns it into per-person
  grants and never re-derives who belongs to a desk.
- `agent_runtime`'s endpoint registry owns which desks the master hosts, and
  each session's desk is the one its endpoint names.
- `config` owns whether a home keeps a desk and each person's Discord binding.
  Its declaration-change notice is the signal on which the master re-syncs desk
  grants and categories.

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

- Discord shows every channel to the guild owner and to holders of the
  Administrator permission, and lets them post there, whatever a desk's
  per-person grants say. A desk's category reaches only its scope while those
  powers rest with platform admins.

<!-- planned-change:help-desk-escalation-in-desk -->

- A desk's escalations forum is provisioned with its grants, but no escalation
  opens a thread in it and nothing in it is relayed. Escalations reach people as
  `local/projects/teleclaude/spec/feature/agent_runtime/help-desk-escalation`
  states.

<!-- change:help-desk-escalation-in-desk -->
<!-- /planned-change:help-desk-escalation-in-desk -->
