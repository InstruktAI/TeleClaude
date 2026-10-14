---
description: Repository release publication binds an independent change assessment
  and full installer proof to one immutable candidate, with provider failover and
  visible failure evidence.
visibility: internal
---

# Release Publication — Spec

## What it is

Repository release tooling turns a captured source revision into an installable,
versioned release. Its owner is the repository's release tooling, separate from
the daemon contexts that install or consume releases. Scheduled and manually
requested attempts use the same flow; the workflow declaration owns the cadence.

Release evidence is grounded in the change itself
(`general/principle/grounding`). A release preserves the identity of the candidate
whose installation was proved (`sdlc/policy/code-quality`). Publication completes
only after that proof. The local commit-quality process and the separate lint
workflow are independent of release orchestration.

## Canonical fields

### Attempt and baseline

An attempt captures its source revision and the last successfully published
release when it starts. Only release attempts are serialized; ordinary source
delivery continues independently. The captured revision remains fixed throughout
inspection, candidate preparation, verification, and publication.

The baseline is a completed publication, not a failed candidate or an unpublished
tag. Its released manifests and recorded source identify the comparison. Release
artifact changes are distinguished from functional source and dependency changes.
The workflow makes each stage's result and its evidence address visible.

### Release decision

An explicit version on a manually dispatched release or dry-run selects the
operator-decided path. It accepts a stable semantic version newer than the
completed baseline, with an unused target tag. It captures remote main after
serialization, and records the supplied version and workflow request as the
release decision. The supplied version bypasses AI version selection; it does
not suppress an AI release summary. The attempt requests a summary when a
provider can supply one and falls back to deterministic commit notes when no
valid summary is available. It is repeatable for subsequent releases and can establish an initial baseline when
no completed release exists (`general/policy/human-contract`). An explicit
version can release the captured source even when it has no new functional
changes; the version decision is the operator's.

A request without an explicit version selects automatic assessment. Its
no-change and no-release outcomes finish successfully before candidate creation.
Automatic assessment requires a completed baseline. The workflow declaration
owns the dispatch inputs and activation settings.

### Compatibility-aware version decisions

Automatic version selection consumes the classification vocabulary and regimes
owned by `local/projects/teleclaude/spec/release-inspector-prompt`. The report
schema, provider adapters, version calculation and candidate metadata all carry
major classifications as well as minor and patch. An unsupported classification
fails the attempt; it is never reduced to a smaller release tier. Existing
published evidence retains its original decision and immutable candidate under
`sdlc/policy/backward-compatibility-hygiene`. Candidate proof and publication
requirements apply unchanged to every selected tier.

<!-- planned:owned-release-execution -->

### Execution target

One repository setting selects the execution target for the Linux release
stages. The release workflow owns its name and supported runner destinations.
An operator can select owned execution or GitHub-hosted execution by changing
that setting alone. Both destinations consume the same immutable attempt,
authentication protocol and candidate evidence; publication retains its full
verification requirements (`sdlc/policy/process-change-authority`). An absent
or unusable destination produces a visible configuration or scheduling failure.
An owned destination earns infrastructure and credential-free qualification
before a controlled pipeline dry-run. Unattended publication on that destination
requires retained full dry-run and cleanup evidence; selecting it for validation
alone supplies no publication activation (`sdlc/policy/process-change-authority`).

Owned execution gives each job a fresh disposable Linux machine. Administrative
registration credentials and the host's live installation remain outside guest
access; each guest receives only its own ephemeral runner configuration. An
external lifecycle owner retains unfinished cleanup across job cancellation
and controller restart (`sdlc/policy/security-awareness`). Disposal does not
establish provider credential settlement. The installation proof keeps its
separate virtualization-capable execution target.

<!-- /planned:owned-release-execution -->

### Inspector

For automatic assessment, one inspector role assesses actual source and contract changes against the
baseline. Codex is attempted first using subscription authentication. An unsuccessful
Codex inspection selects Claude, also using subscription authentication. Each
provider is attempted once. An execution error, invalid report, or incomplete
assessment is an unsuccessful inspection. If neither provider returns a valid,
complete report, the attempt ends without publication.

Explicit-version attempts use the same provider order and isolation to request
an optional, evidence-grounded release summary. This task does not select or
override the supplied version and does not claim a completed automatic version
assessment. Provider unavailability, invalid output or an unsuccessful summary
attempt remains visible but does not prevent the explicit-version path from
using deterministic notes. A first release can summarize its captured history
without requiring a previous release baseline.

<!-- planned-change:owned-release-execution -->

Source, baseline and bounded evidence are frozen once before inspection. Codex
and its fallback run on separate fresh GitHub-hosted Ubuntu jobs, each installing
only its pinned native client and owning its cleanup. A primary job failure or
missing artifact permits independent fallback without claiming a client exit or
credential settlement that was not observed. Automatic no-change attempts
bypass both providers. Eligible Codex success requires a complete report
and confirmed durable post-run auth; runner loss leaves auth uncertainty intact.

<!-- change:owned-release-execution -->

Source, baseline and bounded evidence are frozen once before inspection. Codex
and its fallback run on separate fresh Ubuntu jobs, each installing
only its pinned native client and owning its cleanup. A primary job failure or
missing artifact permits independent fallback without claiming a client exit or
credential settlement that was not observed. Automatic no-change attempts
bypass both providers. Eligible Codex success requires a complete report
and confirmed durable post-run auth; runner loss leaves auth uncertainty intact.

<!-- /planned-change:owned-release-execution -->

Native clients run under the runner identity with explicit clean environments
and private auth/controller state outside immutable evidence. Native filesystem,
network and tool restrictions remain required. Codex uses the supported distro
bubblewrap/scoped Ubuntu AppArmor setup and one credential-free startup check
before restoring credentials; it changes no global security restrictions.

The Codex command sandbox can read the frozen evidence, minimal system runtime
and the exact verified pinned native executable needed by its inner stage.
Runtime provisioning supplies that file explicitly; it does not grant an enclosing
toolcache, package or home read root. Auth/controller reads and source writes
remain denied, and readiness verifies those boundaries before auth use.

A failed fixed credential-free startup retains its native status and bounded
sanitized stderr before any credential restoration or auth-use checkpoint. Known
credential values and local paths are redacted; environment, argv, configuration,
stdout and trace data are not retained. This is setup evidence, with the provider
exit code still absent, and does not prove which helper was selected or establish
native confinement.

Failover preserves the failed provider outcome alongside the successful report.
Expected availability failures and unexpected faults remain distinguishable in
the evidence. Successful fallback does not erase an unexpected fault or discharge
its repair; the release maintainer receives that failure as actionable diagnostic
evidence. A valid no-release decision is terminal and selects no second inspector.

Exceptions caught by the `prepare_codex`, `run_codex` or `run_claude` controller handlers in
`tools/ci/release_stage.py` reference a retained diagnostic file through the
provider attempt's `diagnostic_path`. It identifies
the provider, explicit phase and operation, exception type, and available errno
or native command status. Evidence contains no raw exception message, traceback,
environment, argv, payload or credential content. A failure before provider
launch leaves the provider `exit_code` null; a setup command's status is
diagnostic metadata, not a provider exit code.

Codex run diagnostics distinguish bootstrap preflight, initial auth read,
inspection, result persistence, post-inspection auth read and encrypted settlement.
They also record whether the inspection adapter was not entered, entered without
returning a result, or returned a result. An error inside inspection leaves actual
client execution unknown: neither a null provider exit code nor missing settled
state proves that the client never ran or refreshed its login. Recovery does not
reuse an older login on that evidence alone. A returned provider result retains
its exit code when a later controller operation fails.

When Claude exits unsuccessfully without a parseable event result, its attempt
references retained sanitized stderr. Sanitized stdout remains available as event
evidence, including an empty stream. Diagnostic sanitization and output bounds
remain owned by the inspector adapter and isolated process boundary.

Codex captures and validates its post-run auth cache independently of the final
report. A missing report does not imply unavailable auth state. When current
auth is available, execution failures retain CLI diagnostics scrubbed against
both pre-run and post-run credential values. If current auth cannot be read or
validated, diagnostics retain only the existing fixed findings and output hashes.

The selected inspector receives a compact change inventory and public-contract
comparison and can retrieve focused source evidence in bounded portions. Grouped
resource changes remain discoverable. The inspector declares whether assessment
completed; incomplete or invalid assessment cannot authorize publication.
Classification is owned by
`local/projects/teleclaude/spec/release-inspector-prompt`, and the report contract
by `local/projects/teleclaude/spec/release-report-schema`.

An explicit verified reseed establishes a recovery boundary for its selected
predecessor chain. Settled descendants continue from that boundary without being
blocked by earlier unfinished attempts. Unfinished auth use at or after the
boundary still refuses restoration. Required chain records must retain their
exact producer, recipient, artifact digest and predecessor identities; missing,
expired or conflicting records cannot establish a boundary. An unrelated reseed
record supplies no recovery authority. Historical records remain unchanged.

### Release notes

Both decision paths use git-cliff over the exact completed-baseline-to-source
interval. With no prior baseline, the manual path covers the captured source's
reachable history. The shared notes include every commit once, with a linked
abbreviated SHA, its subject and a comparison link when a baseline exists.
Conventional-commit parsing, category filters and summary generation do not
remove commits from that list (`general/principle/grounding`).

Automatic releases add the selected inspector's concise consumer-facing summary.
Explicit-version releases also add an evidence-grounded AI summary when one is
available. If neither provider supplies a valid summary, their deterministic
commit notes remain publishable with the supplied version and full candidate
proof. Summary generation cannot change that version or omit commits.
The same generated section is committed into the candidate's cumulative
changelog before verification and copied into its GitHub release body. Note
rendering failures and output limits are visible failures; completeness is never
represented by silently dropping commits. The workflow and git-cliff
configuration own the pinned implementation and rendering template.

### Candidate and proof

Candidate preparation produces the final version metadata, coherent package lock,
released manifests, and cumulative changelog before verification. Candidate
identity and its source and baseline travel with the artifacts between jobs.
Read-only hosted inspection and candidate checks are separate from publication's
write authority; installation runs in a disposable machine on the runner that
provides the required virtualization capability.

The candidate passes release lint and the existing full installation harness.
That harness consumes the fresh-machine installation contract rather than a
reduced CI installation mode. Installer proof includes startup, published
documentation and configuration readiness, the harness's access probes, repeat
installation, and restart/reinstallation. Evidence is retained on success and
failure, and the disposable machine is cleaned up.

<!-- planned-change:owned-release-execution -->

### Hosted runtime acceptance

The final candidate passes the full GitHub-hosted runtime profile defined by
`local/projects/teleclaude/spec/feature/agent_runtime/runtime-acceptance`
before full installation proof. Publication requires both results for that
candidate. The bounded journey allowance and its verification purpose are owned
by `local/projects/teleclaude/policy/test-moratorium`.

<!-- change:owned-release-execution -->

### Runtime acceptance

The final candidate passes the full runtime profile defined by
`local/projects/teleclaude/spec/feature/agent_runtime/runtime-acceptance`,
run on the selected Linux execution target before full installation proof. Publication requires both results for that candidate. The
bounded journey allowance and its verification purpose are owned by
`local/projects/teleclaude/policy/test-moratorium`.

<!-- /planned-change:owned-release-execution -->

Acceptance evidence identifies the exact candidate and tree, the full profile,
all required journey outcomes and cleanup. Its digest travels in the durable
proof checked by publication and recovery, under
`sdlc/policy/code-quality` and `sdlc/policy/backward-compatibility-hygiene`.
Historical proofs remain readable with acceptance recorded as absent when it
was never run; migration never manufactures success or changes their original
evidence. Completed publications remain completed. An incomplete publication
without acceptance evidence cannot resume publication until the full profile
has been proved against its original candidate; its captured source is retained.

### Publication and recovery

The published tag names the exact candidate that passed verification. Later
source revisions do not require rebasing, rebuilding, or invalidating it.
Release-generated metadata belongs to the released candidate; publishing does
not require the moving source branch to remain at the captured revision.
Produced releases preserve the existing supported release-to-release update path.

A dry-run uses the same inspection, preparation, and proof stages and finishes
with their results, leaving publication and its baseline unchanged. A no-change
or no-release outcome finishes successfully before candidate preparation.

Partial publication is reconciled against the remote candidate identity and
version. Recovery resumes that publication; an existing version naming another
candidate is a conflict. The next attempt uses a new baseline only after the
previous publication completes.

### Automatic activation

Automatic publication requires a successful full automatic-path dry-run on a
real releasable interval against a completed baseline. Scheduled attempts remain
in verification mode while that prerequisite is pending; no-change outcomes and
manual-version proof do not satisfy it. The release maintainer records the
qualifying evidence when enabling automatic publication. An explicit manual
version remains publishable through its own complete candidate lint and installer
proof regardless of automatic-provider readiness. Both paths preserve the same
verification and publication identity requirements.

### Use cases

#### UC-RP1: Failover preserves unsuccessful inspection evidence

```gherkin
Given a release operator starts an automatically assessed attempt
When the primary inspection ends
Then an unsuccessful primary inspection selects the fallback inspector
And the primary failure remains visible even when the fallback succeeds
And no release is authorized unless an inspector returns a valid complete assessment
And a valid no-release decision finishes the attempt successfully
```

#### UC-RP2: Source delivery proceeds while a candidate is verified

```gherkin
Given a release operator has an attempt verifying a captured source revision
When later source changes are delivered
Then the attempt continues against its captured revision
And its published release identifies the same candidate that passed verification
And the later source changes remain eligible for a later release
```

#### UC-RP3: Publication requires complete candidate proof

```gherkin
Given a release operator has a prepared candidate
When its release checks or full installation proof fail
Then no release is published for that candidate
And the operator can inspect the failed stage's evidence
And the previous successful release remains the comparison baseline
```

#### UC-RP4: A dry-run exercises the release gates without publication

```gherkin
Given a release operator requests a dry-run with releasable changes
When candidate preparation and verification succeed
Then the operator receives the candidate identity and verification results
And no release is published and no publication baseline advances
```

#### UC-RP5: Assessment size does not silently discard change coverage

```gherkin
Given a release inspector receives a change interval larger than one context
When it assesses the interval through bounded evidence reads
Then it reports whether the assessment completed
And an incomplete assessment cannot authorize publication
```

#### UC-RP6: Publication recovery retains the proved candidate

```gherkin
Given a release operator has an attempt interrupted during publication
When that publication is retried
Then recovery reconciles the same version and proved candidate
And an existing conflicting version stops recovery with the conflict visible
And completed publication becomes the next comparison baseline
```

#### UC-RP7: Automatic publication requires its own complete validation

```gherkin
Given a release operator has a completed baseline
And no full automatically assessed dry-run of a real releasable interval has succeeded
When an automatically assessed attempt runs
Then automatic publication remains inactive
And a no-change result or manual-version proof leaves that prerequisite pending
And automatic activation requires retained evidence of its successful full dry-run
```

#### UC-RP8: An explicit version supplies a repeatable manual release decision

```gherkin
Given a release operator supplies a valid newer semantic version for remote main
When the manually dispatched attempt captures its source
Then the supplied version bypasses AI version selection
And an evidence-grounded AI summary is requested when a provider can supply one
And unavailable AI summary leaves deterministic commit notes as the fallback
And the supplied version is bound to the final candidate
And publication requires successful lint and full installer proof of that candidate
And a later explicit version can use the same path for a subsequent release
```

#### UC-RP9: Both release paths retain the complete commit list

```gherkin
Given a release operator has a captured source and its completed baseline
When notes are generated for an automatic or manually versioned candidate
Then every commit in that interval has its subject and commit link in the notes
And automatic notes also contain the selected inspector summary
And manual notes also contain an AI summary when one is available
And unavailable AI summary does not omit commits from manual notes
And the proved candidate changelog and published release use the same section
```

#### UC-RP10: Explicit-version publication remains available without AI

```gherkin
Given a release operator supplies a valid explicit version
And neither provider can supply a valid release summary
When the captured candidate passes its required verification
Then publication can use the supplied version and complete deterministic notes
And unsuccessful summary attempts remain visible
And no automatic version assessment is fabricated
```

<!-- planned:owned-release-execution -->

#### UC-RP11: One setting selects release execution

```gherkin
Given a human release operator has compatible owned and hosted execution targets
When the operator changes the repository execution setting
Then subsequent Linux release stages use the selected target
And changing back requires no workflow rewrite
And an unavailable selected target produces a visible failure
```

<!-- /planned:owned-release-execution -->

### Cross-context references

- Installation proof consumes
  `local/projects/teleclaude/spec/feature/reconciliation/fresh-machine-bootstrap`.
- Release consumers retain their installation authority under
  `local/projects/teleclaude/spec/feature/reconciliation/channel-gated-self-update`.

## Known caveats

- Native Claude permissions prevent model-tool disclosure; stream validation
  observes tool activity afterward and cannot undo a read. Private file modes
  do not separate the client from controller files under the same runner UID.
  The local managed-policy checker covers on-disk policy sources, not every
  possible effective server-managed policy source.
- The Claude inspector adapter's internal setup and process catches retain
  generic diagnostic text. These returned failure outcomes do not carry
  classified exception metadata into the controller handlers; their owner is
  `run_claude_inspection` in `tools/release/claude_inspector.py`.
- A fresh-machine proof on one operating system establishes neither another
  operating system's installation nor an upgrade from an earlier release.
- A no-change dry-run establishes the no-release path; exercising later stages
  requires a candidate with releasable changes.
- Subscription credential readiness and refreshed credential persistence are
  prerequisites of automatic inspection, separate from repository App installation.
- Published candidate and proof evidence remains interpretable across owned
  record migrations; the published commit and tag are immutable. Migration
  behavior is owned by `sdlc/policy/backward-compatibility-hygiene`.
