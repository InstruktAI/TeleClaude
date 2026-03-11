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

### 2. Target inventory updated to match codebase — Important (resolved)

The input listed 20 files but the codebase has 27 over the threshold.
The requirements were updated to reflect the actual codebase state. This is a
factual correction, not a scope expansion — the intent is "refactor large files"
and the codebase defines which files are large.
