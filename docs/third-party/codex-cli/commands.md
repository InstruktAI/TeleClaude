---
description: 'Codex CLI Commands — built-in slash commands; custom prompts are deprecated in favour of skills.'
---

# Codex CLI Commands

## Overview

Codex CLI documents built-in slash commands. Custom prompt files still become slash
commands, but the vendor has deprecated them.

## Custom prompts (deprecated)

OpenAI marks custom prompts deprecated, stating: "Deprecated. Use skills for reusable
prompts." Skills are the recommended mechanism for reusable instructions Codex can invoke
explicitly or implicitly.

- Custom prompt files live in `~/.codex/prompts`.
- Custom prompts are invoked as `/prompts:<name>`.
- The vendor documentation states no removal version or sunset date; the feature is
  deprecated, not documented as removed. Community reports of prompt slash commands
  breaking on specific CLI versions are not vendor statements and are not treated as
  authoritative here.

Author reusable instruction sets as skills rather than custom prompts.

## Sources

- https://developers.openai.com/codex/cli/slash-commands
- https://learn.chatgpt.com/docs/custom-prompts

## See Also

- third-party/codex-cli/research-log — Codex Session Log Rate-Limit Retrieval
