---
description: '1:1 source-to-test mapping, directory conventions, exemptions, and CI enforcement.'
id: 'software-development/policy/test-structure'
scope: 'domain'
type: 'policy'
visibility: 'public'
---

# Test Structure — Policy

## Rules

1. Every source file must have a corresponding test file following the project's mirror convention (1:1 source-to-test mapping).
2. Exemptions are declared in the project's configuration file as an explicit list of paths.
3. Exemptions are valid only for files with genuinely no testable logic (pure type definitions, configuration delegation, thin wrappers). Files containing functions with branching, validation, parsing, or business rules must have tests regardless of their primary purpose.
4. A CI enforcement check validates the mapping and exits nonzero when gaps exist.
5. New source files must have a corresponding test file before merge. The test file may start as a stub, but the mapping must exist.
6. Tests are behavioral contracts, not implementation snapshots:
   - Assert behavior and outcomes, not internal state or call counts.
   - No literal/substring/pattern assertions on string content — composed messages, CLI output, formatted reports, notifications, error prose, agent artifacts, documentation, protocol markers, schema keys, command names. Use snapshots for rendered text and named constants for protocol identity. See `software-development/policy/testing` → "String Assertions — One Paradigm".
   - Reject tests that merely restate literals, keys, or values already visible in the source or fixture without proving any transformation, validation, or decision logic.
   - Reject tests that only confirm primitive effects such as create/copy/write/existence/pass-through when no application-owned behavior, branching, or failure handling was exercised.
   - Maximum 5 mock patches per test. More indicates the code under test has too many dependencies.
   - Each test function must have a descriptive name that serves as a behavioral specification.

### Language and Framework Context

This policy is framework-agnostic. Mirror conventions, test file patterns, exemption configuration
format, and CI enforcement tooling are project concerns — discover them from the codebase
(package config, Makefile, existing tests).

You MUST run `telec docs index --areas policy --domains software-development` to surface
language-specific policy snippets, then `telec docs get <snippet_id>` to read them ALL —
they contain mandatory language idioms for any code-producing work.

## Rationale

- 1:1 mapping makes coverage gaps immediately visible and prevents orphan tests.
- Behavioral contracts survive refactoring; implementation-detail tests create drag.

## Scope

- Applies to all source files and their corresponding test files in any project.

## Enforcement

- CI enforcement checks the mapping and reports gaps.
- Code review verifies new source files have corresponding test files.

## Exceptions

- Files listed in the project's exemption configuration with a comment explaining why.
