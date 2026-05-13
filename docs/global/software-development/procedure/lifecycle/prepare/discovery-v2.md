---
id: 'software-development/procedure/lifecycle/prepare/discovery-v2'
type: 'procedure'
domain: 'software-development'
scope: 'domain'
description: 'Discovery procedure (v2) for the prepare phase. Orchestrator and cross-model peer work named lanes through a turn-based discussion in their own sessions; orchestrator coordinates dispatch and tailing; output is a tailor-fit synthesis and an inspectable reframe for user confirmation.'
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

The procedure follows the deterministic flow defined in `docs/project/design/architecture-v2/prepare-discovery-flow.md`. The orchestrator drives every step. Steps 2 and 3 fork (orchestrator and peer work in parallel for Turn 1); from Step 4 onward the orchestrator coordinates a turn-based discussion via dispatch and tailing.

### Lanes worked across Turn 1 and the discussion turns

Discovery is organized into eight named lanes. Each lane has an objective and anchor questions. Both agents work every lane in Turn 1. From Turn 2 onward, contributions to any lane are welcome whenever engagement with the other's material surfaces them — agents are not required to revisit every lane in every later turn.

| Lane | Objective | Anchor questions |
| --- | --- | --- |
| **Intent** | Surface the underlying job behind the surface request. Apply **5 Whys** to drill past the stated ask, **Jobs To Be Done** to reframe as "the user wants this to do X under conditions Y." | What is the user really hiring this work to do? What's the underlying goal behind the surface ask? What different goals would each plausible reading of the input serve? |
| **Impact map** | Apply **Impact Mapping**: actors affected by this work → behavioral changes each should experience → deliverables that produce those changes. | Who acts on or is affected by this? What would each actor do differently if this succeeded? What outcomes would they experience? What concrete things must exist? |
| **Approach options** | Generate genuinely different shapes the work could take, with their trade-offs. | What are the genuinely different shapes this could take? Short-term hack vs long-term build? Existing pattern vs new pattern? What does each cost in time, complexity, reversibility, risk? |
| **Constraints** | What limits the solution space? | Existing patterns, prior decisions, policy, capacity, expertise gaps, performance, security boundaries — what's hard-edged and what's negotiable? |
| **Dependencies** | What else must be true / exist / change for this to work? | What does this touch? What does it depend on? What other in-flight work blocks or enables it? |
| **Risks** | Apply **Pre-mortem**: imagine this shipped and failed; why? | What goes wrong technically? What goes wrong with adoption? What gets fragile? What's irreversible? What surprises us in six months? |
| **Success criteria** | What does "this is working" observably look like? Express in **Gherkin** form where possible. | What behavior proves it works? What metric moves? What user moment changes? What test would fail before and pass after? |
| **Scope boundaries** | Natural in/out lines for this work item. | Where does the work begin? Where does it stop? What's clearly adjacent but separate? What would over-stretch this work item? |

Each contribution to any lane carries a citation marker: `[from-input]` (grounded in the user's text), `[from-source]` with a `file:lines` or spec section reference (grounded in codebase or docs), or `[speculative]` (reaching beyond grounded source). Speculation is welcome — drift handling happens in tailor-fit.

### 1. Establish context

Orchestrator-only.

- Read `telec todo artifacts read {slug} input` in full.
- Determine **greenfield or brownfield** by inspecting the codebase area the input references.
- Load relevant domain specs: `telec docs index --domains <domains>`, then `telec docs get <ids>`.
- Read the roadmap: `telec roadmap list` — adjacent in-flight or delivered work that constrains or enables this.

The context block (greenfield or brownfield, loaded specs, relevant roadmap entries) is included in the dispatch to the peer.

### 2. Dispatch peer for Turn 1

Orchestrator-only.

```
telec sessions run \
  --command /next-prepare-discovery \
  --agent codex \
  --args {slug} \
  --detach
```

Cross-model preferred. Use `codex` or `gemini`; default to `codex`. The peer brief contains: the user's input, the orchestrator's context block, the eight-lane question set, and the instruction to produce Turn 1 in its own session output (no peer reads).

### 3. Turn 1 — parallel, blind inhalation

Both agents work in their own sessions, blind to each other.

Each agent:

- Reads the input, context references, and any cited domain specs.
- Produces Turn 1 in its own session: a structured pass through all eight lanes, each contribution carrying a citation marker.
- Optionally writes a discovery-scratch artifact for structured consumption later (`telec todo artifacts write {slug} discovery-{a|b} <content>`). The artifact, if used, is the agent's own working document — append-only, free-form within. The session output and the artifact carry the same content; the artifact exists to make consolidation cheaper to consume, not as the channel of the discussion.
- Closes Turn 1 with status: `STATUS: Turn 1 complete. More to surface: yes/no.`

**Critical constraint for Turn 1:** neither agent reads the other's session or artifact. Both work blind from the same source. Independence at Turn 1 is the structural defeat of mirroring.

### 4. Meta-discussion — turn-based, orchestrator-conducted

After Turn 1, the orchestrator conducts a discussion through alternating turns. The discussion runs until both consecutive turns close exhausted.

**Each turn (N ≥ 2)** is the agent doing this work in discussion register, not interview register:

- **Engagement with the other's prior turn.** Process what they surfaced. For each contribution that matters, articulate what it makes you think. Where your reading agrees with reasoning (not "yes, agreed"). Where it diverges or extends with reasoning. The other's material must *land* in your thinking before you respond.
- **Reasoning building from their material.** "You pointed at X; that makes me think Y matters because Z." Generative response, not Q&A.
- **New material from cross-reading.** What surfaces only because both contributions are now present together — lane connections, gaps, implications visible only from the combined view.
- **Residual uncertainty.** Honest open thinking, not as questions for the peer to satisfy.
- **Genuine questions when they arise.** Questions are welcome when they emerge from real engagement ("how does W connect to the constraint you raised?"). They are not the structural backbone — they are an artifact of engagement.
- **Status close.** `STATUS: more to surface: yes/no. Reason: <brief>.`

**Round structure:**

1. **Orchestrator writes its Turn N** in its own session (tailing the peer's prior turn to engage). If using a discovery-scratch artifact, the same content is appended.
2. **Self-check:** if the orchestrator's Turn N is exhausted AND the peer's prior turn was exhausted, the discussion is done — skip dispatch and proceed to Step 5. Otherwise:
3. **Orchestrator dispatches the peer for Turn N** with brief: "Tail my session at marker `[Turn N]` (or read my Turn N from discovery-a). Engage with my Turn N — process it, respond with your reasoning, do not interview-answer. Discussion register. Output to your session (and optionally append to discovery-b). Close with status."
4. **Peer writes Turn N** in its own session.
5. **Orchestrator tails the peer's Turn N.**
6. **Termination check:** if both Turn N (orchestrator and peer) closed exhausted, discussion is done — proceed to Step 5. Otherwise, increment N and return to step 1.

**Peer failure recovery:** if the peer dispatch fails or returns unusable output, the orchestrator continues solo. It conducts a single meta-pass on its own Turn 1 (re-reading and self-engaging) and notes the missing peer perspective in the final reframe.

**No fixed turn cap.** Termination is by structural exhaustion. If the discussion runs longer than feels productive (no convergence after many rounds), that is a signal something is wrong with the input or context — surface to the user.

### 5. Tailor-fit synthesis

Orchestrator-only. Reads both agents' discovery output (session transcripts and/or discovery-scratch artifacts).

- **Synthesize per lane**: merge contributions from both agents into a single view per lane (actors deduplicated, impact map tree-merged, approach options as a comparison matrix with cost / speed / complexity / risk / reversibility columns, etc.).
- **Classify every item with MoSCoW**: Must / Should / Could / Won't, each with a one-sentence rationale.
- **Drift handling**: items whose rationale shows they don't trace to user input default to Could or Won't unless rationale promotes them. Drift is named in the rationale, not as a separate step.
- **Surface unresolved intent questions**: items that cannot be classified without the user's intent input are listed in an "open for user" section with the question phrased at the user's proficiency level.

Write `telec todo artifacts write {slug} discovery-tailor-fit <content>`.

### 6. Reframe

Orchestrator authors the inspectable artifact the user reads:

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

<Intent calls that need your judgment, phrased at your proficiency level>
```

Write `telec todo artifacts write {slug} discovery-reframe <content>`.

### 7. User confirm or refine

Present the reframe to the user. The user either:

- **Confirms** — discovery is complete. Proceed to author the requirements artifact from the confirmed reframe.
- **Refines** — captures the user's delta (additional intent, correction, missed need, rejection of a Won't classification, answer to an open intent question). Incorporate the delta into a re-run of Step 5 (tailor-fit synthesis with the new info), regenerate the reframe (Step 6), present again.

If the refinement opens substantial new territory not surfaced during discovery, the orchestrator may decide to re-open the meta-discussion (return to Step 4) with the delta as additional input — but routine refinements stay in the tailor-fit/reframe loop.

### Stewardship and proficiency

- The agents lead the technical work. The user is not asked technical questions the agents can resolve from source.
- When the user is consulted (open intent questions in the reframe, or refinements), questions and content are phrased at their proficiency level. Novice = goals and outcomes. Expert = compressed technical terms.
- Per `general/principle/stewardship`: the user holds intent, the agents hold craft. Discovery is craft work that serves the user's intent.

## Outputs

- `discovery-tailor-fit.md` — synthesized per-lane content with MoSCoW classification and rationale per item.
- `discovery-reframe.md` — user-facing inspectable artifact.
- Optionally `discovery-a.md` and `discovery-b.md` as agent working scratchpads, append-only, used to make consolidation cheaper to consume.
- The confirmed reframe is the handoff input to the next phase: writing the requirements artifact.

## Recovery

- If the peer dispatch fails or returns unusable output, the orchestrator continues solo, conducts a single self-engagement meta-pass on its own Turn 1, and notes the missing peer perspective in the reframe.
- If discovery exhausts at Turn 1 (both agents report nothing more to surface), the orchestrator may skip the meta-discussion and proceed directly to tailor-fit. Short discoveries are valid for small intents.
- If the discussion runs unusually long without exhaustion, treat it as a non-convergence signal and surface to the user — the input or context may be ambiguous in a way the agents can't resolve.
- If the user's input is too sparse to discover against, surface a single clarifying question to the user immediately at their proficiency level. Do not invent material.

## See Also

- ~/.teleclaude/docs/software-development/concept/intake-frameworks.md
- ~/.teleclaude/docs/software-development/policy/preparation-artifact-quality.md
