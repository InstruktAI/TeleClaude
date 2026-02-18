# Requirements: next-demo

## Goal

Add a demo celebration phase to the software development lifecycle. After every finalize, the system produces a stored, executable demo artifact — a self-contained folder with a data snapshot and render script. Users browse and watch demos at their leisure. Every delivery gets its feast.

Demo artifacts are committed to git and gated by semver. A demo runs only when the current project version is compatible with the version it was created under. Breaking changes (major bump) disable stale demos automatically.

## Scope

### In scope:

1. **Demo artifact storage** — a `demos/` directory at repository root. Each delivery produces one numbered folder containing a data snapshot and a render script. Folders are committed to git.

2. **`/next-demo` command** — an agent command that reads todo artifacts (requirements, implementation plan, review findings, quality checklist, git log, state.json), captures a data snapshot, generates a render script, and presents the demo via `render_widget`. Runs after finalize, before cleanup — the artifacts are still on disk.

3. **Semver gating** — each demo records the project version (minor) at creation time. The render script checks the current version before executing. If the major version has changed, the demo is skipped with a clear message. No silent failures.

4. **Orchestration wiring** — the `next_work` state machine gains a demo step between finalize completing and cleanup starting.

5. **Widget rendering** — `render_widget` presents the demo as a rich card with five acts as sections: text for narrative, table for metrics, code blocks for highlights, dividers between acts, and a success status banner.

6. **Demo procedure doc update** — update the existing `software-development/procedure/lifecycle/demo.md` step 4 (Archive) to reference artifact storage.

7. **Lifecycle overview update** — add Demo as phase 6 between Finalize and Maintenance.

### Out of scope:

- Video or screen recording — demos are composed from artifacts, not captured
- Interactive demos — the artifact is a presentation, not a live environment
- Retroactive demo generation for past deliveries (nice-to-have for later)
- Demo browsing UI — folder listing and render scripts are sufficient; a gallery can come later
- Automatic stale demo cleanup on major bump (maintenance concern, not demo creation)

## Success Criteria

- [ ] `demos/` directory exists with numbered folders
- [ ] `/next-demo` command captures data snapshot + generates render script + presents via widget
- [ ] Demo folder contains `snapshot.json` (metrics, narrative data) and `demo.sh` (render script)
- [ ] `demo.sh` checks semver compatibility before rendering
- [ ] Demo artifact contains all five acts: Challenge, Build, Gauntlet, Numbers, What's Next
- [ ] `render_widget` presents a demo as a rich card
- [ ] `next_work` state machine dispatches demo after finalize, before cleanup
- [ ] Lifecycle overview doc updated with Demo phase
- [ ] Demo procedure doc updated with artifact storage
- [ ] Demo artifacts survive cleanup (they live outside `todos/{slug}/`)

## Constraints

- Demo runs before cleanup — the worktree and todo folder are its data sources
- No new daemon dependencies — orchestration-layer and artifact-layer work only
- The render script must be executable standalone (bash + curl to daemon API) and by agents
- Version gating uses the project semver from `pyproject.toml`

## Risks

- If artifacts are cleaned up before demo runs, data is lost. Mitigation: the state machine enforces ordering (demo before cleanup), and the demo procedure includes recovery from `git log` + `delivered.md`.
- Render scripts may break on major version bumps. Mitigation: semver gate prevents execution; stale demos stay in git as historical records but do not run.

## Demo Artifact Structure

```
demos/
├── 001-{slug}/
│   ├── snapshot.json       # Captured metrics, narrative data, version
│   └── demo.sh             # Executable render script
├── 002-{slug}/
│   └── ...
```

### snapshot.json

```json
{
  "slug": "...",
  "title": "...",
  "sequence": 1,
  "version": "0.1.0",
  "delivered": "2026-02-18",
  "commit": "abc1234",
  "metrics": {
    "commits": 0,
    "files_changed": 0,
    "files_created": 0,
    "tests_added": 0,
    "tests_passing": 0,
    "review_rounds": 0,
    "findings_resolved": 0,
    "lines_added": 0,
    "lines_removed": 0
  },
  "acts": {
    "challenge": "...",
    "build": "...",
    "gauntlet": "...",
    "whats_next": "..."
  }
}
```

### demo.sh

A bash script that:

1. Reads `snapshot.json` from its own directory
2. Reads the current project version from `pyproject.toml`
3. Compares major versions — if incompatible, prints a message and exits
4. Renders the demo via `render_widget` (curl to daemon API) or falls back to formatted terminal output
