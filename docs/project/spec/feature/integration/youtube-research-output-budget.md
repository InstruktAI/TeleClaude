---
description: YouTube research results remain within an agent-requested context budget without requiring transcripts.
delivered_by:
  - align-scripts-runtime-boundary
---

# YouTube Research Output Budget — Spec

## What it is

The integration context provides one canonical YouTube research command for
agents and in-process consumers. A requested character cap limits the complete
serialized result, including when transcript retrieval is disabled, without
triggering hidden network work.

## Canonical fields

- The public command and every in-process consumer use one implementation owner.
- A character cap applies to the serialized video results, not only transcript
  text.
- Enforcing the cap never enables transcript retrieval implicitly.

### Use cases

<!-- planned:align-scripts-runtime-boundary -->
#### UC-YT1:

```gherkin
Given an agent requests YouTube research results with a character cap
And one or more results have no transcript
When the serialized results exceed that cap
Then results are omitted from largest serialized payload to smallest until the returned results fit the requested budget
And transcript retrieval is not performed solely to enforce the budget
```
<!-- /planned:align-scripts-runtime-boundary -->
