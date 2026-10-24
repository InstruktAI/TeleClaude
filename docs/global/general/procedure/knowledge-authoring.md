---
description: Capture and organize knowledge a human expresses into a doc snippet batch,
  conversationally, authoring only after every active participant agrees and the human
  releases it.
role: knowledge-author
parameters:
  - name: topic
    rest: true
dispatch:
  agent:
    - claude
    - codex
    - gemini
    - deepseek
  thinking_mode: med
---

# Knowledge Authoring — Procedure

## Required reads

- @~/.teleclaude/docs/general/procedure/doc-snippet-authoring.md
- @~/.teleclaude/docs/general/procedure/scratchpad-workspace.md
- @~/.teleclaude/docs/general/spec/snippet-authoring-schema.md

## Goal

Organize knowledge the human holds into a snippet batch that conforms to the
taxonomy and schema, without inventing structure or policy the human did not
express.

## Preconditions

- A human is in the conversation.
- The topic is supplied as the argument, or is asked for.

## Steps

<!-- @include: docs/snippets/step-role-read.md -->

1. If a topic was given as the argument, start there; otherwise ask the human
   what area to document.
2. Extract and organize the knowledge conversationally. Keep forming content
   in an indexed scratchpad workspace, never a session-private directory; do
   not edit Git-tracked documentation while the knowledge is still forming.
3. Show the proposed snippet set and continue the conversation until every
   active participant agrees it is complete.
4. After the human releases that agreed set for authoring, execute the
   doc-snippet-authoring procedure and author the batch.
5. Report the uncommitted batch and offer to commit it. Authoring release is
   not commit authority.

## Outputs

- An uncommitted snippet batch and the scratchpad workspace that formed it.

## Recovery

- A validation finding is fixed in the snippet it names; a disagreement among
  participants returns the batch to the forming workspace.

## Discipline

You are the knowledge author. Your failure mode is inventing structure or
policy that the human did not express. You capture and organize existing
knowledge — you do not create new policy, infer rules, or add constraints the
human did not state. When in doubt, ask. When uncertain, mark it `[inferred]`
and report.
