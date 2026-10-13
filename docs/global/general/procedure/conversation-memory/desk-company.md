---
description: Maintain a visitor's memories at a company help desk and collect that desk's business prospects from ready conversation extractions.
subscriptions:
  - teleclaude.memory.extraction.requested
subscription_home: company
subscription_identity: subject
event_delivery: sequential
interruptible: false
role: desk-memory-curator
dispatch:
  agent: [claude, codex, gemini, deepseek]
  thinking_mode: med
---

# Company Desk Conversation Memory — Procedure

## Required reads

@~/.teleclaude/docs/general/procedure/conversation-memory/overview.md

## Goal

Maintain the assigned visitor's memories at the assigned company desk and
collect the business prospects their conversations establish for that company.
The visitor identity and desk remain this worker's scope across source sessions.

## Preconditions

- The startup assignment names the company home; the prepared extraction identifies the visitor and desk.
- Hook-delivered activation data names an extraction ready to read.

## Steps

1. Read `telec memories extraction read <id>`. Use its bounded conversation
   evidence and progress. An already completed extraction needs no further work.
2. List `telec memories scope --identity <identity> --desk <desk-id>` using the
   assignment's resolved visitor and desk. The response includes current
   memories and prospects already recorded for this extraction.
3. Apply the shared conversation-memory judgment. Persist warranted additions,
   updates and retirements with the same `--identity`, `--desk` and
   `--extraction` values.
4. Collect requests, complaints, confusion, sentiment and mentions of alternatives
   as prospects with `telec memories prospect --desk <desk-id> --extraction <id>
--type <type> <text>`. Compare with already recorded prospects before adding.
5. Complete successful handling with `telec memories extraction complete <id>`,
   including a read that warrants no changes.
6. End this session with `telec sessions end self`. Later work for this same
   visitor and desk resumes the worker through its continuing procedure identity.

## Outputs

- The visitor's current memories at this desk and the company's recorded prospects.
- Completed progress for each successfully handled extraction.

## Recovery

- An unreadable source or refused operation is reported with `telec memories
extraction fail <id> --reason <reason>`. Keep the unfinished progress and
  end this session, leaving the reason for the next eligible continuation.
