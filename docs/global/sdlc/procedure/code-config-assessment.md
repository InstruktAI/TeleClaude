---
description: Bring a project's toolchain, quality configuration, and TeleClaude declarations into a working, self-contained contract.
visibility: 'public'
role: helper
dispatch:
  agent: [claude, codex, gemini, deepseek]
  thinking_mode: slow
---

# Code Config Assessment — Procedure

## Required reads

@~/.teleclaude/docs/sdlc/design/project-toolchain.md
@~/.teleclaude/docs/sdlc/policy/language-policy-ownership.md
@~/.teleclaude/docs/general/policy/human-contract.md
@~/.teleclaude/docs/general/policy/agent-artifact-governance.md
@~/.teleclaude/docs/general/policy/commits.md

## Goal

Make the project stand on its own toolchain while TeleClaude's declarations and
installed plumbing tell the truth about it. Reassessment converges the project
again without undoing a defensible project choice.

## Preconditions

- Work from the project root and establish the current project state before
  changing it.
- Read the applicable language policies, the project's existing toolchain, and
  the blessed quality templates in the registered TeleClaude project. The
  templates offer defaults; the Makefile interface is the platform mandate.
- Read the TeleClaude project contracts before authoring those surfaces:
  projects/teleclaude/spec/feature/config/project-capability-manifest,
  projects/teleclaude/procedure/checkpoint-overlay-projection,
  projects/teleclaude/design/architecture/checkpoint-system, and
  projects/teleclaude/spec/feature/reconciliation/project-plumbing-convergence.

## Steps

<!-- planned:role-scoped-cli-context -->

When this procedure is your session’s launch assignment, retrieve its focused tool
help with `telec -h --expand-role` before starting the assigned work. When reading
it inline, retain your current session’s tool context. Use `telec <command> -h`
for individual commands.
<!-- /planned:role-scoped-cli-context -->

1. Bring the project's Makefile onto the install, lint, test, and format
   interface. The targets delegate to tools the project declares and provisions;
   lint and format honor the platform's workspace scope. A configured suite is
   run by test. Do not create an empty check or invent a suite to satisfy an
   interface.
2. Apply blessed quality defaults where the project is silent or weaker by
   omission. Preserve a deliberate, evidenced project choice. Resolve existing
   quality debt by fixing the code and configuration, not by disabling checks or
   adding suppressions to obtain a green result. A proposed relaxation of
   quality-defining configuration follows its independent review gate.
3. Leave no inert protection or configuration: each retained setting and check
   works, each displaced hook or file has its intended effect through the
   active toolchain, and secrets and generated output cannot be accidentally
   picked up by git.
4. Align the capability declaration and checkpoint bindings with the project's
   actual source, configured tests, and runtime obligations. Reconcile the
   installed plumbing and preserve project-owned behavior that the platform
   cannot express.
5. Prove the resulting contract from a clean project environment: make install
   succeeds; unscoped telec code lint, including guardrails, succeeds; and
   telec code test succeeds when a suite is configured and the effective
   checkpoint owes test. Establish that the expected project-declared tools
   actually ran from the project's environment. Reinstall when changed
   declarations require it; the dependency order determines when install runs.
6. Commit a complete, coherent assessment only after its applicable proof is
   green, then route the required independent review. If a human-owned
   consequence blocks completion, finish independent work and report the
   assessment as incomplete with the blocked consequence named.

## Outputs

- A self-contained project toolchain, live quality configuration, accurate
  TeleClaude declarations, and converged plumbing.
- A final report with the install, unscoped lint, and applicable test outputs;
  evidence of which project tools ran and where they resolved; material
  technical decisions; and any unresolved blocker. A passing exit status
  without evidence that the intended checks ran is not completion.

## Recovery

- If an expected tool cannot be provisioned or a check is inert, repair its
  declaration or invocation and repeat the applicable proof. Do not substitute
  an ambient tool or weaken the quality gate.
- If a genuine human-owned decision is required, leave dependent work
  incomplete and identify the decision and consequence without treating it as
  approval of a technical mechanism.

## Discipline

The failure mode is a green assessment that runs the wrong tools, omits checks,
or leaves displaced protection inert. Ground the assessment in the project's
effective behavior and prove that behavior before declaring it done.
