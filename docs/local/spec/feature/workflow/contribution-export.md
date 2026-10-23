---
description: A contributor's reviewed todo is offered upstream as one revision-bound pull request carrying its documentation and reviewer reports, without activating that work locally.
delivered_by:
  - reviewed-pr-contributions
---

# Contribution Export — Spec

## What it is

A contributor installation offers completed local work to the upstream project
through a pull request. The contributor's workflow owns proposal preparation,
its reviewed revision and subsequent updates. Upstream owns acceptance and
integration. Source delivery, release publication and installation adoption are
separate facts, following `sdlc/principle/design-fundamentals`.

## Canonical fields

### Participation and destination

Automatic public contribution follows an explicit standing enrollment naming
the upstream repository and a writable contribution destination. Enrollment
carries the operator's authorization to publish scoped fixes and exportable
review evidence (`general/policy/human-contract`). An unenrolled installation
can retain local development work and reports the missing enrollment when
publication is requested. Unavailable repository authorization leaves the
proposal pending and names the failed operation; it does not change the
installation's release or broaden credentials.

The upstream source baseline and writable contribution destination are recorded
separately. Source refresh and integration comparison consume upstream main;
branch publication, resumption and cleanup consume the recorded contribution
remote and branch. A fork's main is not silently substituted for the upstream
baseline. The contribution destination is independent of release channel. Upstream-authoring
checkouts retain mainline integration; contributor checkouts publish their own
branches and PRs. The recorded checkout association selects that delivery purpose.

### Proposal boundary

Preparation authors the todo's pending documentation in the development root.
Its reviewed source base and owned documentation changes travel with its code
in the proposal. Proposal assembly includes only that todo's intended change
and explicit dependencies; unrelated local-main commits and pending contracts
remain outside it. Where several todos share a snippet file, the owned delta
follows section and companion ownership rather than copying that whole file.
An ownership conflict is retained for agent reconciliation; it does not authorize
flattening unrelated pending material. Dependency changes not yet accepted upstream remain explicit
proposal dependencies. The candidate's full code-and-documentation revision is
the review subject before publication.

The complete proposal is assembled on the item's actual work branch before its
approving review. The independent work driver can review local commits from
the builder's completion notices before public branch publication. Its report
binds the composed code, documentation and evidence subject. The recorded
contributor delivery purpose makes ordinary per-commit publication local until
that review is current.

The holding work driver then invokes the contribution branch-publication
operation, which publishes the exact reviewed commit to the enrolled writable
ref through the normal leased update and publish-intent contract. The ordinary
readiness stamp checks that published ref, the worktree and the proposed commit
before and after native gates. A ready contributor item triggers PR and report
handoff against the already-published subject. Publication failure leaves the
item unready and its branch resumable. Upstream-main comparison remains
independent of that writable ref
(`local/projects/teleclaude/design/architecture/work-state-machine`).

Every proposal records its upstream base, head revision, local todo identity,
upstream PR identity and review-evidence identity. Retry of the same handoff
finds and updates that proposal rather than opening another. The contributor
never treats successful PR creation as upstream delivery or marks the fix
installed. Local work remains associated with its PR while upstream acceptance
is pending; it can be resumed for review findings without losing its branch.
PR closure without merge records that disposition and retains the local work
until its owner retires or resumes it. A confirmed merge records upstream
acceptance and its actual commit before ordinary delivered-work cleanup; closure
alone never supplies that confirmation.

### Contribution operations

The contribution command surface offers proposal publication, inspection and
reconciliation by local todo. Its inspection identifies retained work, the
current proposal revision, publication failures and the independent delivery,
release and installation facts. Branch publication precedes readiness; ready
handling and an explicit retry invoke the same resumable PR/report handoff.

Standing enrollment is a computer-local declaration for the registered logical
project, changed through the configuration owner's semantic operation. The
declaration selects the upstream and writable destination independently of the
release channel; a clone, imported project declaration or supplied PR cannot
enroll its receiving installation. Disabling enrollment stops later public
writes and retains existing proposals. The configuration owner validates and
persists the declaration (`local/projects/teleclaude/spec/domain/config`).

Workflow owns durable proposal and adoption records, including their revision
history, retry position and links to local todo identities. Provider operations
cross integration's typed transport contract; configuration, documentation
projection, release admission and installation assessment retain their owners
(`sdlc/policy/domain-ownership`). An interrupted external write is reconciled
with the provider before it is repeated.

### Review evidence

The PR carries a comment with the exportable reviewer reports, the exact
reviewed revision, verdicts, unresolved findings and their resolution evidence.
Reports remain readable rather than replaced by a bare approval flag. Repository
privacy applies to exported evidence (`sdlc/policy/security-awareness`); local
logs and account details are not automatically copied into a public PR.

A changed head retains historical reports with their original revision and
requests review of the changed subject. The upstream reviewer decides whether
and where prior evidence remains applicable under
`local/projects/teleclaude/spec/feature/workflow/contribution-adoption`.

### Occurrence and resolution tracking

The reported occurrence retains its observed installation revision and evidence.
A fix's source acceptance records the actual upstream delivery commit; release
availability records the release containing it; installation adoption records
the revision actually activated. An affected installation can remain awaiting
an eligible release after source delivery. Repeated evidence for that same
unadopted fix updates the existing matter rather than creating another build.
The bug listing exposes the linked unresolved-adoption matters so reporters
can inspect only their identified todo and evidence rather than scan completed
history. Recurrence after adopting the fix is fresh diagnostic evidence, not
automatically the same unresolved defect. A series that excludes the available fix remains
explicitly awaiting an eligible release or an operator-selected series change.

### Use cases

#### UC-CEX1: A reviewed contribution is offered once

```gherkin
Given an enrolled contributor has a reviewed code-and-documentation proposal
When an agent publishes the contribution and retries its handoff
Then the contributor can inspect one upstream pull request for that proposal
And its reviewer reports identify the revision they examined
```

#### UC-CEX2: A proposal preserves unrelated development work

```gherkin
Given a contributor's development main holds pending documentation for multiple todos
When an agent assembles one todo's contribution
Then the proposal contains that todo's reviewed code and owned contract changes
And unrelated pending work remains outside the proposal and intact locally
```

#### UC-CEX3: A changed proposal retains the scope of prior review

```gherkin
Given a contributor changes a proposal after its review reports were published
When the proposal's current evidence is read by the upstream reviewer
Then earlier reports still identify their original revision
And the changed revision is not represented as already approved
```

#### UC-CEX4: Publication failure preserves resumable work

```gherkin
Given an agent cannot publish an enrolled contributor's proposal
When that handoff fails
Then the contributor can inspect its publication failure and retained proposal
And the work remains available for retry
And no upstream delivery is recorded
```

#### UC-CEX5: An occurrence awaiting deployment reuses its existing fix

```gherkin
Given an installation still runs a revision affected by an upstream-delivered fix
When a bug-reporting agent observes another occurrence of the same diagnosed defect
Then the occurrence is associated with the existing fix and pending adoption
And another implementation todo is not created for that occurrence
```

## Known caveats

- The destination may require a contributor-owned fork. An installation's
  ability to clone the source proves no ability to publish to the upstream.
- Mainline release publication supplies no automatic backport into an older
  compatibility series.
