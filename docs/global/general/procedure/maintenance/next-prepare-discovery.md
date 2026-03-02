---
id: 'general/procedure/maintenance/next-prepare-discovery'
type: 'procedure'
scope: 'global'
description: 'Collaborative discovery phase for next-prepare. Two agents research in parallel and converge to produce preparation artifacts when input is thin.'
---

# Next Prepare Discovery — Procedure

## Goal

Produce preparation artifacts through collaborative research and convergence
when input is too thin for a single draft agent to work from.

Two agents with complementary cognitive profiles research the problem space
in parallel — one on the codebase/architecture, the other on domain/intent —
then converge through direct conversation to produce the same artifacts that
draft produces: `requirements.md`, `implementation-plan.md`, `demo.md`,
`dor-report.md`.

Discovery is an alternative to draft, not a precursor. The router chooses one
path or the other. Both produce the same output contract.

## Preconditions

1. The prepare router has assessed the slug and determined input is insufficient
   for a solo draft agent.
2. The router knows its own agent type and has read the Agent Characteristics
   concept to select the complementary partner.
3. `todos/roadmap.yaml`, `todos/icebox.md`, and `todos/delivered.yaml` are readable.
4. Slug is active (not icebox, not delivered).

## Steps

### Setup

1. The router is one of the two discovery agents. It spawns the complementary
   agent as a worker session:
   ```
   telec sessions start --project <project_path> --agent <complementary_agent> --mode slow --message "<discovery brief>"
   ```
   The discovery brief includes: slug, the existing input (however thin), the roadmap
   description, and the research assignment (see step 2).

2. Research assignments split along natural seams:
   - **Codebase agent** (whichever agent is stronger at architecture): existing
     patterns, related code, architectural constraints, how similar problems are
     solved in the codebase, integration points.
   - **Domain agent** (whichever agent is stronger at thoroughness/analysis):
     intent from `input.md` and roadmap description, related active todos,
     delivered todos (precedent and lessons), doc snippets relevant to the
     problem space, edge cases and failure modes.

3. Both agents research in parallel. The router does its own research while the
   partner works.

### Convergence

4. When the router's research is complete, open a direct conversation with the
   partner: `telec sessions send <partner_session_id> --direct`.

5. Converge through multiple breath cycles:
   - **Inhale**: share findings. Each agent presents what it discovered — codebase
     patterns, domain constraints, related precedents, open questions.
   - **Hold**: identify tensions. Where do findings conflict? Where are gaps?
     What can be confidently inferred vs. what genuinely needs human input?
   - **Exhale**: synthesize. Agree on requirements, approach, scope. Produce
     artifact drafts.

6. Use the DOR gates as convergence criteria — not "do we feel done" but "can
   we satisfy all eight gates with what we have?" The gates are:
   intent/success, scope/size, verification, approach known, research complete,
   dependencies, integration safety, tooling impact.

7. Iterate as many breath cycles as needed. The conversation self-regulates:
   when findings align and gates are satisfiable, convergence is fast. When gaps
   are deep, more cycles are needed.

### Output

8. When converged, the router produces the artifacts:
   - `requirements.md` — grounded in codebase findings and domain research.
   - `implementation-plan.md` — aligned with existing patterns discovered.
   - `demo.md` — demonstration plan.
   - `dor-report.md` — draft assessment with explicit assumptions.
   - `state.yaml` — updated `dor` section with draft metadata.

9. Inferences must be marked as inferred in the artifacts. The human can
   correct them without having to author from scratch.

### Escalation

10. If both agents agree that a design choice has no codebase precedent to
    anchor to AND genuinely goes either way — escalate with the specific
    question and the specific alternatives. Write blockers to `dor-report.md`.

11. Escalation is for decisions that change architecture. Everything that can
    be grounded in evidence, the agents resolve themselves.

### Cleanup

12. End the partner session: `telec sessions end <partner_session_id>`.
13. The router continues with the normal prepare flow (dispatch gate).

## Outputs

1. Same artifact set as draft: `requirements.md`, `implementation-plan.md`,
   `demo.md`, `dor-report.md`, `state.yaml` updates.
2. Artifacts grounded in codebase evidence and domain research.
3. Partner session ended after convergence.

## Recovery

1. If the partner session fails to start, fall back to draft (solo).
2. If convergence stalls (heartbeat fires with no progress after two iterations),
   the router produces artifacts from its own research alone and notes the
   incomplete convergence in `dor-report.md`.
3. If the partner's research contradicts the router's findings, investigate the
   contradiction before resolving — contradictions often reveal the real complexity.
