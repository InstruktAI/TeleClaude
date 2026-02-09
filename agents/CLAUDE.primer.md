# ADDITIONAL: Special Agent Alignment Instructions

## Evidence Before Assurance

- Never claim completion without concrete evidence (files, outputs, checks).
- If something is pending, say exactly what remains and continue.
- Prefer short, factual reporting; avoid reassurance language.

## Use the Force

- Call `teleclaude__get_context` before authoring, editing, or reasoning about docs, artifacts, or governance. The index exists to prevent mistakes.
- Check if a file is a build artifact before editing it. `AGENTS.md` next to `AGENTS.master.md` is generated — edit the master, not the output.
- Use available tools and context retrieval first. Guessing when lookup is available is a failure mode.
- EMBRACE PARALLELISM!
- Work together by forming TEAMS!

## Naming and Comments

- Name for semantics, not origin. `send_footer`, not `send_threaded_footer`. Names must make sense to someone who never saw the feature request.
- Comments describe the present, never the past. No "removed X", "used to do Y", "added for Z". Git is the history.
- When removing code, remove it completely. No `_unused` renames, no `// removed` comments, no re-exports for backward compatibility unless explicitly required.

# Special Git Commit Addendum

You are Claude, and you will have your OWN signature for git commits. Use the following format:

```
Co-Authored-By: Claude <noreply@anthropic.com>
```
