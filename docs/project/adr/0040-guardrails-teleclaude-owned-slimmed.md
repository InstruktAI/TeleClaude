---
adr_status: 'accepted'
date: '2026-06-12'
description: 'Guardrails are TeleClaude-owned and provided as part of the stack; they catch substantive code/structure issues only — the rules that watched other tools or duplicated native type/lint enforcement are removed, and there is no per-project quality-config surface. Supersedes the portable/pack framing of ADR 0039.'
number: '40'
supersedes: ['project/adr/0039-guardrails-locked-no-config']
visibility: 'public'
---

# Guardrails Are TeleClaude-Owned And Slimmed To Substantive Checks — ADR

## Context

ADR 0039 proposed a *portable* guardrails engine with universal/TeleClaude rule
packs so a side project could run a subset of the bar. That portability premise
was not adopted: guardrails are **TeleClaude-owned and shipped as part of the
stack**, run as the always-run lane of `telec code lint` — not a kit a side
project adopts piecemeal. This ADR records the decision actually taken and
supersedes 0039.

The lane had also accumulated rules that do not catch a problem in the code, but
instead **police other tools**: config-integrity checks watching the
ruff/pyright/mypy configs; a pipeline-integrity check; an import-outside-top-level
guard re-implementing ruff's PLC0415 allowlist and blocking inline
`# noqa: PLC0415`; an env-mutation scanner forbidding writes to controlled
`TELECLAUDE_*` vars; plus a test↔source companion/orphan machinery and dead caps
config. These are either erosion-watching or duplicate enforcement a native type
checker / linter already provides.

## Decision

1. **Guardrails are TeleClaude-owned, provided as part of the stack.** There is no
   portability or rule-pack abstraction, and **no `teleclaude.yml` quality-config
   surface** — the bar is not a per-project stance.
2. **Guardrails do not watch the watchers.** Remove the ruff/pyright/mypy
   config-integrity checks, the pipeline-integrity check, and the
   import-outside-top-level guard. Erosion of a tool's config or inline suppression
   of a tool's rule is owned by the **TeleClaude checkpoint** (which watches
   protected config files) and by **reviewers**. `ruff` owns PLC0415 outright — it
   flags function-level imports, allows `if TYPE_CHECKING:` imports natively, and
   allowlists the startup-boundary files via `per-file-ignores`.
3. **Enforce invariants at the strongest layer, not a custom guard.** Remove the
   `TELECLAUDE_*` env-mutation scanner: the runtime configuration is a frozen,
   read-once typed seam, which already makes env mutation inert; the rule is
   codified in `software-development/policy/code-quality-practices` (the process
   environment is not an in-process config/state channel) and enforced by review.
4. **Remove dead config.** Delete `teleclaude/quality/guardrail_caps.py`, the
   `[tool.guardrails]` template section, the hardcoded `*_MAX_*` caps, and
   `RUFF_REQUIRED_RULE_GROUPS`.
5. **The only project-facing flex is a future brownfield unit-test allowance** — a
   shrinking grandfather baseline so an adopted brownfield project can keep its
   existing unit tests and migrate out over time. It is **deferred** until a
   brownfield project is actually adopted; it is not built speculatively.

The guardrails that remain catch substantive issues: module size, loose-dict
typing, invalid `# noqa`, debug probes, hardcoded home paths, banned session env
vars, runtime-path bypass, and the kind-vocabulary rule.

## Consequences

- Config erosion (a weakened ruff/pyright/mypy config, an unwired pipeline, an
  inline rule suppression) is no longer caught by a guardrail; it is caught by the
  checkpoint's protected-config watching and by reviewers. A gap there is closed
  there, not by re-adding a watcher rule.
- The quality bar is non-negotiable for an adopting project: it meets the bar (or
  marks genuine exceptions inline) rather than turning lanes down. When brownfield
  adoption happens, it flexes only through the unit-test baseline and inline
  exemption markers.
- The lane is roughly half its former size and contains only checks a type checker
  or linter cannot express.

## Alternatives Considered

- **The portable engine with universal/TeleClaude rule packs (ADR 0039).**
  Rejected: guardrails are TeleClaude-owned and shipped as part of the stack; the
  pack/portability abstraction has no consumer.
- **A `teleclaude.yml guardrails:` config surface** (per-lane severity/caps).
  Rejected: it reframes a quality control as a project stance and permits
  permanent, invisible weakening — the opposite of a non-negotiable bar.
- **Keeping the config-integrity / pipeline-integrity / import-noqa guards.**
  Rejected: they watch the watchers and duplicate native tooling (ruff owns
  PLC0415, including the `TYPE_CHECKING` carve-out).
