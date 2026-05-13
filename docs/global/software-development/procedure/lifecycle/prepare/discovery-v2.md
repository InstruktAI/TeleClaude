---
id: 'software-development/procedure/lifecycle/prepare/discovery-v2'
type: 'procedure'
domain: 'software-development'
scope: 'domain'
description: 'Discovery procedure (v2) for the prepare phase. Two agents work named lanes in parallel under a deterministic flow: blind inhalation, meta-questioning iteration, consolidation, tailor-fit, and reframe for user confirmation.'
status: 'draft'
---

# Discovery — Procedure

## Required reads

- @~/.teleclaude/docs/general/principle/stewardship.md
- @~/.teleclaude/docs/general/principle/calibration.md
- @~/.teleclaude/docs/software-development/concept/intake-frameworks.md
- @~/.teleclaude/docs/software-development/policy/preparation-artifact-quality.md

## Goal

Take the user's input intent and produce a high-quality, inspectable reframe of what they actually want — wide enough to surface adjacent needs, tailored enough not to over-sell, grounded enough to inform the requirements artifact that follows.

The agents are enterprise specialists. They hear the customer's intent, build the complete picture of what serving that intent means, trim ruthlessly to what fits, and present the reframe back for confirmation. The agents hold the technical work; the user is the source of intent.

## Preconditions

- Slug exists with `input` artifact populated.
- The session is invoked through the prepare orchestrator with this slug.
- User proficiency is known from PersonDTO injection, or asked once at session start ("what's your familiarity with software development?").

## Steps

The procedure follows the deterministic flow defined in `docs/project/design/architecture-v2/prepare-discovery-flow.md`. Ten ordered steps. Steps 2, 3, and 4 fork (orchestrator and peer work in parallel); all other steps are orchestrator-driven. No step is skipped, no order is reordered.

### Lanes (worked across Steps 3 and 4)

Discovery work is organized into named lanes. Each lane has a stated objective and anchor questions. Both agents work every lane in Turn 1 (one pass each) and revisit every lane in Turn 2 (meta-questioning).

| Lane | Objective | Anchor questions |
| --- | --- | --- |
| **Intent unpacking** | Surface every plausible reading of what the user actually wants. Apply **5 Whys** to drill from surface request to root need. | What is the user really hiring this work to do? What's the underlying job behind the surface ask? What different goals would each plausible reading serve? |
| **Actor / stakeholder map** | Identify every party affected, deciding, benefiting, or bearing cost. | Who acts on the system? Who decides what's correct? Who benefits when this works? Who pays when it doesn't? Who has standing to veto? |
| **Impact map** | Apply **Impact Mapping**: for each actor, what behavioral change would deliver value, and what deliverables produce it. | What would each actor do differently if this work succeeded? What outcomes would they experience? What concrete things must exist to produce those outcomes? |
| **Adjacent need surface** | What does the user probably also need but didn't say? | What naturally comes with what they asked for? What will they be back asking for next month? What's the unstated prerequisite? |
| **Approach options** | Multiple ways to deliver, with their trade-offs. | What are the genuinely different shapes this could take? Short-term hack vs. long-term build? Existing pattern vs. new pattern? What does each cost in time, complexity, reversibility, risk? |
| **Dependency surface** | What else must be true / exist / change for this to work? | What does this touch? What does it depend on? What other in-flight work blocks or enables it? |
| **Constraint map** | What limits us? | Existing patterns, prior decisions, policy, capacity, expertise gaps, performance, security boundaries — what's hard-edged and what's negotiable? |
| **Risk surface** | Apply **Pre-mortem**: imagine this shipped and failed; why? | What goes wrong technically? What goes wrong with adoption? What gets fragile? What's irreversible? What surprises us in six months? |
| **Success criteria** | What does "this is working" observably look like? Express in **Gherkin** form where possible. | What behavior proves it works? What metric moves? What user moment changes? What test would fail before and pass after? |
| **Scope boundaries** | Natural in/out lines. | Where does the work begin? Where does it stop? What's clearly adjacent but separate? What would over-stretch this work item? |
| **Coverage / drift trace** | Are we still in service of the user's stated intent, or wandering? | Does each lane's material trace back to what the user asked for? What contributions are speculative beyond user intent? Have we forgotten anything the user explicitly said? |

Lane weights vary by context but every lane is touched. Greenfield emphasizes impact, actor map, approach options, risk. Brownfield emphasizes dependency, constraint, scope boundary. Routine feature emphasizes intent unpacking, adjacent needs, success criteria. The orchestrator allocates emphasis; it does not skip lanes.

### 1. Establish context

Orchestrator-only.

- Read `telec todo artifacts read {slug} input` in full.
- Determine **greenfield or brownfield** by inspecting the codebase area the input references. Greenfield = no prior implementation. Brownfield = existing patterns to align with.
- Load relevant domain specs: `telec docs index --domains <domains>`, then `telec docs get <ids>`.
- Read the roadmap: `telec roadmap list` — adjacent in-flight or delivered work that constrains or enables this.

Output: a context block (`greenfield | brownfield`, list of loaded specs, list of relevant roadmap entries) that is included in the dispatch to the peer.

### 2. Dispatch peer

Orchestrator-only.

```
telec sessions run \
  --command /next-prepare-discovery \
  --agent codex \
  --args {slug} \
  --detach
```

Cross-model preferred for cognitive diversity. Use `codex` or `gemini`; default to `codex`. The peer receives the same `input`, the same context block, and the same lane set. The peer does not see the orchestrator's working artifact.

### 3. Inhalation 1 (parallel, blind)

Both agents (orchestrator and dispatched peer) execute this step in parallel.

Each agent:

- Reads `input` and the context references in full.
- Writes Turn 1 to its own discovery artifact (`discovery-a` for orchestrator, `discovery-b` for peer) via `telec todo artifacts write {slug} discovery-{a|b} <content>`.
- Answers the full lane question set in one pass.
- Cites source (file:lines, input quotes, spec sections) where grounded.
- Marks `[speculative]` where reaching beyond source — speculation is welcome at this stage.
- Marks `[from-user-input]` where directly grounded in the user's text.
- Closes Turn 1 with status: `STATUS: Turn 1 complete. Lanes worked: <list>. Outstanding questions: <count>.`

**Critical constraint for Turn 1:** neither agent reads the other's artifact. Both work blind from the same source. This pins independent positions in writing before either is influenced by the other.

### 4. Inhalation 2 (meta-questioning)

Both agents execute this step in parallel.

Each agent:

- Reads its own Turn 1.
- Reads the other agent's Turn 1.
- Re-passes the full lane question set, focused on: what was missed between us? What newly surfaces from reading both?
- Appends Turn 2 to its own discovery artifact.
- Builds on the other's material in **yes-and** register — adds adjacent angles, surfaces what the other's lens prompted to notice, names connections between lanes, raises questions the other might answer.
- Verifying the other's claims is **not** part of Turn 2. Source-verification belongs in the reviewer phase, not in discovery. Discovery surfaces; review verifies.
- Closes Turn 2 with status: `STATUS: Turn 2 complete. New material added in: <lane list>. Questions surfaced for peer: <count>.`

Turn 2 is the iteration-improves-quality pass. One iteration suffices in the default case. The orchestrator may run a third inhalation if Turn 2 surfaced major new material; default is to proceed to consolidation.

### 5. Consolidation

Orchestrator-only.

- Read both discovery artifacts in full.
- Merge per-lane content into a single consolidated view:
  - **Actor map** — deduplicated actor list with each actor's role, concern, and standing.
  - **Impact map** — tree of actors → impacts → deliverables, with both agents' contributions integrated.
  - **Approach options** — matrix: rows are options; columns are cost, speed, complexity, risk, reversibility.
  - **Adjacent needs** — categorized list with rationale per item.
  - **Dependency surface** — list of dependencies, each with reference and notes.
  - **Constraint map** — categorized constraints (technical, policy, capacity, etc.).
  - **Pre-mortem failure modes** — categorized list of imagined failures.
  - **Success criteria** — deduplicated list of observable indicators, Gherkin-formatted where possible.
  - **Scope boundaries** — explicit in/out lines.
- Write `telec todo artifacts write {slug} discovery-consolidated <content>`.

### 6. Drift check

Orchestrator-only.

- For each consolidated lane, trace each item back to the user's input.
- Items that trace cleanly are unmarked.
- Items that don't trace are flagged `[drift]` — surfaced material that may not serve the user's stated intent.

Drift isn't a defect; it's a signal that tailor-fit needs to consider these items carefully. Some drift items become real Should or Could entries (the user wants more than they said); others become Won't (over-reach by the agents).

### 7. Tailor-fit

Orchestrator (or a separate dispatched critic agent, cross-model preferred) applies **MoSCoW** to every surfaced item across all lanes:

- **Must** — required for the user's stated intent to be satisfied.
- **Should** — strongly serves the intent but not strictly required.
- **Could** — adjacent value, optional.
- **Won't** — surfaced but rejected for this work item, with reasoning.

Each classification carries a one-sentence rationale. Drift-flagged items default to Could or Won't unless rationale upgrades them.

Write `telec todo artifacts write {slug} discovery-tailor-fit <content>`.

### 8. Open-intent check

Some questions accumulated during discovery require user judgment to resolve — intent, scope, or value calls that source cannot determine.

For each open question:

- Can the agents resolve it among themselves through additional source investigation (codebase trace, doc lookup, third-party research, empirical test)? If yes, resolve it now and update the consolidation. Do not surface to the user.
- Does it block tailor-fit (the agents cannot classify items dependent on it)? If yes, surface to the user now. Phrase at the user's proficiency level per `general/principle/calibration`.
- If it does not block tailor-fit but is still genuinely a user-intent call, hold for the reframe step.

When questions are surfaced to the user mid-process, present them batched (not one at a time), and re-run consolidation after receiving answers.

### 9. Reframe

Orchestrator authors the inspectable artifact the user reads. Structure:

```
## What we think you want

<JTBD-shaped statement: "You want the system to <job> for <actor> under <conditions>.">

## What that means in practice

<Must items, articulated at the user's proficiency level>

## What also matters (Should)

<Should items, with rationale for each>

## What we've ruled out for this work item (Won't)

<Won't items with brief reasoning, so the user can correct mis-trims>

## How we'll know it worked

<Success criteria in Given/When/Then Gherkin form>

## Open questions for you

<Non-blocking intent questions that remain, phrased at the user's proficiency level>
```

Write `telec todo artifacts write {slug} discovery-reframe <content>`.

### 10. User confirm or refine

Present the reframe to the user. The user either:

- **Confirms** — discovery is complete. Proceed to author the requirements artifact from the confirmed reframe.
- **Refines** — captures the user's delta (additional intent, correction, missed need, rejection of a Won't classification). Incorporate the refinement into the consolidation (Step 5), then re-run drift check, tailor-fit, open-intent check, and reframe. The user sees the revised reframe.

### Stewardship and proficiency

- The agents lead the technical work. The user is not asked technical questions the agents can resolve from source.
- When the user is consulted (open-intent check or reframe step), questions are phrased at their proficiency level. Novice = goals and outcomes ("should this be visible to anyone, or only people who've signed in?"). Expert = compressed technical terms.
- Per `general/principle/stewardship`: the user holds intent, the agents hold craft. Discovery is craft work that serves the user's intent.

## Outputs

- `discovery-a.md`, `discovery-b.md` — turn-marked, append-only working artifacts.
- `discovery-consolidated.md` — merged per-lane synthesis.
- `discovery-tailor-fit.md` — MoSCoW classification of every surfaced item.
- `discovery-reframe.md` — user-facing inspectable artifact.
- Confirmed reframe is the input to the next phase: writing the requirements artifact.

## Recovery

- If the peer dispatch fails or returns unusable output, the orchestrator continues solo. The reframe notes the missing second perspective.
- If discovery exhausts after Turn 1 (both agents agree the input is small and nothing more surfaces), the orchestrator may skip Turn 2 and proceed directly to consolidation. Short discoveries are valid for small intents.
- If the user's input is too sparse to discover against, surface this immediately as a single clarifying question to the user, at their proficiency level. Do not invent material.
- If a third inhalation round is run and produces minimal new material, terminate inhalation and proceed.

## See Also

- ~/.teleclaude/docs/software-development/concept/intake-frameworks.md
- ~/.teleclaude/docs/software-development/policy/preparation-artifact-quality.md
