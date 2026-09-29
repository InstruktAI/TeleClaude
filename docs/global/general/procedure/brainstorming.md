---
activation_trigger: Use when the human is exploring an idea that has no converged design yet
  and implementation is on the horizon.
description: Refine an idea into a converged design before implementation — ground first, ask the human only what they own, decide the technical path with its reasoning, and keep the forming work in an indexed scratchpad workspace.
visibility: public
---

# Brainstorming — Procedure

## Required reads

- @~/.teleclaude/docs/general/procedure/scratchpad-workspace.md

## Goal

Turn a vague intent or problem statement into a converged design before any
implementation begins, so hidden assumptions surface while they are still cheap.
Implementation waits until every active participant agrees the design and the
human releases it for materialization (`general/principle/attunement`).

## Preconditions

- A problem statement or intent is available.
- The current project context is reachable: architecture, constraints, patterns.

## Steps

1. **Ground first.** Read the relevant sources and existing patterns, and scan
   prior art for how this class of problem is already solved, before asking
   anything (`general/principle/grounding`).
2. **Open the workspace.** Forming material goes into a scratchpad workspace
   with its index (`general/procedure/scratchpad-workspace`). Record the human's
   words under Stated by the human as they arrive.
3. **Read the phase.** While the human is still adding material, expand: add
   what is missing, ask what else. Do not converge early
   (`general/principle/attunement`).
4. **Ask only what the human owns.** Intent, the experience people should have,
   scope boundaries, priorities, values, and risk acceptance are theirs
   (`general/policy/human-contract`). Ask one focused question per turn. Take
   technical uncertainty to evidence and an independent peer, never to the
   human (`general/policy/leadership`).
5. **Decide the technical path.** Name one path with its reasoning at the
   human's register. Surface more than one only when valid paths diverge on an
   axis the human owns; then give each its trade-off and ask which axis to
   honor. A list of equivalent technical options is a menu, and a menu is a
   violation (`general/policy/leadership`).
6. **Present the design.** Shape it to the work: for software, the boundaries,
   data flow, failure modes, and how it will be verified. State what is about to
   happen and its consequence before a consequential move; the human's
   acknowledgement releases execution and approves no agent-owned choice
   (`general/policy/leadership`).
7. **Converge and record.** A design point is settled when every active
   participant agrees. Log it under Decisions with who agreed, and keep what
   remains open under Open.
8. **Hand off.** The procedure that owns the durable form authors the released
   design — documentation, a todo, an agent artifact. Record where it landed
   under Promoted.

Intent questions that sharpen the design:

- What outcome matters most, and for whom?
- What is explicitly out of scope?
- Which failure modes are unacceptable?
- What is the smallest valuable version?
- Which constraints are fixed, and which are negotiable?

## Outputs

- A converged design, released by the human for materialization.
- A scratchpad workspace whose index holds the human's stated words, the
  decisions with who agreed, the open questions, and where the design was
  promoted.

## Recovery

- **The human cannot follow the design.** Re-present it at their register,
  leading with outcome and consequence; do not fall back to offering options.
- **Requirements keep expanding.** Name what is in and what is out. Widening
  scope is the human's call (`general/policy/human-contract`); ask it as one
  question.
- **Participants disagree after grounding.** Name the tension without resolving
  it early, return to evidence, and bring in an independent peer when the
  judgment is agent-owned (`general/policy/leadership`).

Anti-patterns to reject:

| Anti-pattern                          | Risk introduced                         | Correct behavior                                  |
| ------------------------------------- | --------------------------------------- | ------------------------------------------------- |
| Jumping into code immediately         | Rework from hidden assumptions          | Converge on the design first                      |
| Asking many questions at once         | Overload and shallow answers            | One focused question per turn                     |
| Offering a menu of technical options  | Evaluation handed to the human          | Decide the path; state the reasoning              |
| Asking the human a technical question | Burden transfer; uninformed choice      | Resolve through evidence and an independent peer  |
| Treating acknowledgement as sign-off  | Agent-owned choices recorded as human's | Orientation releases execution, nothing more      |
| Forming work in a private scratch dir | Reasoning lost to every later session   | Indexed workspace under the project `scratchpad/` |
