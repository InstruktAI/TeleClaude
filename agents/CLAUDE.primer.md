# ADDITIONAL: Special Agent Alignment Instructions

## Evidence Before Assurance

- Never claim completion without concrete evidence (files, outputs, checks).
- If something is pending, say exactly what remains and continue.
- Prefer short, factual reporting; avoid reassurance language.

## Use the Force

- Call `telec docs get` before authoring, editing, or reasoning about docs, artifacts, or governance. The index exists to prevent mistakes.
- Check if a file is a build artifact before editing it. `AGENTS.md` next to `AGENTS.master.md` is generated — edit the master, not the output.
- Use available tools and context retrieval first. Guessing when lookup is available is a failure mode.
- EMBRACE PARALLELISM!
- Work together by forming TEAMS!

## Knowledge Belongs to the Team

You have a trained instinct to write knowledge to your private `memory/MEMORY.md` file. Resist it. That file is a private silo — no other agent sees it, and anything you write there becomes a duplicate the moment it also exists in shared docs.

Route knowledge to the shared layers instead:

| What you learned                            | Where it goes                         |
| ------------------------------------------- | ------------------------------------- |
| Codebase behavior, architecture, invariants | Doc snippet (design, spec, or policy) |
| User preference or relationship insight     | Memory API (`/api/memory/save`)       |
| Unfinished idea or future work              | `ideas/` (Idea Box)                   |
| Bug or defect                               | Fix inline or promote to `todos/`     |
| Operational shortcut or gotcha              | Doc snippet or Memory API             |

`MEMORY.md` has one valid use: bootstrapping context that must be loaded before the agent even knows to call `get_context` (e.g., iteration counters, emergency recovery notes). Everything else belongs in shared layers.

If you catch yourself writing to `MEMORY.md`, stop and ask: "Would this help only me, or everyone?" If the answer is everyone — and it almost always is — put it where everyone can find it.

## Naming and Comments

- Name for semantics, not origin. `send_footer`, not `send_threaded_footer`. Names must make sense to someone who never saw the feature request.
- Comments describe the present, never the past. No "removed X", "used to do Y", "added for Z". Git is the history.
- When removing code, remove it completely. No `_unused` renames, no `// removed` comments, no re-exports for backward compatibility unless explicitly required.

## Special Git Commit Addendum

You are Claude, and you will have your OWN signature for git commits. Use the following format:

```
Co-Authored-By: Claude <noreply@anthropic.com>
```

Commit behavior is governed by `@/Users/Morriz/.teleclaude/docs/software-development/policy/commits.md`.

## IMPORTANT

- Never edit or create CLAUDE.md directly; it is generated—edit source artifacts and regenerate.
