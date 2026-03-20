# state-machine-versioning — Input

Replace the current bag-of-fields state.yaml with a proper state machine using versioned transition history and rewind capability.

## Problem

The current state management is not a real state machine. It's imperative code that reads YAML fields, infers what phase we're in, patches individual fields, and hopes the result is consistent. Every recurring bug traces back to this:

- Staleness loops: the machine infers state from file digests instead of knowing it
- Missing verdict stamps: nobody owns writing the verdict because there's no transition that says "review done → stamp verdict → advance"
- Ghost artifact protection: exists because files on disk can't be trusted as state — so we double-check with produced_at timestamps
- \_derive_prepare_phase: exists entirely because the stored phase can't be trusted — so we re-derive it from artifact existence every iteration
- mark-\* command proliferation: each one is a manual patch for a specific field, created because agents couldn't figure out which fields to set together

## Solution: Versioned State Machine

A real state machine with: states, transitions, guards, and actions. The current state is one value, not a bag of fields. You can't be in an inconsistent state because transitions are atomic. You can rewind because you have the history.

### CLI interface

telec todo state <slug> — show current state + valid transitions
telec todo state <slug> <transition> — fire a transition (idempotent)
telec todo state <slug> --rewind — pop to previous state from history

### Versioned blob instead of field-by-field YAML mutation

{
"schema_version": 2,
"current": "plan_review",
"history": [
{"state": "input_assessment", "at": "...", "by": "session-abc"},
{"state": "requirements_produced", "at": "...", "digest": "ef3b...", "by": "session-def"},
{"state": "requirements_reviewed", "at": "...", "verdict": "needs_work", "by": "session-ghi"}
]
}

### Idempotent transitions

- Already past it = no-op
- At the right state = fires
- Not there yet = rejects with "current state is X, transition Y requires state Z"

### Steps as functions

Each step is a Python function: (state, context) -> (new_state, action). No YAML config needed for core logic. The function IS the step definition.

### Schema versioning

We already have version schemas. A helper promotes an old schema to a new schema, so we can pull historical state through that helper. Simple and elegant.

### Relationship to iceboxed workflow-engine-refactor

The iceboxed workflow-engine-refactor (todos/\_icebox/workflow-engine-refactor) builds on the broken state model — it replaces HOW fields get mutated but not WHAT gets mutated. That approach adds a configuration layer ON TOP of the broken model. This todo fixes the foundation. The icebox todo can stay iceboxed.

### What this eliminates

- \_derive_prepare_phase and all inference logic
- mark-ready, mark-phase, mark-finalize-ready proliferation
- Ghost artifact protection hacks
- Staleness loops from digest-based state inference
- Field-by-field YAML patching with inconsistent results

Must work across all state machines (prepare, work, integrate).
