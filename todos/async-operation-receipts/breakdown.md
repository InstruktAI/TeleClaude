# Breakdown Assessment: async-operation-receipts

## Verdict

No split required.

## Reasoning

This todo is cross-cutting, but it is still one cohesive first-adopter change rather than
several unrelated features. The work stays focused on a single architectural outcome:
introduce durable operation receipts and polling for long-running commands, starting with
`telec todo work`.

The scope remains atomic enough for one implementation session because:

1. The first implementation is explicitly bounded to one adopter: `telec todo work`.
2. The new operation substrate is justified only to the extent required to make that
   route safe, recoverable, and non-blocking at the API boundary.
3. Follow-on adopters (`todo integrate`, session cleanup/revive) are documented as later
   work, not included in the build scope.
4. Requirements, implementation plan, recovery semantics, and verification strategy are
   already concrete and aligned.

## Guardrails

To preserve atomicity during build:

1. Do not broaden the operation framework beyond what `telec todo work` needs.
2. Do not convert additional slow routes in the same implementation session.
3. Keep the agent-facing CLI simple: blocking by default, powered by submit + poll under
   the hood.
4. Preserve current `next_work()` result semantics; change transport, not workflow meaning.
