# Daemon Restart Protocol — Idea

**ID:** 260219-daemon-restart-protocol
**Status:** Idea
**Severity:** High
**Source:** memory-review

## Problem

Memory 25 documents recurring frustration: agents forget to `make restart` after modifying daemon code, then validate against stale daemon state. This undermines trust in validation results and creates hidden failures.

## Root Cause

- No mandatory checklist for daemon restart
- No clear definition of which files trigger restart requirement
- Validation scripts don't enforce restart prerequisite

## Proposal

Create `project/procedure/daemon-restart-protocol.md` with:

1. **Restart trigger list** — files that require daemon restart:
   - `teleclaude/daemon/**/*.py` — core daemon code
   - `teleclaude/api/**/*.py` — API endpoints
   - `teleclaude/services/**/*.py` — background services
   - `teleclaude.yml` — configuration changes
   - Hook scripts in `.teleclaude/hooks/`

2. **Mandatory checklist** — enforce before validation:

   ```
   [ ] Code changes complete
   [ ] make restart executed
   [ ] make status returns "Running"
   [ ] New code path tested manually
   [ ] Validation scripts run
   ```

3. **Integration points**:
   - Document in agent AGENTS.md
   - Add pre-validation step to CI/CD
   - Include in next-build procedure

## Success Criteria

- Agents consistently restart daemon after relevant changes
- Validation failures no longer happen due to stale daemon state
- New team members understand when restart is required

## Owner

Recommended for project infrastructure/procedures.
