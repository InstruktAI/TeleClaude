---
description: "How text an agent acts on is written: the reality wanted from the role its load path reaches — executor, judge, governor, maintainer — with the human's direction carried faithfully where it is invoked, limits held where they are enforced, and a bounded counter for an act the reader is already invited to take."
visibility: 'public'
---

# Agent-Facing Text — Policy

## Required reads

- @~/.teleclaude/docs/general/principle/priming.md

## Rules

### Write the reality wanted from the reader's role

- **Agent-facing text states what its reader does.** Agent-facing text is any
  text an agent acts on: snippets, commands, skills, dispatched briefs, peer
  messages, CLI help, gate output, and refusal text. It states the reality
  wanted from its reader — the job, what the job takes in, what it produces,
  and where everything else goes.
- **The load path sets the reader's role.** A text's reader is whoever the
  path that delivers it reaches — a baseline, a command's required reads, a
  dispatch brief, a refusal — not whoever the text is about.
- **Text an executor loads is written for the executor.** A baseline reaches
  every role in its scope, executors among them, so baseline text is written
  for the executor. What only a judge, governor, or maintainer needs lives in
  snippets those roles load on demand. Where an executor's job includes
  judging its own output, as an author self-reviews before committing, the
  executor holds the judge's role for that step and reads the judge's text
  there.

### Each role's reality

- **Executors** receive their job, the closed list of outputs it produces,
  and a destination for whatever they notice outside it: a log artifact, the
  dispatching session, the final report. The closed list sets the boundary;
  the destination keeps the list closed.
- **Judges** receive positive definitions of what counts: what a finding
  establishes, what evidence admits a claim. Naming the shape of a defect is a
  judge's job description, and the verdict boundary follows from the
  definition.
- **Governors** — orchestrators, dispatchers, brief authors — receive the
  roles they govern as routing facts, on the paths only governors load: what
  each role produces, and which of its observations reach the governor.
- **Contract maintainers** read a boundary as the subject itself — an
  authorization matrix, a role specification. That text states its
  boundaries plainly and is delivered on maintainers' load paths.

### A limit lives where it is enforced

- **A limit that must hold is enforced in the focus or integrity layer**,
  whose refusal names the gate and the door
  (`general/principle/trust-and-guardrails`) and lists no other acts. Text
  carries the reader's reality; the layer carries the limit.

### Relay and derived text

- **Text that invokes the human's direction carries it faithfully**
  (`general/policy/human-contract`).
- **A brief that states its reader's job derives that job from the intent and
  invokes no one.** Where the human's direction is phrased as what a role
  never does, the brief states what that role does.

### A counter for an invited act

- **A counter names an act to the role that might take it where that role's
  context already invites the act.** The invitation is in evidence: text or an
  affordance already on the reader's load path, such as a harness instruction
  or a tool description; the reader's own attempted act, met by a refusal; or
  an observed occurrence of the reader's default, in a transcript or a review
  finding.
- **The counter sits where the invitation lands.** It occupies the load path
  the invitation reaches, names the act once with its reason and the reality
  wanted instead, and is removed when the invitation is gone.

### Register

- **Directives are written in ordinary register and carry their reason**
  where the text's type has room for one.

## Rationale

- **Framing decides what enters awareness.** A text places what it names in
  its reader's awareness (`general/principle/priming`). The effect is
  directional, not absolute; framing by the reality wanted keeps the excluded
  acts out of awareness instead of relying on the reader to discard them.
- **An observation with a place to go needs no improvised route.** As an
  agent with no sanctioned path routes around a blocker
  (`general/principle/trust-and-guardrails`), an executor with nowhere to put
  an observation improvises one; the destination, not a list of exclusions,
  is what holds its scope.
- **One snippet reaches several roles.** Framed by its subject, a text either
  strips the routing facts a governor needs or hands an executor the
  boundaries only its governor uses. The load path is the one fact that tells
  them apart, and an executor on a shared path is the reader whose behavior
  the text changes most.
- **Text is ignorable; an enforced limit is not.** A limit stated in text
  costs salience and guarantees nothing. Where the limit must hold, the layer
  that holds it is the reliable place, and its refusal reaches only the reader
  who already tried the act.
- **Fidelity and framing answer different acts.** Invoking the human's
  direction needs their exact words, or the invocation misrepresents them; a
  job description needs what those words ask of its reader. Keeping the two
  acts apart lets intent survive relay without priming the act it rules out.
- **An invitation is already salient.** Naming an act the reader's context
  already invites adds no awareness and supplies the reason that outweighs
  the invitation. Requiring the invitation in evidence keeps the counter from
  becoming a place for hypothetical warnings.
- **A reason travels; emphasis distorts.** A rule with its reason generalizes
  to cases the text does not name, while emphasis changes the weight a reader
  gives a rule without telling it why.

## Scope

All agent-facing text, on every surface and in every project. A string that
reaches both a human and an agent counts as reaching an agent, as directive
text read by both is contract (`general/policy/documentation-discipline`);
prose read only by humans, such as a README, is outside this policy.

## Enforcement

Authors apply this policy while drafting
(`general/procedure/doc-snippet-authoring`,
`general/procedure/agent-artifact-authoring`) and when writing a brief
(`general/procedure/ai-to-ai-operations`). The doc-hygiene review lane applies
it to changed snippet bodies and directive-text surfaces
(`sdlc/policy/definition-of-done-lanes`). The judgment is the reviewer's; no
scanner grades it (`general/principle/intelligence-boundaries`). Existing text
comes into line as it is touched.

## Exceptions

None.

## See Also

- https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices — Anthropic, Prompting best practices: instructions stated as what to do, with their reason, in ordinary register.
- https://arxiv.org/abs/2402.07896 — Castricato et al., Suppressing Pink Elephants with Direct Principle Feedback: naming a topic in a prompt raises its occurrence even when the instruction is to avoid it.
