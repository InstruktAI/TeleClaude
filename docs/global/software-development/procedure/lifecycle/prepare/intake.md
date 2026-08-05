---
description: 'Intake procedure for the prepare phase. The BA interviews a stakeholder (real human or AI standin) to fill a PRD via BMAD-aligned template + elicitation toolkit. Output: a human-approved PRD ready to inform downstream derivation.'
visibility: 'public'
---

# Intake — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/concept/intake-frameworks.md
- @~/.teleclaude/docs/software-development/principle/architectural-defaults.md
- @~/.teleclaude/docs/software-development/policy/preparation-artifact-quality.md

## Goal

<!-- planned-change:prepare-scope-shaping-and-prd-review -->

Your focus this turn is the intake phase: interview the Product Owner, fill
the PRD template, write the PRD, AND — **only when classification says so** —
author/enrich the feature spec snippet that captures the business value +
Gherkin acceptance scenarios in the durable docs layer. The wider prepare
lifecycle is still yours; this phase is one focused part of it.

Intake also situates the premise against what already exists: the same collecting
instinct as proactive feature surfacing, turned outward from the domain to the
sibling todos that exist or are coming, so the work is scoped against the
landscape rather than in isolation.
<!-- change:prepare-scope-shaping-and-prd-review -->

Your focus is to turn source intent into a reviewable product target that is
richer than the input where situation-specific domain intelligence earns that
enrichment. Determine the authorized horizon, form the better target before
implementation convention narrows it, choose the smallest coherent present
outcome, and write the choosing reasoning into the PRD's natural sections.

Intake situates the premise against observable current product behavior, the
credible intended state, and the existing todo landscape. It uses internal
implementation detail only to avoid duplicating capabilities and to prepare
later reconciliation; current module shapes do not veto product betterment.
<!-- /planned-change:prepare-scope-shaping-and-prd-review -->

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
  acceptance scenarios. Frontmatter `delivered_by` includes this slug.
  The Gherkin is authored here during intake — there is no separate
  test-specs phase.
  **Produced ONLY when the work is a user-visible product capability** (see
  classification step). Skipped for contract/CLI-surface refinements,
  implementation-only work, and infrastructure work.
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

| Category                                                         | What it looks like                                                                                                                                                                                                                                                                 | Durable doc home                                                                                                                                     | Feature spec?            |
| ---------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------ |
| **A. User-visible product capability**                           | A business-domain capability the human (end user, operator, customer) experiences directly. CRM contact dedup. Pipeline stages. Email templates. Image generation. A new dashboard. A new kind of search. Anything you would put on a product roadmap and demo to a customer.      | `docs/project/spec/feature/<context>/<concept-name>.md` (concept-named)                                                                              | **YES** — author/enrich. |
| **B. Domain model / service contract / CLI surface refinement**  | An agent-facing or operator-facing surface change. New CLI verbs. New service methods. New events. Renamed verbs. Removed deprecated paths. Refined invariants. Tightened validation. Adjusted defaults. The kind of work whose audience is _agents and operators_, not end users. | Existing `docs/project/spec/domain/<context>.md` (the domain spec) + existing CLI surface spec / `docs/project/design/architecture/*.md` as relevant | **NO**.                  |
| **C. Implementation-only / refactor / tooling / infrastructure** | Internal reshape with no contract change. A migration step. A test refactor. A dependency bump. A build-tooling fix. A one-shot data backfill. Work that leaves no durable behavioral contract behind.                                                                             | None — workflow.artifacts only (PRD, plan, etc.). Existing docs that happen to change get touched in `actual` status as part of the build.           | **NO**.                  |

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

<!-- planned-change:prepare-scope-shaping-and-prd-review -->

### 2. Interview the Product Owner to fill the PRD template

The BA fills a structured **PRD template** through elicitation. The template sections are:

| Section                | What it captures                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Goal**               | What the user wants achieved (JTBD-framed: "the user wants the system to do X for Y under conditions Z").                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| **Why**                | The underlying need behind the surface ask. Often surfaced by applying 5 Whys when the stated request looks like a proxy.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| **Affected actors**    | Who is impacted — users, operators, downstream systems, integrating services.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| **Scope**              | What's in (Must / Should / Could) and what's out (Won't, with brief reasoning). Apply MoSCoW for prioritization.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| **Success criteria**   | Observable indicators that the work succeeded, written as outcome-shaped prose in the PO's language ("the user can do X within Y", "the system handles N concurrent requests", "operators see Z when W happens"). **Author each criterion under its own stable subheader** — the header is exactly `#### SC-N` (e.g. `#### SC-1`), with the outcome prose beneath it — so each criterion is stably addressable as `prd#sc-n`. Do **not** put the title text in the header line: a titled header (`#### SC-1: Foo`) generates the anchor `sc-1-foo`, breaking the stable `prd#sc-1` reference. This is the Referencing-upstream-intent rule (every success criterion gets its own stable header); without it the plan phase cannot reference criteria one-by-one and plan-review blocks. **Not Gherkin.** The PRD carries outcome-prose; the `Given / When / Then` behavioral contract for Category A work is authored separately into the feature spec snippet (see Output targets above), not into the PRD. |
| **Constraints**        | Hard limits — existing patterns, capacity, security boundaries, off-the-shelf preferences, integration points.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| **Risks and unknowns** | Failures imagined (light pre-mortem). Things only the user can resolve.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| **Brownfield context** | If the work touches existing code, briefly note what's there. Full code-grounded analysis happens in the Architecture phase, not here — the BA only flags brownfield-vs-greenfield and any obvious code intersections the PO knows about.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| **Open questions**     | Anything the PO couldn't answer that needs further input.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |

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

<!-- change:prepare-scope-shaping-and-prd-review -->

### 2. Shape the product target

Start with four open questions. Their answers organize the PRD; they are not a
form the conversation must visibly traverse:

1. **Authorized horizon:** What outcome is this work authorized to change?
   State the inferred horizon in one sentence. Derive it from the intent and
   situation, not from the todo kind alone.
2. **Better target:** Given that horizon, what would improve the target beyond
   the input alone, and why in this situation?
3. **Reconciliation need:** Against the current system and credible intended
   state, what must change for the better target to survive?
4. **Observable success:** How is the world observably different when the
   outcome is achieved?

Form the target against the human's intent, observable product reality, scale
and phase, credible intended state, and applicable domain knowledge. Domain
knowledge supplies shapes the human should not have to enumerate. It does not
acquire intent authority merely because a pattern is common.

Route attention through the few perspectives the situation earns. A
perspective is a focused question—security, operations, usability, migration,
or something the work itself reveals—not a standing panel or a performance of
seniority. Use the current session by default. Isolate a perspective only when
its unanchored judgment could materially change the scope. Invoke a named
framework only after the situation reveals a question that framework handles;
never run a default framework sequence.

Every consequential recommendation answers “why here?” Its reason resolves to
an inspectable premise or is labelled as an assumption. Consider both failure
pressure and opportunity: what becomes costly or unsafe at the stated scale,
and what the existing situation makes unusually valuable or cheap. Generic
“enterprise-grade” or “best practice” language is not a reason.

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
<!-- /planned-change:prepare-scope-shaping-and-prd-review -->

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

<!-- planned-change:prepare-scope-shaping-and-prd-review -->

When the template is filled and the PO has had a chance to add anything else (BA invites once or twice naturally — "anything else on your mind for this?"), the BA writes the PRD:

```
telec todo artifacts write {slug} prd <content>
```

The PRD content follows the template structure above. JTBD-shaped Goal at the top. Each section filled at the depth the work warrants — small work has terse sections; large work has elaborated sections.
<!-- change:prepare-scope-shaping-and-prd-review -->

When the target is coherent, write the PRD:

```
telec todo artifacts write {slug} prd <content>
```

The artifact follows the shaping structure above at the depth the work earns.
It makes the horizon and consequential scope reasons easy to inspect, preserves
assumptions, and states observable outcomes without selecting concrete proof.
After every write, advance the state machine; a new PRD digest requires a new
independent review before human approval.
<!-- /planned-change:prepare-scope-shaping-and-prd-review -->

### 6. PRD review and approval

<!-- planned-change:prepare-scope-shaping-and-prd-review -->

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

<!-- change:prepare-scope-shaping-and-prd-review -->

After writing the PRD, call `telec todo prepare {slug}`. The state machine
routes to a dispatched `/next-review-prd` worker before human approval.

The reviewer reads the input and PRD, checks every retained choice against its
stated premise or assumption, and independently re-runs the shaping questions
to probe for omissions. It writes `prd-review-findings` only when findings
exist and stamps the digest-bound `prd_review` verdict.

- **`needs_work`** — read the findings, revise the PRD in intake, and advance
  again. The rewrite invalidates the prior review.
- **`approve`** — present the reviewed PRD, its authorized-horizon sentence,
  and genuine human-owned decisions. The human approves or refines product
  intent. A human refinement rewrites the PRD and therefore re-runs review
  before it returns for approval.

The emulator may help shape a draft but never reviews or approves its own
output. The human remains the sole authority for `prd_approved`.
<!-- /planned-change:prepare-scope-shaping-and-prd-review -->

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

<!-- planned:prepare-scope-shaping-and-prd-review -->

- **`prd_review` verdict** — independently bound to the current PRD digest
  before human approval.
- **`prd-review-findings`** — written only when the draft needs work.

<!-- /planned:prepare-scope-shaping-and-prd-review -->

- **`prd` artifact** — written via `telec todo artifacts write {slug} prd <content>`, following the PRD template structure. **Always produced.**
- **Feature spec snippet** at `docs/project/spec/feature/<context>/<concept-name>.md` — **produced ONLY for Category A work** (user-visible product capability per step 1.5). Concept-named, never slug-named. Frontmatter `delivered_by` includes this slug.
- **Domain spec / CLI-surface spec / architecture doc touchpoints noted in PRD** — for Category B work (contract/CLI-surface refinement). The architecture phase authors the actual updates; intake names the affected docs in the PRD's "Docs to author or update" section.
- **No durable doc** for Category C work (implementation-only / refactor / tooling). PRD only.
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

## See Also

- ~/.teleclaude/docs/software-development/concept/intake-frameworks.md
- ~/.teleclaude/docs/software-development/principle/architectural-defaults.md
- ~/.teleclaude/docs/software-development/policy/preparation-artifact-quality.md
