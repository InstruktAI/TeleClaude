---
date: '2026-06-11'
description: 'The portable guardrails are a domain-blind engine running rule packs, locked at error with no per-project quality configuration; brownfield flex lives only in shrinking exemption ramps, and guardrails never watch the watchers.'
number: '39'
visibility: 'public'
---

# Guardrails Are Locked, Pack-Structured, And Do Not Watch The Watchers — ADR

## Context

TeleClaude's guardrails are its opinionated quality bar, run as the always-run
lane of `telec code lint`. To let a side project run that bar behind its own
`telec code lint`, the lane is restructured into a domain-blind engine plus two
rule packs (a universal pack shipped everywhere, a TeleClaude pack active only
for the mother repo).

Two design questions had to be settled, and both invite a tempting wrong answer:

1. **Should adoption be configurable?** The reflex is to add a
   `teleclaude.yml guardrails:` surface — per-lane enable/disable, severity
   (`off|warn|error`), cap tuning — so a brownfield project can ease in. This
   reflex treats a quality control as a project stance.
2. **Should guardrails defend their own enforcement?** The monolith historically
   grew rules that policed tool config (`_check_ruff_invariants`,
   `_check_pyright_invariants`, `_check_mypy_invariants`), pipeline wiring
   (`_check_lint_pipeline_integrity`), and ruff-rule suppression
   (`_check_import_outside_toplevel_policy`). These watch whether someone _weakened
   the watchers_, not whether the code is sound.

## Decision

**Guardrails are locked at error with no per-project quality configuration.** There
is no `teleclaude.yml guardrails:` surface — no toggles, no severity, no caps.
Adoption is **convergence, not negotiation**: a project that adopts the guardrails
trends toward the bar over time. The only flex for brownfield reality is the
**exemption ramp** — inline `# guard:` markers plus curated baseline/exemption
files (the `forbid_new_unit_tests` grandfather baseline, the `snapshot_testing`
exemptions) that can only **shrink** and trend to zero.

The discriminator: a **config toggle** is a project-wide _stance_ — a different,
equally-valid choice — whereas an **exemption** is a justified, visible, shrinking
local escape hatch. Quality controls are never stances, so they are locked; the
ramp is the only sanctioned narrowing.

**Guardrails do not watch the watchers.** A guardrail catches a substantive issue
in the code or structure. It must not police whether someone weakened a tool's
config, suppressed a tool's rule, or unwired the pipeline. That erosion-watching
belongs to the TeleClaude checkpoint (which watches protected config files) and to
reviewers — not to a guardrail. The config-integrity, pipeline-integrity, and
PLC0415-allowlist rules are therefore removed, and `forbid_new_unit_tests`
prevents backsliding only — judging whether functional coverage is _adequate_ is
intelligence in the agent's briefing, never a predicate in the guardrail (per
`general/principle/intelligence-boundaries`).

## Consequences

- A side project running `telec code lint` gets the universal pack against its
  code and cannot turn any guardrail down; it converges toward the bar or carries
  visible, shrinking exemption markers. There is no hybrid quality-juggling.
- Config erosion (a weakened ruff/pyright/mypy config, an unwired pipeline) is no
  longer caught by a guardrail; it is caught by the checkpoint's protected-config
  watching and by reviewers. If that coverage has gaps, they are closed there, not
  by re-adding watcher rules.
- The locked stance removes the caps machinery (`guardrail_caps.py`, the
  `[tool.guardrails]` template section, the hardcoded `*_MAX_*` caps, and
  `RUFF_REQUIRED_RULE_GROUPS`) as dead config.
- Brownfield onboarding is slightly more abrupt than a tunable bar would be, but
  the exemption ramp keeps adoption tractable while making every concession
  visible and time-bounded.

## Alternatives Considered

- **A `teleclaude.yml guardrails:` config surface** (per-lane severity/caps).
  Rejected: it reframes a quality control as a project stance and permits
  permanent, invisible weakening — the opposite of convergence.
- **Keeping the config-integrity / pipeline-integrity guardrails.** Rejected: they
  watch the watchers, duplicating the checkpoint and reviewers, and couple
  guardrails to each project's native tool config.
