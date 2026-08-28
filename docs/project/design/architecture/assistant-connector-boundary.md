---
description: 'How an agent session reaches an external mail or calendar connector: the person binding it inherits rather than resolves, the layer each responsibility sits in, how an instructed send is distinguished from initiative, and how credentials are confined and moved.'
delivered_by:
  - personal-mail-tool-launcher
---

# Assistant Connector Boundary — Design

## Required reads

- @docs/project/spec/feature/integration/assistant-connector-invocation.md
- @docs/project/spec/feature/config/person-mail-accounts.md
- @docs/project/spec/teleclaude-config.md

## Purpose

An assistant reaches a person's mail and calendar through external command-line
connectors. Those connectors carry the operations the personal-assistant conduct
policy prohibits and do not hold the prohibitions themselves. This design places
the prohibitions, the account binding, and credential confinement at the one
boundary where a connector is reached, and states which context and which layer
owns each part.

Three contexts participate, and the split follows meaning rather than hosting:

- **Configuration** owns what a person may declare — their mail accounts, each
  naming a connector from the platform's vocabulary and an address. It sits with
  the person's other operational data rather than in the global identity entry,
  which already refuses credentials-adjacent keys.
- **Integration** owns the boundary: translating the platform's vocabulary into a
  particular tool, binding an invocation to one declared account, directing that
  person's state, determining what an invocation reaches, and applying the two
  prohibitions.
- **Agent runtime** owns that a session reaches the boundary rather than the tool,
  and owns the person binding the boundary consumes.

The prohibitions remain the conduct policy's. This design changes where they are
applied, never what they say.

### The person is inherited, never resolved here

A session reaches a person's workspace only through the launch call that derives
the person from the authenticated caller, and the general session verbs refuse a
destination inside a person workspace. That contract is the authority for who a
session acts as.

This boundary therefore performs no person resolution and accepts no parameter
naming a person. It reads the person the workspace declares of itself — the
workspace-kind declaration that names the workspace a person's and carries that
person's slug — and refuses when the session is not in a person's workspace at
all. That declaration is the binding's only source: a path is not identity, and
inferring a person from a directory name is the impersonation surface the
declaration exists to close. A non-person workspace never
becomes a mail execution origin, and the boundary never opens a workspace other
than the one it is running in. Consuming that binding rather than re-deriving it is
what keeps the conduct policy's scope — an agent acting in that person's workspace —
structurally true instead of conventionally assumed.

### Prior art and adopt-vs-build

The mechanisms this boundary uses are the connector's own, verified against the
installed command surface rather than assumed: which account an invocation acts
as, where its state is directed, and the levers that block sending, restrict the
command set, or refuse mutations. None is compiled into the tool; each holds only
if the invocation is constructed with it, which is what makes a boundary that
constructs invocations the right place for the prohibitions.

Nothing here is bespoke infrastructure, so there is no adopt-versus-build
decision to record. The one place this design deliberately does not build is
credential confinement: a per-person secret store is an owned concern elsewhere,
and the alternative shape for it — a broker owning refresh state and issuing
short-lived tokens — is surveyed by that owner's work rather than by this.

## Inputs/Outputs

**In:** the person binding the session already carries; that person's declared
accounts; the account this invocation names; the person's state location and
store secret; and an explicit declaration when a send was instructed.

**Out:** a constructed invocation of the real connector executed against that
person's confined state, or a refusal naming which condition failed — not in a
person's workspace, no named account, a reached prohibition, an uninstructed
send, or reach that could not be determined.

### Layer placement

| Responsibility                                                                                           | Layer                                            | Owner         |
| -------------------------------------------------------------------------------------------------------- | ------------------------------------------------ | ------------- |
| Entry point published on the agent tool surface                                                          | Artifact / tool surface                          | agent runtime |
| Reading the workspace's person declaration, the named account, and the attendance fact into typed inputs | Injection                                        | agent runtime |
| Account lookup against the person's declared list                                                        | Core service, via configuration's published read | configuration |
| Reach determination, prohibition application, invocation construction                                    | Core service                                     | integration   |
| Connector process execution                                                                              | Infrastructure, behind its owning service        | integration   |

These responsibilities do not fit an existing root. The platform's adapter root
holds inbound and outbound UI adapters, and its integration core holds the
code-delivery state machine; neither is a home for connector invocation, and
placing this there would make a cohesive concern a tenant of an unrelated one.
The connector boundary is therefore a new module under the integration context,
and the plan names it as new rather than adapting a root whose subject is
something else.

The integration core receives fully resolved typed inputs and reads neither the
environment nor the filesystem to fill them; that resolution is the injection
layer's, as the layer contract requires. Every crossing goes through the owning
context's published read rather than direct access to its state.

The entry point carries no logic of its own. This follows the no-inline-logic
contract rather than an existing example: the platform's git entry point is a
several-hundred-line behavioral shell wrapper, not a delegation, and is a
precedent for _where_ such an entry point is published, not for _what_ it may
contain.

## Invariants

- An invocation not bound to both an inherited person and one of that person's
  declared accounts does not reach a connector. Neither is inferred, neither has
  a default, including where the person declared exactly one account.
- The boundary never resolves, accepts, or overrides which person a session acts
  as, and never reaches into a workspace other than its own.
- The prohibitions are applied to what an invocation is determined to reach, not
  to the name it was called by; reach that cannot be determined is refused.
- A send leaves only when the invocation carries an explicit instructed-send
  declaration. The declaration is the acting agent's own statement, recorded with
  the invocation; it is never derived from attendance, role, or lineage.
- Nothing above this boundary names a vendor tool.
- A connector's state location and its secret store are separate concerns, and
  directing the first without confining the second yields no isolation at all.

### The send gate, in two regimes

No context publishes a fact carrying what a person asked for, so instruction
itself is not readable at the boundary. Attendance is: whether a human is present
to the session is an authority-backed fact the identity context already owns, and
the boundary consumes it rather than inferring it. The gate therefore has two
regimes, and only one of them is structural.

**Where attendance cannot be established, sending is made impossible at the
tool.** The invocation is constructed with the connector's own send-blocking
lever engaged, so the process that runs cannot send whatever it is asked to do,
and no declaration by the acting agent lifts it. Where a connector offers no such
lever, no send-capable invocation is constructed for it at all. This is what
carries the conduct policy's requirement that the tool an unattended run uses
cannot send.

**Where attendance is established, sending is available and the claim is
recorded.** Every send carries the acting agent's declaration that the person
asked for it — the same shape as the platform's involvement declaration on
commits: the agent's own statement, never derived, absent by default, and
answered by the durable record when false. The conduct policy's mandate rule
governs the judgment; this boundary makes the claim attributable rather than
preventing a false one.

The asymmetry is the conduct policy's own: it holds that an assistant which
cannot send when told is a worse tool for no gain in safety, since the person
could send it themselves in the same breath. Prevention is therefore spent where
no instruction can exist, and attribution where one can.

## Primary flows

```mermaid
flowchart TD
    A[agent session invokes a connector] --> B{in a person's workspace?}
    B -- no --> R0[refuse: not a person workspace]
    B -- yes --> C[inherit the person binding]
    C --> D{bound to a declared account?}
    D -- no --> R1[refuse: no account named]
    D -- yes --> E{what does this invocation reach?}
    E -- settings --> R2[refuse: prohibition applies]
    E -- undeterminable --> R3[refuse: reach undetermined]
    E -- a send --> F{instructed-send declaration present?}
    F -- no --> R4[refuse: no instruction declared]
    F -- yes --> G
    E -- nothing prohibited --> G[execute against the person's confined state]
```

### Confinement is not delivered here

Directing a connector's state at a person's own location is not confinement: a
connector may resolve an account from a store shared across the machine
regardless of where its state is directed. Closing that needs a per-person secret
store, which is an owned concern elsewhere — its contract covers secrets held per
person, resolution bound to a verified identity, refusal rather than fallback to
a global secret or another person's, and non-exposure through catalogs, logs,
errors, or serialized person configuration.

This boundary therefore makes no confinement claim and defines no secret storage.
Building a second mechanism beside that owner would make this work a second owner
of person-secret policy. When confinement is delivered it brings its own
migration for accounts authorized beforehand, since selecting a confined store
governs only authorizations made after it is in force.

## Failure modes

- **The platform's routes are not the only physical routes.** The agent shell
  front-pins the platform's tool directory, so the published entry point wins name
  resolution — and a package manager publishes its own executable on the same
  path, which an absolute invocation reaches. Relocating that executable does not
  fix it either: a process holding the person's own authority can obtain and run a
  connector regardless. Genuine unreachability requires the session to hold less
  authority than the person, which is process isolation the platform does not
  impose. The product contract states what the platform provides and records the
  isolation as a dependency.
- **A defeasible gate reads as a structural one.** Where a connector offers no
  restriction lever, the prohibitions rest on determining reach from the
  invocation, and an unrecognized endpoint alias or encoding is read as reaching
  nothing prohibited.
- **A false instructed-send declaration sends mail.** The declaration is
  detection, not prevention. What it buys is attribution: the send is recorded
  against the session that declared it.
- **Partial confinement is the dangerous state.** A person given a confined store
  whose earlier credential still sits in the shared one has the appearance of
  isolation and none of it, and nothing fails to reveal it. The boundary refuses
  an account it cannot confirm is confined, so the appearance never arises
  silently.
- **Two concurrent invocations for one person can rotate a credential under each
  other.** Confinement separates people, not a person's own parallel work. The
  connector's native behavior governs it, and nothing here serializes refreshes.
- **A declared account that was never authorized** fails at the connector rather
  than at the boundary. The boundary binds an invocation to a declaration; it does
  not verify the declaration was ever consented to.

## See Also

- ~/.teleclaude/docs/personal/policy/assistant-conduct.md — the prohibitions this boundary applies, and the workspace scope it inherits.
- docs/project/spec/feature/agent_runtime/person-workspace-dispatch.md — the launch contract that establishes the person binding this boundary consumes.
- docs/project/design/architecture/layer-ownership.md — the layer contract the placement table follows.
- docs/third-party/gogcli/authorization.md — the vendor evidence for the connector's account selection, state root, and caller-supplied levers.
