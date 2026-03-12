# workflow-engine-refactor — Input

# Workflow Engine Refactor — Brain Dump

## Summary

Replace the bespoke prepare and work state machines with a single configurable workflow engine. Same functionality, new architecture. Pure refactoring — no new behavior.

## Context from design session (2026-03-12)

Maurice and I converged on this design through extended discussion. The key insight: every production step in the SDLC has the same shape — produce artifact, review, iterate, approve. Currently this pattern is implemented 4+ times as hand-coded state machine handlers in core.py (3500+ lines). The refactor extracts the repeating pattern into a configurable engine.

## Architecture

### One engine, configured by YAML

- Single workflow engine reads YAML definitions and walks through steps
- Each workflow is a sequence of steps
- Each step has a producer (and optionally a reviewer) with required reads, artifact globs, inputs from prior steps, and an optional named validator
- The engine reads state.yaml, determines the current step, emits a fully specified dispatch instruction
- The orchestrator stays a dumb relay — runs engine, gets instruction, dispatches it
- Workers get fully specified instructions and execute verbatim

### File structure

```
workflows/
  prepare.yaml          # Requirements -> Test specs -> Plan -> Gate
  work.yaml             # Build -> Review -> Fix -> Finalize
  creative.yaml         # Future
languages/
  python/
    baseline.md         # Required reads for Python steps that produce code
  typescript/
    baseline.md         # Required reads for TypeScript steps that produce code
```

### Workflow YAML schema (converged design)

Each workflow file defines a sequence of steps. Steps are grouped by cycle (producer + optional reviewer):

```yaml
name: prepare
description: Transform ideas into implementation-ready artifacts

steps:
  - name: requirements
    producer:
      required_reads:
        - software-development/procedure/maintenance/next-prepare-discovery
        - software-development/policy/preparation-artifact-quality
      artifacts:
        - "todos/{slug}/requirements.md"
      thinking_mode: slow
    reviewer:
      required_reads:
        - software-development/procedure/lifecycle/review-requirements
        - software-development/policy/preparation-artifact-quality
      artifacts:
        - "todos/{slug}/requirements-review-findings.md"
      thinking_mode: slow
    max_rounds: 3
    human_gate: true
    state_key: requirements_review
    events:
      produced: prepare.requirements_drafted
      approved: prepare.requirements_approved

  - name: test-specs
    needs_worktree: true
    produces_code: true
    producer:
      required_reads:
        - software-development/policy/testing
        - software-development/policy/test-structure
      artifacts:
        - "{test.spec_pattern}"
      inputs:
        - step: requirements
          artifacts:
            - "todos/{slug}/requirements.md"
      thinking_mode: slow
      validator: spec_check
    reviewer:
      required_reads:
        - software-development/policy/testing
        - software-development/policy/test-structure
      artifacts:
        - "todos/{slug}/spec-review-findings.md"
      thinking_mode: slow
    max_rounds: 3
    state_key: spec_review
    events:
      produced: prepare.specs_drafted
      approved: prepare.specs_approved

  - name: plan
    producer:
      required_reads:
        - software-development/procedure/maintenance/next-prepare-draft
        - software-development/policy/preparation-artifact-quality
      artifacts:
        - "todos/{slug}/implementation-plan.md"
        - "todos/{slug}/demo.md"
      inputs:
        - step: requirements
          artifacts:
            - "todos/{slug}/requirements.md"
        - step: test-specs
          artifacts:
            - "{test.spec_pattern}"
      thinking_mode: slow
    reviewer:
      required_reads:
        - software-development/procedure/lifecycle/review-plan
        - software-development/policy/preparation-artifact-quality
      artifacts:
        - "todos/{slug}/plan-review-findings.md"
      thinking_mode: slow
    max_rounds: 3
    state_key: plan_review
    events:
      produced: prepare.plan_drafted
      approved: prepare.plan_approved

  - name: gate
    producer:
      required_reads:
        - software-development/policy/definition-of-ready
      artifacts:
        - "todos/{slug}/dor-report.md"
      thinking_mode: slow
    state_key: dor_gate
    events:
      produced: prepare.completed
```

### Step schema details

Each step has:
- producer.required_reads: doc snippet IDs loaded as context for the worker
- producer.artifacts: glob patterns — engine checks existence as default validation
- producer.inputs: artifacts from prior steps passed to the worker
- producer.thinking_mode: slow/med/fast for dispatch
- producer.validator: optional named validator for mechanical checks beyond file existence
- reviewer: optional — same structure as producer. If present, engine runs produce-review-fix loop
- max_rounds: cap on review iterations before blocking
- human_gate: if true, engine pauses for human confirmation after approval
- needs_worktree: if true, engine ensures worktree exists before dispatching
- produces_code: if true, engine loads language-specific required reads from language baseline
- state_key: field in state.yaml the engine reads/writes for this step
- events: lifecycle events emitted at transitions

### Language support

Language-agnostic engine. Language-specific details come from baseline files:

- languages/python/baseline.md — required reads for Python test/lint/type tooling
- languages/typescript/baseline.md — required reads for TypeScript test/lint/type tooling

When a step has produces_code: true, the engine detects the project language (from teleclaude.yml config, bootstrapped by telec init) and loads the appropriate language baseline required reads in addition to the step own required reads.

Detection stored in project config:
```yaml
# teleclaude.yml (project)
language: python
# or for multi-language:
languages:
  - python
  - typescript
```

For Python: pytest, xfail markers, pytest.mark.xfail(strict=True)
For TypeScript: vitest, test.fails(), *.spec.ts patterns

The language baseline provides:
- Test framework conventions
- RED marker syntax (xfail equivalent)
- Spec file patterns
- Test/lint/typecheck commands

### Named validators

Registry of validation functions. Steps reference by name. Engine calls after producer completes.

Default validation (no validator field): artifacts matching glob exist.

Named validators for steps that need more:
- spec_check: valid syntax, contains RED markers, tests actually fail
- build_gates: make test passes, make lint passes, all plan tasks checked
- demo_validate: existing telec todo demo validate
- plan_completeness_check: tasks exist, file paths valid, traces to requirements
- artifact_sections_check: file has required sections, non-empty
- finalize_ready_check: branch pushed, merge clean

### One command surface

Current state: ~12 separate command files (next-prepare, next-prepare-discovery, next-review-requirements, next-prepare-draft, next-review-plan, next-prepare-gate, next-work, next-build, next-review-build, next-fix-review, next-finalize, plus new TDD commands).

Target: one command with positional arguments.

```
/next-workflow prepare                     -> orchestrator mode
/next-workflow prepare discovery           -> worker: produce requirements
/next-workflow prepare requirements-review -> worker: review requirements
/next-workflow prepare spec-build          -> worker: write xfail test suite
/next-workflow prepare spec-review         -> worker: review test specs
/next-workflow prepare plan-draft          -> worker: write implementation plan
/next-workflow prepare plan-review         -> worker: review plan
/next-workflow prepare gate                -> worker: DOR validation

/next-workflow work                        -> orchestrator mode
/next-workflow work build                  -> worker: make tests GREEN
/next-workflow work review                 -> worker: code review
/next-workflow work fix                    -> worker: fix findings
/next-workflow work finalize               -> worker: finalize and push
```

The engine resolves the positional arguments to the step config, loads the required reads, and formats the dispatch instruction with everything the worker needs.

### Engine mechanics (same as current, reorganized)

- Engine reads state.yaml to determine current step
- Emits dispatch instruction with: command, required reads, inputs, artifacts expected, thinking mode, notes
- Orchestrator dispatches verbatim via telec sessions run
- Worker executes, updates state.yaml, reports done
- Engine reads state.yaml again, routes to next action (review, fix loop, next step, or done)
- Fix mode: reviewer rejects -> engine re-dispatches producer with findings (same as current FIX MODE prefix)
- Review round cap: exceeded -> engine marks blocked (same as current)
- Grounding/staleness: same mechanics as current, step-level concern
- Human gates: engine emits event and stops, human triggers resume (same as current)
- Cross-workflow: orchestrator proposes next phase at completion (same as current, can use detached mode)

### Migration

- The refactor absorbs ALL existing bespoke machines — prepare, work, and any new ones added before the refactor (like the TDD test-spec phase)
- Old command names can be aliased to workflow+step combinations during transition
- core.py bespoke handler functions get replaced by engine + YAML config
- State.yaml schema stays compatible — the state_key mapping ensures the engine reads/writes the same fields

### What this refactor does NOT do

- Does not add TDD/test-spec behavior (that is a separate todo)
- Does not change what the workers do (same required reads, same artifacts, same procedures)
- Does not change the orchestrator role (still dumb relay)
- Does not change state.yaml semantics (same fields, same values)
- Pure architectural reorganization: hand-coded machines -> configured engine
