---
id: 'creative/procedure/creative-orchestration'
type: 'procedure'
domain: 'creative'
scope: 'global'
description: 'Drive the creative state machine: dispatch workers, park at human gates, advance through design spec, art generation, and visual artifact phases.'
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

The creative orchestrator (creator) is the human-facing coordinator. It translates
machine instructions into actions: facilitating design discovery, dispatching the
artist, dispatching frontender(s), presenting artifacts to the human, collecting
approval signals, and advancing the machine. It is the bridge between the stateless
machine and the interactive creative process.

## Preconditions

1. `todos/roadmap.yaml` exists.
2. Target slug is active and flagged for creative work.
3. `todos/{slug}/input.md` exists with human thinking.
4. The human is available for interactive participation (design spec
   confirmation, art review, and visual review require human presence).

## Steps

### 1. Enter the machine

Call the creative machine with the target slug. Read the returned instruction.

### 2. Execute the instruction

The machine returns one of the following instruction types:

#### DESIGN_DISCOVERY_REQUIRED

`design-spec.md` does not exist. The human needs to participate in design
discovery.

**Action**: open an interactive session. This is not a background dispatch — the
human participates directly. The creator presents reference sites, collects
images the human provides (saved to `todos/{slug}/input/`), and facilitates
the dialogue that produces `design-spec.md`.

The creator may run this session itself (if the human is present in the
current conversation) or dispatch a dedicated discovery session that the human
joins.

After `design-spec.md` is written, call the machine again.

#### DESIGN_SPEC_PENDING_CONFIRMATION

`design-spec.md` exists but the human has not confirmed it.

**Action**: present the design spec to the human. Highlight any `[proposed]`
values that need their input. Ask for one of:

- **Confirm**: mark `creative.design_spec.confirmed: true` in `state.yaml`.
- **Revise**: collect feedback, update `design-spec.md`, present again.

Do not advance until the human explicitly confirms. This is a blocking gate.

After confirmation, call the machine again.

#### ART_GENERATION_REQUIRED

Design spec is confirmed. No art exists yet.

**Action**: dispatch an artist agent to generate mood board images.

```
telec sessions run --command "/next-creative-art" --args "{slug}"
  --project "{project}" --agent "gemini" --mode "slow"
```

Gemini is the default artist because it is natively multimodal — it reads
reference images and generates images in the same conversation using Nano
Banana. The artist session stays open for iteration; it is not fire-and-forget.

The artist receives:
- `design-spec.md` as the constraint document.
- `input.md` for context and content direction.
- `input/` for any reference images the human provided.

The artist uses the `image-generator` meta-skill to select the appropriate
engine. Output goes to `todos/{slug}/art/`.

After images are written, call the machine again.

#### ART_PENDING_APPROVAL

Art images exist but are not approved.

**Action**: present the images to the human. Provide file paths. Optionally
send them via messaging (Discord/Telegram) if the human requests it.

```
Review the mood board:
  todos/{slug}/art/hero-mood.png
  todos/{slug}/art/palette-exploration.png
  todos/{slug}/art/composition-study.png
```

Collect the human's response:

- **Approve**: mark `creative.art.approved: true` in `state.yaml`.
- **Iterate**: collect specific feedback, relay to the artist session.

#### ART_ITERATION_REQUIRED

The human reviewed the art and wants changes.

**Action**: send the feedback to the artist agent (still in session). The
artist generates revised images, potentially switching engines via the
`image-generator` meta-skill if the feedback implies a different style direction.

After revision, call the machine again. The machine loops back to
CHECK_ART_APPROVAL. The human reviews again.

Track iteration count in `state.yaml` (`creative.art.iteration_count`).

#### VISUAL_DRAFTS_REQUIRED

Art is approved. Visual artifacts do not exist yet.

**Action**: dispatch frontender agent(s) to produce HTML+CSS visual artifacts
following the visual drafting procedure.

**Single agent dispatch**:

```
telec sessions run --command "/next-creative-draft" --args "{slug}"
  --project "{project}" --agent "<selection>" --mode "<selection>"
```

The frontender is multimodal — it reads the approved art images for
compositional intent and uses the design spec for exact values. Select
the agent based on agent characteristics. Any agent can be a frontender;
the role is about translating images + spec into code.

**Multi-agent bake-off** (when the human requests it or the design spec
indicates high creative ambiguity):

Dispatch 2-3 agents in parallel, each with the same design spec and art.
Each agent writes to `todos/{slug}/html/{agent-name}/`.

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
  todos/{slug}/html/hero.html
  todos/{slug}/html/features.html
  todos/{slug}/html/story.html
```

For bake-offs, list all agent versions:

```
Version A (Gemini):  todos/{slug}/html/gemini/hero.html
Version B (Claude):  todos/{slug}/html/claude/hero.html
Version C (Codex):   todos/{slug}/html/codex/hero.html
```

Collect the human's response:

- **Approve**: mark `creative.visuals.approved: true` in `state.yaml`.
  For bake-offs, record `selected_version` and promote the winner's files
  to the top-level `html/` folder.
- **Cherry-pick** (bake-off): the human selects specific sections from
  different agents. Dispatch a frontender to merge the selected sections
  into a cohesive set in `todos/{slug}/html/`.
- **Iterate**: collect specific feedback and call the machine again (it
  returns VISUAL_ITERATION_REQUIRED).

#### VISUAL_ITERATION_REQUIRED

The human reviewed and wants changes.

**Action**: dispatch a frontender with the human's feedback as context.
The agent reads the existing artifacts, applies changes, and writes updated
files. The same agent that produced the original is preferred for continuity,
but any agent can iterate if the original is unavailable.

After revision, call the machine again. The machine loops back to
CHECK_VISUAL_APPROVAL. The human reviews again. This loop continues until
approval.

Track iteration count in `state.yaml` (`creative.visuals.iteration_count`).
If iterations exceed 3 without convergence, surface this to the human —
the design spec or art may need refinement rather than the visuals.

#### CREATIVE_COMPLETE

Terminal state. All creative artifacts are confirmed and approved.

**Action**:
- End all creative worker sessions (artist, frontender(s)).
- Report to the human: design spec confirmed, art approved, visuals approved,
  ready for prepare phase.
- The todo can now enter the prepare machine. Requirements discovery will
  reference `design-spec.md`, the approved art, and the visual artifacts.

#### BLOCKER

The machine encountered a condition it cannot resolve.

**Action**: report the blocker to the human. End worker sessions. The todo
folder contains the evidence trail.

### 3. Supervision

After dispatching creative workers:

1. Set a heartbeat timer (5 minutes for art generation, 5 minutes for visual
   drafting).
2. Wait for worker notification.
3. On notification: call the machine again to advance.
4. If the worker stalls (heartbeat fires with no progress), tail the worker
   session. If stuck, open a direct conversation. If unresolvable after two
   attempts, record the blocker and stop.

### 4. Human gate management

At human gates (DESIGN_SPEC_PENDING_CONFIRMATION, ART_PENDING_APPROVAL,
and VISUALS_PENDING_APPROVAL), the orchestrator does not set a heartbeat.
It parks and waits for the human. The human's input arrives as a message
in the conversation.

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
2. Approved art in `todos/{slug}/art/`.
3. Approved visual artifacts in `todos/{slug}/html/`.
4. Updated `state.yaml` with creative phase completion markers.
5. All worker sessions ended on completion.
6. The todo is ready for the prepare machine.

## Recovery

1. If a creative worker session fails, read the error and retry once with
   an explicit constraint reminder. On second failure, record the blocker.
2. If the human's feedback is ambiguous ("make it better"), ask a clarifying
   question before dispatching a revision. Do not guess — the iteration
   will waste a round and erode trust.
3. If the artist's engine produces unusable output, the artist switches
   engines via the `image-generator` meta-skill. If all engines fail,
   record the blocker with the `art/` contents as evidence.
4. If cherry-picking from a bake-off produces visual inconsistency (e.g.,
   Gemini's hero with Claude's footer in different visual registers),
   dispatch a harmonization pass where one agent reviews the merged set
   against the design spec and smooths transitions.
5. If the design spec changes after art or visuals are approved, the
   orchestrator must re-validate. Mark the affected downstream phase as
   unapproved and re-enter the appropriate approval loop.
