---
description: Maintain one person's personal memories from ready conversation extractions, serially across their PA conversations.
subscriptions:
  - teleclaude.memory.extraction.requested
subscription_home: person
event_delivery: sequential
interruptible: false
role: memory-curator
dispatch:
  agent: [claude, codex, gemini, deepseek]
  thinking_mode: med
---

# Person Conversation Memory — Procedure

## Required reads

@~/.teleclaude/docs/general/procedure/conversation-memory/overview.md
@~/.teleclaude/docs/general/procedure/event-handling/overview.md
@~/.teleclaude/docs/general/procedure/event-handling/interruptible.md

## Goal

Maintain the personal memories of the person whose slug the startup assignment
names. Each activation identifies one prepared extraction from that person's
personal-assistant conversations. Carry the assignment across later wakes.

## Preconditions

- The startup assignment names the person this worker serves.
- Hook-delivered activation data names an extraction ready to read.

## Steps

<!-- planned:role-scoped-cli-context -->

When this procedure is your session’s launch assignment, retrieve its focused tool
help with `telec -h --expand-role` before starting the assigned work. When reading
it inline, retain your current session’s tool context. Use `telec <command> -h`
for individual commands.
<!-- /planned:role-scoped-cli-context -->

1. Read `telec memories extraction read <id>` for the activation's extraction.
   Take its bounded conversation evidence and progress state. An already
   completed extraction needs no further handling.
2. Use `person:<slug>` from the assignment to list
   `telec memories scope --identity person:<slug>`.
3. Apply the shared conversation-memory judgment to the supplied material.
   Persist additions, updates and retirements with `--identity person:<slug>`
   and `--extraction <id>` through the corresponding `telec memories` operation.
4. After the changes are finished, run `telec memories extraction complete <id>`.
   Complete a successfully read extract even when it warrants no memory changes.
5. End the turn. Later wakes carry further extractions under this same assignment.

## Outputs

- Current personal memories attributed to the assigned person.
- Completed progress for each successfully handled extraction.

## Recovery

- If the source cannot be read or an operation refuses, report the failed
  extraction with `telec memories extraction fail <id> --reason <reason>` and
  end the turn with the reason. Preserve partial writes and unfinished progress
  for the next eligible handling.
