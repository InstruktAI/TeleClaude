---
description: 'High-level design for code intelligence as an SDLC input substrate: structural fact extraction, role-specific views, and strict automation-vs-judgment boundaries.'
visibility: 'public'
---

# Code Intelligence — Design

## Required reads

- @~/.teleclaude/docs/software-development/principle/externalized-structural-context.md
- @~/.teleclaude/docs/software-development/design/sdlc/overview.md

## Purpose

Define code intelligence as a reusable SDLC capability that externalizes
structural software context into durable, role-appropriate inputs.

The capability exists to replace grep-driven guessing and partial local file
reading with explicit structural truth that both humans and AI can consume.

Code intelligence is not the SDLC itself. It is a supporting substrate used by
prepare, work, review, and integration wherever structural truth improves
judgment.

## Inputs/Outputs

**Inputs**

- source code and worktree-local changes
- explicit declarative surfaces such as commands, routes, events, config keys,
  and database models
- documentation/snippet references where code links to governing docs
- git history and freshness signals

**Outputs**

- canonical structural facts
- derived structural metrics
- role-specific structured views
- explicit blind spots and confidence/freshness degradation signals

## Invariants

- Automation stops at facts, metrics, provenance, and projections. It does not
  perform architectural judgment, contradiction detection, prioritization, or
  narrative synthesis.
- Structural truth is worktree-aware. The active work surface is authoritative,
  not only canonical main.
- The same canonical store must support multiple consumer views without each
  consumer inventing its own extraction logic.
- Partial coverage must degrade honestly. Missing support or unresolved dynamic
  structure is surfaced as blind spots rather than hidden behind false
  confidence.
- The product contract is role-specific structured views, not prose briefings.

## Primary flows

### Structural extraction

Automation extracts canonical facts from the codebase:

- files, symbols, contracts, tests, documentation linkage
- structural relationships such as containment, imports, calls, and coverage
- freshness and provenance

This is the foundational fact layer. It is deterministic, mechanically derived,
and language-extensible.

### Derived metrics

Automation computes metrics from the structural layer:

- fan-in / fan-out
- change velocity and recent motion
- boundary status and documentation gaps
- confidence and blind-spot markers

These metrics support judgment but do not replace it.

### Role-specific projections

Consumers do not read the entire canonical structure directly by default.
Instead, automation produces structured views tuned for the consuming task.

Examples:

- planner-oriented change-surface views
- reviewer-oriented scope-verification views
- refactor-planner views for coupling, cohesion, and test gaps

### SDLC consumption

Lifecycle steps use code intelligence as a supporting input wherever structural
truth changes the quality of judgment:

This section is the high-level summary only. See the SDLC integration design
for the detailed consumption model.

- prepare can consume it when shaping scope, impact, and execution planning
- work can consume it during build and review
- integration can consume it when reasoning about overlap, sequencing, and
  system fit

The SDLC remains responsible for judgment and approval. Code intelligence
supplies the substrate that makes those judgments less guess-driven.

## Failure modes

- code intelligence is mistaken for architectural judgment instead of factual
  support
- consumers treat partial coverage as complete truth
- each lifecycle consumer re-implements extraction logic and diverges from the
  canonical store
- prose briefings replace structured views and hide provenance or blind spots
- mainline-only indexing ignores worktree-local reality and degrades planning

## See Also

- ~/.teleclaude/docs/software-development/spec/code-intelligence-schema.md —
  canonical fact model and result contract
- ~/.teleclaude/docs/software-development/design/code-intelligence-sdlc-integration.md —
  how the capability feeds SDLC stages
