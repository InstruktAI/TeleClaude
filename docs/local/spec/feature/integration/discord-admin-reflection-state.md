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

The desired operational shape comes from configuration and the project
registry: machine identity, master/non-master role, enabled agents, every entry
on the machine's project registry — projects and person or company homes alike —
with its identity, display name, and registry order, and configured people
(`projects/teleclaude/spec/feature/config/project-registry`). A project forum is keyed by its
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

#### UC-DARS-11: Shared containers and their children retain distinct owners

```gherkin
Given a Discord category, forum, or channel is a singleton shared container across the fleet
When the fleet reconciles that container
Then only the master computer may create or adopt it
And every non-master may verify and use the existing container without creating a duplicate
And no computer writes its provider identity to configuration
Given a session or relay thread exists inside a shared forum
When the fleet accepts or reconciles that child
Then every computer publishes observational ownership while any retained fleet member has not adopted the child-ownership protocol
And observational ownership does not change the previously agreed handling
And after every retained fleet member has adopted the protocol, exactly one computer durably owns each newly bound child independently of the shared container
And foreign computers do not mutate the claimed child
And the master treats the child as ownerless only after every retained computer has completed ownership adoption and the same child survives two complete reconciliation epochs without a claim
And incomplete or mixed-version ownership evidence causes no provider deletion
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
