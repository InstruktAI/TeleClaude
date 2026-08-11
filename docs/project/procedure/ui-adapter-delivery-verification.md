---
description: Drive real UI-adapter delivery behavior and verify daemon-side decisions from structured evidence while reserving platform rendering confirmation for the human.
activation_trigger: Use after changing UI-adapter output, reflection, streaming-edit, or author-presentation behavior.
---

# UI Adapter Delivery Verification — Procedure

## Goal

Prove that TeleClaude produced the intended UI-adapter delivery against the
running daemon, without treating logs as proof of how an external platform
rendered the result.

## Preconditions

- The changed daemon code is installed and running through the checkpoint-bound
  `restart` obligation.
- The delivery path emits policy-compliant, body-free structured evidence for
  the decisions the change claims to make.
- The changed scenario and its expected daemon-side outcome are named before
  the live drive begins.

## Steps

1. **Drive the changed path through the real system.** Create or reuse the
   smallest real session, peer link, or adapter input that exercises the named
   behavior. Do not substitute a helper that bypasses acceptance, projection,
   routing, or adapter delivery.
2. **Inspect structured delivery evidence.** Read the relevant log window and
   confirm the complete identifiers, target lane, source binding or generation,
   author/role/relationship resolution, create-or-edit operation, result, and
   platform message identifier expected for the scenario. When the change
   affects replay or ordering, also inspect the durable cursors, bindings, and
   receipts that prove it.
3. **Keep evidence body-free.** Never log or copy conversation bodies, tokens,
   or personal payloads to prove delivery. If the required decision is not
   observable through structured metadata, add the missing policy-compliant log
   event as part of the functionality change; do not add an ad-hoc probe.
4. **State the evidence boundary honestly.** Agent verification may conclude
   that TeleClaude selected and dispatched the intended operation. Visual
   appearance, platform grouping, avatar rendering, and other external-platform
   presentation remain pending until the human confirms them in the actual UI.
5. **Record the split verdict.** Report daemon-side delivery as verified or
   failed from the evidence. Record human visual confirmation separately; its
   absence never turns agent-side dispatch evidence into a claim about rendering.

## Outputs

- A real-system scenario whose daemon-side delivery decisions are supported by
  structured logs and, where relevant, durable cursors, bindings, and receipts.
- A separate human confirmation of external-platform rendering when the claimed
  outcome includes visual presentation.

## Recovery

- If no structured evidence exists for a claimed decision, the delivery is not
  agent-verifiable; add the missing boundary log at the policy-defined level and
  drive the scenario again.
- If daemon evidence is correct but the platform renders incorrectly, treat the
  rendering mismatch as a delivery defect rather than weakening the evidence
  standard.
- If the live scenario cannot reach the changed path, report the concrete
  availability or routing blocker. Do not replace the real-system drive with a
  self-authored simulation.
