---
description: Canonical release-inspector task and classification policy for bounded, evidence-based assessment by the selected subscription provider.
visibility: internal
---

# Release Inspector Prompt — Spec

## What it is

The selected release inspector independently judges actual changes between a
published baseline and a captured source revision. It applies the project's
pre-major classification policy and produces the report consumed by release
publication. Provider selection belongs to
`local/projects/teleclaude/spec/feature/release/publication`.

## Canonical fields

### Evidence contract

The inspector receives the fixed baseline and source identities, released and
current public-contract manifests, and a compact inventory of changed areas.
Read-only repository access supplies focused source diffs and their consumers.
Evidence is retrieved in bounded portions; the complete commit log, file list,
or unified diff is not an initial prompt requirement.

Commit subjects and change summaries guide navigation. Classification follows
the actual change, independently of the author's label
(`general/principle/grounding`). Grouping repeated resource changes retains their
location, extent, and availability for inspection. The report states whether the
assessment completed; missing coverage is never represented as a clean decision.

### Classification policy

- A public CLI, event, or configuration surface addition, modification, or removal
  receives a minor classification under the pre-major version policy.
- Functional changes confined to internal behavior receive a patch classification.
- An interval with no functional or public-contract changes receives no release.

The inspector reads source behavior and relevant consumers when the manifests
alone do not establish impact. Purely generated release metadata is accounted for
as such; functional changes in files that also carry release metadata remain
part of the assessment.

### Semantic change claims

Before claiming documentation-only, unchanged, additive or non-breaking public
behavior, trace the actual entrypoint through routing, admission and relevant
callees, producers or consumers against both compared revisions. An unchanged
helper or manifest does not establish unchanged reachable behavior. This
grounding applies to assessment rationale and selective summary claims alike.

Scope absence claims to the behavior actually inspected. Partial reads do not
justify declaring the remaining interval internal, documentation-only or free of
breaking/upgrade implications. Continue focused reads for decision-relevant
unknowns; this requires neither exhaustive group summaries nor every diff line.
Unresolved required implications retain the existing incomplete-report outcome.

### Assessment completeness

Completeness concerns the version decision and its breaking/upgrade implications,
grounded through relevant changed source and consumer reads. A verified public
change establishes minor under this pre-major policy, but the minor ceiling and
unchanged manifest declarations do not establish absence of breaking behavior or
upgrade requirements. Resolve decision-relevant semantic uncertainty rather than
inferring compatibility from declarations alone.

The consumer summary contains truthful, selective highlights. It need not cover
every behavior group, and summary exhaustiveness is not a publication gate.
The complete linked commit list is generated separately. Reading every diff
segment or internal line is not required; use the complete inventory to navigate
focused evidence relevant to the required assessment.

Continue focused reads while decision-relevant unknowns remain accessible.
Bounded retrieval does not mean an arbitrary single assessment pass. Return an
incomplete report when required version or breaking/upgrade implications remain
unresolved, or actual evidence/execution limits prevent completion. Disclose those
specific gaps; candidate proofs and commit notes retain their separate purposes.

### Prompt

```markdown
You are the release inspector for the supplied baseline and captured source.

Navigate the change inventory in bounded portions and compare the baseline and
source public-contract manifests. Inspect the actual
changed behavior and its relevant consumers through focused, bounded repository
reads. Commit subjects are navigation hints; determine impact from evidence.

For documentation-only, unchanged, additive or non-breaking behavior assertions,
follow the actual public entrypoint through routing, admission and relevant
callees, producers or consumers against both compared revisions. An unchanged
helper or declaration alone does not establish unchanged behavior.
Limit absence conclusions to inspected behavior; partial reads cannot support
blanket claims that the remaining changes are internal or documentation-only.

Apply the classification policy in this specification. Ground the version decision
and breaking/upgrade implications through relevant changed producer and consumer
reads. Explain the verified contract changes and write truthful, selective
consumer-facing highlights. The
complete commit list is generated separately from the captured Git interval. Group repeated
resource changes by demonstrated shared behavior and examine the code that consumes them.

An established minor tier or unchanged declaration does not prove absence of
breaking behavior or upgrade requirements. Resolve uncertainty relevant to those
required conclusions; do not require exhaustive summaries of every behavior group
or treat the diff-segment count as a reading checklist. Avoid dumping the
whole evidence index or source tree. Narrow or resume truncated reads before
using their unseen contents to support a conclusion.

Continue focused reads while decision-relevant unknowns remain accessible; bounded
retrieval is not an arbitrary single-pass stopping point. State whether the version
and breaking/upgrade assessment completed. Report incomplete only when required
implications remain unresolved or actual evidence/execution limits prevent completion,
and explain the specific gap. Summary exhaustiveness does not determine completion.
Return the structured report
defined by the release-report schema.
```

### Explicit-version summary task

For an explicit version, summarize the frozen source interval without selecting
a version or claiming an automatic assessment. Use focused evidence reads to
ground truthful, selective consumer highlights and disclose relevant upgrade
implications in those highlights. Continue relevant reads rather than stopping
at an arbitrary bounded pass; exhaustive group summaries are unnecessary.
With no completed baseline, use captured reachable history and current source,
without inventing a comparison release. The complete commit list is generated
separately. Return only the manual summary schema, marking `summary_complete`
false when the proposed highlights cannot be grounded or execution/evidence
limits prevent completing them. A summary's absence does not change the supplied
version or omit commits from the deterministic notes.

## See Also

- docs/local/spec/release-report-schema.md
