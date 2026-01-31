---
id: general/concept/normalized-agent-artifacts
type: concept
scope: global
description: Normalized agent artifact primitives and how they map to supported CLIs.
---

# Normalized Agent Artifacts — Concept

## What

Normalized agent artifacts are the shared, source‑of‑truth files we author to describe
agent behavior, their artifacts such as sub‑agents, commands, skills, and related configuration
in one consistent format.
They live in two scopes—global and project—so organization‑wide guidance and project‑specific
behavior can coexist without overwriting each other. These sources are intentionally
human‑authored and stable; the agent‑specific outputs are derived from them and treated
as build artifacts rather than hand‑edited files.

## Why

We normalize because we need a repeatable, maintainable way to keep multiple agent
runtimes aligned without copying the same intent into multiple formats. The problem is
that each runtime expects different file shapes and supports different features, which
creates drift and inconsistency when we author them separately. A normalized source
solves that by keeping the intent in one place and letting us emit only what each runtime
can actually use. That reduces duplication, prevents accidental divergence, and makes
changes safer: you update the source once and reliably regenerate every output.
