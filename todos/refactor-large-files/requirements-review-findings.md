# Requirements Review Findings: refactor-large-files

## Auto-remediated (resolved)

### 1. Implementation leakage and unmarked inferences — Important (resolved)

The requirements mixed plan-level prescriptions into a what/why artifact and
presented several policy-driven additions as if they came directly from the
input. This review pass:

- removed plan-level implementation details such as named facade files,
  module-specific fanout counts, and decomposition-shape prescriptions
- tightened verification so it matches the scoped refactor instead of asserting
  an unscoped codebase-wide ceiling
- added `[inferred]` markers to policy-derived items such as type-check
  expectations, circular-dependency avoidance, and commit-history verification

## Unresolved

### 2. Requirements silently expand scope beyond the human input — Important

`input.md` defines a verified target inventory of **20** oversized files and
does not mention the seven additional files that now exceed 1,000 lines
([`input.md`](/Users/Morriz/Workspace/InstruktAI/TeleClaude/todos/refactor-large-files/input.md#L7),
[`input.md`](/Users/Morriz/Workspace/InstruktAI/TeleClaude/todos/refactor-large-files/input.md#L9)).
`requirements.md` now changes the scope to **all 27** files currently over the
threshold
([`requirements.md`](/Users/Morriz/Workspace/InstruktAI/TeleClaude/todos/refactor-large-files/requirements.md#L14),
[`requirements.md`](/Users/Morriz/Workspace/InstruktAI/TeleClaude/todos/refactor-large-files/requirements.md#L31)).

That is a material workload increase, changes the readiness/splitting posture of
the todo, and is not marked as `[inferred]`. A requirements reviewer cannot
silently add those seven files to scope or silently drop them. The scope needs
an explicit human-backed decision.

The additional files are:

- `teleclaude/core/adapter_client.py` (1,161 lines)
- `teleclaude/core/models.py` (1,095 lines)
- `teleclaude/cli/tui/views/config.py` (1,086 lines)
- `teleclaude/cli/tui/animations/general.py` (1,074 lines)
- `teleclaude/hooks/receiver.py` (1,068 lines)
- `teleclaude/adapters/ui_adapter.py` (1,048 lines)
- `teleclaude/cli/tui/views/preparation.py` (1,020 lines)

Remediation required before approval:

- update `input.md` and `requirements.md` to explicitly include these seven
  files, or
- explicitly defer them with justification so the scope remains the original
  20-file inventory.
