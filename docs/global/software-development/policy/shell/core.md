---
description: Shell-script safety, portability, linting, and invocation rules for executable shell modules.
---

# Shell Core — Policy

## Required reads

@~/.teleclaude/docs/software-development/policy/no-inline-logic.md

## Rules

- Executable shell behavior lives in a standalone script owned by this policy; configuration and orchestration files only delegate to it.
- Bash scripts enable strict failure handling with `set -euo pipefail` unless the selected shell lacks that feature or the script documents a narrower, intentional error posture.
- Quote expansions, use arrays for argument vectors, and keep filenames out of word-splitting and glob-expansion paths.
- Prefer shell built-ins and direct commands over string-built commands or `eval`.
- Shell scripts are `shellcheck`-clean under the repository's declared configuration. A suppression is narrow, local, and justified at the suppressed line.
- A caller invokes the script directly through the repository's declared task or package surface; it does not copy the script's command sequence into the carrier.

## Rationale

Shell has language-specific failure and expansion semantics that a generic delegation policy cannot own safely. A dedicated owner keeps those mechanics precise without priming every language to use Bash conventions.

## Scope

- Shell scripts and shell entrypoints in repositories that use Bash or a compatible declared shell.

## Enforcement

- The repository's shell lint configuration and review enforce these rules.
- Reviewers reject unquoted data expansion, unjustified `eval`, silent error-posture weakening, and shell logic embedded in non-script carriers.

## Exceptions

- POSIX-shell or another shell may replace Bash-specific mechanics when the repository declares that runtime; its equivalent safety posture must be explicit.
