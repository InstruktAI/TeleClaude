# session-memory-extraction — Input

## Goal

Wire up the existing session memory extraction job to actually extract cross-project personal memories from mirror conversation deltas.

## Context

The infrastructure exists but the extraction methods are stubbed:
- Idle detection (30min) in maintenance_service.py — marks sessions via last_memory_extraction_at ✅
- Job eligibility logic in jobs/session_memory_extraction.py — finds sessions needing extraction ✅  
- Identity key resolution from adapter metadata ✅
- Memory storage API (MemoryStore.save_observation) ✅
- LLM call pattern with structured outputs (summarizer.py: _call_summarizer, Claude Haiku + OpenAI fallback) ✅
- Mirror generator produces clean conversation_text from raw transcripts ✅

## What needs to happen

1. **_read_transcript_delta()** — Query mirror for session, filter structured messages by timestamp > last_memory_extraction_at. Return only new conversation text. No raw transcript file access — use the mirror's already-cleaned output.

2. **_extract_personal_memories(transcript_delta, identity_key, session)** — LLM prompt against the delta. Extraction focus: cross-project personal facts about the person (preferences, communication style, domain knowledge, recurring needs). NOT session-specific details. Use _call_summarizer pattern with structured output schema mapping to ObservationInput fields (type, title, narrative, facts, identity_key).

3. **_extract_business_memories(transcript_delta, session)** — LLM prompt. Extraction focus: project-scoped business facts (product feedback, pain points, feature requests, domain context). Saved without identity_key (shared across project).

4. **_extract_and_publish_actionable_items(transcript_delta, session)** — LLM prompt. Extract bugs, feature requests, follow-ups. Publish to channels subsystem.

5. **Remove /compact injection** — dead code, no handler exists for it.

## Architecture

Session close → mirror created (conversation_text, clean)
30min idle → maintenance_service marks session
Cron job fires → reads mirror delta (timestamp-filtered) → LLM extraction → MemoryStore.save_observation()

Memories are cross-project (identity_key scoped to person, not session). They get injected at next session start via the already-working memory injection hook.

## Key files

- jobs/session_memory_extraction.py — the job with stubbed methods
- teleclaude/core/summarizer.py — working LLM call pattern to follow
- teleclaude/mirrors/generator.py — mirror generation, clean conversation_text
- teleclaude/mirrors/store.py — mirror queries
- teleclaude/memory/store.py — MemoryStore.save_observation()
- teleclaude/memory/types.py — ObservationInput, ObservationType
- teleclaude/services/maintenance_service.py — idle detection (_check_idle_compaction)
- teleclaude/utils/transcript/_extraction.py — extract_structured_messages() with timestamps
