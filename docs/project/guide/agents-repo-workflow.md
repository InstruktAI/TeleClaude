---
description:
  Recommended workflow for maintaining agent artifacts and generated outputs
  in a local agents repository.
id: guide/agents-repo-workflow
scope: project
type: guide
---

# Agents Repo Workflow — Guide

## Goal

## Required reads

- @docs/project/procedure/agents-distribution.md

Maintain agent artifacts and keep generated outputs in sync.

## Steps

1. Edit source artifacts only (`AGENTS.master.md`, `commands/`, `skills/`).
2. Run distribution to regenerate outputs.
3. Validate outputs by spot-checking generated files.

## Outputs

- Generated agent artifacts match source definitions.

## Recovery

- If generated outputs drift, rerun distribution from source artifacts.
