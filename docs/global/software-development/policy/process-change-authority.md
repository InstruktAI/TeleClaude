---
description: 'Process changes are decided by humans. An agent that holds no human decision for a process-layer behavioral delta escalates the proposal and goes idle; it never files, prepares, or commits the change on its own judgment.'
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

A **process change** is a behavioral delta to a process-layer contract, on
either discriminator `general/policy/documentation-discipline` sets: the change
alters a contract a test could bind (a `Given / When / Then` changes meaning),
or it rewrites instruction text an agent acts on — what a gate blocks, in what
order candidates land, who holds authority, what is skipped, halted, or
escalated. The process layer is largely expressed as instruction text rather
than code, so the second discriminator carries most of it: editing a runtime
decision block or a dispatched worker's brief is a process change precisely
where no test can bind it.

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

### The human decides; the agent escalates

A process change is executed only when the human decided it in a live
conversation. An agent that senses a process-layer delta in its work and holds
no such decision does not file a todo for it, does not prepare it, and does not
commit it — it escalates the proposal per the escalation shape below and goes
idle on that thread. It never self-approves and never re-derives approval from
plausibility.

### Evidence is the existing record, never asserted prose

Whether a human was in the loop is evidenced by the machinery that already
records it: the session transcript of the conversation that decided the change,
the todo creation record (`lineage`, `entry_point`, `human_involved`) for filed
work, and commit lineage for doc-only work. No prose declaration exists or is
required.

**An agent never writes a human's name as an approval or attestation in any
durable record** — not in a commit message, not in an artifact, not in a doc.
A human decision is evidenced by the records above, never claimed by
agent-authored text. Writing such a claim is itself a serious violation
traceable to the writing agent's session.

### Bug plans never contain process changes

A bug's fix is minimal and targeted **within the existing process contract**.
When a diagnosed root cause is a process-design gap, the bug lane's output is
the diagnosis plus an escalation — a proposed change requiring the human's
decision — never a fix that alters the process layer.

### Escalation shape

A refusing or escalating agent packages the decision so ratification costs one
read and one word: **what** process delta the work implies (the snippet lines
that would change), **why** the work appears to demand it, and the **blast
radius**. Then it idles on that thread only; non-gated work continues. A bare
"this might be a process change?" without the package is itself a violation of
this rule.

### The gate never halts running work

The authority question is settled before work starts: at filing and prepare
entry for todo-driven work, and in the live conversation for doc-only
in-context work. A builder that discovers mid-flight its task requires an
undecided process change defers or kicks back under existing scope discipline;
this policy adds no mid-work stop trigger.

## Rationale

- The knowledge asymmetry inverts on process: agents hold technical depth, but
  what the process guards — ordered delivery, forced escalation on blockers,
  gate authority — is the human's design. An agent that reroutes a gate to keep
  its own work flowing has optimized away the thing it was supposed to guard.
- Every downstream gate (diagnosis, plan review, build review) validates
  execution against the todo's intent artifact. When an agent authors a process
  change into that intent unratified, the gates faithfully validate a smuggled
  premise. The only reliable moment to check authority is before the intent
  gains it.
- Asserted approval prose is worse than no record: it dresses an agent's claim
  in the human's name, and a reader cannot distinguish it from the real thing
  without the transcript — which is the actual evidence anyway. The existing
  records (creation record, lineage, transcripts) are falsifiable and
  mechanically stamped; prose is neither.

## Scope

- All agents, all projects driven by the platform lifecycle, every todo and bug
  report, and doc-only in-context work. Humans are not gated; this policy binds
  agent-initiated intent.

## Enforcement

- The prepare orchestrator refuses a process-change intent it cannot trace to a
  human decision and escalates
  (`software-development/procedure/lifecycle/prepare/overview`).
- Plan review: a plan whose tasks alter the process layer without a human
  decision behind the intent is a **Requirement-Violation** (blocking).
- Scope lane at build/commit review: a process-layer behavioral delta the
  approved intent does not call for is **Critical** (existing rule; this policy
  names the process layer as its sharpest case).
- An agent-authored approval claim in a human's name is escalated to the human
  when discovered; the session record answers.

## Exceptions

- None.
