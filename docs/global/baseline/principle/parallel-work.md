---
description: Prefer parallelizing independent work with clear briefs and reconciliation to reduce latency without sacrificing accuracy.
id: general/principle/parallel-work
scope: domain
type: principle
---

# Parallel Work — Principle

## Principle

When tasks can be split without shared state or ordering constraints, run them in parallel to reduce latency and improve coverage. Parallel work must be coordinated with clear briefs, explicit outputs, and a reconciliation step.

## Rationale

Independent work streams reduce end-to-end time while allowing deeper coverage. Without coordination, parallelism creates duplication, conflicting outputs, and missed gaps.

## Implications

- Identify independent sub-tasks early (sources to gather, topics to cover, or artifacts to produce).
- Dispatch parallel work to sub-agents or sub-tasks with a precise brief, expected outputs, and success criteria.
- Prefer parallelization when work can be isolated; avoid it when tasks are tightly coupled.
- Reconcile results into a single, coherent outcome; resolve conflicts and call out gaps.
- Use available skills and capabilities to route tasks to the right worker or tool.
- Offload self-contained sub-tasks to preserve the main thread’s context and reduce cognitive load.
- Prefer background dispatch when possible so the primary agent remains available while work completes.
- Summarize delegated work on return to avoid context bloat and keep decision trails clear.

## Tensions

- **Speed vs. consistency:** parallel results can diverge; reconciliation is mandatory.
- **Coverage vs. cost:** more parallel work can increase resource usage; timebox and scope it.
- **Autonomy vs. alignment:** workers need freedom to execute, but must adhere to the brief and output format.
- **Communication loss:** delegation can drop nuance or intent; mitigate with precise briefs and concise result summaries.
