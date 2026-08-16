---
description: Language-neutral decision and review flow for snapshotting emitted string contracts without literal-echo assertions.
---

# Snapshot Testing — Procedure

## Required reads

@~/.teleclaude/docs/software-development/policy/testing.md
@~/.teleclaude/docs/software-development/policy/language-policy-ownership.md

## Goal

Choose the correct semantic assertion for emitted string content, route its implementation to the applicable language procedure, and accept snapshot changes only after reviewing their intent.

## Preconditions

- The project has opted into test authorship under the generic testing policy.
- The assertion observes behavior at a public boundary.
- The applicable language testing and snapshot guidance is loaded.

## Steps

1. **Choose the semantic move.** Snapshot emitted content when its full value is the contract. Use a narrow non-empty guard only when accidental erasure is the failure mode. Compare an imported production member only when behavior turns on protocol identity.
2. **Capture the outward-facing surface.** Snapshot the complete rendered message, command output, error envelope, or other public value rather than internal fragments.
3. **Normalize nondeterminism before capture.** Replace timestamps, generated identifiers, and other unstable values through the applicable language's snapshot matcher or serializer mechanism. Never weaken the assertion to accommodate unstable output.
4. **Migrate content-grading assertions.** Replace literal, substring, prefix, suffix, search, and regular-expression checks of emitted content with the selected semantic move. Assert exceptions by type; structure protocol identifiers as production-owned members.
5. **Apply the language owner.** Follow the applicable language-specific snapshot procedure for imports, matcher syntax, inline-versus-file placement, runner commands, and update mechanics.
6. **Review every diff before acceptance.** Match the change to active intent and inspect for missing blocks, empty output, stale interpolation, placeholders, or garbling. Update only after that review; continuous integration never accepts snapshots automatically.

## Outputs

- String assertions use snapshots, narrow non-empty guards, or imported production members according to their semantics.
- Snapshot updates carry a reviewed diff and a report of why the delta is intended.

## Recovery

- If a snapshot diff does not match intent, fix the producing behavior and rerun without accepting the snapshot.
- If language guidance is missing, add or obtain a language-owned procedure before selecting concrete syntax or tooling.

## See Also

- ~/.teleclaude/docs/software-development/procedure/python/snapshot-testing.md
- ~/.teleclaude/docs/software-development/procedure/typescript/snapshot-testing.md
- ~/.teleclaude/docs/software-development/policy/rust/testing.md — Rust snapshot mechanics are owned by the Rust testing policy.
