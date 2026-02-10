---
id: 'general/procedure/job-authoring'
type: 'procedure'
scope: 'global'
description: 'How to create a new agent or script job: artifacts, placement, validation.'
---

# Job Authoring — Procedure

## Required reads

@~/.teleclaude/docs/general/procedure/agent-job-hygiene.md

## Goal

Create a new scheduled job with the correct artifacts in the correct locations,
validated by existing infrastructure.

## Preconditions

- The job's purpose is defined (what it does and why).
- The execution mode is known: **script** (direct Python execution) or **agent**
  (headless AI session that reads a spec doc).

## Steps

### 1. Choose execution mode

| Mode     | When to use                                   | Artifacts needed                        |
| -------- | --------------------------------------------- | --------------------------------------- |
| `script` | Deterministic work that needs no AI reasoning | Script file + `teleclaude.yml` entry    |
| `agent`  | Work requiring judgment, reading, or writing  | Procedure + job spec + `teleclaude.yml` |

### 2. For agent jobs: write the procedure first

The procedure contains all workflow logic. Place it based on the job's nature:

- Maintenance jobs: `docs/global/general/procedure/maintenance/{job-slug}.md`
- Domain-specific jobs: `docs/global/{domain}/procedure/{job-slug}.md`

Follow the procedure taxonomy (Goal, Preconditions, Steps, Outputs, Recovery).
Add agent-job-hygiene as a required read.

### 3. Write the job spec

The spec is the entry document — the cron runner points the agent at it.

Place at: `docs/project/spec/jobs/{job-slug}.md`

The spec follows the **spec taxonomy** (What it is, Canonical fields, Allowed values,
Known caveats) and must pass snippet schema validation.

#### What belongs in the spec

- **What it is** — one paragraph: what the job does and its single responsibility.
- **Canonical fields** — files involved, output contracts, scope boundaries.
  Use H3 subsections to organize (Files table, Output contract, Scope contract).
- **Allowed values** — only values the running agent needs to know about
  (e.g., state field enums, threshold constants).
- **Known caveats** — real constraints the running agent must handle.
- **Required reads** — agent-job-hygiene + the procedure doc.

#### What does NOT belong in the spec

- **Schedule or config YAML.** The agent is already running. Schedule belongs
  only in `teleclaude.yml`.
- **Procedural logic.** Steps, ordering, recovery — live in the procedure doc.
- **"How it works" narratives.** The spec defines contracts, not workflows.
- **Config field enumerations** (agent, thinking_mode, schedule options). These are
  validated by `teleclaude.yml` schema, not by the running agent.

### 4. Register in teleclaude.yml

Add under `jobs:`:

```yaml
jobs:
  { job_key }:
    schedule: hourly | daily | weekly | monthly
    type: agent | script
    job: { job-slug }
    agent: claude | gemini | codex # agent jobs only
    thinking_mode: fast | med | slow # agent jobs only
    preferred_hour: 0..23 # optional, non-hourly
    preferred_weekday: 0..6 # optional, weekly
```

### 5. For script jobs: write the script

Place at `jobs/{job_slug}.py`. Must be importable by the cron runner with a `run()`
entry point.

### 6. Sync and validate

Run `telec sync`. Validation checks:

- Snippet schema: required H2 sections per taxonomy type.
- Job config: schedule shape, spec file existence, execution mode.

## Outputs

- Procedure doc (agent jobs only).
- Job spec at `docs/project/spec/jobs/{job-slug}.md`.
- `teleclaude.yml` entry.
- Script file (script jobs only).
- Successful `telec sync` with no validation errors.

## Recovery

- If `telec sync` fails, fix the reported issue and rerun.
- If unsure about execution mode, default to agent — it can always be
  simplified to script later.
