---
id: 'project/spec/feature/session_mirrors/session-summary-generation'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
status: 'actual'
applies_to: 'v1'
description: 'Best-effort one-paragraph LLM summary computed at mirror creation. Truncates the conversation, calls the shared summarizer, and stores the result on the mirror row. Failures are swallowed so the mirror still lands.'
---

# Session Summary Generation — Spec

## Required reads

- @docs/project/spec/domain/session_mirrors.md

## What it is

`telec history list` and downstream UIs lean on a short text blurb to give
operators something readable next to the title. The mirror generator computes
that blurb at mirror creation / refresh time by truncating the
`conversation_text` to 4000 characters, asking the shared summarizer LLM for
a one-paragraph summary, and storing the result on the mirror row's
`summary` column. The call is fully synchronous from the generator's
perspective — it uses `asyncio.run` to drive the async summarizer call from
inside `generate_mirror_sync`.

Summary generation is BEST EFFORT. Any exception from the summarizer (LLM
timeout, network failure, schema parse error, missing credentials) is caught,
a debug log line is emitted, and `summary` is set to `None`. The mirror is
still upserted with whatever it produced. The summary is never re-tried
later; subsequent reconciliation passes will re-generate it whenever the
mirror itself is rebuilt.

## Canonical fields

### Behavioral contract

#### Input truncation and prompt shape

```
Given a non-empty conversation_text
When _generate_session_summary runs
Then the first 4000 characters of conversation_text become the prompt body
And the prompt explicitly asks for "a concise one-paragraph summary"
And the shared SUMMARY_SCHEMA + _parse_summary_response are passed to _call_summarizer
```

#### Empty conversation short-circuits

```
Given conversation_text is empty
When _generate_session_summary runs
Then the function returns None without invoking the summarizer
```

#### Best-effort failure handling

```
Given the summarizer raises any exception (timeout, network, schema parse, etc.)
When _generate_session_summary catches the exception
Then a debug log "Mirror summary generation failed (best-effort skip)" is emitted
And the function returns None
And the surrounding generator continues to the upsert step with summary=None
And the mirror is still written
```

#### Persistence

```
Given the summarizer returns a string
When generate_mirror_sync builds the MirrorRecord
Then record.summary holds the returned string
And upsert_mirror writes it to the mirrors.summary column
And subsequent reads (get_mirror, list_mirrors) include the value
```

#### Synchronous bridge from sync generator

```
Given generate_mirror_sync is called from a synchronous context (worker reconciliation)
When _generate_session_summary is invoked
Then asyncio.run drives the async _call_summarizer call
And the call is fully complete before generate_mirror_sync proceeds to the upsert
```

### V1 implementation pointers

- `teleclaude/mirrors/generator.py:_generate_session_summary` — best-effort wrapper.
- `teleclaude/mirrors/generator.py:_build_mirror_summary_prompt` — prompt builder with 4000-char truncation.
- `teleclaude/mirrors/generator.py:_SUMMARY_MAX_INPUT_CHARS` — 4000 truncation limit.
- `teleclaude/mirrors/generator.py:generate_mirror_sync` — call site that sets `record.summary`.
- `teleclaude/core/summarizer.py:_call_summarizer` — shared async summarizer entry point.
- `teleclaude/core/summarizer.py:SUMMARY_SCHEMA` / `_parse_summary_response` — schema/parser passed in.

## Known caveats

- The summary call is synchronous from the generator's perspective. A slow
  summarizer extends mirror generation latency proportionally — the worker
  pass's processed-count grows but each individual generation blocks on the
  LLM call.
- The 4000-character truncation is byte-exact on string slicing, not
  token-aware. A long single-turn message can dominate the prompt.
- A successful summary on one pass and a failed summary on the next pass
  produces a mirror with `summary = NULL`, overwriting the previously
  successful value. There is no preserve-on-failure logic.
- The `created_at` column is preserved across re-extractions, but `summary`
  is regenerated on every successful pass. A summary may legitimately
  change between two passes for the same transcript.
- `asyncio.run` inside the generator means the generator cannot be called
  from an already-running event loop without first off-loading via
  `asyncio.to_thread` (which is exactly how `generate_mirror` and the
  worker invoke it).
