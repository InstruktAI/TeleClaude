---
description: TypeScript production logging rules for structured fields, interpolation, direct console use, and boundary output.
---

# TypeScript Logging — Policy

## Required reads

@~/.teleclaude/docs/software-development/policy/typescript/core.md

## Rules

- Production diagnostics use the project's declared structured logger and pass context as structured fields.
- Do not preformat diagnostic messages with template literals or string concatenation when the logging framework can receive fields separately.
- Do not use `console.log`, `console.warn`, `console.error`, or temporary console probes for production diagnostics.
- Human-facing command or application output goes through the surface's declared presenter or output abstraction. It is not smuggled through the diagnostic logger.
- Log levels, sensitive-data handling, identifier integrity, and boundary coverage follow the generic observability contract (`software-development/policy/observability`).

## Rationale

TypeScript's console and template-literal syntax makes unstructured diagnostics easy to introduce. Owning those mechanics here keeps `software-development/policy/observability` language-neutral and lets TypeScript tooling and review cite one precise source.

## Scope

- TypeScript production code, including frontend, command, service, and tooling modules.

## Enforcement

- Reviewers reject direct console diagnostics and preformatted context that should be structured fields.
- The project's TypeScript linter enforces direct-console restrictions where its native rules can express them.

## Exceptions

- A surface may use its declared output abstraction to emit user-visible content. That output is not diagnostic logging.

## See Also

- ~/.teleclaude/docs/software-development/policy/observability.md
