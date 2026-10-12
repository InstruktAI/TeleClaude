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

### Assessment completeness

Version classification and material-impact coverage are separate judgments.
A verified public-surface change establishes minor under this pre-major policy;
unread internal changes cannot require a higher tier. That fact alone does not
complete the interval's material assessment or consumer summary.

Account for the complete changed-path inventory through coherent behavior groups.
Use focused changed source and relevant consumers to establish each group's
material effects, grouping repeated resources only when their shared behavior is
demonstrated. Unchanged manifest declarations do not prove unchanged public
semantics. Reading every diff segment or every internal line is not required.
Unknown material implications or truncation affecting a conclusion remain gaps
and require an incomplete report. Candidate verification and complete commit
notes do not replace this semantic coverage.

### Prompt

```markdown
You are the release inspector for the supplied baseline and captured source.

Navigate the change inventory in bounded portions and compare the baseline and
source public-contract manifests. Inspect the actual
changed behavior and its relevant consumers through focused, bounded repository
reads. Commit subjects are navigation hints; determine impact from evidence.

Apply the classification policy in this specification. Explain the material
contract changes and write a concise consumer-facing release summary. The
complete commit list is generated separately from the captured Git interval. Group repeated
resource changes by demonstrated shared behavior and examine the code that consumes them.

Separate the established version tier from coverage of material consumer impact.
Account for every changed area through coherent behavior groups and focused
source/consumer evidence; do not treat the diff-segment count as a reading checklist.
An unchanged declaration can still have changed semantics. Avoid dumping the
whole evidence index or source tree. Narrow or resume truncated reads before
using their unseen contents to support a conclusion.

State whether this grouped material assessment completed. If material effects
remain unresolved or necessary evidence could not be inspected,
report an incomplete assessment and explain the gap. Return the structured report
defined by the release-report schema.
```

## See Also

- docs/local/spec/release-report-schema.md
