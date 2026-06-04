---
id: 'project/spec/feature/session_mirrors/session-summary-generation'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
description: 'Best-effort one-paragraph LLM summary computed at mirror creation. Truncates the conversation, calls the shared summarizer, and stores the result on the mirror record. Failures are swallowed so the mirror still lands.'
---

# Session Summary Generation — Spec

## Required reads

- @docs/project/spec/domain/session_mirrors.md

## What it is

`telec history list` and downstream UIs lean on a short text blurb to give
operators something readable next to the title. The session_mirrors
service computes that blurb at mirror creation / refresh time by
truncating the `conversation_text` to 4000 characters, asking the shared
summarizer LLM for a one-paragraph summary, and storing the result on
the mirror's `summary` field. The summarizer call is fully synchronous
from the extractor's perspective — the synchronous extractor drives the
async summarizer call inline.

Summary generation is BEST EFFORT. Any exception from the summarizer (LLM
timeout, network failure, schema parse error, missing credentials) is
caught, a debug log line is emitted, and `summary` is set to None. The
mirror is still upserted with whatever it produced. The summary is never
retried later; subsequent reconciliation passes will regenerate it
whenever the mirror itself is rebuilt.

## Canonical fields

### Behavioral contract

#### Input truncation and prompt shape

```
Given a non-empty conversation_text
When summary generation runs
Then the first 4000 characters of conversation_text become the prompt body
And the prompt explicitly asks for "a concise one-paragraph summary"
And the shared summary schema and response parser are passed to the summarizer
```

#### Empty conversation short-circuits

```
Given conversation_text is empty
When summary generation runs
Then the function returns None without invoking the summarizer
```

#### Best-effort failure handling

```
Given the summarizer raises any exception (timeout, network, schema parse, etc.)
When summary generation catches the exception
Then a debug log "Mirror summary generation failed (best-effort skip)" is emitted
And the function returns None
And the surrounding extractor continues to upsert with summary=None
And the mirror is still written
```

#### Persistence

```
Given the summarizer returns a string
When the mirror is built
Then the mirror's summary field holds the returned string
And the upsert writes it to the store
And subsequent reads (detail lookup, listing) include the value
```

#### Synchronous bridge from sync extractor

```
Given the synchronous extractor is called from a synchronous context (reconciliation worker)
When summary generation is invoked
Then the async summarizer call is driven to completion inline
And the call is fully complete before the extractor proceeds to the upsert step
```

## Known caveats

- The summary call is synchronous from the extractor's perspective. A
  slow summarizer extends mirror generation latency proportionally — the
  pass's processed count grows but each individual generation blocks on
  the LLM call.
- The 4000-character truncation is byte-exact on string slicing, not
  token-aware. A long single-turn message can dominate the prompt.
- A successful summary on one pass and a failed summary on the next pass
  produces a mirror with summary = NULL, overwriting the previously
  successful value. There is no preserve-on-failure logic.
- The `created_at` field is preserved across re-extractions, but
  `summary` is regenerated on every successful pass. A summary may
  legitimately change between two passes for the same transcript.
- The synchronous extractor drives an async call inline, so it cannot be
  invoked from an already-running event loop without first off-loading
  to a thread — which is how the async surfaces of the session_mirrors
  service invoke it.
