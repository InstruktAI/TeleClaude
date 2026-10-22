---
description: Immutable release candidates, independently advancing main, native provider jobs, and recoverable publication state.
visibility: internal
---

# Release Publication — Design

## Purpose

Repository release tooling implements
`local/projects/teleclaude/spec/feature/release/publication`. It owns the attempt,
candidate, provider outcomes, proof references, and publication transaction. It
consumes the installer and update contracts through their existing boundaries.

## Inputs/Outputs

- An attempt captures canonical main and the previous completed publication
  after acquiring the release stream's serialization.
- Inspection consumes the captured source, released public-contract baseline,
  and bounded repository evidence. It produces a complete assessment or a
  provider failure, with every attempted provider's outcome retained.
- Preparation produces a final candidate and an incremental Git bundle, together
  with source, baseline, tree, version, and artifact identities.
- Verification produces lint, runtime acceptance and disposable-machine installation proof bound to the candidate.
- Publication produces the exact candidate tag, its GitHub Release, retained
  evidence, and a mainline metadata reconciliation when main has advanced.
- A manually supplied version produces an operator-decided candidate through
  the same candidate and proof boundary, with deterministic commit notes and no
  version assessment. The same isolated provider order attempts an optional
  summary; unavailable summaries retain their outcomes and leave deterministic
  notes publishable. A first manual publication establishes a baseline.

## Invariants

### Candidate and mainline

Let the captured source be S, the previous published release B when present, the
proved candidate R, and main's tip at publication H. Capture verifies that S
contains B whenever a completed baseline exists;
it resolves canonical main at execution time rather than using a stale queued
event revision. R is a normal child of S. Its tree differs from S only in the
release-owned artifacts and application-version metadata.

When H equals S, publication advances main to R. Otherwise it constructs a
reconciliation commit M with parents H and R. M preserves H's source,
dependency declarations, and resolved dependencies. It changes only the
application-version fields and release-owned manifest/changelog metadata.
Whole candidate packaging files are not a reconciliation operation.

The tag always identifies R. Main and the tag are updated atomically without a
forced main overwrite. A concurrent advancement rebuilds only M from the new H.
R, its version, assessment, and proof remain fixed. M is metadata reconciliation,
not a second claimed installation proof.

### Baseline and evidence

Only a completed GitHub publication advances B. Its source provenance identifies
the next comparison; ancestry alone does not choose the baseline. Source
comparison normalizes only release-owned metadata, preserving dependency changes
in files that also contain the application's version.

The candidate bundle contains the objects needed beyond the captured source,
which downstream jobs fetch explicitly before importing it. The full repository
bundle used inside the disposable machine remains local to that proof run.
Transferred evidence is addressed by exact artifact identity and checked against
the recorded digest and candidate, rather than accepted by a matching filename.

### Decision and note ownership

The attempt records whether the version decision came from complete automatic
assessment or an explicit manual input. Both paths use the same candidate and
publication owners. The manual decision carries its supplied semantic version;
automatic decisions carry the selected provider assessment. Manual decisions do
not fabricate inspector reports or successful provider attempts
(`general/principle/grounding`).

The pinned git-cliff action renders the complete commit list from captured refs
using the repository-owned template. Its range and version inputs are validated
before invocation. Untrusted commit text and inspector summaries remain data,
and do not enter an executable command string (`sdlc/policy/security-awareness`).
The candidate owner combines automatic summaries with the generated commit notes
and freezes the resulting section before lint and proof. Manual candidates add a
strict, complete summary when available, independently of their version decision.
Summary selection and provider outcomes are retained separately from automatic
assessment metadata. Version selection stays with the recorded decision;
note generation does not reclassify the change.

Owned release records pass through a forward migration boundary before domain
use (`sdlc/policy/backward-compatibility-hygiene`). Historical evidence retains
its original source, candidate, proof and decision identity. Migration establishes
neither a new inspection nor authority to recreate a retired execution path.
Published Git objects and tags stay immutable; in-memory normalization is
separate from their original serialized evidence and integrity hashes.

### Execution placement

The release workflow names a GitHub-hosted runner for every job: hosted Ubuntu
for the Linux stages and outcome reporting, hosted arm64 macOS
(`macos-latest`) for installation proof. No job targets a self-hosted runner,
and no repository setting selects a destination. Placement changes neither the
release stream's serialization nor artifact, candidate and credential-settlement
authority (`local/projects/teleclaude/spec/feature/release/publication`).

Each hosted runner is a virtual machine the provider creates for one job and
decommissions after it; hosted arm64 macOS runners provide no nested
virtualization.
The proof harness installs the candidate directly on its own runner, as the
runner's user, from a repository bundle it builds locally. Release tooling
keeps no host admission, machine ownership record, disposal confirmation or
guest routing; an interrupted attempt leaves its successor nothing to recover.
Job ordering, the serialized attempt stream and exact-artifact binding carry
every guarantee between jobs.

The harness refuses to start unless `RUNNER_ENVIRONMENT` is `github-hosted`
and no TeleClaude platform home, daemon socket or canonical checkout exists on
the machine. The step that runs the harness receives no repository token, and
every installation and probe command runs with the runner user's login
environment, never the job's. Artifact download and upload run as separate
steps that hold the job's token. A proof job that is never assigned, times out
or loses its runner produces no successful proof receipt, and the existing
proof-success requirement then withholds publication. The harness drives
installation and service lifecycle through the sanctioned make surface
(`local/projects/teleclaude/policy/agent-service-control`).

<!-- planned:issue-128 -->

Runtime acceptance uses its own fresh hosted Ubuntu job, separate from candidate
preparation and credential-bearing finalization. The existing immutable artifact
handoff carries candidate identity into that job and its report into finalization;
finalization checks the job outcome and report against the same candidate before
the existing installer proof and publication gates. The acceptance job executes
no earlier or later token-bearing release command. This composition is owned by
`local/projects/teleclaude/spec/feature/release/publication`; its runtime side is
`local/projects/teleclaude/design/architecture/runtime-acceptance/overview`.

<!-- /planned:issue-128 -->

### Credentials and inspection

Capture freezes one source/baseline attempt and bounded evidence artifact before
inspection. A fresh Ubuntu job runs Codex; a separate fresh Ubuntu
job runs Claude only when Codex has no eligible complete report with confirmed
credential settlement. Selection consumes exact artifact identities, digests and
inventories. Explicit versions request a distinct summary report; unchanged
automatic source bypasses provider jobs. Missing,
failed, skipped or cancelled primary job evidence remains an observed failure,
with no invented client exit or settled-auth claim. Claude does not depend on a
cleanup signal from another machine.

Each provider runs its pinned native CLI as the ordinary runner UID. Its
job installs only its own client. Private controller and client configuration
live outside immutable model-readable evidence in ordinary job temporary
storage; existing checkout and home permissions are unchanged. There is no
cross-provider UID switching, privileged filesystem transfer, copied interpreter,
shared public namespace, ownership claim or staged launcher. Child environments
contain only the adapter's explicit allowlist; prompts travel byte-exact through
stdin and credentials never enter argv. Owned private directories/files retain
private permissions and configuration is read-only. Their declarations and owned
filesystem checks belong to `tools/release/isolated_inspection.py` and the
provider configuration adapters.

The Codex job installs compatible distribution bubblewrap and Ubuntu's scoped
AppArmor user-namespace profile using the vendor-supported setup, without
changing global kernel/LSM restrictions. One untraced, credential-free readiness
check runs the pinned native sandbox with the inspection permission profile and
managed requirements using the fixed startup operand owned by
`tools/ci/inspector_sandbox_preflight.py`. Fixed follow-up checks read
captured public evidence, refuse reads of synthetic private controller/auth-path
markers, and refuse a new evidence-file write. They use no credentials or
inference and remove only their own markers. Readiness requires all checks. It
retains native status, mechanical outcomes and output hashes. A failed fixed,
credential-free startup also retains bounded stderr with known credentials and
local paths redacted, so its ordinary native error remains actionable. Successful
startup and confinement checks retain no output bodies; no trace machinery,
environment, argv or configuration capture is collected. Failure records an unexpected
primary execution/platform outcome before credential restoration or auth use;
independent Claude fallback remains available. Startup readiness does not prove
an assessment or attribute a previous platform denial.

The trusted native clients retain authentication/refresh access outside their
model tools. Codex setup resolves the pinned npm platform package's native
executable and records that exact file in the existing private job receipt.
Its profile permits read access to that executable for the sandbox's inner stage,
alongside prepared evidence and the native minimal system runtime. It grants no
read access to the enclosing toolcache, Node installation or package directory.
Codex's exact managed filesystem/network/PID restrictions deny auth, controller, home and
process-credential paths. Its non-interactive `exec` command, permission profile,
requirements and approval settings remain explicit. Claude retains subscription-
compatible restricted safe mode, only Read/Grep/Glob tools, denied outside reads,
empty MCP configuration and managed customization checks. Source symlinks are
data. Unsupported policy, hooks, MCP or tools refuse rather than widening access.
Claude file-tool validation judges evidence containment, including absolute Glob
patterns with an unambiguous evidence-root prefix. Outside paths, parent
traversal, resolved symlink escapes and ambiguous absolute patterns refuse;
addressing syntax alone does not make a contained request unsafe.

Claude's native `StructuredOutput` capability produces report data rather than
file access. Tool requests/results correlate uniquely, in order, within session
and parent context. Only an explicitly SDK-rejected formatter may precede a valid
retry without accepting its malformed payload. Successful formatter input
strictly validates against the task's report schema; the complete terminal report matches its
confirmed formatter. Missing, duplicate, orphaned or ambiguous correlation
refuses. Read/Grep/Glob paths remain checked even on rejected tool attempts.

Each job owns bounded client/descendant lifetime and private-file cleanup before
its result artifact is eligible. Runner loss cannot supply successful cleanup or
auth settlement; fresh independent fallback does not need that machine to
recover. Codex auth checkpoints retain their serialized uncertainty semantics.
The seed-only crypto flow retains its job-temporary controller boundary.

Codex's managed login belongs to one serialized CI stream. Private Actions
artifacts retain only age-encrypted state; the stable decryption identity is a
repository secret available to the restore controller. Runtime model credentials
and storage/publication credentials have separate lifetimes and access.

`tools/ci/release_stage.py` owns checkpoint locations in controller auth storage.
The producers persist those locations in controller state and emit directory
outputs consumed directly by the release workflow's uploads. Report destinations
do not select checkpoint storage; upload wiring does not reconstruct its paths.

Restoration selects current settled authentication state through live artifact
and workflow-attempt metadata after serialization. The encrypted envelope binds
its generation, producing attempt, and predecessor. Ciphertext authentication,
archive integrity, and trusted producer identity are separate checks.

Before the client can refresh, the controller records the beginning of auth use.
After the client and its descendants finish, it settles the resulting cache and
retains an immutable encrypted final state even when inspection failed. A later
potentially refreshing attempt without settlement makes older state unusable.
Initial seeding and reseeding are explicit operations, separate from ordinary
restoration failure. A verified explicit reseed bounds earlier uncertainty for
its selected chain, including later settled descendants. Recovery follows exact
verified predecessor and begin records; unrelated reseeds do not supply that
boundary, and unfinished use at or after it remains a refusal. Required chain
records that are missing, expired or conflicting stop restoration. Key changes
and seeding use the same serialized stream.

## Primary flows

### Automatically assessed attempt

1. Resolve any incomplete owned publication before capturing another baseline.
2. Capture S and B. An unchanged normalized source finishes successfully.
3. Prepare and retain the compact inventory and public-contract comparison once.
   Run Codex on its fresh Ubuntu job, then Claude on a separate fresh job only if
   Codex's inspection or credential settlement is unsuccessful. Select their
   exact artifact-bound outcomes, retaining runner failure as unsuccessful evidence.
   A valid complete no-release result finishes successfully.
4. Generate complete commit notes with git-cliff and add the selected assessment's
   summary. Prepare R with final version and lock coherence, released manifests,
   and the cumulative published changelog before committing R.

5. Run lint and full runtime acceptance on R on hosted Ubuntu, then the full
   existing installer harness on a hosted macOS runner. Retain the candidate
   identity and evidence.

6. A dry-run returns these results. Publication reconciles current H, atomically
   updates the tag and main, then creates the GitHub Release for R and attaches
   its provenance and proof references.

### Explicit-version attempt

A manual dispatch with an explicit valid newer version captures S and the
completed baseline when present. It records the operator decision and generates
the commit notes through the same git-cliff configuration. Frozen evidence feeds
the native Codex-first/Claude-fallback jobs with a summary-only task, including
captured reachable history when no baseline exists. A valid settled summary is
added before the complete notes; unsuccessful summary attempts remain visible
and the deterministic notes remain usable. Candidate preparation, lint, runtime acceptance, full installer
proof and publication consume the same identities as the automatic flow. A
manual dry-run finishes at proof. Automatic publication activation does not
supply or withhold authority for an explicit-version publication.

### Publication recovery

Remote references may have advanced before a release API response is received.
Recovery verifies the existing tag's candidate, restores its bound publication
receipt and proof, and completes the same publication. It neither chooses another
version nor interprets an unpublished tag as the completed baseline.

### Automatic publication activation

The checked-in automatic-publication setting gates automatically assessed
publication. Scheduled attempts remain dry-runs until the release maintainer
records a successful complete automatic-path validation over a real releasable
interval. Manual version selection and no-change outcomes do not establish that
validation. Every published candidate, from either decision path, still earns
its own lint, runtime acceptance and installer proof.

## Failure modes

- Invalid or non-increasing manual versions fail before candidate publication;
  an existing target tag belongs to publication recovery or is a conflict.
- Note generation errors, incomplete output or size limits stop the candidate
  rather than silently filtering its commit denominator.
- Provider failure remains visible after successful fallback. An unexpected fault
  remains repair work; fallback does not erase it. With no complete valid report,
  an automatic attempt cannot prepare a release candidate. An explicit-version
  attempt can proceed with deterministic notes and its recorded version decision.
- The provider controller's covered exception handlers retain classified
  phase/operation diagnostics and Codex adapter progress under the Inspector contract in
  `local/projects/teleclaude/spec/feature/release/publication`.
  An exception after entering Codex inspection can precede or follow client
  execution; absent result or settlement evidence does not prove no invocation.
  Failures handled inside the Claude inspector adapter return generic diagnostic
  text without supplying exception metadata to the controller's diagnostic writer.
- Failed proof leaves publication untouched and retains the failure evidence.
- A conflicting existing tag, unavailable proof receipt, unsupported atomic
  transport, or unresolved metadata conflict stops publication with its candidate
  preserved for recovery.
- A missing, expired, corrupt, untrusted, or unsettled authentication state is an
  explicit Codex-path failure. Recovery does not replay an older credential copy.
- Runner loss can interrupt the interval between token refresh and durable
  settlement; that uncertainty requires reseeding. Artifact retention and token
  lifetime are independent limits.
- A provider version or effective managed policy that cannot establish the
  required tool boundary fails inspection setup; it does not select permissive
  execution.
- Public-recipient encryption provides confidentiality and integrity, not producer
  identity or freshness. Those come from workflow provenance and serialization.
- Main reconciliation preserves ordinary channel ancestry. Exact enrollment from
  an arbitrary newer checkout remains subject to the existing updater limitation
  documented in
  `local/projects/teleclaude/spec/feature/reconciliation/channel-gated-self-update`.

## See Also

- docs/local/spec/feature/reconciliation/fresh-machine-bootstrap.md
- docs/third-party/codex-cli/ci-managed-auth.md
- docs/third-party/claude-code/restricted-inspection.md
- docs/third-party/git/commit-identity-and-atomic-push.md
- docs/third-party/uv/project-version-updates.md
- docs/third-party/git-cliff/changelog-generation.md
- docs/third-party/git-cliff-action/changelog-step.md

- docs/third-party/github-actions/hosted-macos-runners.md
