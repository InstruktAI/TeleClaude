---
description: 'Parallelize independent work with clear briefs, model and reasoning choices suited to each task, and reconciliation.'
visibility: 'public'
---

# Parallel Work — Principle

## Principle

When tasks can be split without shared state or ordering constraints, run them in parallel to reduce latency and improve coverage. Parallel work must be coordinated with clear briefs, explicit outputs, and a reconciliation step.

## Rationale

Independent work streams reduce end-to-end time while allowing deeper coverage. Without coordination, parallelism creates duplication, conflicting outputs, and missed gaps.

Delegated tasks can need different settings from their parent's workload. Choosing models and reasoning effort for the task preserves the required quality while bounding latency and resource use.

## Implications

- Identify independent sub-tasks early (sources to gather, topics to cover, or artifacts to produce).
- Dispatch parallel work to sub-agents or sub-tasks with a precise brief, expected outputs, and success criteria.
- Prefer parallelization when work can be isolated; avoid it when tasks are tightly coupled.
- Reconcile results into a single, coherent outcome; resolve conflicts and call out gaps.
- Use available skills and capabilities to route tasks to the right worker or tool.
- Choose the model and reasoning effort for each delegated task from the options exposed by the active dispatch surface, within the brief's constraints. Match complexity, uncertainty, context needs, consequences of error, and the required quality, latency and cost.
- Prefer faster, lower-cost settings for bounded work whose correctness is straightforward to verify. Increase model capability or reasoning effort when uncertain diagnosis, interacting constraints or consequential judgments require it; a worker's role alone does not determine its settings.
- Apply the choice through supported, permitted dispatch arguments. Inherit settings deliberately when their known configuration fits the task. When the surface fixes or hides settings, treat that as a capability constraint and preserve the required quality bar.
- Offload self-contained sub-tasks to preserve the main thread’s context and reduce cognitive load.
- Prefer background dispatch when possible so the primary agent remains available while work completes.
- Summarize delegated work on return to avoid context bloat and keep decision trails clear.
- Parallel agents are limbs of a single body. The coordination between them is not overhead — it is how the body knows where its hands are.

## Tensions

- **Speed vs. consistency:** parallel results can diverge; reconciliation is mandatory.
- **Coverage vs. cost:** more parallel work can increase resource usage; timebox and scope it.
- **Autonomy vs. alignment:** workers need freedom to execute, but must adhere to the brief and output format.
- **Communication loss:** delegation can drop nuance or intent; mitigate with precise briefs and concise result summaries.
