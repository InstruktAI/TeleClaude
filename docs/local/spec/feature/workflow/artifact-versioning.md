---
description: 'Multi-version storage of workflow Artifacts — every write appends a new version keyed by SHA256 digest, the current pointer updates in place, diffs are computed between digests, and remove cascades version history.'
visibility: 'public'
---

# Workflow Artifact Versioning — Spec

## What it is

The Artifact aggregate inside the `workflow` bounded context persists every Artifact write (PRD, architecture, implementation-plan, etc.) as a content-addressed version. Each write computes the SHA256 digest of the content, appends a new version record, and updates the current-version pointer in place. Previous versions remain addressable by digest so the workflow service can render unified diffs between any two versions on demand.

Artifact provenance — the `origin/main` SHA at write time (captured via the workflow's origin-main-sha helper, never local HEAD) and the workspace paths referenced by the artifact body — is captured alongside the digest, but it is stored on the Todo's lifecycle state (the artifact lifecycle stamp), not on the artifact version itself. The artifact records stay narrow: id, slug, name, content, digest, updated_by, timestamps. The lifecycle stamp is the carrier of the extended drift-evidence fields (`upstream_digests`, `owned_snippet_digests`, `referenced_snippet_digests`, `produced_at`) — see `@spec/feature/workflow/drift-detection` for their per-class semantics and the single workflow provenance boundary that populates them.

Removal of an artifact deletes both the current record and the full version history atomically. Artifact kinds are enumerated; the canonical list is enforced at the workflow boundary before any state mutation. Each artifact kind is unique per Todo (one `prd` per slug, one `implementation-plan` per slug, etc.).

## Canonical fields

### Use cases

```
Given an active todo "my-feature" with no prd artifact
When an agent runs "telec todo artifacts write my-feature prd '<content>'"
Then the workflow service computes the SHA256 digest of the content
And appends a new version tagged with the digest, slug, name, content, updated_by, created_at
And updates the current pointer to the new content + digest + updated_at
And refreshes the codebase_sha_at_write and referenced_paths stamps on the todo's lifecycle state
```

```
Given an active todo with an existing prd artifact at digest D1
When an agent writes a second prd revision producing digest D2
Then the workflow service appends a new version for D2 without mutating the D1 version
And the current pointer advances to D2
And "telec todo artifacts read my-feature prd" returns the D2 content
And both D1 and D2 remain individually addressable for diff
```

```
Given an artifact has two versions with digests D1 and D2
When an agent runs "telec todo artifacts diff my-feature prd <D1> <D2>"
Then the workflow service loads both version bodies by digest
And returns a unified diff with headers "prd@<D1[:12]>" and "prd@<D2[:12]>"
And returns the empty string when D1 == D2 (after confirming the digest exists)
```

```
Given an agent runs "telec todo artifacts diff" with a digest the artifact never had
When the workflow service looks up the digest
Then it refuses the request with a not-found error citing the unknown digest
```

```
Given a todo has an architecture artifact with several historical versions
When an agent runs "telec todo artifacts remove my-feature architecture"
Then the workflow service deletes the current record and every version for (id, "architecture") atomically
And the response reports removed=true plus the versions_deleted count
And subsequent reads return empty content; subsequent diffs raise a not-found error
```

```
Given an agent attempts "telec todo artifacts write my-feature unknown-kind ..."
When the workflow service validates the artifact name against the canonical list
Then it rejects the call with "Unknown artifact name" and the canonical list before any state mutation
```

#### UC-WAV7: API refuses retired artifact writes

```gherkin
Given a known legacy artifact kind is retained for read/remove compatibility
When an agent attempts to write that retired artifact kind through the workflow API
Then the workflow service rejects the call as retired read-only before any state mutation
```

#### UC-WAV8: CLI refuses retired artifact writes

```gherkin
Given a known legacy artifact kind is retained for read/remove compatibility
When an agent attempts to write that retired artifact kind through telec todo artifacts write
Then the CLI rejects the request as retired read-only before calling the workflow API
And the writable kind list excludes the retired artifact kind
```

```
Given a todo whose entry status is delivered
When an agent attempts to write any artifact for that slug
Then the workflow service refuses with a "delivered (read-only)" error
```

#### UC-WAV19: log artifact round-trips and reads empty before its first write

```gherkin
Given an active "kind=task" todo with no log artifact
When an agent reads the log artifact for that todo
Then the workflow service returns empty content without a kind-validation error
When the agent writes a log artifact with a dated continuity entry
Then the workflow service accepts the write and appends a new version
And a subsequent read of the log returns the written content
```

#### UC-WAV24: Diff refuses a malformed digest distinctly from an unknown digest

```gherkin
Given an agent runs "telec todo artifacts diff" with a digest argument that is not a 64-character hexadecimal string
When the workflow service validates the request
Then it refuses the request as malformed input, citing the expected digest shape and the received value
And the refusal is distinct from the not-found refusal for a well-formed digest the artifact never had
```

#### UC-WAV27: Removing a holder's artifact is refused as a holder mutation

```gherkin
Given a todo that is a structural holder with grouped children and retained artifacts
When an agent removes one of that holder's artifacts through "telec todo artifacts remove"
Then the workflow service refuses the removal with the holder refusal, which names the frozen-artifact rule
And the refusal is distinct from the not-found refusal for a slug with no todo
And the holder's artifacts and their version history are unchanged
```

### Write authority

Artifact writes consult the slug's claim. A todo whose `active_runner` names a
live session is claimed, and every writable artifact kind on it is writable only
by that claim's group: the holding session and every session it dispatched,
transitively through `initiator_session_id`. A todo with no `active_runner`, or
one naming a session that is no longer live, is unclaimed and carries no claim
gate. Reads are never gated.

A caller outside the claiming group is refused with HTTP 409 before any state
mutation. The refusal names the holding session and the sanctioned door: address
that session, which owns whether the concern changes its work
(`sdlc/policy/todo-creation-discipline`, "Reconcile a flagged
live todo"). A foreign caller never writes into a claimed todo's record.

A direct human-identity writer — a login-resolved human principal carrying no
agent session id — is not a session and is not gated by the claim. The
prepare-stage human write authority is unchanged.

Artifact authorship is not lifecycle ownership: an accepted write neither
acquires, moves, nor releases the todo claim. `active_runner` remains exclusively
the lifecycle orchestrator's todo claim while the workers it dispatched author
prepare artifacts. The bug lane therefore keeps the prepare driver as claimant
through peer dispatch, diagnosis authorship and revision, interrogation, and
settlement; the diagnosis peer writes as a member of the driver's claiming group
and receives no todo claim, delegated ownership, artifact lease, expiry window,
or liveness fallback. Every accepted write follows the ordinary version-append,
`updated_by`, provenance, and digest-bound invalidation consequences while
leaving `active_runner` unchanged.

<!-- planned-change:local-operator-identity -->

The write path resolves the caller's identity, with parity to the stamp and
artifact-remove boundaries, and records the writing session's id as `updated_by`.
A caller that is no session authors under no session and records nothing there;
an unidentified caller may not write at all.

<!-- change:local-operator-identity -->

The write path resolves the caller's identity, with parity to the stamp and
artifact-remove boundaries, and records the writing session's id as `updated_by`.
A caller that is no session, the computer's operator `system:operator` included
(`local/projects/teleclaude/spec/identity-and-auth` §2), authors under no session
and records nothing there; a session the platform keeps for the operator's agent
writes as that session. A caller whose session identity document names no
admissible session may not write at all.

<!-- /planned-change:local-operator-identity -->

Independently of which session is driving the slug, a prepare artifact is writable
only by a prepare-phase writer: a caller whose reach, as the role catalog resolves
it (`local/projects/teleclaude/spec/feature/identity/agent-roles`), includes the
`prepare-artifact-write` capability, or a direct human-identity writer, which
carries no session. A session the catalog does not admit is refused with HTTP 403;
the refusal names the recorded role and the capability, and states that a focused
session's write belongs to the session that dispatched it. The write boundary keeps
no role list of its own. An unregistered session id is an unknown caller and is
refused with HTTP 403.

A prepare artifact of a todo whose contract is under execution — its lifecycle phase
is one of the work lane's, from build started through finalize ready — is writable
by no caller, the direct human-identity writer included. The write is refused with
HTTP 409 before any state mutation, naming the phase and the door that reopens the
contract: the todo's work orchestrator returns it to preparation with
`telec todo stamp <slug> --kickback --reason <why>`, so any other caller addresses
the session that holds the todo; the prepare lane's next call then moves the todo
out of the work lane. A delivered todo stays read-only for every artifact kind.

These gates read the object and the catalog, not the slug's holder, and compose with
the claim gate above. The claim gate decides first: a caller outside the claiming
group is refused as a claim conflict whatever its role. The closed-contract refusal
applies next, to every caller the claim gate admitted, and the capability refusal
last.

Work artifacts (`review-findings`, `deferrals`, `quality-checklist`) carry no
prepare-artifact capability or closed-contract gate. Like every other writable kind,
they are gated by the claim.

The `check-failures` artifact is platform-written. The API and CLI write and
remove boundaries refuse it as platform-owned read-only for every caller, before
any state mutation, and the CLI's writable kind list excludes it. Only the
workflow's failed-check filer writes it, through the workflow store in its own
process and under no session, so the claim gate never applies to it. Reads are
not gated. What it records is
`local/projects/teleclaude/spec/feature/workflow/failed-check-bugs`.

#### UC-WAV9: Worker write to a prepare artifact is refused by role

#### UC-WAV10: A dispatched worker writes while the orchestrator that dispatched it holds the todo

```gherkin
Given a prepare-stage todo is owned by its lifecycle orchestrator
And a registered worker the orchestrator dispatched is authorized to author the current prepare artifact
When that worker writes the artifact
Then the workflow accepts the write and appends a new version
And records the worker as the artifact principal
And lifecycle ownership remains with the orchestrator
```

#### UC-WAV11: Write to a prepare artifact is accepted and acquires no claim

```gherkin
Given a slug with no live holder
When a session writes a prepare artifact
Then the workflow service accepts the write
And records that session's id as updated_by
And the slug acquires no live active-runner
```

#### UC-WAV12: Artifact write records the writing session

```gherkin
Given a permitted prepare-artifact write
When the workflow service persists the new version
Then updated_by is the writing session's id
And a write from a caller that is no session records no updated_by
```

#### UC-WAV26: The artifact listing names each artifact's writers

```gherkin
Given a slug holding an artifact whose versions were written by more than one session
And an artifact with no version history
When a caller lists that slug's artifacts
Then every stored artifact is listed
And each artifact carries the distinct session ids recorded as updated_by across its versions
And an artifact whose versions recorded no writer carries none
```

#### UC-WAV15: A work-orchestrator write to a prepare artifact is refused by role

#### UC-WAV16: A human-identity write to an unheld slug is accepted without acquiring a claim

```gherkin
Given a slug with no live holder
When a direct human-identity session writes a prepare artifact
Then the workflow service accepts the write
And records no updated_by, the writer being no session
And the slug acquires no live active-runner
```

#### UC-WAV21: Two concurrent writers each append a version and neither acquires a claim

```gherkin
Given a slug with no live holder
And two prepare-phase writers writing a prepare artifact at the same time
When both writes are processed
Then the workflow service accepts both as successive content-addressed versions
And neither write is refused as a claim conflict
And the slug acquires no live active-runner
```

#### UC-WAV20: A write by a session outside the claiming group is refused

```gherkin
Given a slug whose live active_runner names a session the caller neither is nor was dispatched by
When the caller writes any artifact kind for that slug
Then the workflow service refuses the write as a claim conflict with HTTP 409, before any state mutation
And the refusal names the holding session and the door that addresses it
And the artifact's current version is unchanged
And this slug's active-runner is unchanged
```

#### UC-WAV22: The claimant's own write to its claimed slug is accepted

```gherkin
Given a slug whose live active_runner is the caller's own session
When the caller writes a prepare artifact for that slug
Then the workflow service accepts the write and appends a new version
And the slug's active-runner is unchanged
```

#### UC-WAV23: A human-owner write to a claimed prepare-stage slug is accepted

```gherkin
Given a todo in the prepare stage whose active_runner names a different live session
When the human owner (login-resolved human email and role, no agent session id, no system role) writes a prepare artifact for that slug
Then the workflow service accepts the write and appends a new version
And records no updated_by, the writer being no session
And the slug's active-runner is unchanged
```

### Cross-context references

#### UC-WAV25: Every review pass advances its report artifact version

```gherkin
Given a preparation or build reviewer completes a pass with findings or with a clean verdict
When the reviewer writes the phase-specific report before stamping
Then the workflow appends a report artifact version with its SHA256 digest, updated_by principal, and timestamp
And the current report pointer advances to that pass, even when an older report already exists
And the verdict stamp binds the current report digest rather than inferring evidence from report content or transcript state
```

- `integration` — drift analysis reads each artifact's `codebase_sha_at_write` and `referenced_paths` from the Todo's lifecycle state (not from the artifact record) to detect codebase drift since the artifact was authored.
- `workflow` (state machines) — artifact presence and digests drive lifecycle phase readiness (e.g., a non-empty `prd` digest advances the prepare state machine out of intake).

## Known caveats

- The `codebase_sha_at_write` and `referenced_paths` fields live on the Todo's lifecycle state, not on the artifact records. The artifact records intentionally stay narrow (content + digest + audit columns); provenance is a Todo-lifecycle-state concern refreshed by the single workflow provenance boundary only for the lifecycle-relevant artifact kinds (`input`, `prd`, `requirements`, `architecture`, `implementation-plan`).

- The `input` artifact follows the claim-free prepare-artifact write rule (see Write authority), and `telec todo artifacts remove input` is unconditionally rejected. A holder's retained `input` artifact is also frozen by the holder invariant: it remains readable as split source material, but write/remove paths refuse all holder artifact mutations.

- The `bug` artifact kind is retained only for legacy read/remove compatibility after bug content moved to the universal `input` artifact. API and CLI write boundaries refuse `bug` as retired read-only.

- The `investigation` artifact kind is retained only for legacy read/remove compatibility;
  a bug's evidence and its causal conclusion are one artifact. API and CLI write boundaries
  refuse `investigation` as retired read-only, so legacy records keep their readable trail.

- Diff lookup is digest-keyed, not chronological — callers must already know the two digests. The artifact-versions listing is the source for valid digests.
- Removing an artifact is destructive: the full version history is lost atomically. There is no undo.
- `telec todo update --kind ... --force` may remove orphaned kind-specific
  artifacts as part of a pre-build kind
  migration. Those removals use the same destructive artifact-remove semantics:
  the current artifact row and full version history are deleted atomically. The
  seeded `change -> task` exception folds an initial `implementation-plan` into
  `input` before removing the plan when the only artifacts are `input` and
  `implementation-plan`.
- Artifact writes against a delivered todo are blocked to keep delivered todos read-only.

- The CLI write path constructs the `codebase_sha_at_write` and `referenced_paths` request body by calling the workflow's origin-main-sha helper (the canonical drift anchor per `@spec/feature/workflow/drift-detection`) and the referenced-paths extractor against the invocation cwd; the workflow service uses those if supplied, otherwise recomputes them via the same helper.

- `list_artifacts` returns names only; version metadata (digest, timestamps) requires a follow-up `artifact_versions` call.

## See Also

- docs/local/adr/0096-claimed-todo-artifacts-are-writable-only-by-the-claiming-group.md — why a claimed todo's artifacts are writable only by the claiming group, and why the claim gate decides before the role gate.

- docs/local/adr/0149-prepare-artifact-write-authority-is-a-catalog-capability.md — why a prepare artifact's writer is admitted by a catalog capability rather than a role list the write boundary keeps.
- docs/local/adr/0151-prepare-artifacts-close-while-their-contract-is-under-execution.md — why a contract under execution closes the prepare artifacts to every caller.
