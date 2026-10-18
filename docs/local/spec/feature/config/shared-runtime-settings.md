---
description: One configuration-owned authority for shared runtime values, with explicit scope, atomic revisions and recoverable change publication.
visibility: internal
delivered_by:
  - central-shared-configuration
---

# Shared Runtime Settings — Spec

## What it is

An administrator changes shared runtime settings once, through the configuration
owner. Relevant computers resolve the same committed subject snapshot. A
computer retains its identity, bootstrap connection, filesystem locations and
local resources. Scope follows the setting's meaning under
`sdlc/policy/domain-ownership`; sharing a Redis server does not make a project
setting cluster-wide.

The repository owns key definitions and configuration behavior. Redis owns the
mutable shared values. Repository-authored project declarations, jobs, actions,
schemas and capability policy remain repository source. Discovery owns the set
of advertised computers. Native provider login storage retains its provider
owner.

**Business value:** a shared configuration change has one accepted state and an
identifiable revision; operators can distinguish acceptance from application,
and a competing edit cannot silently discard their change.

## Canonical fields

### Subjects and definitions

A shared subject is either the cluster singleton or one registered project by
stable project slug. Each has an independent snapshot and revision. A write
addresses one subject; it supplies no transaction across subjects or local
configuration files. Shared subjects are value namespaces, separate from the
file-backed overlay tiers and invocation-context resolution.

Repository-owned definitions declare each key's stable logical path, subject
scope, type, allowed values, sensitivity, requiredness and explicit meaning
when unset or null. This authority is distinct from the existing machine
section's execution applicability and from its editability tier. Defaults used
to initialize a shared subject are materialized in its first revision; a
different checkout's defaults never override a stored shared value.

Enablement flags, agent default and designations are required once initialized.
Optional credentials admit explicit null as no configured credential; unsetting
removes the declaration and returns explicit absence without recreating a local
value. Optional provider models and voice declarations retain their component
schema's domain meaning and normalization. Their definitions state the effective
result of absence, including any provider-owned default, so removal never
implicitly means reset. The read retains the distinction between a present
null and an absent key even when both make a provider unavailable
(`sdlc/policy/code-quality-practices`).

The current component validators validate their owned portions of the complete
candidate. In particular, agent selection retains its known-agent, enabled
default and nonempty enabled-set validation, and a cloud TTS room voice is
validated against its provider's declared voices. Relationships stay with those
owners under `sdlc/policy/domain-ownership`; key metadata supplies no generic
cross-key rule language.

### Migrated values and consumers

All paths in this table are cluster-scoped. Paths name the existing declaration
whose authority moves; the runtime aggregate retains its typed consumer-facing
shape. The schema owns the types and sensitivity of these fields, including
credentials nested in provider records
(`local/projects/teleclaude/policy/config-public-surface`).

| Shared declaration                                                                                                                                                                                              | Runtime consumer and application boundary                                                                                                                    |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `telegram.enabled`, `telegram.bot_token`                                                                                                                                                                        | Telegram lifecycle; master eligibility retains its existing meaning.                                                                                         |
| `discord.enabled`, `discord.token`, `discord.guild_id`                                                                                                                                                          | Discord adapter and infrastructure; generated reflection identifiers retain their integration-state owner.                                                   |
| `whatsapp.enabled`, `whatsapp.phone_number_id`, `whatsapp.access_token`, `whatsapp.webhook_secret`, `whatsapp.verify_token`, `whatsapp.business_number`, `whatsapp.template_name`, `whatsapp.template_language` | WhatsApp adapter, inbound verification and outbound template delivery.                                                                                       |
| `email.enabled`, `email.smtp_username`, `email.smtp_key`, `email.email_from`, `email.reply_to`, `email.smtp_relay`                                                                                              | SMTP delivery; its existing execution eligibility remains in force.                                                                                          |
| `agents.default`, `agents.<known-agent>.enabled`                                                                                                                                                                | Agent selection and launch policy; the derived `default_agent` is a projection. Binary presence, login and local launch prerequisites remain runtime facts.  |
| `summarizer.provider_priority`, `summarizer.openai.model`, `summarizer.openai.api_key`, `summarizer.anthropic.model`, `summarizer.anthropic.api_key`, `summarizer.google.model`, `summarizer.google.api_key`    | Cloud summary/title provider selection; the local provider remains a separate local-first capability.                                                        |
| `tts.services.openai.enabled`, `tts.services.openai.api_key`, `tts.services.openai.voices`, `tts.services.openai.discord_voice`; the same four leaves for `tts.services.elevenlabs`                             | Cloud synthesis and logical cloud voice choice. Application refreshes the TTS manager while preserving its live local mute state.                            |
| `stt.services.openai.enabled`, `stt.services.openai.api_key`                                                                                                                                                    | Cloud transcription. Applying changed credentials invalidates the cached provider client before subsequent transcription.                                    |
| `master_computer`, `ingress_computer`                                                                                                                                                                           | Named, initialization-only designations. Local `computer.is_master` and `computer.is_ingress_node` are derived comparisons with the local computer identity. |

The designation import derives each name from the existing declarations on the
contributing computers and requires exactly one established target for each
designation. The two targets may differ. Initialization preserves those targets.
An unassigned computer identity or ambiguous designation is an import refusal.
An ordinary patch keeps an initialized designation unchanged; reassignment has
no application operation in this contract. Execution applicability retains the
single-ingress and existing master contracts
(`local/projects/teleclaude/spec/feature/integration/single-ingress-webhook-termination`).

### Values retaining their existing owners

The migration is the closed list above. Remaining leaves keep their current
authority and interpretation; a family containing a shared leaf is never
relocated as a whole. This boundary follows
`sdlc/principle/design-fundamentals`.

| Retained declaration or state                                                                                                                     | Authority                                                                                                                                                                                                                               |
| ------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Other `computer` leaves, `redis.url`, `redis.password`                                                                                            | Computer identity, connection bootstrap, OS identity and local realization. Redis connection material is available before shared values are resolved.                                                                                   |
| Redis pool/socket and stream-length/TTL controls, `polling`, `hook_outbox`, `event_reliability`, `api`, `daemon`, `terminal`, `process_janitor`   | Existing transport or local runtime owner; shared storage creates no new administrative knobs.                                                                                                                                          |
| Agent `profiles`, `model_chains`, flags and launch patches                                                                                        | Existing local launch declarations, including opaque strings that can carry local paths; binaries, protocol catalog and native session/login directories retain their current owners.                                                   |
| `summarizer.local.*`                                                                                                                              | Local endpoint, local model and its credential.                                                                                                                                                                                         |
| `tts.enabled`, TTS runtime mute/provisioning state, `tts.service_priority`, `tts.events`, local-provider entries and every other TTS service leaf | Local playback, local execution preference and provider-specific configuration. Cloud backend model constants remain code-owned; unused generic cloud `model`, `params`, `cli_bin` and `instruct` fields acquire no new shared meaning. |
| `stt.enabled`, `stt.service_priority`, local-provider entries and other STT service leaves                                                        | Local transcription capability and execution preference. The cloud backend's model constant remains code-owned; its unused generic `model` and `cli_bin` fields acquire no shared behavior.                                             |
| `chiptunes`                                                                                                                                       | Local media and playback.                                                                                                                                                                                                               |
| `backup.*` and the backup job's environment                                                                                                       | Existing backup job owner. Its job-environment consumer is separate from the machine model; this delivery changes neither archive identity nor backup topology.                                                                         |
| `workflow.*`, `database_url`, project `todos.store`                                                                                               | Existing workflow/store owners and their independent deliveries. Local dispatch capacity retains its local meaning.                                                                                                                     |
| `deployment.*`                                                                                                                                    | This computer's installation and release selection.                                                                                                                                                                                     |
| `creds`, global `people`, person/company declarations, inbound-source secrets                                                                     | Existing identity or subject declaration owners. The machine legacy credential fields gain no cluster copy.                                                                                                                             |
| `remote_computers`, discovered peers, generated adapter identifiers, `load_id`                                                                    | Existing attachment hints, discovery or operational-state owners.                                                                                                                                                                       |
| `experiments`, project capabilities, jobs, checkpoints, bindings, publishing declarations, `env_allow_list`, layout and home declarations         | Existing repository or subject owners. A scope classification supplies no permission to replace their Git authority with mutable values.                                                                                                |

### Reading and editing

The kind-addressed configuration command and editor are the operator entrypoint
under `local/projects/teleclaude/spec/feature/config/kind-addressed-configuration`.
They return definitions, explicit set/unset state, the coherent subject revision
and masked values. Selecting several keys retains that one revision. Null is a
present domain value where its definition admits it; unset is absence. Clearing
a required key is refused. A read performs no initialization or persistence.

Shared reads report stored declarations independently of this computer's
execution applicability. A non-master's disabled effective adapter projection
never changes the shared declared enablement
(`local/projects/teleclaude/policy/config-public-surface`).

A patch contains explicit set and unset operations, the subject revision read
before editing, its schema identity and a caller-retained operation identity.
Omission keeps a key. An overlapping set/unset, unknown path, wrong scope,
invalid value or unsupported schema is refused before mutation. The complete
resulting candidate passes owner validation before persistence. Clearance is
decided at the target boundary under
`local/projects/teleclaude/spec/feature/identity/configuration-target-clearance`.
Failure descriptions use known definition paths and value-free findings;
rejected sensitive values and undeclared input are never echoed
(`sdlc/policy/security-awareness`).

The configuration owner conditionally commits the snapshot, fresh opaque
revision, immutable revision record, operation identity and secret-free change
record in one atomic record mutation. Its comparison covers the observed head
and schema. A stale revision changes nothing and is never silently rebased.
A matching retry of the same operation returns its recorded outcome; reusing
that identity with different intent is refused. A no-op keeps the revision and
creates no change occurrence. These invariants apply
`sdlc/policy/code-quality-practices` to the shared persistence boundary.

The response identifies the committed revision and persistence confirmation
separately from application progress. A lost reply or connection after submission
is an unconfirmed outcome, not evidence of rollback. The retained operation
identity resolves that uncertainty through the same configuration owner. An
operator restores an earlier value through a new validated revision; revision
identities are never reused, including after restoration from backup.

### Persistence and publication

Configuration records have no expiry and are protected from cache eviction.
The configured Redis deployment provides authenticated, encrypted transport,
synchronous AOF persistence and a protected off-host backup with a verified
restore path. Deployment acceptance qualifies the actual event and
configuration workload under that synchronous-AOF policy before shared values
become authoritative. Successful write
acknowledgement is evaluated under that qualified persistence contract;
uncertain outcomes retain the operation identity. Storage protection follows
`sdlc/policy/security-awareness`, and persistence failure stays explicit under
`sdlc/policy/code-quality-practices`.

The writer creates the change occurrence as part of the atomic configuration
mutation. It stages the occurrence with the writer's bootstrap identity and
verified caller facts without recursively resolving shared configuration.
A config-owned publisher recovers pending records and publishes them
through the existing event producer. It retains the same event identity and
original occurrence attributes on every attempt, marking delivery only after
stream acceptance. A crash between publication and marking can redeliver the
same occurrence. The source's durable handover follows
`local/projects/teleclaude/design/architecture/event-delivery`; consumer retry
and duplicate handling remain event-runtime behavior.

The change event names the configuration subject, schema identity, committed
revision, changed logical paths and operation identity. Its origin is none for
the cluster and the registered project for a project subject. It carries no
values, secret digests or local environment references. Application reads the
authoritative snapshot through the configuration owner; the event supplies no
consumer instruction or membership declaration
(`local/projects/teleclaude/spec/feature/event-catalog/event-envelope`).

Configuration-bound actions and startup/reconnect convergence are integration
behavior under
`local/projects/teleclaude/spec/feature/integration/event-bound-maintenance`.
Configuration acceptance never claims that those actions completed.

### Sensitive values and local projection

Sensitive shared values are stored directly under the configuration owner with
the same subject revision as related settings. Operator reads, editor answers,
outcomes, event payloads and logs reveal only masked presence. Trusted runtime
components receive resolved typed inputs through the internal configuration
capability; the operator API supplies no unmasked secret-export operation.
Sensitive-value access and transport follow
`sdlc/policy/security-awareness` within the trusted-computer operating model.

Migrated fields resolve exclusively from the shared snapshot. Local files,
checkout `.env` files and inherited process variables cannot override them.
Shared strings are final typed values and undergo no per-computer environment
expansion. A child process receives any needed generated environment snapshot
at its startup boundary under `sdlc/policy/code-quality-practices`.

Each computer composes the shared projection with genuine local values through
the configuration owner. Component-owned validation precedes activation.
Local installation absence does not rewrite shared enablement. An unavailable
source returns an unavailable snapshot result. Consumer application during that
outage follows
`local/projects/teleclaude/spec/feature/integration/event-bound-maintenance`.
Local bootstrap inspection and validation remain usable independently.

### Migration and schema compatibility

Migration uses the configuration migration list and persisted-effect owner
under `local/projects/teleclaude/policy/configuration-migrations`. The explicit
initial import inventories raw declarations and their owning environment
resolution before master applicability or effective section enablement is applied.
It compares all
contributing sources before seeding the complete candidate. Unset, false, null
and an independently declared value remain distinct. Differing values produce
a path-addressed conflict with no secret values and no automatic winner.

The import input names its contributing source documents and computer
identities; it establishes no configured fleet. An omitted source field
contributes no declaration, and a raw explicit value is compared before any
default is considered. Initialization materializes a declared default only
when no source supplies a value and the key definition permits it. Required
values without an admissible source or default are refused. Source revisions
are captured with the inventory and checked again before cleanup; a source
changed since collection is retained and reported for reconciliation under
`local/projects/teleclaude/policy/configuration-migrations`.

Initialization occurs inside the coordinated deployment's stopped-runtime
boundary. Every contributing legacy consumer is upgraded or remains stopped;
each upgraded source persists its ordered migration before starting shared
consumption. The candidate reaches Redis before any source loses a value.
Source cleanup is independently atomic per document and resumable; an
interruption after destination persistence does not claim the destination was
rolled back. Ordinary shared reads never import or select a local fallback.

The migrated declarations lose their computer-document write surface and their
local environment override path. Unrelated environment entries and native login
stores are preserved. A retained environment entry used by another owner is no
longer consulted for a migrated field. Migration reports distinguish shared
persistence, source-document outcomes and unresolved deployment prerequisites.

The shared record carries its document schema version from the same ordered
configuration migration list. Pure read-time adaptation writes nothing; the
configuration owner persists forward migration through the shared revision
transaction under
`local/projects/teleclaude/spec/feature/config/document-migration`.
The shared key-schema identity is separate from that document migration version.
Readers and writers declare their supported shared-schema identities. A writer
validates the whole candidate only against a supported head schema. A consumer
applies only a schema its repository declaration explicitly supports; unknown
compatibility is refused with no regression of its applied state. Additive
cross-version handling and retirement use
`sdlc/policy/backward-compatibility-hygiene` and
`local/projects/teleclaude/spec/feature/reconciliation/fleet-cross-version-interop`.
An older offline executable is not fenced by storing a central designation;
the deployment compatibility boundary remains a prerequisite for running it.

### Use cases

#### UC-SRS1: An administrator changes shared settings once

```gherkin
Scenario: Save one shared change
  Given an administrator has read the shared settings they intend to change
  When they save their changes together
  Then one accepted revision contains the complete validated change
  And reading those shared settings from another computer reports the same accepted revision and values
  And sensitive values remain masked in the operator view

Scenario: Preserve a competing administrator's accepted change
  Given an administrator has prepared a change from an earlier view
  And another change has been accepted since that view
  When the administrator submits their prepared change
  Then it is refused as stale without changing the accepted settings
  And the administrator can read the current view before preparing a new change
```

## Known caveats

- Project scope is represented by key definitions and subject addressing; no
  existing project runtime value migrates in this contract. Project source
  declarations remain in Git.
- Master and ingress designation changes require a separately owned transfer
  contract. This surface initializes and preserves the existing targets.
- Configuration revisions establish accepted state. A consumer's applied
  revision establishes only that consumer's completed application; external
  effects have no exactly-once guarantee from a local progress record.
- Redis deployment qualification covers the actual endpoint's transport,
  persistence, event and configuration workload, eviction and restoration
  behavior. A container image or a data
  mount alone establishes none of those acceptance results.

## See Also

- https://redis.io/docs/latest/develop/using-commands/transactions/ — storage implementation error semantics.
- https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/ — deployment persistence qualification.
