---
description: Python verification permits one bounded black-box CLI acceptance harness, independent review, and agent judgment of runtime logs.
---

# Test Moratorium — Policy

## Rules

- **Python test authorship is limited to the CLI acceptance harness.** Exceptions defines its allowed scope. Outside that allowance, adding a test file, a test dependency, or a test runner is a violation regardless of quality, size, or justification, and that includes markup-serialization snapshots (`toMatchSnapshot` over component trees) — a serialized render is the code restating itself.
- **The harness exception is bounded by the assignment.** A product delivery uses the existing checks and adds nothing to the harness: no journey, scenario data or helper. The harness changes only through work whose stated purpose is that change. It does not authorize a new verification capability or a replacement verification architecture. An evidence gap is reported to the driver for disposition within the existing scope, not converted into permission to build infrastructure. New verification infrastructure requires its own explicitly authorized scope and any change to this policy that scope needs (`general/policy/human-contract`). Calling a subsystem a harness helper, dependency, probe or acceptance requirement does not supply that authority.

- **The live daemon supplies operational signals.** Where a started daemon's health is reported is owned by `local/projects/teleclaude/policy/daemon-availability`. After an install, the installation inspector reads that install's log window under `sdlc/procedure/maintenance/installation/overview` and uses its judgment to investigate anomalies and fix forward. The log bug hunter provides a later anomaly backstop. A regular committer's validation and independent commit-review obligations remain governed by `general/policy/commits`.

- **The CLI help smoke runs in the worktree.** A CLI-touching builder exercises each affected help path once through its worktree's own `bin/telec`, and the independent reviewer repeats that targeted smoke the same way. The wrapper runs the worktree's code against the home repository clone the platform provisions with the worktree, and the global `telec` runs installed code against the live platform (`local/projects/teleclaude/spec/feature/agent_runtime/isolated-home`); neither agent assembles home files or sets the variable. A shared command-surface change may traverse its affected help paths in one batch of those wrapper calls; routine lint never performs or substitutes for this check. Throwaway in-session probes are permitted — driven the same way and deleted before commit. An agent never sets, exports, or removes `TELECLAUDE_HOME` or `HOME`, and never removes a directory named by a variable: a shell variable does not survive from one tool call to the next, so a home set in one call and removed in another resolves to the live home. This smoke covers behavior inside the CLI process; commands that write project state or act through the daemon are outside its scope.
- **This repository does not bind the generic `test` action.** The platform base registry defines the action without a binding. Each repository owns its bindings through its own `teleclaude.yml`; satellite projects follow their own testing contracts.
- **The moratorium expires when the Rust runtime supersedes v1.** The Rust runtime states its own testing doctrine; nothing in this policy constrains it.

## Rationale

Verification uses a standard independent of the implementation under judgment
(`general/principle/verification-independence`). Python runtime substitution can
bypass the process boundaries where integration failures occur. The bounded
harness exercises those boundaries with real CLI processes, daemon requests and
persistent state, against independently reviewed public scenarios.

A harness that every delivery may extend grows by each delivery's own
justification, and nobody weighs the total: within days of its admission it had
more than doubled through journeys added by unrelated feature deliveries. Its
author also grades the work it delivered. Keeping additions to work whose
purpose is the harness keeps its size a decision someone makes.

An uneventful log window does not prove every specified behavior occurred.
Build review judges conformance to the specifications, the logging policy
exposes significant operations and failures, and the installation inspector
judges anomalies after each install. The CLI journeys supply evidence for the
behavior they exercise; unvisited behavior is outside that evidence.

Disposable runtime isolation protects the operator's configuration, credentials
and services. Shared cold and full profiles concentrate verification on the
named public journeys, while full installation proof covers the supported
installation path. These boundaries keep the verification claim proportional to
what actually executes.

A delivery's evidence needs can otherwise expand into a second software project:
each new proof demand generates another helper and its own proof demands. Scope
is established before that construction. Review checks both authorization and
necessity; conformance to an agent-authored verification contract cannot create
authorization for the contract's expansion.

## Scope

This repository only. Satellite projects keep their own testing contract, declared in their own configuration. Extending the moratorium beyond this repository is a separate decision on its own evidence, never a consequence of this policy.

## Enforcement

- The `code` overlay block is absent from this repository's `teleclaude.yml`, and no binding there owes `log-check`: a commit in this repository activates nothing live (`local/projects/teleclaude/policy/agent-service-control`), so it owes no runtime log judgment. A re-authored overlay binds no `log-check`.
- **The quality-configuration assessment does not author a `code` block for this repository.** The checkpoint overlay is authored at assess-time — `sdlc/procedure/code-config-assessment` writes it and feeds `agent_stop` with `test` + `log-check` — and every session started with `/projects-assess-config` reaches that path. A re-authored `code` block silently re-binds `test` and voids this policy. Until a guardrails check enforces this, the absence of that block is a contract, not an oversight — an agent that finds it missing leaves it missing. The project-analysis procedure (`/projects-analyze`) never touches the overlay and is not a door to this failure.
- **Runtime log judgment follows the install.** The installation inspector's assessment of an install is the judgment of the runtime's log window after it. Its assessment and recovery remain intelligence work per `general/principle/intelligence-boundaries`.

- Reviewers treat test files, runners, and dependencies outside the bounded CLI acceptance allowance as blocking findings. The harness consumes independently reviewed scenarios from before implementation; its author does not bless a captured failure as the expected result.
- Reviewers assess the complete verification mechanism against the assignment and the existing harness, not its filename or claimed membership in the harness. An unauthorized infrastructure expansion is a scope finding even when each of its components has been reviewed individually. A delivery whose stated purpose is not the harness and that changes it is a scope finding as well.

## Exceptions

- One black-box CLI acceptance harness may be authored and maintained under
  `local/projects/teleclaude/spec/feature/agent_runtime/runtime-acceptance`.
  It drives real public entry points in fresh subprocesses and, for the full
  profile, a disposable runtime with real daemon, socket and persistent storage.
  Its controller imports no application modules and substitutes no application
  collaborators or authentication decisions. Synthetic input and disposable
  operating environments provide isolation; no live user configuration,
  credentials, daemon or storage is used.
- Python is preferred for harness orchestration, health observations, timeouts,
  cleanup and report handling, keeping shell orchestration from accumulating.
  Real CLI journeys invoke the public executables as subprocesses.
  Public command-line tools, including `curl`, are permitted when they serve the
  boundary being verified; supporting HTTP reads may use a Python client.
  Tool choice preserves real invocation fidelity and bounded, diagnosable
  execution. The Python preference is not a categorical subprocess-tool ban.
- The allowance includes only the harness, its scenario data, essential execution
  dependencies, and its fast commit/full CI/release wiring. General-purpose
  test corpora, the generic `test` binding, unit tests, per-module checks and markup
  snapshots are outside that allowance. Full installation proof is required by
  the release contract.
- Maintenance of that harness covers the admitted journeys and the execution path
  that already serves them. The terms essential dependency and CI wiring do not
  admit a newly constructed provisioning, observation or proof system as incidental
  delivery work. Such a capability follows the explicit scope boundary above.
- Scenario assertions derive from the public contracts and are independently
  reviewed before implementation. Any unexpected error or wrong observable
  result fails its journey, regardless of error class. Coverage claims name the
  journeys exercised; passing cannot imply that every command works.
- Other verification needs require changes to this policy rather than one-off
  additions to the corpus.

## See Also

- ~/.teleclaude/docs/general/principle/intelligence-boundaries.md — why the log-check conclusion is not machine-graded.
- ~/.teleclaude/docs/general/principle/verification-independence.md — why a self-authored check carries no information, and what counts as a standard from outside the session.
- ~/.teleclaude/docs/sdlc/policy/testing.md — the opt-in default this policy declares against.
- docs/local/adr/0100-commit-maintenance-drains-after-hook-return.md — why post-commit maintenance may complete after the agent's log read.
