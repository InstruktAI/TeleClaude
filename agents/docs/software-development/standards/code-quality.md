---
description:
  Architecture, typing, contracts, state management, error handling. Generic
  quality standards for all code.
id: software-development/standards/code-quality
scope: domain
type: policy
---

# Code Quality Standards

Principle

- Code quality is enforced through explicit contracts, stable boundaries, and verifiable outcomes.

Rules

- Honor repository configuration and established conventions.
- Encode invariants explicitly and validate at boundaries.
- Preserve contract fidelity across all call chains.
- Keep responsibilities narrow and interfaces explicit.
- Fail fast on contract violations with clear diagnostics.
- Keep state ownership explicit and observable.

Scope

- Applies to all code changes and design decisions.

See also

- @~/.teleclaude/docs/software-development/guide/code-quality-practices.md
