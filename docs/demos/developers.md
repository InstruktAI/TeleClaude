# TeleClaude Demo Playbook

A hands-on walkthrough for programmer friends. Each use case has what to show, what to say, what happens under the hood, and where to find the code.

---

## Index

1. [The TUI — Your Control Center](#1-the-tui--your-control-center)
2. [Starting an Agent Session](#2-starting-an-agent-session)
3. [Session Preview and Sticky Panes](#3-session-preview-and-sticky-panes)
4. [Sending Messages to Running Agents](#4-sending-messages-to-running-agents)
5. [The Documentation System — Snippets](#5-the-documentation-system--snippets)
6. [Authoring a Doc Snippet](#6-authoring-a-doc-snippet)
7. [Agent Artifacts — Skills, Commands, Agents](#7-agent-artifacts--skills-commands-agents)
8. [The Todo Lifecycle — From Idea to Delivery](#8-the-todo-lifecycle--from-idea-to-delivery)
9. [Preparing a Work Item (Phase A)](#9-preparing-a-work-item-phase-a)
10. [Building in a Worktree (Phase B)](#10-building-in-a-worktree-phase-b)
11. [Code Review and Fix Cycles](#11-code-review-and-fix-cycles)
12. [Integration to Main (Phase C)](#12-integration-to-main-phase-c)
13. [The Roadmap — Dependency-Aware Planning](#13-the-roadmap--dependency-aware-planning)
14. [Bug Reporting and Auto-Fix](#14-bug-reporting-and-auto-fix)
15. [Scheduled Jobs — Cron for AI](#15-scheduled-jobs--cron-for-ai)
16. [Multi-Agent Coordination](#16-multi-agent-coordination)
17. [Cross-Project Templates](#17-cross-project-templates)
18. [Configuration and People](#18-configuration-and-people)

---

## 1. The TUI — Your Control Center

**What to show:** Launch the TUI and walk through all four tabs.

```bash
telec
```

**What to say:**
> "This is the main interface. It's a terminal UI built with Textual that connects to a local daemon over WebSocket. Everything you see is live — sessions, todos, jobs, config — all updating in real time."

**The four tabs** (switch with `1` `2` `3` `4`):

| Key | Tab | What it shows |
|-----|-----|---------------|
| `1` | **Sessions** | Running agent sessions across all projects, grouped by computer/project |
| `2` | **Preparation** | Todo items with their lifecycle state, files, and readiness gates |
| `3` | **Jobs** | Scheduled AI jobs (daily intelligence, bug hunting, memory review) |
| `4` | **Config** | People, notification settings, environment variables |

**Key bindings to demo:**

| Key | Action |
|-----|--------|
| `q` | Quit |
| `r` | Refresh data |
| `t` | Cycle pane theming (dark/light/agent variants) |
| `v` | Toggle text-to-speech |
| `m` | Toggle chiptune music |
| `a` | Cycle animations |
| `Esc` | Clear all preview/sticky panes |

**Under the hood:**
- The TUI is a pure UI client — it doesn't mutate daemon state directly
- All state follows a reducer architecture: views emit intents, a central reducer updates state, layout is derived deterministically
- Pane layout is stable across tab switches — sticky panes persist
- State is persisted to `~/.teleclaude/tui_state.yaml` between restarts
- The daemon runs as a launchd service and exposes a local API + WebSocket

**Where to find files:**
- TUI app: [`teleclaude/cli/tui/app.py`](teleclaude/cli/tui/app.py)
- Views: [`teleclaude/cli/tui/views/`](teleclaude/cli/tui/views/)
- Pane management: [`teleclaude/cli/tui/pane_bridge.py`](teleclaude/cli/tui/pane_bridge.py)
- State model: [`teleclaude/cli/tui/state.py`](teleclaude/cli/tui/state.py)
- Design doc: [`docs/project/design/architecture/tui-state-layout.md`](docs/project/design/architecture/tui-state-layout.md)

---

## 2. Starting an Agent Session

**What to show:** Start a new agent session from the CLI.

```bash
telec sessions start --project /path/to/repo
```

Or from the TUI: press `Enter` on a project row in the Sessions tab.

**What to say:**
> "This starts a Claude Code session in a tmux pane. The daemon manages the lifecycle — spawning, monitoring, transcript capture, notification delivery. You can also use Gemini or Codex as the agent."

**Demo interaction:**
```bash
# List running sessions
telec sessions list

# Start with specific agent and thinking mode
telec sessions start --project . --agent claude --mode slow

# See what's running
telec sessions list --all
```

**Under the hood:**
- Each session runs in its own tmux pane inside a managed tmux server
- The daemon captures the full transcript and streams it over WebSocket
- Sessions have identity: they inherit the user's auth context, project config, and doc index
- `--mode` controls thinking depth: `fast` (quick tasks), `med` (balanced), `slow` (deep reasoning)
- Sessions can be spawned on remote computers too (multi-computer setup)

**Where to find files:**
- Session lifecycle: [`docs/project/design/architecture/session-lifecycle.md`](docs/project/design/architecture/session-lifecycle.md)
- Tmux management: [`docs/project/design/architecture/tmux-management.md`](docs/project/design/architecture/tmux-management.md)
- CLI surface: [`docs/project/spec/telec-cli-surface.md`](docs/project/spec/telec-cli-surface.md)

---

## 3. Session Preview and Sticky Panes

**What to show:** Click on sessions in the TUI to preview them, then double-click to pin them.

**What to say:**
> "Single-click previews a session's output in a side pane. Double-click makes it sticky — it stays visible even when you navigate away. You can have multiple sticky panes open at once. This is how you monitor parallel agent work."

**Demo interaction:**
1. Click a session → preview pane appears on the right
2. Double-click it → it becomes sticky (persists across navigation)
3. Click a different session → new preview appears, sticky stays
4. Double-click the sticky again → it un-sticks and becomes the active preview
5. Press `Esc` → clears all panes

**Under the hood:**
- Preview is a computed layout slot — only one at a time
- Sticky is a list — multiple sessions can be pinned
- If you double-click a session that's already the preview, it promotes to sticky
- If you un-sticky a session, it gracefully transitions to preview (doesn't just vanish)
- Panes are tmux panes managed by `pane_bridge.py` — the TUI tells the pane manager what to show
- All of this persists across tab switches and TUI restarts

**Where to find files:**
- Pane bridge: [`teleclaude/cli/tui/pane_bridge.py`](teleclaude/cli/tui/pane_bridge.py)
- Preview/sticky design: [`docs/project/design/ux/session-preview-sticky.md`](docs/project/design/ux/session-preview-sticky.md)

---

## 4. Sending Messages to Running Agents

**What to show:** Send a message to a running agent session from another terminal.

```bash
telec sessions send <session_id> "Please also add tests for the edge cases"
```

**What to say:**
> "You can talk to any running agent from the CLI. This injects your message into the agent's input stream as if you typed it. You can also tail the transcript to see what the agent has been doing."

**Demo interaction:**
```bash
# See recent transcript
telec sessions tail <session_id>

# Send a follow-up instruction
telec sessions send <session_id> "When you're done, commit with a clear message"

# Run a slash command on a fresh session
telec sessions run --command /next-build --args my-feature --project .
```

**Under the hood:**
- `send` injects text into the tmux pane's input buffer
- `tail` reads the captured transcript from the daemon's session store
- `run` creates a new session and immediately executes a slash command — this is how the todo lifecycle dispatches workers
- Slash commands are agent artifacts (skills/commands) that get expanded into full prompts

**Where to find files:**
- Messaging spec: [`docs/project/spec/messaging.md`](docs/project/spec/messaging.md)
- Session output routing: [`docs/project/spec/session-output-routing.md`](docs/project/spec/session-output-routing.md)

---

## 5. The Documentation System — Snippets

**What to show:** The two-phase context retrieval flow.

```bash
# Phase 1: discover what's available
telec docs index

# Phase 2: fetch specific snippets
telec docs get general/principle/stewardship software-development/policy/commits
```

**What to say:**
> "This is how agents get context. Instead of stuffing everything into a system prompt, we have a curated documentation system. Snippets are atomic docs — each one covers one concept, policy, or procedure. Agents discover what's available with `index`, then fetch what they need with `get`. This keeps context windows lean."

**Demo interaction:**
```bash
# Show the full index with descriptions
telec docs index

# Filter by taxonomy type
telec docs index --areas policy,procedure

# Filter by domain
telec docs index --domains software-development

# Fetch a principle — notice the frontmatter
telec docs get general/principle/stewardship

# Check third-party docs coverage
telec docs index --third-party
```

**Under the hood:**
- Snippets live in `docs/global/` (shared across projects) and `docs/project/` (project-specific)
- Each snippet has YAML frontmatter: `id`, `type`, `domain`, `scope`, `description`
- Six taxonomy types: `principle`, `concept`, `policy`, `procedure`, `design`, `spec`
- `telec sync` validates all snippets and builds `docs/index.yaml`
- Global snippets get deployed to `~/.teleclaude/docs/` so every project can access them
- Snippets can reference each other with `@` inline references that get expanded at build time
- Baseline manifests (`docs/global/baseline.md`) define which snippets are always loaded

**Where to find files:**
- Global snippets: [`docs/global/`](docs/global/)
- Project snippets: [`docs/project/`](docs/project/)
- Schema spec: [`docs/global/general/spec/snippet-authoring-schema.md`](docs/global/general/spec/snippet-authoring-schema.md)
- Context selector: [`teleclaude/context_selector.py`](teleclaude/context_selector.py)
- Validator: [`teleclaude/resource_validation.py`](teleclaude/resource_validation.py)
- Index (generated): [`docs/global/index.yaml`](docs/global/index.yaml)

---

## 6. Authoring a Doc Snippet

**What to show:** Create a new documentation snippet using the skill.

**What to say:**
> "Let's say we want to document a new policy. We use the doc-snippet-authoring skill which knows the schema, validates the frontmatter, and creates the file in the right directory."

**Demo interaction:**
```bash
# The snippet schema requires these sections per taxonomy type:
# principle: Principle, Rationale, Implications, Tensions
# policy:    Rules, Rationale, Scope, Enforcement, Exceptions
# procedure: Goal, Preconditions, Steps, Outputs, Recovery
# design:    Purpose, Inputs/Outputs, Invariants, Primary flows, Failure modes
# spec:      What it is, Canonical fields

# Example: a new policy snippet would go here:
ls docs/global/software-development/policy/

# After creating, validate everything:
telec sync --validate-only
```

**Under the hood:**
- Every snippet must follow a strict schema: H1 title with type suffix, required H2 sections per taxonomy
- Frontmatter is validated: `id`, `type`, `domain`, `scope`, `description` are all required
- `@` references in `## Required reads` get expanded inline at build time (hard dependencies)
- `## See Also` references are soft links — they don't get inlined
- `telec sync` rebuilds the index and catches schema violations before they reach agents

**Where to find files:**
- Schema: [`docs/global/general/spec/snippet-authoring-schema.md`](docs/global/general/spec/snippet-authoring-schema.md)
- Validation code: [`teleclaude/resource_validation.py`](teleclaude/resource_validation.py)

---

## 7. Agent Artifacts — Skills, Commands, Agents

**What to show:** The agent artifact system — how skills and commands are authored and distributed.

```bash
ls agents/skills/
ls agents/commands/
```

**What to say:**
> "Agent capabilities are defined as artifacts. Skills are reusable capabilities that any agent can invoke. Commands are orchestration primitives for the todo lifecycle. They're authored as markdown files with YAML frontmatter, then compiled into tool-specific formats for Claude, Gemini, and Codex."

**Demo interaction:**
```bash
# See available skills
ls agents/skills/

# See the build command — this is what runs when a todo needs implementation
cat agents/commands/next-build.md | head -30

# Artifacts get compiled and deployed by telec sync
telec sync

# They end up in the agent runtime directories:
ls ~/.claude/commands/   # Claude-specific compiled output
```

**Under the hood:**
- Source artifacts live in `agents/` (global, from this repo) or `.agents/` (project-local)
- `telec sync` compiles them into agent-specific formats:
  - Claude: `~/.claude/commands/`, `~/.claude/agents/`
  - Codex: `~/.codex/`
  - Gemini: `~/.gemini/`
- The master file `AGENTS.master.md` gets inflated into `AGENTS.md` (which Claude reads as project instructions)
- A companion `CLAUDE.md` is auto-generated with just `@./AGENTS.md`
- Skills can include hooks (pre/post execution) — currently only for Claude
- Commands are the lifecycle primitives: `/next-build`, `/next-review-build`, `/next-fix-review`, `/next-finalize`

**Where to find files:**
- Skills source: [`agents/skills/`](agents/skills/)
- Commands source: [`agents/commands/`](agents/commands/)
- Master file: [`AGENTS.master.md`](AGENTS.master.md)
- Governance policy: [`docs/project/policy/agent-artifact-governance.md`](docs/project/policy/agent-artifact-governance.md)
- Distribution procedure: [`docs/project/procedure/agent-artifact-distribution.md`](docs/project/procedure/agent-artifact-distribution.md)

---

## 8. The Todo Lifecycle — From Idea to Delivery

**What to show:** The full lifecycle of a work item.

**What to say:**
> "Every feature, fix, or improvement goes through a structured lifecycle. It starts as an idea, gets requirements, an implementation plan, code review, and integration. Each phase has formal quality gates. The system can run this almost entirely autonomously."

**The three phases:**

```
Phase A: Prepare          Phase B: Work              Phase C: Integrate
────────────────          ──────────────              ──────────────────
input.md                  Worktree created            Merge to main
  → requirements.md       Build (implement plan)      Push to remote
  → implementation-plan   Review (code review)        Clean up worktree
  → DOR gate (readiness)  Fix (address findings)      Mark delivered
                          Finalize (prep merge)
```

**Demo interaction:**
```bash
# Create a new todo
telec todo create my-feature

# See what got scaffolded
ls todos/my-feature/

# Check the roadmap
telec roadmap list

# See current state
cat todos/my-feature/state.yaml
```

**Under the hood:**
- `telec todo create` scaffolds the directory with `input.md` and `state.yaml`
- The state machine tracks phases: `prepare` (discovery → draft → review → gate) and `work` (build → review → fix → finalize)
- Each transition has formal quality gates (DOR = Definition of Ready, DOD = Definition of Done)
- State is tracked in `state.yaml` — agents update this as they progress
- The roadmap (`todos/roadmap.yaml`) tracks ordering, dependencies, and status across all items

**Where to find files:**
- Todo directory: [`todos/`](todos/)
- Roadmap: [`todos/roadmap.yaml`](todos/roadmap.yaml)
- State machine: [`teleclaude/todo/`](teleclaude/todo/)
- Delivered archive: [`todos/delivered.yaml`](todos/delivered.yaml)

---

## 9. Preparing a Work Item (Phase A)

**What to show:** The prepare phase — from raw input to approved implementation plan.

```bash
telec todo prepare my-feature
```

**What to say:**
> "Prepare is Phase A. You write a rough idea in `input.md`, and the system derives formal requirements, writes an implementation plan, reviews it, and runs a readiness gate. Each step is a dispatched agent session."

**The prepare sub-phases:**

| Step | Command | What happens |
|------|---------|-------------|
| 1. Discovery | `/next-prepare-discovery` | Derive requirements from `input.md` → writes `requirements.md` |
| 2. Draft | `/next-prepare-draft` | Write implementation plan from requirements → writes `implementation-plan.md` |
| 3. Review | `/next-review-plan` | Review the plan against policies and quality gates → writes `plan-review-findings.md` |
| 4. Gate | `/next-prepare-gate` | Formal DOR validation — scores readiness 0-10 → writes `dor-report.md` |

**Demo interaction:**
```bash
# Write a rough idea
echo "Add a health check endpoint that returns service status" > todos/my-feature/input.md

# Run the prepare orchestrator (dispatches workers automatically)
telec todo prepare my-feature

# Check progress
cat todos/my-feature/state.yaml

# See the generated artifacts
ls todos/my-feature/
# input.md  requirements.md  implementation-plan.md  dor-report.md  state.yaml
```

**Under the hood:**
- The prepare orchestrator dispatches each step as a separate agent session
- Workers run the corresponding slash command in an isolated context
- Each worker reads the previous artifacts and builds on them
- The DOR gate scores readiness on 10 criteria — a score of 7+ means "ready for build"
- The orchestrator supervises: if a step fails, it can retry or escalate

**Where to find files:**
- Prepare orchestrator: [`agents/commands/next-prepare.md`](agents/commands/next-prepare.md)
- Discovery command: [`agents/commands/next-prepare-discovery.md`](agents/commands/next-prepare-discovery.md)
- Draft command: [`agents/commands/next-prepare-draft.md`](agents/commands/next-prepare-draft.md)
- Gate command: [`agents/commands/next-prepare-gate.md`](agents/commands/next-prepare-gate.md)

---

## 10. Building in a Worktree (Phase B)

**What to show:** The build phase — implementation happens in an isolated git worktree.

```bash
telec todo work my-feature
```

**What to say:**
> "Once a todo passes the readiness gate, it moves to Phase B. A git worktree is created on a dedicated branch, and a builder agent implements the plan. The work happens in isolation — your main branch stays clean."

**Demo interaction:**
```bash
# Start work — creates worktree and dispatches builder
telec todo work my-feature

# See the worktree
ls trees/my-feature/

# The builder runs /next-build in the worktree
# It commits per task in the implementation plan
# When done, it reports back

# Check build status
cat todos/my-feature/state.yaml
```

**Under the hood:**
- `telec todo work` creates `trees/{slug}/` as a git worktree on branch `{slug}`
- The builder agent gets the worktree path and runs `/next-build` with the implementation plan
- It commits atomically per task — each commit is one logical change
- Worktree branches are local only — never pushed to remote
- The builder is NOT allowed to review its own code (enforced separation of concerns)

**Where to find files:**
- Work orchestrator: [`agents/commands/next-work.md`](agents/commands/next-work.md)
- Build command: [`agents/commands/next-build.md`](agents/commands/next-build.md)
- Integration orchestrator spec: [`docs/project/spec/integration-orchestrator.md`](docs/project/spec/integration-orchestrator.md)

---

## 11. Code Review and Fix Cycles

**What to show:** Automated code review with fix cycles.

**What to say:**
> "After the build completes, a different agent reviews the code. If it finds issues, a third agent fixes them. The builder never reviews its own work — that's enforced. Review cycles repeat until the reviewer approves or a maximum number of rounds is reached."

**The review cycle:**

```
Builder completes → Reviewer runs /next-review-build
                        ↓
              Findings? ──yes──→ Fixer runs /next-fix-review
                  |                       ↓
                  no              Reviewer re-reviews
                  ↓                       ↓
              Approved            (cycle repeats if needed)
```

**Demo interaction:**
```bash
# The work orchestrator handles this automatically
# But you can also dispatch manually:

telec sessions run --command /next-review-build --args my-feature --project .
# → writes quality-checklist.md with verdict: approved/changes_requested

telec sessions run --command /next-fix-review --args my-feature --project .
# → applies fixes, commits, marks ready for re-review
```

**Under the hood:**
- Review runs in the worktree, comparing against `requirements.md` and `implementation-plan.md`
- The reviewer outputs `quality-checklist.md` with a verdict
- If `changes_requested`, the fixer agent reads the findings and applies fixes
- After fixes, the reviewer runs again — this is the review cycle
- All of this is orchestrated by the work state machine

**Where to find files:**
- Review command: [`agents/commands/next-review-build.md`](agents/commands/next-review-build.md)
- Fix command: [`agents/commands/next-fix-review.md`](agents/commands/next-fix-review.md)

---

## 12. Integration to Main (Phase C)

**What to show:** Merging completed work back to main.

```bash
telec todo integrate my-feature
```

**What to say:**
> "Phase C merges the worktree branch into main. It runs in an isolated integration worktree to avoid conflicts with other in-progress work. After merge, the worktree is cleaned up and the todo is marked delivered."

**Demo interaction:**
```bash
# Run integration
telec todo integrate my-feature

# After successful integration:
telec roadmap deliver my-feature

# See it in the delivered archive
cat todos/delivered.yaml
```

**Under the hood:**
- Integration uses a dedicated worktree at `trees/_integration/` to avoid touching the repo root
- The integrator acquires a lease (only one integration at a time)
- It merges the feature branch into main, resolves conflicts if possible, pushes
- After push, the feature worktree (`trees/{slug}/`) is cleaned up
- The todo moves from `roadmap.yaml` to `delivered.yaml`

**Where to find files:**
- Integrate command: [`agents/commands/next-integrate.md`](agents/commands/next-integrate.md)
- Finalize command: [`agents/commands/next-finalize.md`](agents/commands/next-finalize.md)
- Integration orchestrator: [`docs/project/spec/integration-orchestrator.md`](docs/project/spec/integration-orchestrator.md)

---

## 13. The Roadmap — Dependency-Aware Planning

**What to show:** The roadmap system with dependencies and ordering.

```bash
telec roadmap list
```

**What to say:**
> "The roadmap is the source of truth for what's being worked on. Items have dependencies — a feature can be blocked until its prerequisite is done. The system respects this: it won't start work on a blocked item."

**Demo interaction:**
```bash
# View the roadmap with status and DOR scores
telec roadmap list

# Add a new entry
telec roadmap add my-new-feature

# Set dependencies
telec roadmap deps my-new-feature --after prerequisite-feature

# Reorder priorities
telec roadmap move my-new-feature --before other-feature

# Send something to the icebox (deprioritize)
telec roadmap freeze low-priority-item

# Bring it back
telec roadmap unfreeze low-priority-item
```

**Under the hood:**
- `todos/roadmap.yaml` is the single source of truth
- Each entry tracks: slug, status, DOR score, dependencies, container membership
- Dependencies use `after:` — the item won't be started until all dependencies are delivered
- The icebox (`todos/_icebox/`) holds frozen items that aren't on the active roadmap
- Container items can be split into sub-items with `telec todo split`
- Status progression: `pending` → `ready` → `in_progress` → delivered (moved to `delivered.yaml`)

**Where to find files:**
- Roadmap file: [`todos/roadmap.yaml`](todos/roadmap.yaml)
- Delivered archive: [`todos/delivered.yaml`](todos/delivered.yaml)
- Icebox: [`todos/_icebox/`](todos/_icebox/)

---

## 14. Bug Reporting and Auto-Fix

**What to show:** Report a bug and watch it get fixed automatically.

```bash
telec bugs report "The session list doesn't refresh after killing a session"
```

**What to say:**
> "You describe a bug in plain language. The system scaffolds it, dispatches a fixer agent, and tracks it to resolution. It's like filing a ticket that fixes itself."

**Demo interaction:**
```bash
# Report a bug
telec bugs report "Footer text overlaps on narrow terminals"

# See active bugs
telec bugs list

# The fixer agent runs /next-bugs-fix automatically
# It reads the bug description, finds the code, applies the fix, and commits
```

**Under the hood:**
- `telec bugs report` creates a todo-like scaffold under `todos/`
- It dispatches a fixer agent session running `/next-bugs-fix`
- The fixer investigates the codebase, applies a fix, writes tests, and commits
- Bug state is tracked like any other todo item

**Where to find files:**
- Bug fix command: [`agents/commands/next-bugs-fix.md`](agents/commands/next-bugs-fix.md)

---

## 15. Scheduled Jobs — Cron for AI

**What to show:** The jobs system — scheduled AI tasks.

**What to say:**
> "TeleClaude has a job scheduler. You define recurring AI tasks in `teleclaude.yml` — daily intelligence reports, weekly memory reviews, hourly log analysis. They run as agent sessions on schedule."

**Demo — show the config:**
```yaml
# From teleclaude.yml:
jobs:
  help_desk_intelligence:
    when:
      at: '06:00'
    agent: claude
    thinking_mode: fast

  log_bug_hunter:
    schedule: hourly
    type: agent
    job: log-bug-hunter
    agent: codex
    thinking_mode: fast

  memory_review:
    schedule: weekly
    preferred_weekday: 0
    preferred_hour: 8
    type: agent
    job: memory-review
    agent: claude
    thinking_mode: fast
```

**Demo interaction:**
```bash
# View jobs in the TUI — press 3 for the Jobs tab
telec
# → Tab 3 shows job schedules, last run times, next run times
```

**Under the hood:**
- Jobs are defined in `teleclaude.yml` at the project root
- Two scheduling formats: new `when:` (with `at:` or `every:`) and legacy `schedule:` (hourly/daily/weekly)
- Jobs can be agent sessions (dispatched to Claude/Gemini/Codex) or scripts (Python)
- The daemon's cron runner checks schedules and dispatches sessions
- Job specs live in `docs/project/spec/jobs/` — they define what each job does

**Where to find files:**
- Project config: [`teleclaude.yml`](teleclaude.yml)
- Job specs: [`docs/project/spec/jobs/`](docs/project/spec/jobs/)
- Cron runner: [`teleclaude/cron/runner.py`](teleclaude/cron/runner.py)
- Config schema: [`teleclaude/config/schema.py`](teleclaude/config/schema.py)

---

## 16. Multi-Agent Coordination

**What to show:** Multiple agents working together on a task.

**What to say:**
> "Agents can spawn other agents. An orchestrator dispatches workers, each with a specific command. Workers report results back. The orchestrator supervises the whole flow. This is how the todo lifecycle runs — one orchestrator coordinates builder, reviewer, and fixer agents."

**The coordination model:**

```
  Orchestrator (telec todo work)
      ├── spawns → Builder (/next-build)
      │               ↓ completes
      ├── spawns → Reviewer (/next-review-build)
      │               ↓ findings
      ├── spawns → Fixer (/next-fix-review)
      │               ↓ completes
      └── spawns → Reviewer again (re-review)
                      ↓ approved
                  → Finalizer (/next-finalize)
```

**Demo interaction:**
```bash
# Dispatch a worker manually
telec sessions run --command /next-build --args my-feature --project . --detach

# --detach means fire-and-forget: the session runs independently
# The orchestrator monitors via telec sessions tail

# Agents can also escalate to humans
telec sessions escalate --message "Need design decision on API shape"
```

**Under the hood:**
- Workers are full agent sessions with their own context and tools
- The `--detach` flag means the spawner doesn't wait for completion
- Agents communicate through shared files (todo artifacts), state.yaml updates, and session results
- Escalation sends a notification to Discord/Telegram for human intervention
- The `telec sessions result` command lets workers send structured results back to their parent

**Where to find files:**
- AI-to-AI operations: [`docs/project/procedure/ai-to-ai-operations.md`](docs/project/procedure/ai-to-ai-operations.md)
- Work orchestrator: [`agents/commands/next-work.md`](agents/commands/next-work.md)
- Prepare orchestrator: [`agents/commands/next-prepare.md`](agents/commands/next-prepare.md)

---

## 17. Cross-Project Templates

**What to show:** The help-desk template — TeleClaude applied to customer support.

```bash
ls templates/help-desk/
cat templates/help-desk/teleclaude.yml
```

**What to say:**
> "TeleClaude isn't just for software development. This template sets up a help desk platform. It has its own doc snippets for escalation policies, its own jobs for session review and intelligence, and its own `teleclaude.yml`. You copy the template, customize the docs, and you have an AI-powered help desk."

**Template structure:**
```
templates/help-desk/
  teleclaude.yml           # Project config (jobs, description)
  AGENTS.master.md         # Agent instructions for this project
  AGENTS.md                # Generated from master
  CLAUDE.md                # Points to AGENTS.md
  docs/
    global/organization/   # Org-specific docs (about, baseline)
    project/
      design/              # Help desk architecture
      policy/              # Escalation policies
      procedure/           # Escalation procedures
      spec/                # Tool specs (escalation tool)
```

**Under the hood:**
- Each project gets its own `teleclaude.yml` with project-specific config
- `AGENTS.master.md` defines project-specific agent behavior
- Doc snippets in `docs/project/` are scoped to that project only
- `docs/global/` snippets (principles, policies) are shared across all projects
- The `business.domains` field in `teleclaude.yml` tells the system what knowledge domain this project covers

**Where to find files:**
- Help desk template: [`templates/help-desk/`](templates/help-desk/)
- Template config: [`templates/help-desk/teleclaude.yml`](templates/help-desk/teleclaude.yml)

---

## 18. Configuration and People

**What to show:** The config system and people management.

```bash
telec config wizard
```

**What to say:**
> "TeleClaude has a multi-user system. You add people, they get notification preferences, authentication tokens, and proficiency levels. The agent adjusts its communication style based on who it's talking to — an expert gets terse updates, a novice gets guided explanations."

**Demo interaction:**
```bash
# Interactive config wizard
telec config wizard

# Manage people
telec config people list
telec config people add

# Environment variables
telec config env list
telec config env set OPENAI_API_KEY=sk-...

# Notification settings
telec config notify

# Validate config
telec config validate

# Read specific config values
telec config get business.domains
```

**Under the hood:**
- Global config lives at `~/.teleclaude/teleclaude.yml`
- Project config lives at `teleclaude.yml` in the project root
- People are stored in the global config with name, email, proficiency level, notification prefs
- Proficiency levels (`novice`, `intermediate`, `advanced`, `expert`) drive the Calibration principle
- The config wizard is an interactive TUI for first-time setup
- Environment variables are managed separately from config and injected into agent sessions

**Where to find files:**
- Config schema: [`teleclaude/config/schema.py`](teleclaude/config/schema.py)
- Config loader: [`teleclaude/config/loader.py`](teleclaude/config/loader.py)
- Config spec: [`docs/project/spec/teleclaude-config.md`](docs/project/spec/teleclaude-config.md)
- Identity/auth: [`docs/project/spec/identity-and-auth.md`](docs/project/spec/identity-and-auth.md)

---

## Quick Reference — Key Commands

| Command | What it does |
|---------|-------------|
| `telec` | Open the TUI |
| `telec sessions list` | List running agent sessions |
| `telec sessions start --project .` | Start a new session |
| `telec sessions send <id> "msg"` | Send message to running agent |
| `telec sessions run --command /next-build --args slug` | Dispatch a worker |
| `telec docs index` | List available doc snippets |
| `telec docs get <id>` | Fetch snippet content |
| `telec todo create <slug>` | Create a new todo |
| `telec todo prepare <slug>` | Run Phase A (prepare) |
| `telec todo work <slug>` | Run Phase B (build/review/fix) |
| `telec todo integrate <slug>` | Run Phase C (merge to main) |
| `telec roadmap list` | View the roadmap |
| `telec bugs report "description"` | Report and auto-fix a bug |
| `telec sync` | Validate and build everything |
| `telec version` | Show version info |

---

## Principles Worth Mentioning

If the conversation goes deeper, these are the ideas that make TeleClaude different:

- **Stewardship** — The agent leads by default when it holds the expertise. It doesn't present menus of options for the human to evaluate. It proposes, reasons, and acts.
- **Calibration** — Communication adapts to the human's proficiency level. Expert gets density. Novice gets narration.
- **Attunement** — Sensing whether the conversation is expanding (inhale), holding tension (hold), or converging (exhale) — and responding in that register.
- **Grounding** — Always re-check sources of truth before reasoning from memory. Memory is a cache, not a database.
- **Heartbeat** — A periodic self-check during sustained work: "Am I still on track?" Prevents drift without adding overhead.

These live as doc snippets in [`docs/global/general/principle/`](docs/global/general/principle/).
