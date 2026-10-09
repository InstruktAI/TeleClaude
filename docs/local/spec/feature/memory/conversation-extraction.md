---
description: Record what an extraction worker took from a stretch of conversation — each pass recorded whole, once, with a receipt, through a surface only sanctioned extraction workers may use.
delivered_by:
  - help-desk-idle-memory-cycle
---

# Conversation Extraction — Spec

## Required reads

- @docs/local/spec/domain/memory.md

## What it is

An extraction worker reads a stretch of conversation, judges what is worth
remembering, and hands memory the result as one **pass**. Memory records the
pass and answers with a **receipt**. The worker's judgment — which observations
to keep, and which are already covered by documentation — is the worker's
(`local/projects/teleclaude/adr/0006-mandatory-dedup-against-doc-snippets` — codified knowledge is not
re-encoded as memory); memory owns recording what it was handed, and who may
record it (`local/projects/teleclaude/adr/0005-scraper-only-memory-writer` — only extraction workers write memory).

A pass carries:

- a **pass key** chosen by whoever started the extraction, identifying the
  stretch of conversation;
- how far into the conversation the pass reached;
- **personal observations** about the person the conversation was with, each
  recorded with the namespace, identity key, subject and principal handed over;
- **business observations**, each recorded with the namespace and subject handed
  over and no identity key.

The pass is recorded whole or not at all, and a pass key is recorded once. The
receipt names the pass key and how far the pass reached; whoever started the
extraction advances its own bookkeeping from it.

## Canonical fields

### Use cases

#### UC-CX1: A pass is recorded whole, with its receipt

```gherkin
Given an extraction worker hands memory a pass under a pass key not recorded before
When memory records it
Then every observation of the pass is recorded, together with a receipt for the pass key
And the receipt names how far into the conversation the pass reached
And the worker is answered with the receipt
```

#### UC-CX2: A repeated pass records nothing again

```gherkin
Given a pass key memory already recorded
When an extraction worker hands memory a pass under the same pass key
Then no observation is recorded
And the worker is answered with the receipt recorded for that pass key
```

#### UC-CX3: A pass that cannot be recorded leaves nothing behind

```gherkin
Given a pass that fails while it is being recorded
When the failure occurs
Then no observation of the pass and no receipt is recorded
And the worker is told the pass was not recorded
And the same pass key can be recorded later
```

#### UC-CX4: A pass with nothing worth remembering still completes

```gherkin
Given an extraction worker found nothing worth remembering in its stretch of conversation
When it hands memory an empty pass under a pass key
Then no observation is recorded
And a receipt for the pass key is recorded and returned
```

#### UC-CX5: Only a sanctioned extraction worker records a pass

```gherkin
Given a caller asks memory to record a pass
When the caller is not a daemon-started worker session with no person anywhere in its lineage
Then the pass is refused and nothing is recorded
And the refusal says that passes are recorded only by sanctioned extraction workers
```

#### UC-CX6: The receipt is readable by the daemon

```gherkin
Given a pass key
When the daemon asks memory for the receipt of that pass key
Then it receives the receipt when the pass was recorded
And it learns that no receipt exists when it was not
```

### Cross-context references

- **agent_runtime** — the desk idle cycle starts the extraction worker, chooses
  the pass key, and advances its marker from the receipt
  (`local/projects/teleclaude/spec/feature/agent_runtime/desk-conversation-continuity`).
- **identity** — resolves the facts memory's writer rule reads: whether the
  calling session was started by the daemon, carries the worker role, and has a
  person anywhere in its lineage. It also supplies the visitor's identity key
  and principal that memory records as handed over
  (`local/projects/teleclaude/spec/feature/memory/identity-key-ownership`).

## Known caveats

- **Memory does not judge.** It records the observations a pass carries;
  what to keep, and documentation overlap, were decided by the worker.
- **Memory does not read transcripts.** The worker reads the conversation;
  memory only receives observations.
- **Saving a single observation is unchanged.** The existing save path and its
  surfaces keep their behavior; only recording a pass is gated to extraction
  workers.
