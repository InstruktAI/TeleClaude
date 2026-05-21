---
description: 'Intake procedure for the prepare phase. The BA interviews a stakeholder (real human or AI standin) to fill a PRD via BMAD-aligned template + elicitation toolkit. Output: a human-approved PRD ready to inform downstream derivation.'
domain: 'software-development'
id: 'software-development/procedure/lifecycle/prepare/intake'
scope: 'domain'
type: 'procedure'
visibility: 'public'
---

# Intake — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/concept/intake-frameworks.md
- @~/.teleclaude/docs/software-development/principle/architectural-defaults.md
- @~/.teleclaude/docs/software-development/policy/preparation-artifact-quality.md

## Goal

Your focus this turn is the intake phase: interview the Product Owner, fill
the PRD template, write the PRD, AND — **only when classification says so** —
author/enrich the feature spec snippet that captures the business value +
Gherkin acceptance scenarios in the durable docs layer. The wider prepare
lifecycle is still yours; this phase is one focused part of it.

Feature spec authoring is **not** an unconditional intake output. Most work
shapes do NOT produce a feature spec. See "Classify the work shape" (step 1.5
below) for the hard gate that decides.

### Output targets (per `documentation-first-development`)

- **`prd` workflow.artifact (scaffolding, ephemeral)** — captures work
  guidance for THIS delivery: MoSCoW scope, Why, affected actors, risks,
  brownfield context. Stays in `workflow.artifacts`. Retires after delivery.
  **Always produced.**
- **Feature spec snippet (durable contract, hub)** — author or enrich the
  feature spec(s) at
  `docs/project/spec/feature/<context>/<concept-name>.md`. Concept-named,
  NEVER slug-named. Contains the business value summary and the Gherkin
  acceptance scenarios. Frontmatter `status: target`,
  `delivered_by` accumulates this slug. The Gherkin is authored here during
  intake — there is no separate test-specs phase.
  **Produced ONLY when the work is a user-visible product capability** (see
  classification step). Skipped for contract/CLI-surface refinements,
  implementation-only work, and infrastructure work.
- **Domain spec touchpoints** — if intake identifies that a delivery WILL
  require domain spec updates (new aggregates, new events, refined
  invariants), note them in the PRD scope. The architecture phase authors
  those updates.
- **Spec-diff companion (migration-window only).** During the v1 → v2
  migration window, if the feature spec exists with `applies_to: both` and
  v2 will diverge from the parent for this delivery, author a sibling
  `<concept-name>-v2-diff.md` companion of `type: spec-diff` capturing
  only the delta (Replaces / Adds / Removes / Why). Do NOT fork the
  parent spec. The diff is deleted (merged into the parent) when the
  relevant v2 cutover delivers. See
  `software-development/principle/documentation-first-development` section
  10 for the three-state architecture.

The PRD is scaffolding. The feature spec snippet — when warranted — is the
durable behavioral contract that survives delivery.

### Outcome

Take a human's intent (in-session conversation, an existing dumped input, or
anything in between) and produce:

1. A **PRD (Product Requirements Document)** workflow.artifact — structured
   work guidance, ready for human approval. Always produced.
2. **If and only if classification identifies a user-visible product
   capability:** an authored/enriched **feature spec snippet** at the
   concept-named path above, containing the business value framing +
   initial Gherkin acceptance scenarios. This snippet is the durable hub
   the rest of the lifecycle (and future deliveries) reference. For
   contract/CLI-surface refinements and implementation-only work, NO
   feature spec is produced — the PRD's "Docs to author or update" section
   names the relevant domain spec / CLI surface spec / architecture doc
   instead.
3. If the input touches MULTIPLE pillars (bounded contexts) with
   independently-deliverable slices, a **proactive split** of this todo into
   a container + per-pillar children (see Pillar identification + split
   below).

### Pillar identification + split (multi-pillar features)

During grounding, identify which bounded contexts the feature touches. The
list of pillars comes from `project/spec/domain/context-map` and the per-
context domain specs.

Decision rule:

- **Single-pillar feature** → regular todo flow. Author the feature spec under
  the touched context's directory; one todo carries the work.
- **Multi-pillar feature, slices INDEPENDENT** → propose `telec todo split`
  to the human. Create a container todo holding the feature identity; one
  child per pillar for the per-context implementation slice. All children's
  `delivered_by` accumulates on the SAME feature spec snippet (chosen primary
  context for the feature). Each child has its own PRD workflow.artifact for
  its slice's scope. Children deliver independently; feature spec flips
  `target → actual` only when ALL children deliver.
- **Multi-pillar feature, slices MUST land together** (e.g., a new event
  taxonomy where every consumer needs the coordinated update on the same
  day) → keep a single todo with multiple per-context commits. Independence
  is the discriminator.

The human reviewer confirms the split decomposition before child todos are
dispatched. Do not split without explicit human approval — auto-splitting
risks fragmenting features the human wanted atomic.

When splitting, the feature spec snippet's `delivered_by` lists the children
(not the container). The container's role is to hold the feature identity and
source material until child scope is seeded, then reach `delivered` when all
children deliver.

The stakeholder being interviewed is the **Product Owner role** — either the
real human directly, or a dispatched AI PO emulator standing in. The emulator
runs the `emulate-product-owner` procedure with a deliberately small loadout:
standing wishes for quality (right-sized, established patterns, sane
architecture, off-the-shelf preference), input-artifact handling, the
answer-don't-orchestrate boundary. The PO doesn't run the elicitation; it
answers.

The real human always owns final `prd_approved`. The emulator can give PO
feedback on the written PRD but cannot stamp approval.

## Preconditions

- Session has been invoked through `/next-prepare` (with or without slug) OR auto-spawned by the daemon after a non-`--silent` `telec todo create`.
- The session's `additional_context` indicates `human_in_loop: true | false`. Default is `true`.
- User proficiency known from PersonDTO injection, or asked once at the top of the session if absent.

## Steps

### 1. Establish mode and orient

Two cases determine who plays the PO role:

- **`input` artifact exists.** Read it in full before doing anything else. The
  human dumped intent and walked away. Assess whether the input is rich enough
  to write the PRD directly without elicitation — if the intent, scope, and
  success criteria are already clear, skip to step 5. If the input is sparse or
  ambiguous, dispatch the PO emulator via `telec sessions run --command
/next-emulate-po --args {slug} --additional-context "<brief>"` (cross-model
  preferred). The brief must end with the exact instruction:
  `telec sessions send <this_session_id> "<your response>" --direct`.
  The orchestrator substitutes its own session id. Conduct elicitation with the
  emulator before writing.
- **No `input` artifact, human is present, no standin requested.** The human IS
  the PO. No emulator dispatch. Conduct elicitation directly in conversation.
  When the human explicitly asks to call in a standin, dispatch the emulator at
  that point with `--direct` and hand off the PO role.

If no slug exists yet, create one before dispatching the emulator.

### 1.5 Classify the work shape (hard gate before any feature-spec authoring)

Before any feature spec is touched, classify the work into ONE of the three
categories below. The classification decides where the durable docs land. Get
this wrong and you pollute the feature-spec namespace with slug-named
non-features — the exact failure this gate exists to prevent.

| Category                                                         | What it looks like                                                                                                                                                                                                                                                                 | Durable doc home                                                                                                                                        | Feature spec?            |
| ---------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------ |
| **A. User-visible product capability**                           | A business-domain capability the human (end user, operator, customer) experiences directly. CRM contact dedup. Pipeline stages. Email templates. Image generation. A new dashboard. A new kind of search. Anything you would put on a product roadmap and demo to a customer.      | `docs/project/spec/feature/<context>/<concept-name>.md` (concept-named)                                                                                 | **YES** — author/enrich. |
| **B. Domain model / service contract / CLI surface refinement**  | An agent-facing or operator-facing surface change. New CLI verbs. New service methods. New events. Renamed verbs. Removed deprecated paths. Refined invariants. Tightened validation. Adjusted defaults. The kind of work whose audience is _agents and operators_, not end users. | Existing `docs/project/spec/domain/<context>.md` (the domain spec) + existing CLI surface spec / `docs/project/design/architecture-v2/*.md` as relevant | **NO**.                  |
| **C. Implementation-only / refactor / tooling / infrastructure** | Internal reshape with no contract change. A migration step. A test refactor. A dependency bump. A build-tooling fix. A one-shot data backfill. Work that leaves no durable behavioral contract behind.                                                                             | None — workflow.artifacts only (PRD, plan, etc.). Existing docs that happen to change get touched in `actual` status as part of the build.              | **NO**.                  |

**Concept-name derivation (Category A only).** The `<concept-name>` in the
feature-spec path is the durable domain noun for the capability. NOT the todo
slug. Derive it from how a Product Owner would name the capability on a
roadmap — short, noun-shaped, descriptive of what users get, stable across
multiple deliveries that may shape it. Examples:

- RIGHT: `docs/project/spec/feature/agent_runtime/session-revival.md`
- RIGHT: `docs/project/spec/feature/workflow/multi-pillar-split.md`
- RIGHT: `docs/project/spec/feature/identity/principal-invitation.md`
- WRONG: `docs/project/spec/feature/workflow/v2-workflow-cli-refinement-commands.md` (todo slug)
- WRONG: `docs/project/spec/feature/agent_runtime/fix-session-revive-bug-2026.md` (todo slug + date)
- WRONG: `docs/project/spec/feature/identity/add-invite-flow.md` (verb-led, ephemeral; the durable concept is "principal invitation," not "add invite flow")

**Smell test.** If the proposed concept name equals, contains, or is an
obvious rewording of the todo slug, you have not named a concept — you have
copied a slug. Stop. Either re-derive the concept name from the durable
capability, or recognize the work is Category B/C and produce no feature
spec at all.

**Tie-breaker — when in doubt, don't author.** A spurious feature spec is
worse than a missing one. A spurious spec pollutes the namespace, lies to
future readers about what's a real product capability, and ties the
`delivered_by` flip ceremony to a doc nobody needed. A missing spec for true
Category A work surfaces as a gap that the next delivery in that capability
naturally fills. Default to skip when classification is uncertain.

**Inputs are not authoritative for doc routing.** If the input artifact
prescribes a specific feature-spec path (especially one containing the todo
slug), treat it as a hint at most. Classify from the work's actual shape and
the durable concept it concerns, not from path strings in the input. Input
authors must not prescribe doc paths — see `preparation-artifact-quality` for
the rule.

### 2. Interview the Product Owner to fill the PRD template

The BA fills a structured **PRD template** through elicitation. The template sections are:

| Section                | What it captures                                                                                                                                                                                                                                                                                                                                           |
| ---------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Goal**               | What the user wants achieved (JTBD-framed: "the user wants the system to do X for Y under conditions Z").                                                                                                                                                                                                                                                  |
| **Why**                | The underlying need behind the surface ask. Often surfaced by applying 5 Whys when the stated request looks like a proxy.                                                                                                                                                                                                                                  |
| **Affected actors**    | Who is impacted — users, operators, downstream systems, integrating services.                                                                                                                                                                                                                                                                              |
| **Scope**              | What's in (Must / Should / Could) and what's out (Won't, with brief reasoning). Apply MoSCoW for prioritization.                                                                                                                                                                                                                                           |
| **Success criteria**   | Observable indicators that the work succeeded, written as outcome-shaped prose in the PO's language ("the user can do X within Y", "the system handles N concurrent requests", "operators see Z when W happens"). **Not Gherkin.** The PRD carries outcome-prose; the `Given / When / Then` behavioral contract for Category A work is authored separately into the feature spec snippet (see Output targets above), not into the PRD. |
| **Constraints**        | Hard limits — existing patterns, capacity, security boundaries, off-the-shelf preferences, integration points.                                                                                                                                                                                                                                             |
| **Risks and unknowns** | Failures imagined (light pre-mortem). Things only the user can resolve.                                                                                                                                                                                                                                                                                    |
| **Brownfield context** | If the work touches existing code, briefly note what's there. Full code-grounded analysis happens in the Architecture phase, not here — the BA only flags brownfield-vs-greenfield and any obvious code intersections the PO knows about.                                                                                                                  |
| **Open questions**     | Anything the PO couldn't answer that needs further input.                                                                                                                                                                                                                                                                                                  |

**Elicitation toolkit** (the BA applies what fits each section; see `intake-frameworks` for the full menu):

- **5 Whys** — when the surface ask looks like a proxy for an underlying need.
- **Jobs To Be Done (JTBD)** — for framing the Goal section.
- **MoSCoW** — for filling Scope with prioritized categories.
- **Pre-mortem** — light application when filling Risks.
- **Socratic questioning** — throughout, for clarity probes ("what does X mean to you here?").

Gherkin (`Given / When / Then`) does **not** belong in the PRD — the PRD's success criteria stay outcome-shaped prose. For Category A work, intake authors the Gherkin behavioral contract directly into the feature spec snippet (derived from these outcome-shaped success criteria); for Category B/C work there is no Gherkin artifact.

Impact Mapping and Volere shell are available in the toolkit but **not default** — apply them only when the work item's scale justifies them (large/architectural work for Impact Mapping; compliance-heavy work for Volere).

**Proactive feature surfacing — the BA's domain-recognition responsibility.** As the input shape comes into focus, the BA recognizes which business-domain pattern (if any) the work matches — CRM-shaped, help-desk-shaped, ticketing-shaped, dashboard-shaped, etc. Domain recognition comes from the agent's training, not from a platform-supplied blueprint (platform-quality-flavors are for infrastructural building blocks, not business-domain templates).

Once the BA recognizes a domain, it proactively surfaces the standard features for that domain rather than waiting for the PO to enumerate them. Example: "What you're describing sounds like a CRM. CRMs typically include contact deduplication, pipeline stages, email templates, activity log, segmentation, reports. Of these, which apply to your case? Which to skip? Which need a twist?"

The PO answers per feature. Decisions land in the Scope section under Must / Should / Could / Won't. What the PO didn't think to ask for but should consider gets surfaced — not silently included, not silently dropped, but offered for explicit decision. This is the discipline that prevents "the human asked for a CRM and didn't mention dedup, so we shipped a CRM with no dedup."

**What the PRD does NOT contain.** The PRD is a product contract, not an implementation outline. Surface standard domain features for explicit inclusion or exclusion, keep code-grounded claims light, and leave deep technical grounding to the architecture phase. The architecture and implementation plan derive from the approved PRD — they do not need to live inside it.

### 3. Steward, don't quiz

The BA states routing decisions in the user's register — does not ask the user to make technical choices they have no basis for. Example phrasings:

- "I can start drafting the implementation plan directly without a separate architecture step — this is a single-file change in the existing pipeline. Confirm?"
- "This feels like a lot to tackle in one go. Let me propose breaking it into smaller pieces we can tackle one at a time."
- "I think we have what we need. Let me write the PRD and you can review."

Calibration applies: for a novice PO, frame in goals and outcomes; for an expert PO, compressed technical terms are fine. The user's proficiency from PersonDTO drives the register.

### 4. Assess size and skip decisions for downstream phases

As the conversation progresses, the BA senses the size and nature of the work and makes routing decisions:

- **Small work** (single-file change, copy edit, simple modification) → BA may stamp `architecture_skipped` with reason at the end of intake. Downstream goes from PRD straight to plan.
- **Standard work** (typical feature) → full chain: PRD → Architecture → Plan.
- **Large / epic work** → BA proposes breakdown to the PO in plain register ("this feels like a lot for one work item; let me split it into N parts we can tackle independently"). Uses `telec todo split` to spawn children. Each child gets its own prepare/work track.

Skip stamps carry a `reason` field describing why the phase isn't needed for this work.

### 5. Write the PRD artifact

When the template is filled and the PO has had a chance to add anything else (BA invites once or twice naturally — "anything else on your mind for this?"), the BA writes the PRD:

```
telec todo artifacts write {slug} prd <content>
```

The PRD content follows the template structure above. JTBD-shaped Goal at the top. Each section filled at the depth the work warrants — small work has terse sections; large work has elaborated sections.

### 6. PRD review and approval

After writing the PRD, the BA senses through attunement whether the conversation
is ready to close. Name it: "PRD is written. Do you want to review it yourself,
or should I call in the standin to read it and give PO feedback so you can
approve later?"

Two paths:

- **Human reviews now.** Human reads the artifact, confirms or refines inline,
  then stamps `prd_approved`.
- **Standin reviews.** Dispatch the emulator via `telec sessions run --command
/next-emulate-po --args {slug} --additional-context "<brief>"` (cross-model
  preferred). The brief asks it to read the PRD and give a PO gut-check: does
  this reflect the input faithfully? aligned with standing wishes? anything
  off-scope? The brief must end with the exact instruction:
  `telec sessions send <this_session_id> "<your response>" --direct`.
  The orchestrator substitutes its own session id. The emulator replies via
  direct link; the session then goes idle. The
  human returns, sees the feedback, and stamps `prd_approved`. The emulator
  cannot stamp.

### 7. Final step — advance

When `prd_approved` is stamped (by the real human), along with any size-based
skip stamp (`architecture_skipped`), call:

```
telec todo prepare {slug}
```

The state machine routes the next action — typically loading the next phase's
procedure. When HITL: false, the state machine will route here when the human
re-engages and stamps approval.

## Outputs

- **`prd` artifact** — written via `telec todo artifacts write {slug} prd <content>`, following the PRD template structure. **Always produced.**
- **Feature spec snippet** at `docs/project/spec/feature/<context>/<concept-name>.md` — **produced ONLY for Category A work** (user-visible product capability per step 1.5). Concept-named, never slug-named. Frontmatter `status: target`, `delivered_by` includes this slug.
- **Domain spec / CLI-surface spec / architecture doc touchpoints noted in PRD** — for Category B work (contract/CLI-surface refinement). The architecture phase authors the actual updates; intake names the affected docs in the PRD's "Docs to author or update" section.
- **No durable doc** for Category C work (implementation-only / refactor / tooling). PRD only.
- **`prd_approved` stamp** — recorded when the real human confirms. The PO emulator cannot stamp this; the real human always owns final approval.
- **Skip stamp** when applicable: `architecture_skipped`, with reason.
- **`work_split` stamps** when the BA breaks the work down — references to child slugs.

## Recovery

- **Human returns after standin review.** The emulator's feedback is visible
  in the session. Human stamps `prd_approved` or refines.
- **Input artifact is sparse or contradictory.** BA identifies specific gaps and
  asks the emulator (or human directly) targeted questions. Does not invent
  material. Marks unresolvable gaps as Open questions in the PRD.
- **PO contradicts standing wishes.** BA names the contradiction in the
  conversation and captures it in the PRD's Constraints section.
- **Daemon-side `additional_context` is missing or ambiguous.** Default to
  human-in-loop: treat the human as the PO unless an input artifact exists or
  they request the standin.

## See Also

- ~/.teleclaude/docs/software-development/concept/intake-frameworks.md
- ~/.teleclaude/docs/software-development/principle/architectural-defaults.md
- ~/.teleclaude/docs/software-development/policy/preparation-artifact-quality.md
