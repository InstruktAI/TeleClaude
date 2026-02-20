# Generated Artifact Discovery — Pattern

## Pattern

Memory ID 24 (Feb 9) records a recurring friction: **AGENTS.md is generated from AGENTS.master.md, but AIs keep editing AGENTS.md directly**, undoing the generate step and losing work.

This suggests a broader pattern: there may be other generated artifacts in the codebase that follow the same `.master.*` convention, and AIs are unaware they're generated.

## Current Known Artifacts

- `AGENTS.md` ← generated from `AGENTS.master.md` (distribute.py)

## Actionable Insight

Create a **registry of generated artifacts** that agents can consult before editing. Include:

- File pattern (e.g., `*.md` without `.master.` suffix)
- What generates it (script name)
- Where the source lives
- How to regenerate if you accidentally edited the output

Alternatively, **block direct edits** via pre-commit hooks or file watchers to prevent the mistake entirely.

## Next Steps

- Audit the codebase for other `.master.*` files or patterns
- Document all generated artifacts in a spec
- Consider adding a pre-commit guard that prevents editing generated artifacts
