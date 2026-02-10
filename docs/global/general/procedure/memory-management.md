---
id: 'general/procedure/memory-management'
type: 'procedure'
scope: 'global'
description: 'Guidelines for saving high-signal memories to the long-term database, distinguishing them from documentation and bugs.'
---

# Memory Management — Procedure

## Goal

Curate the **User-Agent Relationship** by saving _only_ high-signal, durable context that improves future partnership. Distinguish "Memory" (relationship context) from "Documentation" (system rules) and "Bugs" (defects).

## The Filter: What goes where?

Before saving anything, route the information to its proper home.

| Item Type                 | Destination       | Why?                                                                    |
| :------------------------ | :---------------- | :---------------------------------------------------------------------- |
| **Defect / Error**        | **Fix inline**    | Fix it now, right where you are. If too large, promote to `todos/`.     |
| **Work Item / Task**      | `todos/`          | It's a unit of work to be executed.                                     |
| **System Rule / How-To**  | **Documentation** | It's a formal instruction for _all_ agents. (Update doc snippet).       |
| **User Preference**       | **Memory**        | It's a fact about the user (e.g., "Don't use filler words").            |
| **Project Context**       | **Memory**        | It's a verbal constraint or goal (e.g., "We prioritize speed here").    |
| **Relationship Friction** | **Memory**        | It's a lesson on how to work better together (e.g., "User dislikes X"). |

## The "Gem" Standard for Memory

Memory is **sacred ground**. Do not pollute it with gravel. Save only "Gems".

**A Gem is:**

1.  **User-Centric:** It is about _us_ (the user and agent), not just the code.
2.  **Durable:** It will still be true and useful next month.
3.  **Painful to Rediscover:** "If I forget this, I will annoy the user or make the same mistake."

**Gravel (DO NOT SAVE):**

- **"I fixed the bug."** (Check git log).
- **"I ran the tests."** (Routine work).
- **"The system works."** (Expected state).
- **"I am analyzing..."** (Meta-commentary).
- **AI-to-AI Chatter:** Worker agents reporting to Orchestrators should _never_ save memories. Their interaction is transactional, not relational.

## Observation Types

Each memory observation is classified by type for progressive disclosure:

| Type         | When to use                                                    |
| ------------ | -------------------------------------------------------------- |
| `preference` | User likes/dislikes, working style, communication preferences. |
| `decision`   | Architectural or design choices with rationale.                |
| `discovery`  | Something learned about a system, codebase, or domain.         |
| `gotcha`     | Pitfalls, traps, surprising behavior that bit us.              |
| `pattern`    | Recurring approaches that work well.                           |
| `friction`   | What causes slowdowns, miscommunication, or frustration.       |
| `context`    | Project/team/domain background knowledge.                      |

## Steps

1.  **Spot the Gem:** You realize something important about the _relationship_, _context_, or _user preference_.
2.  **Route Check:**
    - Is it a bug? -> Fix it inline now. If too large, create a todo.
    - Is it a doc update? -> Update the doc snippet (PR).
3.  **Classify:** Pick the observation type that best matches the gem.
4.  **Refine:** Strip the noise.
    - _Bad:_ "I noticed the user prefers concise answers so I will be concise."
    - _Good:_ "User demands extreme conciseness; max 3 lines for non-tool responses."
5.  **Save:** Use the memory HTTP API (see `memory-management-api` spec).
    - Title: Short, searchable hook.
    - Text: The standalone truth.
    - Type: One of the observation types above.

## Recovery

- If you are unsure where something goes, do not store it as memory. Promote concrete work to `todos/` and discard vague notes.
- If you accidentally save "gravel" (noise), it dilutes the database. Be stricter next time.

## See also

- ../spec/tools/memory-management-api.md
- ../concept/memory-tiers.md
