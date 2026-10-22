---
description: The complete native GitHub write boundary, canonical comment envelope and durable provider-object/session attribution, composed with sealed adapter owners.
visibility: internal
delivered_by:
  - issue-129
---

# GitHub Posting — Spec

## What it is

Integration transports native conversation and artifact authoring to GitHub
under the authenticated session/actor facts supplied by
`local/projects/teleclaude/spec/feature/identity/platform-github-identity`.
Sealed acts and event reflections enter separately through their existing
trusted owners. Native prose remains opaque and supplies no lifecycle authority
(`sdlc/policy/domain-ownership`, `sdlc/policy/no-semantic-validators`).

## Canonical fields

### Native invocation scope

The native entry consumes the identity owner's positively corroborated session
observation. Its recorded project/context is the only scope input; invocation
cwd, `gh` arguments, host overrides and repository flags do not select the
project or backend. Config resolves that project's declared scope, and posting
consumes the selected-backend answer from
`local/projects/teleclaude/design/architecture/workflow-store`; valid-default
and configuration-error behavior remain with those owners. A missing,
ambiguous, unreadable or invalid scope answer refuses rather than becoming a
local selection.

Before allowing native pass-through or credential-bearing execution, the entry
rereads the observed session,
project context, selected backend and GitHub actor/target bindings. Any existing
GitHub binding, including a partial or invalid actor or target record, anchors
the session to GitHub. A changed backend, missing target, unreadable binding or
project/config disagreement refuses without human credentials or local
fallback.
A local backend with any actor or target binding also refuses; a removed or
changed backend declaration never clears or rebinds existing session scope.

A positively corroborated managed session whose owner-resolved backend is local
and whose session has no GitHub actor or target binding runs the real `gh` with
its original arguments, environment, I/O and invocation directory. It receives
no App credential, envelope or GitHub object association. This includes a
genuinely absent session role; the identity owner distinguishes that fact from
an unknown role. A GitHub-selected session requires its canonical role and
both bindings; a missing or unreadable producer result refuses. Positively
identified human execution outside managed panes keeps native `gh` behavior.
The real binary lookup excludes this installed entry to prevent recursion
(`local/projects/teleclaude/spec/feature/identity/platform-github-identity`,
`local/projects/teleclaude/spec/domain/config`).

### Complete supported native mutation set

Each admitted native mutation fits exactly one row below. Target, every field
and every possible provider effect are resolved before credentials are forwarded
or a mutation begins. Unsupported, mixed, opaque or unresolved interactive
invocations refuse whole, without partially performing their permitted fields
(`sdlc/policy/security-awareness`).

| Native operation                                                                               | Target and permitted effect                                                                                                                                       | Authority and attribution                                                                                                                                                                                                                      |
| ---------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Append a comment, comment-only PR review or prose reply                                        | Bound item, associated PR or their threads; body only. A review explicitly submits the provider COMMENT event and records its actual reviewed commit SHA.         | The new object is native context, with its own authenticated session/actor association and no source delivery identity. Thread placement is not a sealed finding disposition or reply act.                                                     |
| Edit/delete the session's recorded native conversational comment, reply or comment-only review | Exact provider object whose immutable creation association proves this session produced it through the preceding row; body-only edit or deletion where supported. | Native context provenance is required before effect. Sealed actions and reflections remain with their owners, including when actor or displayed act matches. Creator provenance remains separate from later editor/deleter attribution.        |
| Edit the issue's intent/spec body                                                              | Bound issue body only; issue identity and all metadata remain unchanged.                                                                                          | Consume the body-write owner's holder/claiming-group eligibility and last-read revision/immediate reread result. Return/associate the resulting provider body revision with the writing session. No comment envelope or prepared act is added. |
| Open the builder's draft work PR                                                               | Bound work branch after its first confirmed platform push; title/body and owner-resolved repository/head/integration base only; draft required.                   | Consume `local/projects/teleclaude/spec/feature/integration/github-publication`; discover/reuse the branch's existing PR and verify its creating actor/session.                                                                                |
| Maintain the creating builder's PR description                                                 | Same associated builder-authored PR; title/body only.                                                                                                             | Retain verified PR/session authorship. Head/base, readiness and all other metadata remain outside this row; no comment envelope or invocation identity is fabricated.                                                                          |

Reply-target verification establishes authenticated provider repository, item,
PR and thread membership. The target may be a human comment or sealed finding;
it need not be this session's native context. Editing/deleting that target
requires the separate creation-provenance check in the maintenance row.
Same-App author identity, a displayed note act or a last-comment selector
establishes neither maintenance ownership nor target selection
(`sdlc/policy/security-awareness`).

The body-write row consumes
`local/projects/teleclaude/spec/feature/workflow/item-acts` and the existing
WorkflowStore adapter's eligibility/revision operation. Posting supplies
authenticated facts and carries the result; it decides no holder, claiming
group, phase, prepared revision or commit-instant fence
(`sdlc/policy/domain-ownership`).

Every native mutation outside the table is refused before effect. Lifecycle
creation, claims, prepared state, stamps, readiness and delivery use their
sealed owners under
`local/projects/teleclaude/spec/feature/workflow/item-lifecycle` and
`local/projects/teleclaude/spec/feature/workflow/item-acts`. Native merge and
deferred-merge/queue mutations do not substitute for the integrator's delivery
path, including for an integrator caller, approved PR or matching head
(`sdlc/policy/domain-ownership`).

### Finite native execution

Concrete native commands and supported REST write spellings use fixed
target/argument/payload schemas with the same table's limits. Unknown fields,
methods, endpoints, aliases, extensions, diagnostics, host/repository overrides
and defaults do not widen support or acquire an App credential. Native review
verdicts, pending-review verdict submissions and bare undecided interactive
reviews refuse before provider effect. Admission is finite structural handling,
not a generic interception framework or semantic command/prose parser
(`sdlc/policy/no-semantic-validators`, `sdlc/policy/security-awareness`).

Structural target and operation admission completes before prose collection.
Argument, body-file, stdin and editor prose collection then finishes before
credential injection. An editor receives a sanitized environment; the fixed
collected prose reaches the provider process, which cannot reopen an editor,
pager or default-selection prompt after credentials arrive. Credential-bearing
execution uses controlled native configuration and no uncontrolled extension
subprocess. Token-printing auth commands, token-disclosing status modes, shared
auth switching and credential/header diagnostics receive no platform token
(`sdlc/policy/ai-agent-security`).

Only structurally exact help/version spellings run as reconstructed bounded
native commands with sanitized empty native configuration and no App token.
Other read-only commands must match the supported read shape and use controlled
configuration. Aliases, extensions, opaque controls and flag-looking text in
body/file/stdin/editor prose do not select a help or version path.

### Canonical envelope mapping

The role catalog owns role names and labels. The item lifecycle owns act/phase
values and performer eligibility; posting consumes its canonical types and
owner decisions without another enum or allowed-value list. The envelope maps
trusted posting facts to readable prose only
(`local/projects/teleclaude/spec/feature/identity/agent-roles`,
`local/projects/teleclaude/spec/feature/workflow/item-lifecycle`).

The one UTF-8 comment prefix is:

```text
TeleClaude envelope
Role: {role}
Session: {session_id}
Act: {act}
Phase: {phase}
Delivery: {delivery_id}
Turn: {turn_id}
Part: {part}
End TeleClaude envelope

{original_prose}
```

The header uses exactly the displayed spelling, case, order, punctuation and
single space after each colon, with LF line endings and one empty line after
the ending line. All prose after that separator is preserved, including leading
and trailing whitespace and header-looking spans. Recognition starts only at
the beginning of the comment and uses this one header/body boundary, never a
delimiter search inside prose (`sdlc/policy/ai-agent-security`).

Role is the canonical catalog name; act and present phase are canonical owner
values. Session, delivery and turn identifiers are the owner's exact identifiers
encoded as RFC 3986 percent-encoded UTF-8 tokens: ASCII letters, digits and
`-._~` remain literal, every other byte is uppercase `%HH`. The complete
identifier `-` is `%2D`; literal `-` marks absence. An absent owner phase is
not inferred. The renderer mints no identifier
(`sdlc/policy/domain-ownership`).

Ordinary native context uses the canonical note act and absent delivery.
Sealed actions require the owner's invocation identity; reflections require the
source event-delivery identity. Only the trusted native conversational path can
have absent delivery; an act string or prose cannot select it. Mirror facts
come from the mirror owner: turn identifies the source turn and part is `i/n`,
positive decimal integers without leading zeros with `1 <= i <= n`.
Non-mirror comments have absent turn and part. Every path uses the same prefix;
no mirror or phase act is invented (`sdlc/policy/domain-ownership`).

Original issue/spec bodies and PR descriptions remain artifacts without comment
envelopes. A body saying approved/prepared/stamp changes no provider event or
act classification. A structurally identical header typed into an unrecorded
object establishes no authenticated association
(`sdlc/policy/no-semantic-validators`, `sdlc/policy/ai-agent-security`).

### Durable result association and ingress

Success requires the provider response's verified actor and a durable
repository/item/provider-object/producing-session/actor association. The record
retains source invocation/delivery identity where present and explicit source
absence for native context, a review's exact reviewed head, source-kind and
owner-supplied mirror ordering facts. Provider object ID and source Delivery
identity are separate facts. Creation attribution is immutable and separate
from edit/deletion attribution. The existing durable session owner retains
these records across restart (`sdlc/policy/ai-agent-security`).

Concurrent sessions retain separate producing-object associations even when
they share an App. Association updates never replace another session's creator
facts or change shared credential selection
(`sdlc/policy/ai-agent-security`).

Authenticated provider author/editor facts plus the stored association decide
ingress attribution. A platform-authored object without a verified producing
session is reported unattributed and counts as no state. A non-platform last
editor invalidates a state-bearing comment. Deletion is absence, not a reason
to invent provenance. A human-account comment remains that provider account's
input; resolving it to a registered person consumes
`local/projects/teleclaude/spec/feature/identity/person-context-binding`.
Headers, actor names and absent Delivery do not replace these checks
(`sdlc/policy/ai-agent-security`).

Outbound source Delivery IDs retain their idempotency role and remain distinct
from GitHub's inbound webhook delivery IDs. Echo qualification follows UC-19:
verified ingress and current-state reconciliation continue, while only an event
whose verified actor and action match the exact configured TeleClaude App and
whose canonical envelope is structurally valid for a sealed/reflected post with
its mandatory source Delivery suppresses echo-generated conversation, session
wake and outward mirror/reflection. A native conversational note with
`Delivery: -` remains eligible under the existing ingress and attribution
rules. External bot input and human edits or deletions of App-authored objects
are not discarded because of the object's original author. App identity,
envelope text or delivery-key text alone does not establish an echo.

The adapter and mirror owners retain their event and effect decisions. Echo
classification supplies no positive session or workflow-state attribution;
the recorded provider-object association remains required for those facts. The
association may still be read for attribution, but echo suppression alone does
not require a cross-computer association lookup or create an internal event or
session wake from envelope prose (`sdlc/policy/domain-ownership`, #124 UC-19).

### Separate sealed transport

The existing sealed/adapter owner authorizes the operation and supplies its
canonical caller, act, target, revision/head and invocation/event identity
through its actual published port. Posting carries that request and its
provider results. An agent argument cannot select the trusted entry path.
Adapter-owned payloads, per-item per-fact/occurrence keys, allocation and
body/revision realization remain with the WorkflowStore owner; a provider
effect sequence is not represented as one GitHub transaction
(`sdlc/policy/domain-ownership`).

### Use cases

This contract supports the existing goals of spec collaboration, human
participation, builder-authored work PRs and mirrored work. Rendering, admission,
token handling and attribution add no independent stakeholder goal
(`sdlc/principle/documentation-first-development`).

## Known caveats

Provider acceptance followed by a lost response or failed association write is
an incomplete operation, not attributed state. The failure reports known object
IDs and possible remote effects where available. Neither another session
sharing the App nor a restarted writer may reconstruct missing provenance from
the header. Native context has no automatic retry, invented source key or
pending-write queue. Sealed and reflected recovery uses its owner's source
identity and actual recovery contract; reflections retain the owner's shared
budget/backoff and part ordering, and unresolved effects remain reported
(`sdlc/policy/code-quality-practices`).

Provider errors, rate limits, unavailable grants and credential failures return
to the native caller or the owning sealed/reflection recovery. They supply no
stale workflow state or actor fallback; the daemon remains available
(`sdlc/policy/code-quality-practices`). Body rereads do not promise atomic
commit-instant revision fencing or provider edit-history completeness.
