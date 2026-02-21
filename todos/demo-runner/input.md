# Input: demo-runner

## Problem

Demos are currently generated post-finalize as AI-composed narrative widgets — not real demonstrations of working software. This contradicts the scrum sprint review ceremony the lifecycle is modeled after. A demo means showing the stakeholder what was built, with working software.

## What we want

### 1. Demo as a build deliverable

The demo is created during the build phase, not after finalize. The builder writes a runnable demo as part of their implementation. The reviewer verifies it works. It ships as a tested artifact alongside the code.

`snapshot.json` gains a `demo` field that specifies exactly how to run the demonstration — a CLI command, a TUI interaction sequence, or whatever makes sense for that delivery.

### 2. Demo runner CLI: `telec todo demo [slug]`

A CLI subcommand that:

- No slug: lists available demos, lets the user pick
- With slug: finds `demos/*-{slug}/snapshot.json`, reads the `demo` field, executes it
- Semver gate: skips demos from incompatible major versions

### 3. Conversational AI interface

When a user says "run next demo" or invokes `/next-demo`:

- The AI finds delivered demos
- Asks "which one?" or presents a list to choose from
- Runs `telec todo demo <slug>` — which just works because it was already tested
- The AI is a friendly frontend to the runner, not a creator

### 4. Build gate: demo verified

The quality checklist / implementation plan includes a checkbox: "demo is runnable and verified." The reviewer must run it and confirm it works before approving.

### 5. Remove demo.sh

`demo.sh` is replaced by the `demo` field in `snapshot.json` + the `telec todo demo` runner. No more standalone bash scripts.

### 6. Redefine `/next-demo` skill

The skill stops creating narrative widgets. Instead it becomes:

- During build: guidance for the builder on what constitutes a good demo
- At presentation time: the conversational interface that finds and runs demos

## What changes

- Demo artifact spec (`docs/project/spec/demo-artifact.md`)
- `snapshot.json` schema (add `demo` field)
- CLI surface (`telec todo demo`)
- Build quality gates (demo checkpoint)
- `/next-demo` skill (from creator to runner)
- `POST_COMPLETION["next-finalize"]` (remove demo dispatch step — demo is already done during build)
- Lifecycle procedure docs
