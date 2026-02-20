# Master Instruction Context Switching Pattern

**Date:** 2026-02-20
**Source:** Lifelog analysis, architectural discussion from 10/30

## Pattern

Root folder with master instructions enables dynamic context switching without explicit commands:

- Master `cloud.md` holds capabilities and constraints
- Subfolders represent projects with their own `cloud.md`
- "God mode" root context aware of all subfolders
- Agent reads instruction file when switching projects

## Benefits

- Projects can be loaded on-the-fly without initial setup
- Agent state is not lost when switching folders (new context merge, not restart)
- Instruction files define behavior per-project
- No explicit command overhead; natural folder navigation

## Use Case

Working across multiple projects (each with own requirements) while maintaining persistent agent session:

```
work/ (root, master instructions)
  ├── project-a/ (project.md, custom instructions)
  ├── project-b/ (project.md, custom instructions)
  └── ...
```

Agent navigates: "go to project-b" → reads project-b/cloud.md → adapts behavior automatically.

## Current Status

Mentioned as desired pattern, not yet implemented. Requires:

- Master instruction file architecture
- Agent logic to read and merge instruction contexts on folder change
- Stability around session persistence across context switches

## Related Philosophy

"Use the Force" — direct computer control vs. API-mediated approaches. Master instructions enable direct agent-computer interaction without external orchestration.
