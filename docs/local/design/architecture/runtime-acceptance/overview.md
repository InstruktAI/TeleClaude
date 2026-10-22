---
description: Hosted job isolation and exact-candidate artifact handoff for the single runtime acceptance harness.
visibility: internal
delivered_by:
  - issue-128
---

# Hosted Runtime Acceptance — Design

## Purpose

Compose the runtime-acceptance controller with the existing hosted CI and release
artifact paths. Agent runtime owns the public-journey report and application
cleanup; release owns candidate identity, job ordering and publication eligibility.
The contracts are `local/projects/teleclaude/spec/feature/agent_runtime/runtime-acceptance`
and `local/projects/teleclaude/spec/feature/release/publication`. Reusing the
hosted job boundary follows `sdlc/policy/substrate-anchoring`; evidence remains
subject to `general/principle/verification-independence`.

## Inputs/Outputs

- The checked source or immutable release candidate supplies its commit/tree and
  the existing dependency and installation inputs.
- The controller consumes the independently reviewed public journeys and emits
  one source-bound report with command, scenario and cleanup outcomes.
- Workflow artifacts carry only the named candidate, report and sanitized
  diagnostics, addressed by their recorded identities and digests.
- A downstream release job consumes the candidate and full report together.
  Successful runtime acceptance does not replace the full installation proof.

## Invariants

The standard hosted Ubuntu VM is the full profile's disposable environment.
The provider owns its lifecycle. TeleClaude's controller owns the bounded test
operations, their actual cleanup and truthful outcome; it implements no nested
guest manager or separate substrate qualification.

Acceptance occupies a fresh job with read-only repository permissions, no
persisted checkout credentials and no injected product/provider secrets.
Candidate processes receive a synthetic, allowlisted environment. The job
contains neither earlier nor later credential-bearing release commands.
Artifact transfer uses the existing workflow transport; its credentials are
not passed to candidate processes (`sdlc/policy/ai-agent-security`).

Candidate preparation and credential-bearing finalization use different fresh
jobs from acceptance. The acceptance job obtains only the exact candidate and
necessary source objects; transfer identity/digest and candidate commit/tree
are verified before execution. Finalization consumes the fixed candidate and
its report by recorded artifact identity/digest, verifies the source/tree and
complete profile, and requires the acceptance job's successful completion.
It executes no candidate payload. Report bytes alone cannot turn a cancelled,
failed or incomplete job into acceptance.

The controller retains the public session/operation/effect assertions and the
supported daemon stop and cleanup checks. Disposal of the hosted VM is outer
resource reclamation, not proof of product shutdown or claim settlement. A
cleanup failure stays a failed profile. The result makes no independently
observed universal descendant-extinction claim before artifact upload.

## Primary flows

1. CI checks out its exact source. Release preparation freezes the candidate and
   transfers its existing immutable artifact without running the full profile.
2. A dedicated fresh acceptance job verifies the source/candidate identity and
   executes the existing full profile through real public process boundaries.
3. The controller records actual results, attempts bounded owned cleanup, and
   writes the report. The workflow retains the named diagnostics when possible.
4. Release finalization in a fresh job verifies the successful acceptance job,
   exact candidate and full report. Existing installation proof and publication
   continue through their owning gates.

## Failure modes

- Missing, mismatched or incomplete candidate/report evidence fails acceptance.
  A partial selection is never a full-profile pass.
- Installation, journey, shutdown and cleanup failures retain their own outcomes;
  later environment disposal does not repair them.
- Cancellation, timeout or runner loss can prevent cleanup or artifact retention.
  The job supplies no successful acceptance, and no rootfs recovery is promised.
- Placing credential-bearing release work in the acceptance job breaks its
  isolation contract even when the payload's environment omitted those credentials.

## See Also

- docs/third-party/github-actions/hosted-runtime-validation.md
- docs/third-party/github-actions/secret-and-artifact-lifecycle.md
