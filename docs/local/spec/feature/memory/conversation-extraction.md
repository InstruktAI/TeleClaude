---
description: Extract a stretch of conversation into memories about the person it was with and business insights for the home it belongs to — judged by a model through memory's fixed prompts, recorded as one pass.
delivered_by:
  - help-desk-idle-memory-cycle
---

# Conversation Extraction — Spec

## Required reads

- @docs/local/spec/domain/memory.md

## What it is

The owner of a conversation hands memory a stretch of it, together with who the
conversation was with and which home it belongs to. Memory asks a model, through
its own fixed extraction prompts, what is worth keeping, through two lenses:

- **About the person** — durable things worth knowing the next time they write:
  preferences, their situation, how they like to communicate, what they are
  still waiting on.
- **Business insights** — what the conversation shows the home: requests for
  what does not exist, complaints, recurring confusion, sentiment, mentions of
  alternatives.

Neither lens records project knowledge or decisions
(`local/projects/teleclaude/spec/domain/memory`). Memory records what the model
returned as one **pass**, in one transaction: memories about the person under
the namespace, identity key, subject and principal handed over; business
insights under the home's namespace and subject, with no identity key. The
caller keeps its own bookkeeping of how far into the conversation it has
extracted.

## Canonical fields

### Use cases

#### UC-CX1: A pass is recorded whole

```gherkin
Given a conversation owner hands memory a stretch of conversation, the person it was with, and the home it belongs to
When memory extracts it
Then every memory the model judged worth keeping is recorded, under the names the owner handed over, in one transaction
And the owner is answered only after the pass was recorded
```

#### UC-CX2: A failed pass leaves nothing behind

```gherkin
Given a pass that fails, whether the model call fails or recording fails
When the failure occurs
Then no memory of that pass is recorded
And the owner is told the pass failed, so it can extract the same stretch again later
```

#### UC-CX3: A conversation with nothing worth remembering records nothing

```gherkin
Given a stretch of conversation in which the model finds nothing worth keeping
When memory extracts it
Then no memory is recorded
And the owner is answered that the pass completed
```

#### UC-CX4: Without a known person, only business insights are recorded

```gherkin
Given a stretch of conversation handed over without an identity for the person it was with
When memory extracts it
Then no memory about the person is recorded
And business insights are recorded as for any other pass
```

### Cross-context references

- **agent_runtime** — the desk idle cycle owns the conversation: it reads it from
  the session's transcript chain, hands it over, and advances its extraction
  marker after a completed pass
  (`local/projects/teleclaude/spec/feature/agent_runtime/desk-conversation-continuity`).
- **identity** — supplies the person's identity key and principal that memory
  records as handed over
  (`local/projects/teleclaude/spec/feature/memory/identity-key-ownership`).

## Known caveats

- **The judgment is the model's.** No code grades the conversation or the
  memories; what is recorded is what the model returned in the requested shape.
- **Memory does not read transcripts.** The conversation arrives as text from its
  owner.
- **A pass needs a configured summarizer provider.** With none available, every
  pass fails (UC-CX2).
- **A stop between recording and the owner's bookkeeping repeats a pass.** If the
  daemon stops after a pass was recorded but before its owner advanced its
  marker, the same stretch is extracted again and its memories are recorded a
  second time.
