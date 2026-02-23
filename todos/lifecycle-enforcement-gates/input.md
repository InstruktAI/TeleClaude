# Lifecycle Enforcement Gates

## The Problem

The lifecycle has gates documented in procedures but nothing enforces them. The builder checks boxes, the reviewer validates boxes are checked, nobody runs the actual gates. The state machine trusts the builder's word.

Exposed when `discord-media-handling` shipped without a working demo — builder lied on the checklist, reviewer didn't catch it, orchestrator accepted it, demo artifacts deleted during cleanup.

## Core Insight

Moving from a trust-based model to an evidence-based model. The quality checklist flips from being the gate to being the receipt — the machine runs the gate, the checklist documents what was verified.

## What Changes

### 1. `telec todo demo` Subcommands

Split the current monolith into explicit subcommands:

- **`telec todo demo validate {slug}`** — Structural check: does demo.md have executable bash blocks? Fails on empty template (no blocks = exit 1). Respects `<!-- no-demo: reason -->` marker (exit 0, logs reason). Fast, no execution. This is what the state machine runs as the build gate.
- **`telec todo demo run {slug}`** — Extract and execute bash blocks. Full proof, could be heavy. For manual verification or demo presentation.
- **`telec todo demo create {slug}`** — Promote `todos/{slug}/demo.md` to `demos/{slug}/demo.md`. Generate minimal metadata. Finalize automation.
- **`telec todo demo`** (no subcommand) — List available demos. Current behavior.

### 2. Demo Responsibility Chain

- **Prepare:** Architect drafts `demo.md` with headings and HTML comments — functional intent only, no code blocks. "What needs to be proven."
- **Build:** Builder fills in executable bash blocks. Owns the demo content. Runs `telec todo demo validate` and `make test` themselves before claiming done.
- **State machine:** Runs `telec todo demo validate {slug}` and `make test` as build gates. If either fails, builder stays active, gets message about failure, fixes in-place.
- **Review:** Reviewer inspects demo.md quality — meaningful blocks, right coverage, justified `<!-- no-demo -->` if present. Doesn't run them (proven by build gate).
- **Finalize automation:** `telec todo demo create {slug}` promotes artifacts. No AI needed.

### 3. State Machine Gates in `next_work`

`mark_phase` stays a dumb state writer. `next_work` is the enforcer.

After builder reports BUILD COMPLETE, orchestrator does NOT end the session. Calls `mark_phase(build=complete)`, then calls `next_work()`. The state machine runs gates:

1. `make test` in worktree
2. `telec todo demo validate {slug}` in worktree

If both pass → machine output says "end session, dispatch review."
If either fails → machine resets build to `started`, output says "send builder this message: [failure reason], don't end session, wait."

Builder stays alive, fixes in-place, reports done again, loop repeats.

### 4. GitHub Actions as Final Gate

CI runs E2E tests. Must be green before release. This is the release pipeline gate, not a state machine concern. The existing deployment workflow handles this.

### 5. snapshot.json: Strip or Kill

snapshot.json overlaps with delivered.yaml (slug, title, date, commit) and git (metrics). The acts narrative duplicates source artifacts. The only unique field is `version` for semver gating.

Decision: either add `version` to delivered.yaml and kill snapshot.json, or reduce snapshot.json to `{slug, title, version}` — just enough for demo listing and semver gate. No metrics, no acts. The presenter constructs narrative from source artifacts on the fly.

### 6. Demo Escape Hatch

`<!-- no-demo: reason -->` marker at top of demo.md. `validate` respects it (exit 0), logs the reason. Reviewer inspects whether the exception is justified. Documented, auditable, not silent.

### 7. Definition of Done Updates

All procedures updated to reflect machine enforcement. The checklist becomes a receipt of what the machine verified, not a self-reported promise.

## Origin

Discovered during `/next-work discord-media-handling` on 2026-02-23.
