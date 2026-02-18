# Requirements: next-demo

## Goal

Add a demo celebration phase to the software development lifecycle. After every finalize, the system produces a stored demo artifact — a rich, self-contained presentation of what was built. Users browse and watch demos at their leisure, like choosing what to watch on Netflix. Every delivery gets its feast.

## Scope

### In scope:

1. **Demo artifact storage** — a `demos/` directory with a well-defined taxonomy. Each delivery produces one demo file, named by slug, containing the full five-act presentation in a structured format that can be rendered richly or read as markdown.

2. **`/next-demo` command** — an agent command that reads the todo artifacts (requirements, implementation plan, review findings, quality checklist, git log, state.json) and composes the demo artifact. Runs inline by the orchestrator after finalize, before cleanup — the artifacts are still on disk.

3. **Orchestration wiring** — the `next_work` state machine gains a demo step between finalize completing and cleanup starting. The orchestrator executes `/next-demo` (or runs the logic inline), stores the artifact, then proceeds to cleanup.

4. **Widget rendering** — when a user wants to watch a demo, `render_widget` presents it as a rich card with the five acts as sections: text for narrative, table for metrics, code blocks for highlights, dividers between acts, and a success status banner.

5. **Demo procedure doc update** — update the existing `software-development/procedure/lifecycle/demo.md` step 4 (Archive) to reference artifact storage instead of "no separate artifact needed."

6. **Lifecycle overview update** — add Demo as phase 5.5 between Finalize and Maintenance.

### Out of scope:

- Video or screen recording — demos are composed from artifacts, not captured
- Interactive demos — the artifact is a presentation, not a live environment
- Retroactive demo generation for past deliveries (nice-to-have for later)
- Demo browsing UI — artifact storage and rendering are sufficient; a dedicated gallery can come later

## Success Criteria

- [ ] `demos/` directory exists with a defined structure
- [ ] `/next-demo` command reads todo artifacts + git data and writes a demo file
- [ ] Demo artifact contains all five acts: Challenge, Build, Gauntlet, Numbers, What's Next
- [ ] `render_widget` can present a demo artifact as a rich card
- [ ] `next_work` state machine dispatches demo after finalize, before cleanup
- [ ] Lifecycle overview doc updated with Demo phase
- [ ] Demo procedure doc updated with artifact storage step
- [ ] Demo artifacts survive cleanup (they live outside `todos/{slug}/`)

## Constraints

- Demo must run before cleanup — the worktree and todo folder are its data sources
- Demo artifact format must be renderable as both rich widget and plain markdown
- No new daemon dependencies — this is orchestration-layer and artifact-layer work
- The `/next-demo` command should be lightweight enough to run inline (no separate session spawn needed), but structured as a proper command for consistency

## Risks

- If artifacts are cleaned up before demo runs, data is lost. Mitigation: the state machine enforces ordering (demo before cleanup), and the demo procedure includes recovery from `git log` + `delivered.md`.

## Demo Artifact Taxonomy

```
demos/
├── {slug}.md              # One file per delivery
```

Each demo file structure:

```markdown
---
slug: { slug }
title: { title from delivered.md }
delivered: { date }
commit: { merge commit hash }
metrics:
  commits: N
  files_changed: N
  files_created: N
  tests_added: N
  tests_passing: N
  review_rounds: N
  findings_resolved: N
  lines_added: N
  lines_removed: N
---

# {title}

## Act 1 — The Challenge

{What problem did this solve, framed from the user's perspective}

## Act 2 — The Build

{Key architectural decisions, what was created/modified/wired}

## Act 3 — The Gauntlet

{Review rounds, critical findings caught and fixed}

## Act 4 — The Numbers

| Metric | Value |
| ------ | ----- |
| ...    | ...   |

## Act 5 — What's Next

{Non-blocking suggestions, ideas sparked, what this unlocks}
```

The YAML frontmatter makes demos machine-parseable for indexing and filtering. The markdown body is human-readable and widget-renderable. The metrics block in frontmatter enables summary views without parsing the full document.
