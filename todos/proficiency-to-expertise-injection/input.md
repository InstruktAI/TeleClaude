# proficiency-to-expertise-injection — Input

## Summary

Update the hook receiver to render the full expertise block as human-readable text in the SessionStart injection. Replace the single "Human in the loop: {name} ({level})" line with a structured expertise context block.

## Injection Change

### Hook receiver (`hooks/receiver.py:235-278`)

Current injection (line 263-264):
```python
person_proficiency = getattr(person, "proficiency", "intermediate")
proficiency_line = f"Human in the loop: {person.name} ({person_proficiency})"
```

New injection renders the full expertise block as human-readable text. Example output:
```
Human in the loop: Maurice Faber
Expertise:
  teleclaude: expert
  software-development: expert (frontend: intermediate, devops: advanced)
  marketing: novice
```

The AI reads this naturally and calibrates per domain without code-path detection.

### Hook adapter (`hooks/adapters/claude.py:33-41`)

No change needed — adapter formats the context string as-is. The richer content flows through the same `additionalContext` JSON field.

## Behavioral Templates

Per-level directive blocks injected alongside the expertise signal. These replace the static behavioral sections in CLAUDE.md that currently apply uniformly:

- Expert: "Act and report. Maximum density. Surface only genuine blockers."
- Novice: "Explain before acting. Plain language. Surface every decision point."

The Calibration principle stays as philosophical guidance. The injected templates are the operational implementation.

Sections in CLAUDE.md/AGENTS.md to refactor: Refined Tone Gradient, Evidence Before Assurance, Active Directive vs Conversational Input.

## Touchpoints

| Component | File | Lines | Change needed |
|-----------|------|-------|--------------|
| Injection | `hooks/receiver.py` | 243-264 | Render rich expertise block |
| Injection tests | `test_hooks_receiver_memory.py` | 100-170 | Rich block tests |
| Demo | `demos/person-proficiency-level/` | — | Update or replace demo |

## Dependency

Requires `proficiency-to-expertise-schema` (the Pydantic model) to be complete first.
