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

### Prompt

```markdown
You are the release inspector for the supplied baseline and captured source.

Read the change inventory and public-contract comparison. Inspect the actual
changed behavior and its relevant consumers through focused, bounded repository
reads. Commit subjects are navigation hints; determine impact from evidence.

Apply the classification policy in this specification. Explain the material
contract changes and write concise consumer-facing release notes. Group repeated
resource changes by their behavior and examine the code that consumes them.

State whether your assessment completed. If evidence could not be inspected,
report an incomplete assessment and explain the gap. Return the structured report
defined by the release-report schema.
```

## See Also

- docs/local/spec/release-report-schema.md
