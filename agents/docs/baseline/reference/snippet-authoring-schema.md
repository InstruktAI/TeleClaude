# Snippet authoring schema

ONLY for NON baseline snippets will we write ON THE TOP the frontmatter fields:

```yaml
---
id: teleclaude/guide/how-to-do-x
type: guide
scope: project
description: How to do X in TeleClaude.
---
```

Then we will have markdown headers and sections as follows:

1. Title header (single #)
2. Required reads: list hard reading dependencies as inline `@` references.
3. Main content structure per taxonomy (write header for each)

- Principles: Principle, Rationale, Implications, Tensions
- Architecture / Concept: Purpose, Inputs/Outputs, Invariants, Primary flows, Failure modes
- Policy / Standard: Rule, Rationale, Scope, Enforcement or checks, Exceptions or edge cases
- Procedure / Checklist / Guide: Goal, Preconditions, Steps, Outputs, Recovery
- Reference / Example: What it is, Canonical fields, Allowed values, Known caveats

4. See also (optional): list soft reading dependencies as plain text references (no `@`).
