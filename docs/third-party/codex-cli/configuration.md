---
description: Codex CLI Configuration and Compaction
id: third-party/codex-cli/configuration
scope: project
type: third-party
---

# Codex CLI Configuration and Compaction

## Overview

Codex reads configuration from layered TOML files and CLI overrides. The official docs
separate general configuration from the compaction API guide, so this snippet consolidates
the parts that matter for local Codex behavior.

## Configuration layers

Codex reads configuration in this precedence order:

1. CLI flags and `--config` overrides
2. Selected profile values from `--profile <name>`
3. Project config files at `.codex/config.toml` from repo root down to the current working directory
4. User config at `~/.codex/config.toml`
5. System config at `/etc/codex/config.toml` when present
6. Built-in defaults

Project-scoped `.codex/config.toml` files are only loaded for trusted projects.

## Common Codex config surfaces

- `~/.codex/config.toml` stores user defaults.
- `.codex/config.toml` stores project overrides.
- `--config key=value` applies one-off overrides at invocation time.
- `[profiles.<name>]` lets you define named configuration sets and switch with `codex --profile <name>`.

## Compaction-related keys

These are the documented Codex CLI configuration keys that directly affect history
compaction or the threshold at which it happens:

| Key                                | Meaning                                                                                                         |
| ---------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| `model_auto_compact_token_limit`   | Token threshold that triggers automatic history compaction. If unset, Codex uses model defaults.                |
| `compact_prompt`                   | Inline override for the history compaction prompt.                                                              |
| `experimental_compact_prompt_file` | Experimental file-based override for the compaction prompt.                                                     |
| `model_context_window`             | Context-window token capacity available to the active model. Useful when reasoning about compaction thresholds. |

## Built-in compaction prompt

The current upstream Codex source stores the built-in prompt at:

- `codex-rs/core/templates/compact/prompt.md`

Current upstream text:

```md
You are performing a CONTEXT CHECKPOINT COMPACTION. Create a handoff summary for another LLM that will resume the task.

Include:

- Current progress and key decisions made
- Important context, constraints, or user preferences
- What remains to be done (clear next steps)
- Any critical data, examples, or references needed to continue

Be concise, structured, and focused on helping the next LLM seamlessly continue the work.
```

Codex falls back to this built-in prompt when `compact_prompt` is unset:

- `codex-rs/core/src/compact.rs`
- `codex-rs/core/src/codex.rs`

## What is not documented as a Codex CLI mode switch

The official Codex CLI docs do **not** document a user-facing setting that chooses between
multiple compaction modes.

What the official OpenAI docs do document is:

- Codex CLI threshold and prompt overrides via `config.toml`
- API-level compaction workflows:
  - server-side compaction triggered by `context_management` with `compact_threshold`
  - standalone explicit compaction via `/responses/compact`

Those API workflows explain how compaction works in model interactions, but they are not
documented as a separate Codex CLI "mode" selector.

## Practical interpretation

- If you want Codex to compact earlier or later, tune `model_auto_compact_token_limit`.
- If you want different summarization behavior during compaction, override the compaction prompt
  with `compact_prompt` or `experimental_compact_prompt_file`.
- If you need per-project behavior, prefer `.codex/config.toml` rather than changing user-global defaults.
- If you need a one-off experiment, prefer `codex --config ...` over editing config files.

## File-based override behavior

- `experimental_compact_prompt_file` is loaded into `compact_prompt` during config resolution.
- Codex trims surrounding whitespace from the file contents and rejects an empty file.
- Config-layer path values are resolved against the parent directory of the config file before deserialization.

Example project-local setup:

```toml
# .codex/config.toml
experimental_compact_prompt_file = "CODEX.compaction.md"
```

With that layout, Codex resolves the prompt file as `.codex/CODEX.compaction.md`.

## Sources

- https://developers.openai.com/codex/config-basic
- https://developers.openai.com/codex/config-advanced
- https://developers.openai.com/codex/config-reference
- https://developers.openai.com/api/docs/guides/compaction
- https://github.com/openai/codex/blob/main/codex-rs/core/templates/compact/prompt.md
- https://github.com/openai/codex/blob/main/codex-rs/core/src/compact.rs
- https://github.com/openai/codex/blob/main/codex-rs/core/src/codex.rs
- https://github.com/openai/codex/blob/main/codex-rs/core/src/config/mod.rs
- https://github.com/openai/codex/blob/main/codex-rs/core/src/config/config_tests.rs
