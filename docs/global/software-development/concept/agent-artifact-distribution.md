---
id: software-development/concept/agent-artifact-distribution
type: concept
scope: domain
description: How agent artifacts are built and distributed to tool-specific formats.
---

# Agent Artifact Distribution — Concept

## Purpose

Describe how agent artifacts flow from source files into runtime-specific outputs.

## Inputs/Outputs

- **Inputs**: `agents/` source files.
- **Outputs**: generated artifacts for supported CLIs.

## Invariants

- Source-of-truth lives in `agents/`.
- Generated artifacts are derived, not edited manually.

## Primary flows

1. Author or update source artifacts.
2. Run the distribution tooling.
3. Consume generated artifacts in the target CLI.

## Failure modes

- Generated artifacts drift from sources.
- Missing artifacts when distribution is not run.
