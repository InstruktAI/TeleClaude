---
description: A change is verified only against a standard that originated outside the session that produced it; an agent that writes both the work and the definition of correct has produced agreement, not verification.
---

# Verification Independence — Principle

## Principle

A change is verified only against a standard that originated **outside the
session that produced it**. An agent that writes both the work and the statement
of what "correct" means has produced agreement, not verification: the artifact
and its check restate one another, and a wrong design yields a check that
certifies the wrongness.

Four kinds of standard qualify, because none of them is authored by the session
under judgment:

- a contract a human wrote — a requirement, an acceptance scenario;
- an artifact a human ratified — an approved baseline, a blessed capture;
- the behavior of the real running system;
- a type system that rejects the illegal state before the code runs.

Where at least one is available, verification is possible. Where none is, a green
result carries no information about correctness — only about consistency.

The question is therefore never _are there checks?_ but _where did the standard
come from?_

## Rationale

Three forces make self-authored verification fail, and none of them is a defect
of care that better instruction could repair.

**Self-agreement is an information problem, not an intelligence problem.** A
check derived from the artifact it checks restates that artifact. When one
context window produces both, a wrong design produces a check that agrees with
the wrong design. More capable models produce the same tautology, because the
missing ingredient is an independent source of truth, not reasoning power.

**The required stance is trained out.** Writing a valuable check is an act of
adversarial distrust toward one's own work. Reinforcement learning from human
feedback rewards agreeableness toward context, including code the model just
produced. Instruction text cannot restore a stance the fine-tuning objective
removes, which is why accumulated guidance on "write better tests" never holds.

**Cost lands in-session; value lands after.** The expense of authoring and
running a check falls on the session that does it; the payoff falls on some later
session. Under that asymmetry any agent-maintained check erodes toward
weak-or-absent regardless of doctrine.

A compiler escapes all three. It is an oracle the agent did not write, it
rejects states the author never considered, and it costs nothing to maintain.
This is why the same principle yields opposite rules on different substrates:
where a compiler enforces unit-level correctness, colocated unit tests are
sound and expected; where none does, an agent-authored unit test grades its own
code and is forbidden. The rules differ because the available standards differ,
not because the languages are held to different values.

## Implications

- **Ask where the standard came from, not whether a check exists.** A suite
  proves nothing about verification; a single human-authored scenario bound to a
  real boundary proves a great deal.
- **Substrate determines how much external standard is already supplied.** A
  language with exhaustive matching and closed types supplies a large share at
  the unit level. A dynamically patched one supplies none there, and faking a
  collaborator costs a line — so the cheapest route to green is a check that
  asserts nothing.
- **Live verification is mandated by this principle, never banned by it.**
  Driving the real running system — a CLI invocation, an API call, a browser walk
  of the changed flow — is an external standard. Skipping it because checks are
  restricted elsewhere inverts the principle.
- **Ratification is what makes a captured baseline trustworthy.** A baseline
  taken from the rendered system is recorded reality. An author blessing the diff
  its own change produced collapses the standard back inside the session and
  destroys the property that made it worth capturing.
- **A project's posture is a recorded decision, not a taste.** What its substrate
  supplies, plus a deliberate ruling, determines whether it holds no checks,
  holds and runs existing ones without authoring more, or authors new ones bound
  to external contracts.
- **Removing a check is safe in a way that adding one is not.** Deletion
  withdraws a claim; authoring without an external standard manufactures
  assurance that was never earned.

## Tensions

- **Independence vs. coverage.** External standards are scarce; self-authored
  checks are cheap and unlimited. Honest verification therefore covers visibly
  less than a large suite appears to. What was false was the appearance, not the
  new, smaller number — but the smaller number is genuinely less reach, and
  pretending otherwise is its own dishonesty.
- **The compiler as oracle vs. over-trust in it.** A type system rejects illegal
  states, not wrong intentions. It is an external standard for a bounded class,
  and treating it as total verification repeats the original error one layer up.
- **Live verification vs. blast radius.** Driving the real system proves the flow
  that was walked and is blind to everything it never visited. That blindness is
  exactly where captured-and-ratified baselines earn their keep.
- **Deletion's safety vs. lost signal.** Freely removing checks protects against
  false assurance but discards real regression signal along with it. The
  asymmetry favors deletion only where the check's standard was self-referential
  to begin with; where it was external, deletion is a loss.
- **The principle vs. the momentum.** The cheapest available path is always to
  write the check oneself, in the same session, from the same understanding. The
  cost of this principle is paid every time that path is declined.
