---
description: "Process changes are decided by humans. A todo whose intent alters the process layer's behavioral contract carries an explicit human-approval declaration in its input, or it is not filed and not prepared."
---

# Process Change Authority — Policy

## Rules

### The process layer is its doc contract

The process layer is the machinery that governs how work is validated and
delivered: the lifecycle state machines (prepare, work, integrate), the quality
gates and their composition (hooks, lint composition, ratchets, spec coverage),
the review lanes and lifecycle procedures, and todo/state semantics. Its
contract is the doc snippets that describe it — the lifecycle procedures, the
integration and workflow feature specs, the review-lane catalog, and the
gate-composition specs. Changing the process means changing what those snippets
bind.

### What is a process change

A **process change** is a behavioral delta to a process-layer contract — the
same discriminator `general/policy/documentation-discipline` uses everywhere:
the change alters a contract a test could bind (a `Given / When / Then` changes
meaning) — what a gate blocks, in what order candidates land, who holds
authority, what is skipped, halted, or escalated.

Restoring code to match the current process-layer contract is a bug fix, not a
process change: the docs are the process, and code drifting from them is a
defect.

### What is NOT a process change

A descriptive edit to a process-layer snippet is not a process change: prose
hygiene, clarification, restructuring, typo fixes, aligning a scenario's
wording to what the machinery already verifiably does. Behavior bound before
and after is identical.

Two exemption claims are explicitly void:

- **"It's minute" is not an exemption.** Size is not the axis. A one-line
  behavioral change to a gate is gated; a large descriptive cleanup is not.
- **"It aligns with the process's intent" is not the agent's call.** Perceived
  intent-alignment is precisely the judgment the human ratifies; an agent never
  self-grants it.

### Declaration at filing

A todo or bug report whose intent involves a process change carries an
**explicit human-approval declaration** in its `input`: who approved and in
what context (`Process change — human approved: <name>, <session/date>`). An
agent holding no such approval does not file the todo — it escalates the
proposal to the human and goes idle on that thread.

### Doc-only process changes

A process change that alters documentation only follows the doc-only in-context
route and creates no todo. Its durable approval declaration lives in the commit
message as:

`Process-Change-Approved-By: <name> (<session/date>)`

The author records the human's explicit approval from the active conversation;
it is never inferred from silence, prior delegation, or technical fitness. The
independent doc-hygiene review verifies the declaration and the behavioral
delta. This is the doc-only equivalent of the `input` declaration and does not
exempt the change from process authority.

### Refusal at prepare

The prepare orchestrator enforces the gate before any artifact work: when the
intent requires a process change and the `input` carries no human-approval
declaration, the todo is **refused** — not prepared, not partially prepared.
The orchestrator escalates per the escalation shape below and goes idle as a
beacon. It never self-approves and never re-derives approval from
plausibility.

### Bug plans never contain process changes

A bug's fix is minimal and targeted **within the existing process contract**.
When a diagnosed root cause is a process-design gap, the bug lane's output is
the diagnosis plus an escalation — a proposed change requiring human approval —
never a fix that alters the process layer.

### Escalation shape

A refusing or escalating agent packages the decision so ratification costs one
read and one word: **what** process delta the work implies (the snippet lines
that would change), **why** the work appears to demand it, and the **blast
radius**. Then it idles on that thread only; non-gated work continues. A bare
"this might be a process change?" without the package is itself a violation of
this rule.

### The todo/prepare gate fires at two moments only

For todo-driven work, the gate fires at filing time and prepare entry. It never
halts running work: build scope is fixed and gate-checked before build starts. A
builder that discovers mid-flight its task requires an unapproved process change
defers or kicks back under existing scope discipline; this policy adds no
mid-work stop trigger. Doc-only in-context work has no filing or prepare phase;
its declaration gate fires at commit review through the doc-hygiene lane.

### Accountability

The declaration is durable, auditable text in the `input` artifact for
todo-driven work and in the commit message for doc-only work. A false
human-approval declaration is a serious violation traceable to the declaring
agent's session.

## Rationale

- The knowledge asymmetry inverts on process: agents hold technical depth, but
  what the process guards — ordered delivery, forced escalation on blockers,
  gate authority — is the human's design. An agent that reroutes a gate to keep
  its own work flowing has optimized away the thing it was supposed to guard.
- Every downstream gate (diagnosis, plan review, build review) validates
  execution against the todo's intent artifact. When an agent authors a process
  change into that intent unratified, the gates faithfully validate a smuggled
  premise. The only reliable moment to check authority is before the intent
  gains it: filing and prepare entry.
- The behavioral-delta discriminator keeps the gate sharp: agents already apply
  it for doc reflection, it is mechanically checkable against the doc layer,
  and it cannot be inflated into "everything is a process change" without
  visibly misapplying a shared test.

## Scope

- All agents, all projects driven by the platform lifecycle, every todo and bug
  report. Humans are not gated; this policy binds agent-initiated intent.

## Enforcement

- Doc-only process commits carry the `Process-Change-Approved-By` declaration;
  independent doc-hygiene review blocks a missing or false declaration.
- The prepare orchestrator refuses unapproved process-change intents at prepare
  entry (primary gate; `software-development/procedure/lifecycle/prepare/overview`).
- Plan review: a plan whose tasks alter the process layer while the `input`
  carries no human-approval declaration is a **Requirement-Violation**
  (blocking) — parallel to the documentation hard gate.
- Scope lane at build/commit review: a process-layer behavioral delta the
  approved intent does not call for is **Critical** (existing rule; this policy
  names the process layer as its sharpest case).
- A false declaration is escalated to the human when discovered; the durable
  record answers.

## Exceptions

- None.
