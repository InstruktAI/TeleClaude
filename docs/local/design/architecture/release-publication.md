---
description: Immutable release candidates, independently advancing main, isolated
  subscription inspection, and recoverable publication state.
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
- Verification produces lint, hosted runtime acceptance and disposable-machine installation proof bound to the candidate.
- Publication produces the exact candidate tag, its GitHub Release, retained
  evidence, and a mainline metadata reconciliation when main has advanced.
- A manually supplied version produces an operator-decided candidate through
  the same candidate and proof boundary, with deterministic commit notes and no
  inspector invocation. A first manual publication establishes a baseline.

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
and freezes the resulting section before lint and proof. Manual candidates use
the generated notes alone. Version selection stays with the recorded decision;
note generation does not reclassify the change.

Owned release records pass through a forward migration boundary before domain
use (`sdlc/policy/backward-compatibility-hygiene`). Historical evidence retains
its original source, candidate, proof and decision identity. Migration establishes
neither a new inspection nor authority to recreate a retired execution path.
Published Git objects and tags stay immutable; in-memory normalization is
separate from their original serialized evidence and integrity hashes.

### Credentials and inspection

The trusted controller supplies the resolved job temporary parent for both
controller-root creation and cleanup. Controller roots are proper resolved
descendants of that parent; creation rejects an existing root, and both paths
reject symlink roots. Cleanup verifies the root boundary before deleting provider
material (`sdlc/policy/security-awareness`).

Provider-private path resolution, containment and symlink checks, and exclusive
directory/file creation run together under the privileged controller filesystem
boundary. Descriptor-relative traversal refuses symlinks instead of requiring
the controller UID to search provider-owned directories. Provider directories
remain mode 0700; private files remain mode 0600, with read-only configuration
files mode 0444. Temporary input files remain in controller-owned mode-0700
staging and are removed after installation. Credential bytes never enter argv.

The isolated launcher consumes only the newline-delimited JSON environment frame
from the stdin descriptor, without buffering subsequent bytes. After `execve`,
the provider receives the original trailing stdin byte stream unchanged,
including empty input, embedded newlines and large prompts. Environment values
stay off argv; malformed environment frames fail before provider launch.

The trusted controller owns credentials, persistence, and artifact transport.
The inspector runs under a separate unprivileged identity with read-only source
access and provider-native tool permissions. Its tool processes cannot read the
authentication cache or controller state, reach control credentials, or write
the source. The Codex client retains its native authentication and refresh
capability outside its command sandbox.

Claude uses its native restricted non-interactive mode with only file-read,
search, and listing tools. The controller supplies complete indexed evidence
for the fixed source and baseline, including segmented diffs and deleted-file
content, so inspection needs no shell or GitHub token. Source and evidence are
controller-owned and immutable to the inspector identity. Source symlinks remain
data rather than links into the host filesystem.

Claude runtime authentication and private configuration stay outside every
model-readable working root. Native safe mode and an empty external-tool
configuration suppress discovered customizations; the effective managed policy
must also contain no unapproved executable integrations. The controller rejects
unsupported permissions or unexpected tools instead of widening access. Both
providers' descendants are settled before result transport or later privileged
operations. Native tool restrictions are not a claim that the vendor client
itself cannot use its own authentication.

Codex's managed login belongs to one serialized CI stream. Private Actions
artifacts retain only age-encrypted state; the stable decryption identity is a
repository secret available to the restore controller. Runtime model credentials
and storage/publication credentials have separate lifetimes and access.

Restoration selects current settled authentication state through live artifact
and workflow-attempt metadata after serialization. The encrypted envelope binds
its generation, producing attempt, and predecessor. Ciphertext authentication,
archive integrity, and trusted producer identity are separate checks.

Before the client can refresh, the controller records the beginning of auth use.
After the client and its descendants finish, it settles the resulting cache and
retains an immutable encrypted final state even when inspection failed. A later
potentially refreshing attempt without settlement makes older state unusable.
Initial seeding and reseeding are explicit operations, separate from ordinary
restoration failure. Key changes and seeding use the same serialized stream.

## Primary flows

### Automatically assessed attempt

1. Resolve any incomplete owned publication before capturing another baseline.
2. Capture S and B. An unchanged normalized source finishes successfully.
3. Prepare the compact inventory and public-contract comparison. Run Codex, then
   Claude only if Codex's inspection or credential settlement is unsuccessful.
   A valid complete no-release result finishes successfully.
4. Generate complete commit notes with git-cliff and add the selected assessment's
   summary. Prepare R with final version and lock coherence, released manifests,
   and the cumulative published changelog before committing R.
5. Run hosted lint and full hosted runtime acceptance on R, then the full
   existing installer harness in a disposable machine. Retain the candidate identity and evidence; clean up the machine.
6. A dry-run returns these results. Publication reconciles current H, atomically
   updates the tag and main, then creates the GitHub Release for R and attaches
   its provenance and proof references.

### Explicit-version attempt

A manual dispatch with an explicit valid newer version captures S and the
completed baseline when present. It records the operator decision and generates
the commit notes through the same git-cliff configuration, without invoking
providers or adding an AI summary. Candidate preparation, lint, hosted runtime acceptance, full installer
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
its own lint, hosted runtime acceptance and installer proof.

## Failure modes

- Invalid or non-increasing manual versions fail before candidate publication;
  an existing target tag belongs to publication recovery or is a conflict.
- Note generation errors, incomplete output or size limits stop the candidate
  rather than silently filtering its commit denominator.
- Provider failure remains visible after successful fallback. An unexpected fault
  remains repair work; fallback does not erase it. With no complete valid report,
  the attempt cannot prepare an ordinary release candidate.
- Codex preparation and Claude setup/execution catches retain bounded diagnostic
  evidence identifying the provider, phase, operation, exception type and any
  available errno or native command status. They do not serialize exception text,
  tracebacks, paths from exceptions, environment, argv or credential content.
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
