---
id: software-development/guide/agent-artifacts-quickstart
type: guide
scope: domain
description: Quickstart for authoring and distributing agent artifacts.
---

# Agent Artifacts Quickstart — Guide

## Goal

Get an agent artifact authored and distributed to tool-specific outputs.

## Context

Agent artifacts (commands, skills, agents) are authored in a normalized format and compiled into runtime-specific outputs for Claude Code, Codex CLI, and Gemini CLI. The distribution tooling handles the transformation.

## Approach

1. Choose the scope (global or project) for the artifact.
2. Author or update the artifact in the chosen scope following the schema.
3. Validate snippet structure and required reads.
4. Run `./scripts/distribute.py` to generate outputs and `./scripts/distribute.py --deploy` to deploy them.

## Pitfalls

- Editing generated output files directly — they get overwritten on next distribution run.
- Forgetting to run distribution after changing source artifacts — runtimes will use stale outputs.
