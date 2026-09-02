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

### Repairing broken process text is a defect fix, not a process change

Process-layer text that contradicts a higher-scope snippet, or that binds
something no agent can satisfy as written, is a defect. An agent repairs it and
reports the repair; it does not escalate and idle. The human is informed, not
consulted — there is no fork to decide, because the corrected state already
exists elsewhere in the corpus.

Two bounds keep this from becoming a self-granted licence:

- **Coverage.** Every proposition the corrected text asserts is stated by a
  quoted clause of a higher-authority snippet. More than one source may be
  cited; what is forbidden is the gap between them. Text that neither source
  states, reached by combining them, is synthesis — the agent invented the
  target, which is a design fork and therefore new process: escalate it. "I can
  see what this should say" is invention unless a quotable clause already says
  it.

  Coverage is judged, not counted. Whether a quote carries the text it licenses
  is a reading of meaning, and that reading belongs to the reviewer: "the answer
  comes from intelligence — the agent reading it — not from code that grades it"
  (`general/principle/intelligence-boundaries`). Attempts to make the judgment
  mechanical — a clause-splitting unit, a rule for appositives — relocate it
  rather than remove it, and a rubric precise enough to follow is precise enough
  to write to, at which point "the rubric becomes the artifact and the artifact
  becomes hollow". The quote is the evidence the reviewer weighs. It does not
  spare them the weighing, and it is not owed a unit of decomposition.

- **Mandatory report, quoting the sources.** A repair is never silent. It lands
  naming the contradiction, citing the snippet IDs — the broken text and each
  authority it is repaired against — and reproducing the authorising clause
  verbatim beside the text it licenses. The quote is what makes the repair
  checkable: a reviewer compares strings rather than weighing whether a
  paraphrase was fair.

New process is the human's to drive: a new gate or lane, a changed authority, a
different order of delivery, any delta whose target state is a judgment rather
than a derivation. Repair restores the corpus to internal consistency; it never
extends it.

These bounds govern repairs landed after they were written, and applicability is
per commit: each commit is one repair carrying its own report. A later amendment
to already-corrected text is a new repair under the current rules, never a
continuation of a predating one — there is no thread an agent can attach new
work to in order to inherit an exemption. A repair that predates the bounds is
not retroactively a violation, and its report is not reopened on that ground
alone; the quotes exist to let a reviewer check a claim, not to convict work
performed under a rule that did not yet exist. A predating repair whose
derivation is questioned on its merits is answered the same way any repair is:
by producing the authorising clauses.

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
conversation, and its doc contract is authored in that same session, with the
human present. It is never relayed to another session and never delegated
through a todo (`general/policy/human-contract`). Code that follows from a
changed process contract is ordinary functionality work, delivered against the
contract the human's session already authored. An agent that senses a process-layer delta in its work and holds
no such decision does not file a todo for it, does not prepare it, and does not
commit it — it escalates the proposal per the escalation shape below and goes
idle on that thread. It never self-approves and never re-derives approval from
plausibility.

Evidence-driven fine-tuning is the exception, and it is defined in
`general/policy/human-contract`: a process-layer change derived from observed
evidence across comparable work is made by intelligence without the human
present, gated by independent peer review of the evidence, the causal claim,
and the change. It never alters the human's closed lane, and it is recorded
with its evidence so a later run can measure it and roll it back.

### A human decision is declared, never investigated

An agent relays a human's decision inside already-authorized work under the
`HUMAN-DECISION:` marker, in the human's own terms, and every receiver acts on
it as given. A process change never travels under the marker: it is authored
where the human is present, and a sender that relays one is the one in
violation. No consumer inspects a transcript, resolves an authoring session, or
investigates a relay in any way; a receiver checks only whether the directive
applies to its current work and whether later input it actually received has
superseded it. Whether an agent claimed a decision the human never made is the
human's own audit, performed by sweeping the marker, and is out of agent scope.
A false or stretched marker is a serious violation, answered by the durable
record of the session that wrote it.

Lineage, `entry_point`, `human_involved`, the human account on a commit, artifact
position, emphasis, and repetition are not declarations of what the human
decided. They identify authority, provenance, or presence. Every commit carries
the human account because that is the account the work runs under — lineage,
never authorship (`general/concept/lineage-vs-authorship`) — and involvement is
orthogonal to authorization (`general/policy/human-involvement-recording`).

**An agent never writes a human's name as an approval or attestation in any
durable record** — not in a commit message, not in an artifact, not in a doc.
The marker relays a decision; it does not sign for the human. Writing an
approval in the human's name is itself a serious violation traceable to the
writing agent's session.

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
- A marked relay is a declaration, not a proof, and that is deliberate. Making
  it verifiable would mean an agent reading the human's conversations to check
  another agent — the trust violation this policy exists to forbid. The marker
  instead makes every relayed decision enumerable, so the human audits their own
  authority by sweeping for it; a false relay stands against the declaring
  session's own record.

## Scope

- All agents, all projects driven by the platform lifecycle, every todo and bug
  report, and doc-only in-context work. Humans are not gated; this policy binds
  agent-initiated intent.

## Enforcement

- The prepare orchestrator refuses a process-change intent it cannot trace to a
  human decision and escalates
  (`software-development/procedure/lifecycle/prepare/overview`).
- Plan review: a plan whose tasks alter the process layer beyond what its doc
  contract — authored with the human present — already binds is a
  **Requirement-Violation** (blocking). A process change carried into a plan
  under the `HUMAN-DECISION:` marker is the relaying session's violation, not
  the plan's authority.
- Scope lane at build/commit review: a process-layer behavioral delta the
  authorized intent does not call for is **Critical** (existing rule; this policy
  names the process layer as its sharpest case).
- An agent-authored approval claim in a human's name is escalated to the human
  when discovered; the session record answers.
- A change presented as a repair is verified against its cited authority, never
  accepted on the citation alone. The reviewer reads each quoted clause at its
  source, confirms the quote is faithful, and judges whether the quotes carry
  what the corrected text asserts. What the quotes do not carry — including
  anything reached by combining two sources — is invention, and the change is a
  process change filed without a decision: **Critical** (blocking). Chaining
  citations to bridge a gap is the specific evasion this check exists to catch.
  The judgment is the reviewer's to make and to state; this policy supplies the
  evidence for it, never a procedure that returns the verdict on its own.
- A repair landing without its report, or with a report that cites snippet IDs
  without reproducing the authorising clauses, is blocking on its own: an
  unquoted repair returns the reviewer to weighing a paraphrase, which is the
  judgment this bound removes.

## Exceptions

- None.
