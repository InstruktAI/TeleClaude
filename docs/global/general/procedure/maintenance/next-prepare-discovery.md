---
id: 'general/procedure/maintenance/next-prepare-discovery'
type: 'procedure'
scope: 'global'
description: 'Triangulation phase for next-prepare. Two agents research in parallel and converge to derive requirements from input, codebase, and documentation.'
---

# Next Prepare Triangulation — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/policy/definition-of-ready.md
- @~/.teleclaude/docs/software-development/policy/definition-of-done.md

## Goal

Derive `requirements.md` through triangulation: two agents with complementary cognitive
profiles research the problem space in parallel — one grounding in the codebase and
architecture, the other in domain intent and documentation — then converge to produce
requirements that are grounded in all three sources of truth.

Triangulation is the default and only path for deriving requirements from input.md.
Two agents consistently produce better coverage than one. There is no single-agent
alternative for this phase.

The output is `requirements.md` only. Implementation planning is a separate phase
that takes approved requirements as input.

## Preconditions

1. `todos/{slug}/input.md` exists with human thinking to derive from.
2. The router knows its own agent type and has read the Agent Characteristics
   concept to select the complementary partner.
3. `todos/roadmap.yaml` is readable.
4. Slug is active (not icebox, not delivered).

## Steps

### 1. Setup

The router is one of the two triangulation agents. It spawns the complementary
agent as a worker session:

```
telec sessions start --project <project_path> --agent <complementary_agent> --mode slow --message "<triangulation brief>"
```

The brief includes: slug, the full content of `input.md`, the roadmap description,
and the research assignment (see step 2).

### 2. Parallel research

Research assignments split along natural seams:

- **Codebase agent** (whichever agent is stronger at architecture): existing
  patterns, related code, architectural constraints, how similar problems are
  solved in the codebase, integration points, file paths that will be affected.
- **Domain agent** (whichever agent is stronger at thoroughness/analysis):
  intent from `input.md` and roadmap description, related active and delivered
  todos (precedent and lessons), doc snippets relevant to the problem space
  (use `telec docs index` to discover), edge cases and failure modes.

Both agents research in parallel. The router does its own research while the
partner works.

### 3. Triangulation convergence

When the router's research is complete, open a direct conversation with the
partner: `telec sessions send <partner_session_id> --direct`.

Converge through multiple breath cycles:

- **Inhale**: share findings. Each agent presents what it discovered — codebase
  patterns, domain constraints, related precedents, open questions.
- **Hold**: identify tensions. Where do findings conflict? Where are gaps?
  What can be confidently inferred vs. what genuinely needs human input?
- **Exhale**: synthesize. Agree on requirements and scope.

Use DOR gates 1–3 as convergence criteria — not "do we feel done" but "can
we satisfy intent/success, scope/size, and verification with what we have?"

Iterate as many breath cycles as needed. The conversation self-regulates:
when findings align and gates are satisfiable, convergence is fast. When gaps
are deep, more cycles are needed.

### 4. Requirements quality standard

The converged `requirements.md` must satisfy:

- **Completeness**: every intent expressed in `input.md` is captured as a
  concrete requirement or explicitly deferred with justification.
- **Testability**: each requirement has a verification path (test, observable
  behavior, or measurable outcome). "Works correctly" is not testable.
- **Grounding**: requirements reference codebase patterns, existing APIs, or
  documented conventions — not invented abstractions. If the codebase has an
  established way to do X, the requirement says "using the existing X pattern."
- **Review-awareness**: requirements anticipate what the reviewer will check.
  If a requirement implies CLI changes, it explicitly states help text and
  config surface updates. If it implies new behavior, it explicitly states
  test expectations. The Definition of Done gates are the checklist.
- **No implementation leakage**: requirements state what and why, never how.
  Implementation approach belongs in the plan.
- **Inferences marked**: anything inferred from codebase or docs rather than
  explicitly stated in `input.md` is marked `[inferred]`. The human can
  correct inferences without searching for them.

### 5. Write requirements

When converged, the router produces `requirements.md`:

- Grounded in the triangulated findings from both agents.
- Structured per the quality standard above.
- Inferences marked explicitly.

Update `todos/{slug}/state.yaml`:

```yaml
grounding:
  valid: true
  base_sha: "<current HEAD>"
  input_digest: "<hash of input.md>"
  last_grounded_at: "<now ISO8601>"
  invalidation_reason: null
```

### 6. Escalation

If both agents agree that a design choice has no codebase precedent to anchor
to AND genuinely goes either way — escalate with the specific question and the
specific alternatives. Write blockers to `dor-report.md`.

Escalation is for decisions that change architecture. Everything that can be
grounded in evidence, the agents resolve themselves.

### 7. Cleanup

End the partner session: `telec sessions end <partner_session_id>`.
The router continues with the normal prepare flow (the state machine advances
to requirements review).

## Outputs

1. `todos/{slug}/requirements.md` — triangulated, grounded, review-aware.
2. `todos/{slug}/state.yaml` — grounding metadata updated.
3. Partner session ended after convergence.

## Recovery

1. If the partner session fails to start, the router produces requirements
   from its own research alone and notes the incomplete triangulation in
   `dor-report.md`. Solo derivation is the fallback, not an alternative path.
2. If convergence stalls (heartbeat fires with no progress after two iterations),
   the router produces requirements from its own research alone and notes the
   incomplete convergence in `dor-report.md`.
3. If the partner's research contradicts the router's findings, investigate the
   contradiction before resolving — contradictions often reveal the real complexity.
