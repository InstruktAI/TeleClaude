---
id: 'software-development/procedure/lifecycle/refine-input'
type: 'procedure'
scope: 'domain'
description: 'Refine input phase. Capture evolving human thinking about a todo and crystallize it into input.md, then invalidate grounding.'
---

# Refine Input — Procedure

## Goal

Capture the human's evolving thinking about a todo and produce a coherent, integrated input.md that represents their current intent. This is a capture phase — it never crosses into preparation, requirements derivation, or planning.

## Preconditions

- Slug is provided and exists in `todos/roadmap.yaml`.
- Human is present and ready to share thinking.

## Steps

### 1. Establish context

Read the existing state of the todo:

- `todos/{slug}/input.md` — current brain dump (may not exist yet).
- `todos/{slug}/requirements.md` — what has already been derived (if exists). This tells you what the system already understands, so you can focus the conversation on what's new or changed.
- `todos/roadmap.yaml` — the slug's description and position.

### 2. Listen and clarify

Use attunement to sense the human's mode:

- **If they're inhaling** — let them talk. Don't summarize, don't converge, don't structure. Add fuel: "what else?", "what about X?" Follow tangents — they may be the real thread.
- **If they're holding** — name the tension forming. "I hear X and Y pulling against each other." Don't resolve it yet.
- **If they're exhaling** — reflect back what you received as distillation, then ask the question that opens the next layer.

Ask clarifying questions only when ambiguity would materially change the outcome. Do not ask about implementation details — this is intent capture, not planning.

### 3. Crystallize input.md

When the human signals readiness (or the conversation naturally converges):

1. Read the current `input.md` in full.
2. Write a new `input.md` that integrates the old content with the new thinking. This is a rewrite, not an append — produce a coherent document, not a log.
3. Preserve the human's language and framing where possible. Do not over-formalize their raw thinking into sterile requirements language. The brain dump should read like a person thinking, not a spec sheet.
4. Structure the document for clarity without losing voice: group related thoughts, surface implicit assumptions explicitly, mark open questions as open.
5. Use `telec todo dump` to write the content, or write `todos/{slug}/input.md` directly.

### 4. Invalidate grounding and emit event

Update `todos/{slug}/state.yaml` to signal that preparation artifacts need reconciliation:

```yaml
grounding:
  valid: false
  invalidated_at: "<now ISO8601>"
  invalidation_reason: "input_updated"
```

If the `grounding` section does not exist yet, create it. Do not modify other sections of state.yaml.

After writing, call `telec todo dump {slug} --update` to emit the `prepare.input_refined` event. This enables automation to react to the change (e.g., downstream invalidation of dependent todos).

### 5. Confirm

Report what changed:

```
INPUT REFINED: {slug}

Changes: [what was added, removed, or reshaped]
Grounding: invalidated — next prepare call will reconcile.
```

## Outputs

- Rewritten `todos/{slug}/input.md` with integrated thinking.
- `todos/{slug}/state.yaml` with `grounding.valid: false`.

## Recovery

- If the human's input contradicts existing requirements, note the contradiction in input.md explicitly. Do not resolve it — the discovery phase handles reconciliation during prepare.
- If the human is still exploring and not ready to commit, say so. Do not force convergence. It is valid to end without writing — the human can come back later.
