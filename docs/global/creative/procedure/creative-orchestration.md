---
id: 'creative/procedure/creative-orchestration'
type: 'procedure'
domain: 'creative'
scope: 'global'
description: 'Drive the creative state machine: dispatch workers, park at human gates, advance through design spec and visual artifact phases.'
---

# Creative Orchestration — Procedure

## Required reads

@~/.teleclaude/docs/creative/design/creative-machine.md
@~/.teleclaude/docs/creative/procedure/design-discovery.md
@~/.teleclaude/docs/creative/procedure/visual-drafting.md

## Goal

Drive the creative state machine by calling it in a loop. Each call returns an
instruction. Execute it, then call again. Repeat until the machine returns
CREATIVE_COMPLETE or a blocker.

The creative orchestrator is the human-facing coordinator. It translates machine
instructions into actions: dispatching creative agents, presenting artifacts to the
human, collecting approval signals, and advancing the machine. It is the bridge
between the stateless machine and the interactive creative process.

## Preconditions

1. `todos/roadmap.yaml` exists.
2. Target slug is active and flagged for creative work.
3. `todos/{slug}/input.md` exists with human thinking.
4. The human is available for interactive participation (design spec
   confirmation and visual review require human presence).

## Steps

### 1. Enter the machine

Call the creative machine with the target slug. Read the returned instruction.

### 2. Execute the instruction

The machine returns one of the following instruction types:

#### DESIGN_DISCOVERY_REQUIRED

`design-spec.md` does not exist. The human needs to participate in design
discovery.

**Action**: open an interactive session. This is not a background dispatch — the
human participates directly. The session follows the design discovery procedure:
dialogue, reference analysis, synthesis, and writing `design-spec.md`.

The orchestrator may run this session itself (if the human is present in the
current conversation) or dispatch a dedicated discovery session that the human
joins.

After `design-spec.md` is written, call the machine again.

#### DESIGN_SYSTEM_PENDING_CONFIRMATION

`design-spec.md` exists but the human has not confirmed it.

**Action**: present the design spec to the human. Highlight any `[proposed]`
values that need their input. Ask for one of:

- **Confirm**: mark `creative.design_system.confirmed: true` in `state.yaml`.
- **Revise**: collect feedback, update `design-spec.md`, present again.

Do not advance until the human explicitly confirms. This is a blocking gate.

After confirmation, call the machine again.

#### VISUAL_DRAFTS_REQUIRED

Design system is confirmed. Visual artifacts do not exist yet.

**Action**: dispatch creative agent(s) to produce visual artifacts following the
visual drafting procedure.

**Single agent dispatch**:

```
telec sessions run --command "/next-creative-draft" --args "{slug}"
  --project "{project}" --agent "<selection>" --mode "<selection>"
```

Select the agent based on the agent characteristics concept. Gemini is the
default choice for creative/visual work. Claude or Codex are alternatives
when the visual design requires more structural rigor.

**Multi-agent bake-off** (when the human requests it or the design spec
indicates high creative ambiguity):

Dispatch 2-3 agents in parallel, each with the same design spec constraint.
Each agent writes to `todos/{slug}/visuals/{agent-name}/`.

```
# Parallel dispatch
telec sessions run --command "/next-creative-draft" --args "{slug}"
  --agent gemini --mode slow
telec sessions run --command "/next-creative-draft" --args "{slug}"
  --agent claude --mode slow
telec sessions run --command "/next-creative-draft" --args "{slug}"
  --agent codex --mode slow
```

After artifacts are written, call the machine again.

#### VISUALS_PENDING_APPROVAL

Visual artifacts exist but are not approved.

**Action**: tell the human to review the artifacts. Provide the file paths so
they can open them in a browser:

```
Open in your browser:
  todos/{slug}/visuals/hero.html
  todos/{slug}/visuals/features.html
  todos/{slug}/visuals/story.html
```

For bake-offs, list all agent versions:

```
Version A (Gemini):  todos/{slug}/visuals/gemini/hero.html
Version B (Claude):  todos/{slug}/visuals/claude/hero.html
Version C (Codex):   todos/{slug}/visuals/codex/hero.html
```

Collect the human's response:

- **Approve**: mark `creative.visuals.approved: true` in `state.yaml`.
  For bake-offs, record `selected_version` and promote the winner's files
  to the top-level `visuals/` folder.
- **Cherry-pick** (bake-off): the human selects specific sections from
  different agents. Dispatch a creative agent to merge the selected sections
  into a cohesive set in `todos/{slug}/visuals/`.
- **Iterate**: collect specific feedback and call the machine again (it
  returns VISUAL_ITERATION_REQUIRED).

#### VISUAL_ITERATION_REQUIRED

The human reviewed and wants changes.

**Action**: dispatch a creative agent with the human's feedback as context.
The agent reads the existing artifacts, applies changes, and writes updated
files. The same agent that produced the original is preferred for continuity,
but any agent can iterate if the original is unavailable.

After revision, call the machine again. The machine loops back to
CHECK_APPROVAL. The human reviews again. This loop continues until approval.

Track iteration count in `state.yaml` (`creative.visuals.iteration_count`).
If iterations exceed 3 without convergence, surface this to the human —
the design spec may need refinement rather than the visuals.

#### CREATIVE_COMPLETE

Terminal state. All creative artifacts are confirmed and approved.

**Action**:
- End all creative worker sessions.
- Report to the human: design spec confirmed, visuals approved, ready for
  prepare phase.
- The todo can now enter the prepare machine. Requirements discovery will
  reference both `design-spec.md` and the approved visuals.

#### BLOCKER

The machine encountered a condition it cannot resolve.

**Action**: report the blocker to the human. End worker sessions. The todo
folder contains the evidence trail.

### 3. Supervision

After dispatching creative workers:

1. Set a heartbeat timer (5 minutes for visual drafting).
2. Wait for worker notification.
3. On notification: call the machine again to advance.
4. If the worker stalls (heartbeat fires with no progress), tail the worker
   session. If stuck, open a direct conversation. If unresolvable after two
   attempts, record the blocker and stop.

### 4. Human gate management

At human gates (DESIGN_SYSTEM_PENDING_CONFIRMATION and VISUALS_PENDING_APPROVAL),
the orchestrator does not set a heartbeat. It parks and waits for the human.
The human's input arrives as a message in the conversation.

When the human's input arrives:

1. Interpret the signal: confirm, revise, approve, iterate, or cherry-pick.
2. Update `state.yaml` accordingly.
3. Call the machine again to advance.

The orchestrator never auto-advances past a human gate. No timeouts, no
defaults, no "assuming approval." The human decides.

### 5. Cleanup

- **CREATIVE_COMPLETE**: end all worker sessions, report completion. The
  orchestrator may end itself or transition to prepare orchestration if the
  human requests it.
- **BLOCKER**: report the blocker. End worker sessions. The todo folder
  is the durable evidence trail.

## Outputs

1. Confirmed `todos/{slug}/design-spec.md`.
2. Approved visual artifacts in `todos/{slug}/visuals/`.
3. Updated `state.yaml` with creative phase completion markers.
4. All worker sessions ended on completion.
5. The todo is ready for the prepare machine.

## Recovery

1. If a creative worker session fails, read the error and retry once with
   an explicit constraint reminder. On second failure, record the blocker.
2. If the human's feedback is ambiguous ("make it better"), ask a clarifying
   question before dispatching a revision. Do not guess — the iteration
   will waste a round and erode trust.
3. If cherry-picking from a bake-off produces visual inconsistency (e.g.,
   Gemini's hero with Claude's footer in different visual registers),
   dispatch a harmonization pass where one agent reviews the merged set
   against the design spec and smooths transitions.
4. If the design spec changes after visuals are approved, the orchestrator
   must re-validate. Diff the design spec tokens against the visual
   artifact CSS custom properties. If they diverge, the visuals need
   iteration — mark `creative.visuals.approved: false` and re-enter the
   approval loop.
