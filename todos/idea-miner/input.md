# Idea Miner — Periodic Idea Box Processing

## Context

The Idea Box (`ideas/`) is a write-only capture mechanism for out-of-scope thoughts
during active work. By design, agents write and immediately forget — no browsing, no
acting on ideas during sessions. This protects flow.

The problem: without a read path, ideas accumulate indefinitely. The Idea Box becomes
a dead letter box. The Evolution principle says our partnership is a living system that
matures through continuous refinement — but there's no mechanism to close this loop.

`ideas/` IS the box. There is no `ideas/box/` subdirectory — the folder itself is the
capture surface. Each file is a markdown entry with a `YYMMDD-slug.md` naming convention.

## The Feature

A periodic job that mines the idea box using AI agents, applies structured analysis,
and produces actionable output. The job runs daily at a quiet hour (e.g., 23:00).

### Core Flow

```
Cron Runner (daily, 23:00)
  |
  v
IdeaMinerJob (jobs/idea_miner.py)
  |
  +-- Scan ideas/*.md for unprocessed entries
  |   (bail early if nothing new — no AI sessions, no cost)
  |
  +-- Collection: read entries, group by theme
  |
  +-- Divergence: dispatch parallel AI workers with distinct analytical lenses
  |   +-- Feasibility lens: technical effort, existing patterns, dependencies
  |   +-- Impact lens: who benefits, workflow changes, upside/downside
  |   +-- Fit lens: alignment with architecture, roadmap, principles
  |
  +-- Convergence: orchestrator synthesizes worker outputs
  |   +-- Find contradictions between lenses
  |   +-- Identify what all lenses missed
  |   +-- Produce verdict per idea: actionable / needs research / defer / discard
  |
  +-- Output:
      +-- Actionable ideas -> todos/{slug}/input.md (new work items)
      +-- Full report -> reports/ideas/YYYY-MM-DD.md
      +-- Report file sent via Telegram (teleclaude__send_file)
```

### Worker Design

Workers are **fire-and-forget**. They receive a brief, produce a structured markdown
artifact, and session ends. No back-and-forth, no chattiness.

The orchestrator receives worker output directly — not as a notification to go poll
logs, but as cognitive input to reason about. The synthesis is the orchestrator's real
work: reconciliation and verdict, not box-checking.

### Analytical Lenses (not "personas")

Each worker gets the same idea batch but a different analytical frame. The value comes
from genuinely different questions being asked, not from pretending to be different
"people." The prompts should be precise and structural:

- **Feasibility**: What does this require? What exists already? What's new? Effort?
- **Impact**: Who benefits? What changes? What's the risk? What's the upside?
- **Fit**: Does this align with the roadmap? The architecture? The principles?

### Tracking "Processed" State

Ideas that have been analyzed are marked so they don't get re-processed next run.
Options: rename/move to `ideas/processed/`, add frontmatter, or track in cron state.
Decision deferred to implementation planning.

## Infrastructure

- **Jobs framework**: `jobs/base.py` (Job, JobResult), `teleclaude/cron/runner.py`
- **Scheduling**: `teleclaude.yml` under `jobs:` key
- **AI dispatch**: `teleclaude__start_session`, `teleclaude__get_session_data`
- **Report delivery**: `teleclaude__send_file` (Telegram file upload)
- **Pattern to follow**: `jobs/youtube_sync_subscriptions.py` as structural reference

## Relationship to Other Work

- **github-maintenance-runner**: Same pattern (periodic job -> dispatch AI workers ->
  produce artifact). Building idea-miner first establishes the "job dispatches AI
  sessions" pattern that github-maintenance-runner will reuse.
- **next-maintain**: Currently a stub. The idea-miner could eventually live under a
  broader maintenance umbrella, but should be standalone first.

## Design Decisions to Make

1. **Processed tracking**: rename-to-processed, frontmatter flag, or cron state?
2. **Worker dispatch**: start_session (long-running) vs. run_agent_command (skill-based)?
3. **Number of lenses**: start with 3 (feasibility/impact/fit) or 1 (single-agent MVP)?
4. **Report format**: structured markdown template or free-form synthesis?
5. **Cost control**: skip divergence for single-idea batches? Use fast thinking mode?

## Dependencies

- Jobs runner infrastructure (exists)
- `teleclaude__start_session` / `teleclaude__send_file` MCP tools (exist)
- `ideas/` directory with entries to process (currently near-empty — will accumulate)

## Out of Scope

- Changing the Idea Box write procedure (that stays as-is)
- Real-time processing (this is batch, periodic)
- Agent-to-agent direct chat during divergence (fire-and-forget only)
- Role-based notification routing (separate todo: role-based-notifications)
