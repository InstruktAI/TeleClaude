---
description: 'Multi-version storage of workflow Artifacts — every write appends a new version keyed by SHA256 digest, the current pointer updates in place, diffs are computed between digests, and remove cascades version history.'
visibility: 'public'
---

# Workflow Artifact Versioning — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md
- @docs/project/spec/domain/workflow.md

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

### Write authority

<!-- planned-change:bug-lane-splits-evidence-from-diagnosis -->

Prepare-artifact writes (`input`, `prd`, `architecture`, `diagnosis`,
`implementation-plan`) never bind the slug's `active_runner`: authoring is not a
claim and acquires nothing. A write is nonetheless gated on the slug's claim —
its `active_runner`. The write is permitted only when the caller is the slug's
live `active_runner`, or the slug has no live claim (no `active_runner`, or one
that names a session no longer live); it is refused as a claim conflict (HTTP 409)
when the `active_runner` names a live session other than the caller. `active_runner`
itself is set only by lifecycle-machine invocation (the dispatch / driver-start
path), where lifecycle ownership is taken. Successive writes by the claimant, or
writes to an unclaimed slug, append digest-keyed content-addressed versions; the
claim gate governs only whether a foreign session may write at all, and a stuck or
erroneous claim is cleared through the unclaim path, never by weakening the gate.

<!-- change:bug-lane-splits-evidence-from-diagnosis -->

Prepare-artifact writes (`input`, `prd`, `architecture`, `investigation`,
`diagnosis`, `implementation-plan`) never bind the slug's `active_runner`:
authoring is not a claim and acquires nothing. A write is nonetheless gated on the
slug's claim — its `active_runner`. The write is permitted only when the caller is
the slug's live `active_runner`, or the slug has no live claim (no `active_runner`,
or one that names a session no longer live); it is refused as a claim conflict
(HTTP 409) when the `active_runner` names a live session other than the caller.
`active_runner` is set by lifecycle-machine invocation (the dispatch /
driver-start path), where lifecycle ownership is taken, and it moves with the write
turn when a phase hands authorship to a dispatched session: the bug lane's
diagnosis author holds the claim for its turn, which excludes the driving session
while it does. The claim therefore names exactly one writer at every moment, with
no unowned interval between owners. Successive writes by the claimant, or writes to
an unclaimed slug, append digest-keyed content-addressed versions; the claim gate
governs only whether a foreign session may write at all, and a stuck or erroneous
claim is cleared through the unclaim path, never by weakening the gate.

<!-- /planned-change:bug-lane-splits-evidence-from-diagnosis -->

The write path resolves the caller's identity, with parity to the stamp and
artifact-remove boundaries, and records the resolved principal as `updated_by`.

<!-- planned-change:bug-lane-splits-evidence-from-diagnosis -->

Independently of which session is driving the slug, a prepare artifact is writable
only by a prepare-phase writer: a prepare-orchestrator session, a human-identity
session, or a roleless session — a TeleClaude session that carries no job role,
the shape of a human-originated, operator-driven session. A session that carries a
non-prepare job role — a work orchestrator, a create orchestrator, the integrator,
or any worker — is refused by role with HTTP 403. An unregistered session id is an
unknown caller and is refused with HTTP 403. This role gate is authorization, not a
claim: it does not consult or alter the slug's holder. The write boundary does not
enforce the convention that a work-phase defect in a prepare artifact is routed
back through prepare.

<!-- change:bug-lane-splits-evidence-from-diagnosis -->

Independently of which session is driving the slug, a prepare artifact is writable
only by a prepare-phase writer: a session carrying one of the prepare-authoring job
roles, a human-identity session, or a roleless session — a TeleClaude session that
carries no job role, the shape of a human-originated, operator-driven session. The
prepare-authoring roles are the ones the prepare lifecycle confers on a session that
derives a prepare artifact: the prepare orchestrator and the intake, architecture,
diagnosis, and planning authors. A session that carries a non-prepare job role — a
work orchestrator, a create orchestrator, the integrator, or any worker — is refused
by role with HTTP 403. An unregistered session id is an unknown caller and is refused
with HTTP 403. This role gate is authorization, not a claim: it does not consult or
alter the slug's holder, so a prepare-authoring role still faces the claim gate above.
The write boundary does not enforce the convention that a work-phase defect in a
prepare artifact is routed back through prepare.

<!-- /planned-change:bug-lane-splits-evidence-from-diagnosis -->

Work artifacts (`review-findings`, `deferrals`, `quality-checklist`)
carry no claim gate.

#### UC-WAV9: Worker write to a prepare artifact is refused by role

```gherkin
Given a worker session that carries a non-prepare job role
When the worker attempts to write a prepare artifact (input, prd, architecture, diagnosis, or implementation-plan)
Then the workflow service refuses the write by role with HTTP 403, before any state mutation
And the artifact's current version is unchanged
```

#### UC-WAV10: Write to a slug whose live active_runner is a different session is refused

```gherkin
Given a slug whose active_runner names a different live session
When a prepare-phase writer that is not that active_runner writes a prepare artifact for that slug
Then the workflow service refuses the write as a claim conflict with HTTP 409, before any state mutation
And the artifact's current version is unchanged
And the slug's active-runner is unchanged
```

#### UC-WAV11: Write to a prepare artifact is accepted and acquires no claim

```gherkin
Given a slug with no live holder
When a session writes a prepare artifact
Then the workflow service accepts the write
And records the resolved caller principal as updated_by
And the slug acquires no live active-runner
```

#### UC-WAV12: Artifact write records the resolved principal

```gherkin
Given a permitted prepare-artifact write
When the workflow service persists the new version
Then updated_by is the resolved caller principal, not a constant placeholder
```

#### UC-WAV15: A work-orchestrator write to a prepare artifact is refused by role

```gherkin
Given a live work-orchestrator session
When it attempts to write a prepare artifact for any slug at any lifecycle phase
Then the workflow service refuses the write by role before any state mutation
And the response status is HTTP 403
And the artifact's current version is unchanged
```

#### UC-WAV16: A human-identity write to an unheld slug is accepted without acquiring a claim

```gherkin
Given a slug with no live holder
When a direct human-identity session writes a prepare artifact
Then the workflow service accepts the write
And records the resolved human principal as updated_by
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

#### UC-WAV20: A write by a session bound to a different slug is accepted

```gherkin
Given a caller whose TeleClaude session is already bound to a different slug
When the caller writes a prepare artifact for this slug
Then the workflow service accepts the write and appends a new version
And this slug's active-runner is unchanged
And the response is not a conflicting-session-binding refusal
```

#### UC-WAV22: The claimant's own write to its claimed slug is accepted

```gherkin
Given a slug whose live active_runner is the caller's own session
When the caller writes a prepare artifact for that slug
Then the workflow service accepts the write and appends a new version
And the slug's active-runner is unchanged
```

### Cross-context references

- `integration` — drift analysis reads each artifact's `codebase_sha_at_write` and `referenced_paths` from the Todo's lifecycle state (not from the artifact record) to detect codebase drift since the artifact was authored.
- `workflow` (state machines) — artifact presence and digests drive lifecycle phase readiness (e.g., a non-empty `prd` digest advances the prepare state machine out of intake).

## Known caveats

- The `codebase_sha_at_write` and `referenced_paths` fields live on the Todo's lifecycle state, not on the artifact records. The artifact records intentionally stay narrow (content + digest + audit columns); provenance is a Todo-lifecycle-state concern refreshed by the single workflow provenance boundary only for the lifecycle-relevant artifact kinds (`input`, `prd`, `requirements`, `architecture`, `implementation-plan`).

- The `input` artifact follows the claim-free prepare-artifact write rule (see Write authority), and `telec todo artifacts remove input` is unconditionally rejected. A holder's retained `input` artifact is also frozen by the holder invariant: it remains readable as split source material, but write/remove paths refuse all holder artifact mutations.

- The `bug` artifact kind is retained only for legacy read/remove compatibility after bug content moved to the universal `input` artifact. API and CLI write boundaries refuse `bug` as retired read-only.
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
