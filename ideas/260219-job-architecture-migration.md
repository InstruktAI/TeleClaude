# Idea: Migrate All Jobs to Agent-Supervisor Architecture

## Problem

The target job architecture is well-defined (Memory ID 21) but incompletely applied:

- **Target**: All jobs should be agent-type jobs that act as supervisors of functional scripts
- **Current state**: Some jobs follow this pattern; others are direct Python modules or partial implementations
- **Gap**: Architecture decision exists but no migration plan or enforcement

## Observation

Memory ID 21 is classification "decision" with clear rationale:

- "Agents are supervisors that run existing functional scripts, not reimplementations"
- "Agent owns the outcome: run script, handle errors, fix forward, report results"
- "Python job modules become the workers that agents call"

This is a settled architectural decision, not a proposal. But implementation is incomplete.

## Opportunity

Create a systematic migration plan to unify all job implementations:

1. **Audit current jobs**:
   - Identify jobs that are direct Python implementations (not agent-supervised)
   - Identify jobs without proper run reporting
   - Map worker scripts vs agent entry points

2. **Standardize job structure**:
   - All jobs spawn agent sessions with spec-based instructions
   - Worker scripts are called by agents via bash/subprocess
   - Agent handles error recovery, fix-forward, and reporting
   - Agent jobs follow agent-job-hygiene procedure

3. **Enforce via job template**:
   - Create template job that demonstrates correct pattern
   - Ensure job distribution process validates structure
   - Add lint check to catch non-agent jobs

4. **Migrate existing jobs**:
   - Prioritize high-impact jobs (memory-review, log scanning, etc.)
   - Convert direct Python to agent + worker structure
   - Verify reporting and fix-forward behavior

## Estimated Value

High. Improves job reliability, error handling, and debugging through consistent architecture.

## Risks

- Requires rewriting existing job implementations
- Agent spawn overhead (if jobs are lightweight)
- Testing and validation effort

## Dependencies

- Agent job hygiene procedure (already exists)
- Job spec schema (already exists)
- agent-artifact-distribution process

## Next Steps

1. Audit teleclaude/cron/jobs/ for architecture compliance
2. Identify conversion priority (highest-impact first)
3. Create reference implementation (conversion of one job as template)
4. Build migration checklist and assign work
