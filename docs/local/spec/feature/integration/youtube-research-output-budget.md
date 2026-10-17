---
description: YouTube research results remain within an agent-requested context budget
  without requiring transcripts.
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

#### UC-YT1: An agent gets useful research within its requested context budget

```gherkin
Scenario: Keep research within the requested budget without fetching transcripts
  Given an agent requests YouTube research within a character budget and transcript retrieval is off
  When the serialized video results exceed the budget
  Then the returned results fit within the requested budget
  And transcript retrieval is not performed solely to meet that budget
```
