---
description: 'Feature-lane intake. Confirm observable behavior, shape the product target with its owner, and author the PRD and behavioral feature-spec contract before downstream derivation.'
visibility: 'public'
---

# Intake — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/concept/intake-frameworks.md
- @~/.teleclaude/docs/software-development/principle/architectural-defaults.md
- @~/.teleclaude/docs/software-development/policy/preparation-artifact-quality.md

## Goal

Your focus is to turn source intent into a reviewable product target whose
authority is explicit. Determine the authorized horizon, use
situation-specific domain intelligence within that horizon, choose the smallest
coherent present outcome, and write the choosing reasoning into the PRD's
natural sections. When the prepare overview's creating-session fidelity gate
applies, the verified filing basis bounds product and business intent: intake
may clarify and situate it, but unsupported agent-authored requirements are not
enrichment.

Intake situates the premise against observable current product behavior, the
credible intended state, and the existing todo landscape. It uses internal
implementation detail only to avoid duplicating capabilities and to prepare
later reconciliation; current module shapes do not veto product betterment.

This procedure runs only for `kind=feature`. Before authoring, confirm that the
intent changes behavior observable by a human, agent, or operator. A
non-behavioral intent is a kind mismatch: reclassify it to `change` and return
to prepare routing instead of producing feature-lane artifacts.

### Output targets (per `documentation-first-development`)

- **`prd` workflow.artifact (scaffolding, ephemeral)** — captures work
  guidance for THIS delivery: MoSCoW scope, Why, affected actors, risks,
  brownfield context. Stays in `workflow.artifacts`. Retires after delivery.
  **Produced for every confirmed feature.**
- **Feature spec snippet (durable contract, hub)** — author or enrich the
  feature spec(s) at
  `docs/project/spec/feature/<context>/<concept-name>.md`. Concept-named,
  NEVER slug-named. Contains the business value summary and the Gherkin
  acceptance scenarios. Frontmatter `delivered_by` includes this slug.
  The Gherkin is authored here during intake — there is no separate
  test-specs phase.
  **Produced for every confirmed behavioral feature**, including behavior
  observed through agent-facing and operator-facing CLI, event, or structured
  runtime surfaces.
- **Domain spec touchpoints** — if intake identifies that a delivery WILL
  require domain spec updates (new aggregates, new events, refined
  invariants), note them in the PRD scope. The architecture phase authors
  those updates.

The PRD is scaffolding. The feature spec snippet — when warranted — is the
durable behavioral contract that survives delivery.

### Outcome

Take a human's intent (in-session conversation, an existing dumped input, or
anything in between) and produce:

1. A **PRD (Product Requirements Document)** workflow.artifact — structured
   work guidance, ready for human approval, for every confirmed feature.
2. An authored or enriched **feature spec snippet** at the concept-named path
   above, containing the business-value framing and initial Gherkin acceptance
   scenarios. Human-facing and agent/operator-facing behavioral features both
   produce this durable hub. A non-behavioral kind mismatch exits intake before
   either feature-lane artifact is authored.
3. If the input touches MULTIPLE pillars (bounded contexts) with
   independently-deliverable slices, a **proactive grouping** of this todo into
   a container + per-pillar children (see Pillar identification + grouping
   below).
4. **Reconciliation against the existing landscape** (step 1.6): undeclared
   dependencies recorded as `after` edges; overlap where this premise yields
   descoped into Scope or surfaced to the PO; and, where this premise supersedes an
   existing todo, that todo escalated to the human — halted only on certainty when
   it is already building.

### Pillar identification + grouping (multi-pillar features)

During grounding, identify which bounded contexts the feature touches. The
list of pillars comes from `project/spec/domain/context-map` and the per-
context domain specs.

Decision rule:

- **Single-pillar feature** → regular todo flow. Author the feature spec under
  the touched context's directory; one todo carries the work.
- **Multi-pillar feature, slices INDEPENDENT** → create a container todo first,
  then one child per pillar using `telec todo create <child> "<child-content>" --kind <k> --group <container>`. Read the container's full scope first; each
  child partitions the parent's existing scope — adding no functional or business
  scope absent from the parent. A child that needs scope not present in the parent
  is a NEW todo, not a grouped child. Each child owns its own feature spec(s) 1:1;
  there is no shared feature spec across children. Each child has its own PRD
  workflow.artifact scoped to its slice. Children deliver independently.
- **Multi-pillar feature, slices MUST land together** (e.g., a new event
  taxonomy where every consumer needs the coordinated update on the same
  day) → keep a single todo with multiple per-context commits. Independence
  is the discriminator.

Grouping is an agent intelligence decision derived from the work's shape — there
is no human approval gate. The agent partitions the parent's EXISTING scope into
children that together sum to the parent and add no new scope.

The container holds the feature identity and frozen source input. It has no
lifecycle state of its own; it projects delivered when all children deliver.

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

- The todo is recorded as `kind=feature`; other kinds are routed by the prepare
  overview and do not enter intake.
- The session's `additional_context` indicates `human_in_loop: true | false`. Default is `true`.
- User details injected.

## Steps

### 1. Establish mode and orient

Apply the artifact-discovery rule from `preparation-artifact-quality` first —
`telec todo artifacts list {slug}` — before assuming `input` is the only thing
present. A re-entry after later phases already ran may carry `architecture`,
`implementation-plan`, or a `log` breadcrumb; read whatever exists that bears
on re-orienting, not only the two cases below.

Two cases determine who plays the PO role:

- **`input` artifact exists.** Read it in full before doing anything else. It
  may be a human dump or an agent-authored handoff. When the prepare overview's
  creating-session fidelity gate applies, use its verified filing basis rather
  than treating the whole input as the human's words. Assess whether that basis
  is rich enough to write the PRD directly without elicitation — if the intent,
  scope, and success criteria are already clear, skip to step 5. If it is sparse
  or ambiguous, dispatch the PO emulator via `telec sessions run --command
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

### 1.5 Confirm behavioral feature intent (hard gate before authoring)

Before touching a PRD or feature spec, answer one question: does this intent
alter behavior that an observer can experience? The observer may be a human,
agent, or operator. Logged decisions, CLI responses, events, validation
outcomes, and defaults are observable behavior; implementation-only reshaping
is not.

| Classification                     | What it looks like                                                                                                                                | Intake action                                                                                                            |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| **Human-facing behavior**          | A capability or outcome an end user, customer, or operator experiences directly.                                                                  | Continue feature intake and author or enrich the feature spec.                                                           |
| **Agent/operator-facing behavior** | A CLI verb, service contract, event, structured decision, invariant, validation outcome, or default observed by an agent or operator.             | Continue feature intake and author or enrich the feature spec with the appropriate typed actor.                          |
| **Non-behavioral intent**          | A refactor, migration, dependency update, build-tooling change, data backfill, or infrastructure reshape with no observer-visible contract delta. | Run `telec todo update {slug} --kind change`, leave intake, and re-enter prepare routing. Author no PRD or feature spec. |

Silence is not a classification. Ground the observer and changed outcome from
the input and current contract; if the residue is genuinely intent-owned, ask
one focused question. Never default to skipping the feature spec merely because
the observer is an agent or operator.

**Concept-name derivation (behavioral features only).** The `<concept-name>` in the
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
copied a slug. Re-derive the name from the durable capability. If no behavioral
capability can be named after grounding the observer and outcome, treat that as
evidence of the non-behavioral kind mismatch above.

**Inputs are not authoritative for doc routing.** If the input artifact
prescribes a specific feature-spec path (especially one containing the todo
slug), treat it as a hint at most. Classify from the work's actual shape and
the durable concept it concerns, not from path strings in the input. Input
authors must not prescribe doc paths — see `preparation-artifact-quality` for
the rule.

**Strip prescriptions; carry only intent.** The input's HOW (file paths,
mechanisms, edit/step instructions) and any doc-layer deliverable it names —
which snippets to author, and especially "author an ADR" — are not directives.
Re-home implementation HOW into the plan as hypotheses to verify (recording the
divergence per `preparation-artifact-quality`), strip doc-layer prescriptions,
and make the doc-routing call from the work's shape. Never carry an "author an
ADR" instruction: ADRs are governed by `general/policy/adr-discipline` (default
none, never by process step) and are assessed by the plan reviewer, not scheduled
by an input. An input that is a work order rather than intent — pervasive HOW, no
discernible WHAT/WHY — fails the viability gate; escalate rather than mine scope
from it.

### 1.6 Situate the premise in the existing todo landscape

Before scoping, compare this premise against the existing todo landscape — the
same collecting discipline as proactive feature surfacing (step 2), pointed at the
todo list instead of the domain.

**Scan** the active and prepared-unclaimed todos (`telec todo list`). Keep it
bounded so it stays cheap: that set only — delivered, removed, and iceboxed todos
are out of scope — and read cheap signals first (slug, then `input`), reaching for
a candidate's deeper artifacts only when it looks genuinely related.

**Judge the relation and its direction.** Overlap has a direction — precedence is
the default, intent is the override:

- **This premise yields** — it is redundant with an existing todo. The existing
  todo came first and is authoritative. Descope the overlapping portion of this
  premise and write the boundary into the PRD Scope; for a true duplicate of
  intent, surface it to the PO for an explicit decision (do not silently proceed,
  do not silently drop — the same discipline as feature surfacing).
- **This premise supersedes** — it replaces, broadens, or obsoletes an existing
  todo. Precedence does not rule here; this premise's intent displaces the older
  work. The action targets the **other** todo and is higher-stakes — see "Acting
  on a supersession" below.
- **Undeclared dependency** — this premise needs another todo's deliverable that
  the creator never declared as an `after`.

**Act on a dependency or a hand-off by the living-vs-dormant split** — the same
pattern as the duplicate triage in `diagnose`:

- The related todo has a **living orchestrator** (an active prepare or work
  session) AND you hold context it lacks → send one **best-effort** informational
  message (`telec sessions send <session_id> "<info>"`), substance only — no
  acknowledgement, no echo. Never block on it: if that session is absent or flaky,
  move on.
- A **dormant prepared/unclaimed** todo this premise depends on → record the edge:
  `telec todo update {slug} --after {dep}`. The edge **records the ordering
  dependency that gates dispatch** — an unmet dependency holds the dependent until
  the dep is satisfied. That gate is the reliable backbone; the message above is
  the best-effort enhancement on top of it.

**Acting on a supersession.** A supersession judgment from this orchestrator is a
hypothesis, not a verdict, and it touches another's existing work — so obsoleting
that work is the human's call unless the case is unambiguous. Act by the other
todo's state, and **never halt running work except on certainty**:

- Other todo **dormant (prepared, unclaimed)** → surface to the human; optionally
  freeze it (`telec todo freeze`, reversible) to hold it pending their decision.
  Nothing in flight is lost.
- Other todo **claimed, still in prepare** → hand the supersession to its living
  orchestrator (`telec sessions send`) and surface to the human. The obsolete call
  remains the human's.
- Other todo **claimed, building or delivering** → the gate is **confidence**, set
  tight:
  - **Certain or extremely confident** it is truly superseded or obsolete → halt it
    before it commits to main: freeze the todo, signal its worker to stand down,
    then surface to the human.
  - **Below that bar** → do not halt; that is a premature stall on a hunch. Surface
    to the human and let it proceed unless they pull it.

  Only 100%-sure / extremely-confident licenses halting claimed, running work.
  Confidence is the gate; the other todo's state sets what is at stake, not whether
  to act.

**Fold** the findings into the PRD: overlap into Scope (and "Docs to author or
update" where a shifted boundary moves doc ownership), declared dependencies noted
alongside the edges you recorded.

### 2. Shape the product target

Start with four open questions. Their answers organize the PRD; they are not a
form the conversation must visibly traverse:

1. **Authorized horizon:** What outcome is this work authorized to change?
   State the inferred horizon in one sentence. Derive it from the intent and
   situation, not from the todo kind alone.
2. **Product target:** What outcome and constraints does the authorized horizon
   support, and what clarification would make them coherent?
3. **Reconciliation need:** Against the current system and credible intended
   state, what must change for the better target to survive?
4. **Observable success:** How is the world observably different when the
   outcome is achieved?

Form the target against the human's intent, observable product reality, scale
and phase, credible intended state, and applicable domain knowledge. Domain
knowledge supplies shapes the human should not have to enumerate. It does not
acquire intent authority merely because a pattern is common.

For a creating-session-audited filing, a consequential product or business
detail enters the PRD only as a direct human statement, a faithful restatement,
a logically necessary implication, or an existing authoritative product
constraint. Ask whether another reasonable realization could satisfy everything
the human said while omitting or varying the detail; if so, it is unspecified.
Record it as an open human-owned decision or exclude it from contract scope.
Technical choices required for safe and correct delivery remain the concern of
plan, build, and their reviews; they do not become PRD requirements merely
because intake can foresee them.

Route attention through the few perspectives the situation earns. A
perspective is a focused question—security, operations, usability, migration,
or something the work itself reveals—not a standing panel or a performance of
seniority. Use the current session by default. Isolate a perspective only when
its unanchored judgment could materially change the scope. Invoke a named
framework only after the situation reveals a question that framework handles;
never run a default framework sequence.

Every consequential recommendation answers “why here?” Its reason resolves to
an inspectable premise or is labelled as an assumption. For a
creating-session-audited filing, an assumption may orient investigation or name
an open decision; it cannot supply missing product or business authority.
Consider both failure pressure and opportunity: what becomes costly or unsafe
at the stated scale, and what the existing situation makes unusually valuable
or cheap. Generic “enterprise-grade” or “best practice” language is not a
reason.

Look toward the plausible destination before choosing the present slice. Keep
a future consideration only when it constrains today's coherent choice or
deserves a deferral with a meaningful trigger. Record exclusions that bound the
accepted outcome; do not preserve a ledger of ideas that were plainly
inapplicable.

Write the PRD with these natural sections:

- **Authorized horizon** — the outcome this work may change.
- **Goal and why** — the better target and the need it serves.
- **Affected actors** — users, operators, systems, or services affected.
- **Scope** — inclusions and exclusions with situation-specific reasons.
- **Success criteria** — observable outcomes, each under a stable `#### SC-N`
  header; never mechanism or concrete proof.
- **Premises and assumptions** — the facts the scope rests on and what remains
  inferred.
- **Current and intended context** — product reality and credible trajectory,
  without turning internal implementation into a constraint on intent.
- **Risks, deferrals, and open decisions** — only meaningful deferral triggers
  and judgments genuinely owned by the human.

The PRD carries the accepted reasoning, not the drafting transcript. It does
not contain a framework report, perspective checklist, per-requirement metadata
form, or implementation outline.

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
- **Large / epic work** → BA proposes breakdown to the PO in plain register ("this feels like a lot for one work item; let me break it into parts we can tackle independently"). Creates a container todo, then one child per part using `telec todo create <child> "<content>" --kind <k> --group <container>`. Each child gets its own prepare/work track.

Skip stamps carry a `reason` field describing why the phase isn't needed for this work.

### 5. Write the PRD artifact

When the target is coherent, write the PRD:

```
telec todo artifacts write {slug} prd <content>
```

The artifact follows the shaping structure above at the depth the work earns.
It makes the horizon and consequential scope reasons easy to inspect, preserves
assumptions, and states observable outcomes without selecting concrete proof.
After every write, advance the state machine; a new PRD digest requires a new
independent review before human approval, except for an owner-directed literal
correction satisfying
`software-development/policy/preparation-artifact-quality#owner-directed-literal-prd-corrections`.

### 6. PRD review and approval

After writing the PRD, call `telec todo prepare {slug}`. The state machine
routes to a dispatched `/next-review-prd` worker before human approval.

The reviewer reads the input and PRD and, when the creating-session fidelity
gate applies, independently reads the creation record and creating transcript.
It checks every retained choice against its actual authority and re-runs the
shaping questions to probe for supported omissions. It writes
`prd-review-findings` only when findings exist and stamps the digest-bound
`prd_review` verdict.

- **`needs_work`** — read the findings, revise the PRD in intake, and advance
  again. The rewrite invalidates the prior review.
- **`approve`** — present the reviewed PRD, its authorized-horizon sentence,
  and genuine human-owned decisions. The human approves or refines product
  intent. A human refinement rewrites the PRD and therefore re-runs review
  before it returns for approval.

The emulator may help shape a draft but never reviews or approves its own
output. The human remains the sole authority for `prd_approved`.

When the human owner supplies an exact literal correction and explicitly
directs approval under the policy exception, the active prepare claimant writes
only that replacement and stamps `prd_review=approve` against the corrected
digest. It does not dispatch `/next-review-prd`. If the human also approves the
corrected PRD, the claimant records `prd_approved` and advances normally.

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

- **`prd_review` verdict** — bound to the current PRD digest before human
  approval, either by independent review or by the narrowly bounded
  owner-directed literal-correction path.
- **`prd-review-findings`** — written only when the draft needs work.

- **`prd` artifact** — written via `telec todo artifacts write {slug} prd <content>`, following the PRD template structure for every confirmed feature.
- **Feature spec snippet** at `docs/project/spec/feature/<context>/<concept-name>.md` — produced for human-facing and agent/operator-facing behavioral features alike. Concept-named, never slug-named. Frontmatter `delivered_by` includes this slug.
- **Domain spec / CLI-surface spec / architecture doc touchpoints noted in PRD** — when the behavioral feature also changes domain or cross-cutting design. The architecture phase authors the actual updates; intake names the affected docs in the PRD's "Docs to author or update" section.
- **No feature-lane artifacts for a non-behavioral kind mismatch** — reclassify to `change`, leave intake, and let prepare routing derive the change lane.
- **`prd_approved` stamp** — recorded when the real human confirms. The PO emulator cannot stamp this; the real human always owns final approval.
- **Skip stamp** when applicable: `architecture_skipped`, with reason.
- **`work_split` stamps** when the BA breaks the work down — references to child slugs.
- **Dependency edges + overlap reconciliation** (step 1.6) — an undeclared
  dependency is recorded via `telec todo update {slug} --after {dep}`; overlap
  where this premise yields is reconciled into the PRD Scope or surfaced to the PO;
  a supersession is escalated to the human, and a superseded todo already building
  is halted only on certainty.

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
- **A related todo's session is down or flaky (step 1.6).** Do not block intake
  on the best-effort message. The recorded `after` edge is the backbone; the
  message is an enhancement. Record the edge and proceed.
