---
description: 'Drift analysis phase. Classify each pending prepare-artifact drift across the six drift classes (code, upstream-artifact, owned-snippet, upstream-snippet, dependency-graph, age) as cosmetic or substantive and stamp the verdict so the lifecycle can continue or re-derive the affected layer.'
domain: 'software-development'
id: 'software-development/procedure/lifecycle/prepare/drift-analyze'
scope: 'domain'
type: 'procedure'
visibility: 'public'
status: 'target'
delivered_by:
  - drift-detection-consolidation
---

# Drift Analyze — Procedure

## Goal

Classify each pending prepare-artifact drift across every applicable drift
class. Stamp `cosmetic` when the artifact remains valid despite the
evidence change. Stamp `substantive` when the artifact must be re-derived
to match current reality. The same procedure handles drift dispatched from
the prepare BLOCKED branch AND drift dispatched from the work-entry bounce
to prepare — the procedure does not care which entry point routed the
worker; it reads the pending classes per artifact and stamps verdicts.

## Preconditions

- The prepare state machine reported one or more artifacts with a
  collapsed `drift.<artifact>` status of `pending` and recommended this
  worker. The orchestrator script names the pending classes per artifact.
- The slug is active and not delivered.

## Steps

### 1. Identify pending artifacts and pending classes

Read the prepare state machine output (or `telec todo show {slug}`) to
enumerate which artifacts are pending drift review and, for each, which
classes are pending. The collapsed per-artifact status is the
most-blocking class status; the analyzer must consider every pending
class, not only the one that drove the collapse.

The six drift classes:

- **code** — `codebase_sha_at_write` vs current `origin/main` HEAD,
  scoped to `referenced_paths`.
- **upstream-artifact** — `upstream_digests` (persisted-state field
  name; aka `upstream_artifact_digests` in spec/documentation) vs
  current digest of each named upstream artifact.
- **owned-snippet** — `owned_snippet_digests` vs current digest of each
  snippet the Todo owns via its `delivered_by` membership at write time.
- **upstream-snippet** — `referenced_snippet_digests` vs current digest
  of each non-owned snippet the artifact references by validator-
  accepted inline reference extraction (`@<HOME>/.teleclaude/docs/...`
  for global snippets, `@docs/...` for project snippets — per
  `teleclaude/resource_validation/_snippet.py:124`), mapped to
  canonical snippet IDs.
- **dependency-graph** — `dependency_set_at_write` vs the Todo's current
  **immediate** `after` set and each direct dep's roadmap status.
  Shallow only — not transitive.
- **age** — `produced_at` vs the artifact-kind's configured freshness
  window (policy-driven; disabled when unset).

### 2. For each pending (artifact, class)

- Read the artifact: `telec todo artifacts read {slug} <artifact>`.
- Read the recorded provenance for the class from `telec todo show {slug}`.
- Inspect the evidence change scoped to the artifact:
  - **code** — `git fetch origin main` then
    `git log <codebase_sha_at_write>..origin/main -- <referenced-paths>`
    and `git diff <codebase_sha_at_write>..origin/main -- <referenced-paths>`.
    Always compare against `origin/main`, never local HEAD, so the
    derivation matches the write-time anchor captured by
    `get_origin_main_sha(cwd)`.
  - **upstream-artifact** — read the named upstream artifact at its
    current digest (`telec todo artifacts read {slug} <upstream>`) and
    compare to the recorded digest's content. The state machine has
    already detected the digest mismatch; the analyzer's job is to read
    the upstream change and judge whether THIS artifact's claims still
    hold.
  - **owned-snippet** — read each owned snippet at its current digest
    (`telec docs get <snippet-id>`) and compare to the recorded digest's
    content. A sibling delivery may have edited a snippet this todo owns
    via `delivered_by`; judge whether the edit changes anything THIS
    artifact relies on.
  - **upstream-snippet** — read each referenced non-owned snippet at its
    current digest (`telec docs get <snippet-id>`) and compare. Judge
    whether the referenced snippet's edit changes the contract THIS
    artifact references.
  - **dependency-graph** — compare the recorded `dependency_set_at_write`
    to the Todo's current **immediate** `after` set (added/removed deps)
    and each direct dep's roadmap status flips (e.g., HELD → DELIVERED).
    Shallow only — do NOT resolve a transitive closure; deep transitive
    changes are surfaced upward by each direct dep's own drift detection
    when that dep is itself prepared. Judge whether the dep-graph change
    affects the artifact's plan or claims.
  - **age** — the artifact has aged past its configured freshness window.
    Re-ground against current code/snippets/deps and judge whether the
    artifact still holds; an aged artifact whose claims happen to remain
    accurate is `cosmetic`, an aged artifact whose grounding has drifted
    is `substantive`.
- Apply the verdict rubric:
  - **`cosmetic`** — the artifact's intent and claims still hold. The
    evidence change is real but does not invalidate this artifact.
    Examples: rename/refactor that preserves behavior; constants
    extraction; formatting; an upstream snippet's `delivered_by`
    frontmatter churn that did not change the body; a dep delivering
    without affecting this artifact's plan tasks.
  - **`substantive`** — the artifact's claims are now wrong, its
    referenced surfaces no longer exist as described, or its grounding
    no longer matches reality. The artifact's owning layer must
    re-derive.

### 3. Stamp the verdict per artifact

Stamping is per-artifact, not per-(artifact, class). The CLI signature
is unchanged:

```bash
telec todo stamp {slug} --drift-reviewed <artifact> cosmetic <reason>
# or
telec todo stamp {slug} --drift-reviewed <artifact> substantive <reason>
```

The reason text MUST name each class evaluated and what was found:
"code: cosmetic — rename of `foo()` to `bar()` preserves the call
contract the plan references. upstream-snippet: cosmetic — the
referenced domain spec gained a clarifying paragraph that does not
change the contract the architecture depends on." The reason is the
audit trail per class for the per-artifact stamp.

When ANY class for an artifact is `substantive`, the overall verdict
for that artifact is `substantive` — substantive on any class clears the
review verdict for the artifact and every downstream artifact's review
verdict per the spec's re-derivation contract. Only when EVERY pending
class is cosmetic does the artifact get a `cosmetic` stamp.

The state-stamping boundary captures the **evidence anchor** at stamp
time automatically (`head_sha_at_review`, `upstream_digests_at_review`,
`snippet_digests_at_review`, `dep_set_at_review`). The analyzer does not
pass these as flags; they are read from current state by
`_apply_drift_reviewed_stamp` and persisted on the `DriftReviewedStamp`.
A cosmetic verdict at this anchor expires lazily on a future derivation
if evidence has moved past the anchor on any anchored dimension; the
analyzer is re-dispatched at that point. A substantive verdict does not
need lazy expiry — re-derivation produces a fresh artifact whose write
clears the drift stamps.

### 4. Go idle

After every pending artifact has a stamp, end the worker turn. The
dispatching session re-enters the state machine and acts on the new
state.

## Outputs

- One `--drift-reviewed <artifact> cosmetic|substantive <reason>` stamp
  per pending artifact, with the reason naming each class evaluated and
  its per-class finding.

## Discipline

Classify drift only. Do not rewrite prepare artifacts, do not approve
gates, do not start build work. The artifact's owning procedure
(intake, architecture, plan) re-derives substantive drift when the
dispatching session re-enters the state machine.

A `cosmetic` verdict must be grounded in the actual evidence change for
EVERY pending class, not assumed. If any pending class cannot be cleanly
classified — provenance unreadable, upstream digest unresolvable,
referenced snippet not found, baseline SHA missing — stamp `substantive`
and let the owning layer re-derive.

The same per-class evaluation discipline applies whether the analyzer
was dispatched from the prepare BLOCKED branch or from a work-entry
bounce. The work-entry path produces no separate verdict semantics — it
is the same stamp on the same artifact, evaluated against the same
evidence.

## Recovery

- If a referenced path cannot be read (deleted, renamed without rename
  detection), stamp `substantive` on the code class and explain in the
  reason — the owning layer must re-derive against the new reality.
- If a baseline SHA cannot be resolved (history rewrite, missing
  object), stamp `substantive` — provenance cannot be verified.
- If a referenced upstream artifact's recorded digest cannot be matched
  against any current artifact version (e.g., the upstream was rewritten
  multiple times since the recorded digest), stamp `substantive` on
  upstream-artifact — the chain must re-derive.
- If a referenced snippet ID no longer resolves (`telec docs get` errors
  or the snippet was removed), stamp `substantive` on
  upstream-snippet — the artifact's grounding is now incomplete.
- If a dep slug no longer exists in the roadmap, stamp `substantive` on
  dependency-graph — the artifact's dep assumptions are invalid.
- If the project's age window for the artifact kind is unset (`0` or
  absent), the age class is disabled and does not appear in the
  pending-class set; do not stamp on it.

## See Also

- ~/.teleclaude/docs/software-development/policy/regression-zero-tolerance.md
- ~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/overview.md
