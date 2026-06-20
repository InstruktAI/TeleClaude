---
description: 'Operational definition of a functional test: the boundary it enters, the only mocks it may use, the tells of a unit test in disguise, and why this distinction is enforced at review rather than by automation.'
visibility: 'public'
---

# Functional Test Boundary — Concept

## What

A functional test enters the system where a real caller enters it — the same
surface an agent, a user, or a peer process touches — and exercises the whole
chain behind that surface with real in-process components.

**The boundary.** A functional test drives one of the system's real entry
surfaces and asserts the contract that surface emits:

- a CLI command — its handler invoked the way the command dispatches it;
- an HTTP route — driven through a real client against the app;
- a state machine — its public driver/step, never an internal step function;
- the event bus — a real envelope published and consumed;
- a TUI screen or widget — driven through its real update path.

The contract it asserts is what the surface actually produces: printed output, an
emitted event, a response payload, a persisted artifact.

**Legitimate mocks — only the process or network line.** A functional test fakes
only what leaves the process or the machine: a spawned subprocess (git, the agent
CLI), the message broker (redis), outbound HTTP, the model/LLM, and a filesystem
location treated as an external store. Everything in-process runs for real. The
discriminator is never the leading underscore on a name; it is whether the faked
thing crosses a process or network boundary.

**A unit test in disguise — the tells.** A test is a unit test wearing the
functional label when it does any of the following:

- enters at an internal symbol that is not the behavior's real surface, and fakes
  that symbol's in-process collaborators (the classic "call the private step,
  patch its neighbors");
- patches in-process, non-boundary collaborators, so the chain under test never
  actually runs;
- asserts a constructor default, a model's field shape, or a config-dict literal —
  the library owns those, and the test only pins source it can already read;
- asserts a function's return value or a passthrough where no real branch is
  exercised, or echoes a mock with data the test itself supplied;
- scans source files or the filesystem to police a structural rule — a meta-test,
  forbidden outright.

A leading-underscore symbol can still be the real surface: a CLI handler named
`_handle_blueprint_affected` is the command's entry point, so driving it
end-to-end while faking only the subprocess it shells out to is functional. Judge
the surface and the fakes, never the name.

**Enforcement is judgment, not automation.** Whether a test is functional is a
structural judgment about how it is wired. It is not a property a type can make
unrepresentable, and not one a scanner can decide without being gamed — the same
call shape is legitimate at one surface and a violation at another. It is
therefore enforced at review, against this definition, as a first-class gate. A
forbidden directory name or a filename pattern is at most a trivial backstop
against one naive regression; it is never the enforcement, and presenting it as
such manufactures false assurance. Per the enforcement-placement order in
`software-development/policy/definition-of-done-lanes`, a custom scanner that
tried to grade functional-versus-unit would itself be the
lint-as-type-substitute, gameable-automation anti-pattern this codebase rejects.

## Why

The product is orchestration glue — handlers, state machines, adapters, and
projectors that compose in-process units into behavior. A unit test of one such
unit, with its neighbors faked, asserts the author's own wiring back to them: it
stays green while the composition it was meant to protect breaks, and it resists
the very refactor it should survive. Where no compiler enforces unit-level
correctness (Python, TypeScript), an agent-authored unit test grades the code its
author just wrote and drifts to green-theater. Functional tests catch real
defects because they run the real chain. The boundary discipline is what keeps a
suite worth keeping — the difference between coverage that pins behavior and
coverage that pins implementation and has to be thrown away.

## See Also

- ~/.teleclaude/docs/software-development/policy/testing.md — the testing doctrine this boundary definition serves
- ~/.teleclaude/docs/software-development/policy/definition-of-done-lanes.md — the review lane that enforces the distinction
- ~/.teleclaude/docs/software-development/policy/python/testing.md — the Python idioms and the path-guard's limits
