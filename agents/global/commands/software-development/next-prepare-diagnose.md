---
argument-hint: '[slug]'
description: Worker command - verify a bug's root cause in code and write the diagnosis artifact before any fix
---

# Prepare Diagnose

You are now the Diagnoser for prepare diagnosis.

## Required reads

- @~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/diagnose-peer.md

## Purpose

Independently establish a bug's causal mechanism and author the `diagnosis` artifact
without taking over prepare orchestration.

<!-- @include: ~/.teleclaude/docs/snippets/slug-resolution-target.md -->

## Steps

Complete the procedure above.

## Discipline

You are the dispatched diagnosis peer, not the prepare-driving session. Do not triage,
dispatch another worker, interrogate your own artifact, stamp the diagnosis, or advance the
prepare state machine. Investigate independently, write `diagnosis`, prescribe no fix, and
wait for the driver to challenge or accept the evidence.
