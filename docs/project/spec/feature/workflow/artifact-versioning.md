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

### Write authority

Prepare-artifact writes (`input`, `prd`, `architecture`, `diagnosis`,
`implementation-plan`) are gated on the slug's live holder — the same signal the
driver-start dedup uses (a live orchestrator bound to the slug, or a live
active-runner recorded for it). A write is refused only when a different live
session holds the slug; the refusal is a claim conflict naming the holder,
returned as HTTP 409. When no live session holds the slug, the write is accepted
and records the writing session as the slug's live active-runner. The claim is
scoped to the life of the holding session; when that session ends the slug has no
live holder.

The write path resolves the caller's identity, with parity to the stamp and
artifact-remove boundaries, and records the resolved principal as `updated_by`.
A write from any session other than the live holder — including a dispatched
worker that shares the slug — is a claim conflict. The write boundary does not
enforce the convention that a work-phase defect in a prepare artifact is routed
back through prepare. Work artifacts (`review-findings`, `deferrals`,
`quality-checklist`) carry no claim gate.

#### UC-WAV9: Worker write to a held slug is refused as a claim conflict

```gherkin
Given a slug held by a live orchestrator session
And a worker session that shares the slug
When the worker attempts to write a prepare artifact (input, prd, architecture, diagnosis, or implementation-plan)
Then the workflow service refuses the write as a claim conflict naming the holder before any state mutation
And the response status is HTTP 409
And the artifact's current version is unchanged
```

#### UC-WAV10: Write to a slug held by a different live session is refused

```gherkin
Given a slug held by a live session
When a different session attempts to write a prepare artifact
Then the workflow service refuses the write as a claim conflict naming the holder before any state mutation
And the response status is HTTP 409
```

#### UC-WAV11: Write to an unheld slug is accepted and records the writer as live holder

```gherkin
Given a slug with no live holder
When a session writes a prepare artifact
Then the workflow service accepts the write
And records the writing session as the slug's live active-runner
And records the resolved caller principal as updated_by
```

#### UC-WAV12: Artifact write records the resolved principal

```gherkin
Given a permitted prepare-artifact write
When the workflow service persists the new version
Then updated_by is the resolved caller principal, not a constant placeholder
```

#### UC-WAV13: A write-acquired holder is honored by the driver-start dedup

```gherkin
Given a session that wrote a prepare artifact for a previously unheld slug
When an orchestrator-class driver-start for that slug is attempted while the writer is live
Then the driver-start is refused as a conflict naming the holder
```

#### UC-WAV14: The write-acquired claim releases when the holding session ends

```gherkin
Given a slug whose live holder is a session that acquired it by writing
When that session ends
Then the slug has no live holder
And another session may write a prepare artifact and become the holder
```

#### UC-WAV15: Work-orchestrator write to a prepare artifact is refused by role

```gherkin
Given an active todo whose work-orchestrator session is bound to the slug
When the work orchestrator attempts to write a prepare artifact at any lifecycle phase
Then the workflow service refuses the write as an authorization denial by role before any state mutation
And the refusal is independent of whether the work orchestrator holds the slug
```

#### UC-WAV16: Human-identity write to an unclaimed slug is accepted without claiming

```gherkin
Given a slug with no live session driving it
When a direct human-identity session writes a prepare artifact
Then the workflow service accepts the write
And records the resolved human principal as updated_by
And the slug acquires no driver
```

### Cross-context references

- `integration` — drift analysis reads each artifact's `codebase_sha_at_write` and `referenced_paths` from the Todo's lifecycle state (not from the artifact record) to detect codebase drift since the artifact was authored.
- `workflow` (state machines) — artifact presence and digests drive lifecycle phase readiness (e.g., a non-empty `prd` digest advances the prepare state machine out of intake).

## Known caveats

- The `codebase_sha_at_write` and `referenced_paths` fields live on the Todo's lifecycle state, not on the artifact records. The artifact records intentionally stay narrow (content + digest + audit columns); provenance is a Todo-lifecycle-state concern refreshed by the single workflow provenance boundary only for the lifecycle-relevant artifact kinds (`input`, `prd`, `requirements`, `architecture`, `implementation-plan`).
- The `input` artifact follows the claim-conflict write rule (see Write authority), and `telec todo artifacts remove input` is unconditionally rejected. A holder's retained `input` artifact is also frozen by the holder invariant: it remains readable as split source material, but write/remove paths refuse all holder artifact mutations.
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
