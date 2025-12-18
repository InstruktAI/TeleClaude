# Agent Learning

> **Created**: 2025-12-17
> **Status**: Requirements

## Problem Statement

AI sessions receive static context (coding directives, testing directives, project AGENTS.md) but don't learn from corrections and preferences expressed during conversations. When Mo corrects an AI or expresses a preference, that knowledge is lost after the session ends. The next session makes the same mistakes.

We need a system that:
- Captures novel facts from conversations autonomously
- Filters out already-known information (no noise)
- Stores learned preferences for future sessions
- Operates without human intervention

## Goals

**Primary Goals**:

- Autonomous fact extraction from conversations (no human in loop)
- Non-blocking extraction (doesn't slow down conversation)
- Context-aware filtering (only extract novel facts, not already-known)
- Persistent storage of learned preferences
- Automatic injection into future sessions

**Secondary Goals**:

- Confidence scoring for learned facts
- Decay mechanism for stale/unused facts
- Project-specific vs global preference separation

## Non-Goals

- Real-time pattern matching or regex-based extraction
- Manual confirmation of learned facts
- Complex ontology or schema design
- Graph database or vector store (keep it simple: files)
- Sentiment analysis or emotion detection

## Architecture

### Two-Stage Pipeline

```
STAGE 1: Fast Extraction (UserPromptSubmit hook, async, non-blocking)
    Input: User message + known-facts summary
    LLM: Haiku-class (fast, cheap)
    Task: Extract ONLY novel facts not in known-facts
    Output: Append to tmp/learning-raw.jsonl (or empty if nothing new)

STAGE 2: Smart Synthesis (SessionStop hook, sync)
    Input: tmp/learning-raw.jsonl + full context
    LLM: Sonnet-class (smart)
    Task: Dedupe, merge, detect patterns, update LEARNED.md
    Output: Updated LEARNED.md (+ subfolder AGENTS.md), regenerated known-facts summary
    Cleanup: Delete tmp/learning-raw.jsonl
```

### File Locations

**Agent-agnostic. NOT in .claude/ folder.**

```
{project}/
├── AGENTS.md                # Project instructions, references LEARNED.md
├── LEARNED.md               # Project-level learned preferences (visible, capital)
├── tmp/                     # Ephemeral files (gitignored)
│   ├── learning-raw.jsonl   # Ephemeral, deleted after Stage 2
│   └── known-facts-summary.md  # For Stage 1 filtering
└── {subfolder}/
    └── AGENTS.md            # Module-specific facts (created by Stage 2 when relevant)
```

### Hierarchical Memory Placement

Stage 2 LLM determines WHERE to store each learned fact:

1. **Project-level** (`LEARNED.md`) - General preferences, coding style, communication
2. **Subfolder-level** (`{module}/AGENTS.md`) - Module-specific patterns, package-specific facts

**Examples:**
- "Prefers functions over classes" → `LEARNED.md`
- "The learning module uses event bus pattern" → `teleclaude/learning/AGENTS.md`
- "Use sonnet for synthesis in LLM utility" → `teleclaude/utils/AGENTS.md`

Stage 2 prompt must include context about WHICH folders were discussed to make scoping decisions.

### Fact Format (Semantic, Concise)

Stage 1 raw output:
```json
{"ts": "2025-12-17T01:50:00Z", "facts": ["Prefers X over Y", "Corrected: do Z"]}
```

### Stage 1 Prompt (Opinion Mining & Preference Extraction)

Use industry-standard NLP terminology for better LLM comprehension:

```
Perform opinion mining and preference extraction on the following user message.

Extract:
- Stated preferences (likes, dislikes, wants)
- Corrections (negations of previous behavior)
- Beliefs and opinions
- Stance on topics

Context - already known facts (do NOT re-extract these):
{known_facts_summary}

Output as semantic triples in natural language. One fact per line.
If no NEW extractable preferences or opinions, output: NONE

Message: {user_message}
```

### Stage 2 Prompt (Knowledge Synthesis with Scoping)

```
Perform knowledge synthesis on the following extracted facts.

Tasks:
- Deduplicate semantically similar facts
- Merge related facts into coherent statements
- Detect patterns (repeated corrections = strong preference)
- Compare against existing learned preferences
- Determine SCOPE for each fact: project-level or module-specific
- Output only NEW or UPDATED preferences with their target location

Scoping rules:
- General preferences (coding style, communication) → LEARNED.md (project root)
- Module-specific facts (about a specific folder/package) → {folder}/AGENTS.md
- Look at conversation context to determine which folders were discussed

Conversation context (folders mentioned/edited):
{folders_context}

Existing learned preferences:
{learned_md_content}

Raw extracted facts:
{raw_facts}

Output format:
For each fact, output:
FILE: {relative_path}
FACT: {the preference statement}

Example:
FILE: LEARNED.md
FACT: Prefers functions over classes

FILE: teleclaude/learning/AGENTS.md
FACT: Use event bus pattern for hook communication
```

LEARNED.md format (project root):
```markdown
# Learned Preferences

## Coding
- Prefers functions over classes
- Avoids type annotations for internal code
- Dislikes premature abstractions

## Communication
- Prefers concise responses
- Wants answers without summaries at end

## Testing
- Wants tests written after code, not before
```

Module AGENTS.md format (subfolder):
```markdown
# Learning Module

## Architecture
- Use event bus pattern for hook communication
- Handlers subscribe via events.on()

## Implementation
- LLM utility shared in teleclaude/utils/
```

Plain markdown. Human readable. No invented formats. No "User" prefix (implicit).

**AGENTS.md should reference LEARNED.md:**
```markdown
# Project AGENTS.md
...
See also: [LEARNED.md](LEARNED.md) for dynamically learned preferences.
```

## User Stories / Use Cases

### Story 1: Correction Capture

As an AI system, I want to capture when Mo corrects my output so that future sessions don't repeat the same mistake.

**Acceptance Criteria**:

- [ ] Stage 1 hook fires on UserPromptSubmit (async, non-blocking)
- [ ] Correction like "No, don't add docstrings" extracted as fact
- [ ] Fact appended to tmp/learning-raw.jsonl
- [ ] Stage 2 processes at session end
- [ ] LEARNED.md or relevant AGENTS.md updated with new preference
- [ ] Next session receives this preference in context

### Story 2: Novel Fact Filtering

As an AI system, I want to only extract facts not already known so that I don't create noise or duplicate existing directives.

**Acceptance Criteria**:

- [ ] Stage 1 receives tmp/known-facts-summary.md as context
- [ ] Facts already in coding-directives.md are NOT extracted
- [ ] Facts already in LEARNED.md are NOT extracted
- [ ] Only genuinely novel facts make it to tmp/learning-raw.jsonl
- [ ] Empty output when nothing new in message

### Story 3: Session End Processing

As an AI system, I want to synthesize raw facts at session end so that LEARNED.md stays clean and deduplicated.

**Acceptance Criteria**:

- [ ] Stage 2 hook fires on SessionStop
- [ ] Reads all entries from tmp/learning-raw.jsonl
- [ ] Deduplicates similar facts
- [ ] Determines scope (project-level vs module-specific) for each fact
- [ ] Merges with existing LEARNED.md or creates/updates subfolder AGENTS.md
- [ ] Regenerates tmp/known-facts-summary.md
- [ ] Deletes tmp/learning-raw.jsonl after processing

### Story 4: Cross-Session Persistence

As Mo, I want learned preferences to persist across sessions so that AI remembers my corrections.

**Acceptance Criteria**:

- [ ] LEARNED.md survives session end
- [ ] New sessions load LEARNED.md into context
- [ ] Subfolder AGENTS.md files loaded when working in that subtree
- [ ] Preferences from previous sessions affect current behavior

### Story 5: Hierarchical Memory Placement

As Mo, I want facts about specific modules to be stored in that module's AGENTS.md so the AI has module-specific context when working there.

**Acceptance Criteria**:

- [ ] Stage 2 analyzes conversation context to determine relevant folders
- [ ] General preferences go to LEARNED.md
- [ ] Module-specific facts go to {module}/AGENTS.md
- [ ] Stage 2 creates new AGENTS.md files in subfolders when needed
- [ ] Existing AGENTS.md files are updated (not overwritten) with new facts

## Technical Constraints

- Must use Claude Code hooks (UserPromptSubmit, SessionStop)
- Stage 1 must be async/non-blocking
- Stage 1 LLM must be fast and cheap (Haiku-class)
- Stage 2 LLM can be smarter (Sonnet-class)
- No external dependencies (no databases, no vector stores)
- File-based storage only (.md, .jsonl)
- Must work with existing TeleClaude infrastructure
- Must handle session crashes (orphan tmp/learning-raw.jsonl files)

### LLM Invocation via Claude Code CLI

**All LLM calls must use Claude Code CLI in non-interactive mode**, not direct API calls:

```bash
# Stage 1 (Haiku - fast, cheap)
claude -p "prompt" --model haiku --output-format text

# Stage 2 (Sonnet - smarter)
claude -p "prompt" --model sonnet --output-format text

# Init (Sonnet)
claude -p "prompt" --model sonnet --output-format text
```

**Why CLI over API:**
- Uses existing Claude subscription (within account budget)
- No API key management
- No separate billing
- Claude CLI handles auth transparently

## Success Criteria

- [ ] UserPromptSubmit hook implemented and fires async
- [ ] SessionStop hook implemented and processes accumulated facts
- [ ] tmp/known-facts-summary.md generated from directives + LEARNED.md
- [ ] Stage 1 correctly filters already-known facts
- [ ] Stage 2 correctly deduplicates and merges facts
- [ ] LEARNED.md persists and loads in new sessions
- [ ] No noticeable latency impact on conversation (async Stage 1)
- [ ] Orphan tmp/learning-raw.jsonl files handled gracefully

## Bootstrap / Initialization

### Init Function

A one-time initialization that creates `tmp/known-facts-summary.md` from existing knowledge sources:

```
Input sources:
├── ~/.agents/docs/development/coding-directives.md
├── ~/.agents/docs/development/testing-directives.md
├── {project}/AGENTS.md (if exists)
└── {project}/LEARNED.md (if exists)

Output:
└── {project}/tmp/known-facts-summary.md
```

**Init behavior:**

1. Read all input sources
2. Use LLM to extract/summarize key facts into concise list
3. Write tmp/known-facts-summary.md
4. Create empty LEARNED.md if not exists

**When to run:**

- First time setup (no tmp/known-facts-summary.md exists)
- When source directives change (manual trigger or file watcher)
- Stage 2 regenerates it after each session (keeps it fresh)

**Init prompt (Knowledge Extraction):**

```
Perform knowledge extraction on the following directive documents.

Extract semantic triples representing:
- Stated preferences and requirements
- Prohibited patterns and anti-patterns
- Required practices and conventions
- Architectural principles

Output as concise natural language statements. One fact per line.
No "User" prefix. Keep under 50 lines total.
Group by category: Coding, Testing, Communication, Architecture.

Documents:
{directive_contents}
```

### Story 5: Bootstrap Initialization

As an AI system, I want to initialize the known-facts summary from existing directives so that Stage 1 doesn't extract already-documented preferences as "new."

**Acceptance Criteria**:

- [ ] Init function reads coding-directives.md
- [ ] Init function reads testing-directives.md
- [ ] Init function reads project AGENTS.md if present
- [ ] Init function reads existing LEARNED.md if present
- [ ] Generates tmp/known-facts-summary.md (~50 lines max)
- [ ] Creates empty LEARNED.md if not exists
- [ ] Can be triggered manually or runs on first Stage 1 if missing

## Open Questions

- Should LEARNED.md have global (~/.agents/) and project-specific variants?
- What confidence/decay mechanism, if any, for v1?
- Should Stage 2 also fire on PreCompact (not just SessionStop)?

## References

- Claude Code hooks documentation
- Existing hookify plugin for hook patterns
- coding-directives.md, testing-directives.md (existing knowledge sources)
- Mem0, Zep for industry patterns on AI memory
