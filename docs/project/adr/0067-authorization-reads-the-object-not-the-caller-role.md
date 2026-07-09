---
visibility: 'public'
number: '67'
date: '2026-07-09'
description: 'Authorization for todo and artifact mutation derives from the object — the live-holder claim and the lifecycle phase — plus the operation set a session brief includes. The caller-role allowlist is retired; the self-restart and self-end carve-outs collapse into ownership.'
---

# ADR-0067: Authorization reads the object, not the caller role — ADR

## Context

Authorization for workflow mutation is expressed as a caller-role allowlist. A CLI verb declares which system roles may invoke it, and prepare-artifact writes consult a job-role allowlist before the live-holder claim is checked. Around that model sit four carve-outs that each re-derive one idea: a caller may act on what is its own. Self-restart admits a session restarting itself. Self-end admits a parentless session ending itself. The prepare-write gate admits a roleless session and defers to the claim. The claim guard refuses a foreign live holder.

ADR-0056 considered removing the role allowlist entirely and governing prepare writes by the live-holder claim alone. It rejected that alternative for a specific and correct reason: during the work phase the work orchestrator is itself the live holder, so a claim-only rule would admit its writes to the prepare artifacts the role allowlist exists to protect.

That reason is a statement about the todo's lifecycle phase, expressed as a statement about the caller's role, because the phase was not available to the gate. The role list stands in for the phase. Standing in is why the list must enumerate every job that happens to be present during a build, why each new job forces an entry, and why entries persist after the dispatch that justified them stops occurring.

Two conditions have since made the phase directly expressible. The todo's lifecycle state carries whether a build has started, and the slug-mutation guard on `telec todo update` already consults it to refuse rename and reclassification once a build is under way. Separately, the state layer treats durable records as reversible: artifacts are versioned and removals are soft, so destructiveness is a defect in that layer rather than a property authorization must guard.

## Decision

Authorization for a workflow mutation is the conjunction of three conditions.

**Capability** — the operation belongs to the set the session's brief includes, declared alongside that brief and keyed by the command that spawned the session. Capability is configuration. It expresses focus, and an explicit human-involvement declaration widens it.

**Ownership** — the session holds the object's live claim, or the object is unheld. Ownership is a fact about the object and admits no override.

**Phase** — the object's contract is open. A contract under execution is closed to mutation, whatever the caller is. Phase is a fact about the object and admits no override.

The caller's system role and job role are not authorization inputs. The CLI verb's system-role allowlist, the prepare-write job allowlist, the dispatch role matrix, and the self-restart and self-end carve-outs are retired: self-restart and self-end are ownership of one's own session, and the roleless exemption is ownership of an unheld todo.

A refusal names the operation that satisfies the invariant — releasing a claim, or returning a contract to an open phase. Neither invariant is suspended by any declaration, by any role, or by a human.

The human-involvement declaration governs capability alone. It is unverifiable by construction, so it is wired to the layer whose forgery costs a wider brief and nothing more.

## Consequences

- Ownership and phase are read from the object. A gate no longer enumerates the callers that happen to be present when a condition holds, and no entry can rot when the dispatch that justified it stops occurring.
- The four carve-outs collapse into one rule. A session acting on what it holds is the ordinary case, not an exception granted per verb.
- Prepare artifacts stay protected during a build by the phase condition, which is what ADR-0056's reasoning was reaching for. The protection no longer depends on enumerating the roles present at that time.
- Reversibility becomes load-bearing. A durable mutation that cannot be undone is a defect in the state layer, and no authorization rule compensates for it.
- A human directing an agent past its brief is ordinary collaboration. A human mutating a held or closed object is refused and handed the door, which is a narrowing of what a human-identity caller may previously do directly.
- The declaration of human involvement is forgeable. Its integrity rests on being auditable and on governing only focus; an agent that forges it reaches an invariant that reads the object and cannot be persuaded.

## Alternatives Considered

- **Widen the role allowlist to admit the roles that hold claims.** Rejected: it adds entries to the structure whose growth is the defect, and each new job reopens the question. The claim it approximates is already recorded on the object.
- **Keep the role allowlist and add the phase condition beside it.** Rejected: with the phase expressed directly, the allowlist protects nothing the phase does not, and a redundant gate is a gate that drifts. Its only remaining function would be to enumerate roles.
- **Govern by ownership alone, without a capability layer.** Rejected: ownership does not bound a session to its brief. A session holding a claim would reach any operation when it met an anomaly, which is the behavior the role bands were introduced to prevent.
- **Derive human involvement from the caller's principal.** Rejected: a principal without a system root records that a human started the session, never that a human is present for the act. Deriving presence from provenance reads an authority thread as a signature.

## See Also

- ~/.teleclaude/docs/general/principle/trust-and-guardrails.md
- ~/.teleclaude/docs/general/policy/human-involvement-recording.md
