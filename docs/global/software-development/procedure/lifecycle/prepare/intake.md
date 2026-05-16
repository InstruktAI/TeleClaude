---
id: 'software-development/procedure/lifecycle/prepare/intake'
type: 'procedure'
domain: 'software-development'
scope: 'domain'
description: 'Intake procedure for the prepare phase. The orchestrator (BA) interviews a stakeholder (real human or AI standin) to fill a PRD via BMAD-aligned template + elicitation toolkit. Output: a human-approved PRD ready to inform downstream derivation.'
---

# Intake — Procedure

## Required reads

- @~/.teleclaude/docs/general/principle/stewardship.md
- @~/.teleclaude/docs/general/principle/calibration.md
- @~/.teleclaude/docs/general/principle/attunement.md
- @~/.teleclaude/docs/software-development/concept/intake-frameworks.md
- @~/.teleclaude/docs/software-development/principle/architectural-defaults.md
- @~/.teleclaude/docs/software-development/policy/preparation-artifact-quality.md

## Goal

Take a human's intent (in-session conversation, an existing dumped input, or anything in between) and produce a **PRD (Product Requirements Document)** — a structured artifact capturing what the user actually wants, with success criteria, scope, constraints, and any open intent questions, ready for downstream derivation.

The orchestrator acts in **Business Analyst mode** for this phase: it elicits, structures, decides routing, and stewards the conversation. **"BA mode" is a procedural awareness configuration the same general intelligent agent loads — not a separate AI entity.** The agent loads this procedure and its required reads; that loadout is "BA mode." At other phases of the lifecycle the same agent loads different skills and operates in different modes.

The stakeholder being interviewed is the **Product Owner role**. This IS a separate session — represented either by a real human (default) or by a dispatched AI emulator (when the session is in standin mode per `additional_context`). The emulator runs the `emulate-product-owner` procedure with a deliberately small loadout: standing wishes for quality, no intake-frameworks tools, no artifact-writing, no stamping. The PO doesn't run the elicitation; it answers.

## Preconditions

- Session has been invoked through `/next-prepare` (with or without slug) OR auto-spawned by the daemon after a non-`--draft` `telec todo dump`.
- The session's `additional_context` indicates `human_in_loop: true | false`. Default is `true`.
- User proficiency known from PersonDTO injection, or asked once at the top of the session if absent.

## Steps

### 1. Establish mode and orient

- Read the session's `additional_context`. If it indicates **standin mode**, dispatch a Product Owner emulator via `/next-emulate-po {slug}` (cross-model preferred — Codex or Gemini). The command's required reads carry the PO loadout: standing wishes for quality (right-sized, established patterns, sane architecture, off-the-shelf preference), input-artifact handling, the answer-don't-orchestrate boundary.
- If **human_in_loop**, the human IS the Product Owner. No peer dispatch for this role.
- If no slug exists yet, hold off on creating one until the conversation has produced something concrete enough to commit to.
- If a slug exists and an `input` artifact is already present (dumped earlier, or partial from a prior session), read it in full before engaging.

### 2. Interview the Product Owner to fill the PRD template

The BA fills a structured **PRD template** through elicitation. The template sections are:

| Section | What it captures |
| --- | --- |
| **Goal** | What the user wants achieved (JTBD-framed: "the user wants the system to do X for Y under conditions Z"). |
| **Why** | The underlying need behind the surface ask. Often surfaced by applying 5 Whys when the stated request looks like a proxy. |
| **Affected actors** | Who is impacted — users, operators, downstream systems, integrating services. |
| **Scope** | What's in (Must / Should / Could) and what's out (Won't, with brief reasoning). Apply MoSCoW for prioritization. |
| **Success criteria** | Observable indicators that the work succeeded. Express in Gherkin (`Given / When / Then`) where the behavior is testable. |
| **Constraints** | Hard limits — existing patterns, capacity, security boundaries, off-the-shelf preferences, integration points. |
| **Risks and unknowns** | Failures imagined (light pre-mortem). Things only the user can resolve. |
| **Brownfield context** | If the work touches existing code, briefly note what's there. Full code-grounded analysis happens in the Architecture phase, not here — the BA only flags brownfield-vs-greenfield and any obvious code intersections the PO knows about. |
| **Open questions** | Anything the PO couldn't answer that needs further input. |

**Elicitation toolkit** (the BA applies what fits each section; see `intake-frameworks` for the full menu):

- **5 Whys** — when the surface ask looks like a proxy for an underlying need.
- **Jobs To Be Done (JTBD)** — for framing the Goal section.
- **MoSCoW** — for filling Scope with prioritized categories.
- **Pre-mortem** — light application when filling Risks.
- **Gherkin** — for Success criteria where observable behavior is testable.
- **Socratic questioning** — throughout, for clarity probes ("what does X mean to you here?").

Impact Mapping and Volere shell are available in the toolkit but **not default** — apply them only when the work item's scale justifies them (large/architectural work for Impact Mapping; compliance-heavy work for Volere).

**Proactive feature surfacing — the BA's domain-recognition responsibility.** As the input shape comes into focus, the BA recognizes which business-domain pattern (if any) the work matches — CRM-shaped, help-desk-shaped, ticketing-shaped, dashboard-shaped, etc. Domain recognition comes from the agent's training, not from a platform-supplied blueprint (platform-quality-flavors are for infrastructural building blocks, not business-domain templates).

Once the BA recognizes a domain, it proactively surfaces the standard features for that domain rather than waiting for the PO to enumerate them. Example: "What you're describing sounds like a CRM. CRMs typically include contact deduplication, pipeline stages, email templates, activity log, segmentation, reports. Of these, which apply to your case? Which to skip? Which need a twist?"

The PO answers per feature. Decisions land in the Scope section under Must / Should / Could / Won't. What the PO didn't think to ask for but should consider gets surfaced — not silently included, not silently dropped, but offered for explicit decision. This is the discipline that prevents "the human asked for a CRM and didn't mention dedup, so we shipped a CRM with no dedup."

**What the PRD does NOT contain.** The PRD is a product contract, not an implementation outline. Surface standard domain features for explicit inclusion or exclusion, keep code-grounded claims light, and leave deep technical grounding to the architecture phase. The architecture, test specs, and implementation plan derive from the approved PRD — they do not need to live inside it.

### 3. Steward, don't quiz

The BA states routing decisions in the user's register — does not ask the user to make technical choices they have no basis for. Example phrasings:

- "I can start drafting the implementation plan directly without a separate architecture step — this is a single-file change in the existing pipeline. Confirm?"
- "This feels like a lot to tackle in one go. Let me propose breaking it into smaller pieces we can tackle one at a time."
- "I think we have what we need. Let me write the PRD and you can review."

Calibration applies: for a novice PO, frame in goals and outcomes; for an expert PO, compressed technical terms are fine. The user's proficiency from PersonDTO drives the register.

### 4. Assess size and skip decisions for downstream phases

As the conversation progresses, the BA senses the size and nature of the work and makes routing decisions:

- **Small work** (single-file change, copy edit, simple modification) → BA may stamp `architecture_skipped` and/or `test_specs_skipped` with reason at the end of intake. Downstream goes from PRD straight to plan (or PRD → specs → plan).
- **Standard work** (typical feature) → full chain: PRD → Architecture → Test specs → Plan.
- **Large / epic work** → BA proposes breakdown to the PO in plain register ("this feels like a lot for one work item; let me split it into N parts we can tackle independently"). Uses `telec todo split` to spawn children. Each child gets its own track.

Skip stamps carry a `reason` field describing why the phase isn't needed for this work.

### 5. Write the PRD artifact

When the template is filled and the PO has had a chance to add anything else (BA invites once or twice naturally — "anything else on your mind for this?"), the BA writes the PRD:

```
telec todo artifacts write {slug} prd <content>
```

The PRD content follows the template structure above. JTBD-shaped Goal at the top. Each section filled at the depth the work warrants — small work has terse sections; large work has elaborated sections.

### 6. Present for approval

The BA presents the PRD to the PO (human or standin) for confirmation. Phrasing matches proficiency:

- Novice: walks through the document in user-facing language, asks "does this match what you want?"
- Expert: terser presentation, surfaces the structure quickly.

The PO either:

- **Confirms** → BA stamps `prd_approved` (only when a real human is in the loop; standin cannot stamp this — see Recovery).
- **Refines** → BA captures the delta, rewrites the PRD, presents again.

### 7. Hand off

Once `prd_approved` is stamped, intake is complete. The state machine's next-recommended-step transitions to the next phase based on skip stamps:

- No skips → Architecture phase next.
- `architecture_skipped` → Test specs phase next.
- Both skipped → Plan phase next.

The intake session can end; the next phase is invoked separately (or by the same agent loading the next phase's skill).

## Outputs

- **`prd` artifact** — written via `telec todo artifacts write {slug} prd <content>`, following the PRD template structure.
- **`prd_approved` stamp** — recorded when the real human confirms. Standin-mode sessions cannot stamp this; the real human must do so when they re-engage.
- **Skip stamps** when applicable: `architecture_skipped`, `test_specs_skipped`, each with reason.
- **`work_split` stamps** when the BA breaks the work down — references to child slugs.

## Recovery

- **Standin mode produces a PRD that the real human hasn't seen yet.** Agent goes idle after writing PRD. When the human invokes `/next-prepare {slug}`, the state machine reports "PRD authored in standin mode, awaiting your approval." The agent then presents the PRD to the human: "we role-played you and worked this through — here's what we landed on. Confirm or refine." Standard refinement flow applies from there.
- **Conversation stalls / human can't articulate.** BA applies more probing techniques (Socratic questions, "tell me about a similar problem you've solved before," "what would a successful version look like a year from now"). If genuinely stuck, BA captures what is known, marks remaining gaps as Open questions in the PRD, and writes a partial PRD flagged as needing more input. Human approves the partial-with-gaps explicitly.
- **Input artifact is sparse or contradictory.** BA reads what's there, identifies specific gaps, asks the human (or standin) targeted questions to fill them. Doesn't invent material.
- **PO contradicts the standing wishes** (e.g., explicitly asks for a hacky one-off solution). BA flags the contradiction in stewardship register: "the platform defaults toward [established pattern]; you're asking for [hack] — confirm you want this override and the reason." Captured in PRD's Constraints section.
- **Daemon-side `additional_context` is missing or ambiguous about mode.** Default to human_in_loop. Better to underuse standin than to standin-mode a real-human session.

## See Also

- ~/.teleclaude/docs/software-development/concept/intake-frameworks.md
- ~/.teleclaude/docs/software-development/principle/architectural-defaults.md
- ~/.teleclaude/docs/software-development/policy/preparation-artifact-quality.md
