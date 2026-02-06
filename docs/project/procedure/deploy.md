---
id: 'project/procedure/deploy'
type: 'procedure'
scope: 'project'
description: 'Deploy TeleClaude changes safely with verification.'
---

# Deploy — Procedure

## Goal

Deploy project changes to TeleClaude computers safely and verify health.

## Preconditions

- You are in the TeleClaude repository.
- Working tree is clean.
- Remote access to target computers is configured.

## Steps

1. Check for local changes:

   ```bash
   git status --porcelain
   ```

   If the working tree is dirty, stop and report. Do not auto-commit.

2. Pull updates safely:

   ```bash
   git fetch origin
   git pull --ff-only origin main
   ```

3. Push commits if needed:

   ```bash
   git push origin main
   ```

4. Deploy via MCP:

   ```
   teleclaude__deploy()
   ```

   If no computers are specified, deploys to all.

5. Verify each target reports healthy:

   ```bash
   make status
   ```

6. If MCP deploy is unavailable, fall back to SSH per computer:

   ```bash
   ssh -A {user}@{host} 'cd <teleclaude-path> && git pull --ff-only origin main && make restart && make status'
   ```

(See `config.yml` for computer list, their host names and teleclaude paths.)

## Outputs

- Deployment status per target computer.

## Recovery

- If any step fails, stop and report the error.
- Do not continue with partial deployment.
