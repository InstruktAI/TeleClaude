---
description: Codex CLI 0.160.0 composer control on pasted input — which leading characters run a shell command or slash command, how leading whitespace is trimmed, and which leading character neutralizes them.
---

# Codex CLI 0.160.0 composer control

## Evidence boundary

TUI source at tag `rust-v0.160.0` (commit `a956835d0207`, `codex-rs/tui/src/`)
plus pastes through tmux bracketed paste (`load-buffer`, `paste-buffer -p -r`,
then a separate `send-keys C-m`) into `codex` 0.160.0. Model replies were
observed.

## Leading characters that act on pasted input

- `!` — runs the rest as a user shell command (`/bin/zsh -lc`, recorded with
  `source: user_shell`), when idle and also mid-turn. Pastes take the typed-text
  path (`paste_input.rs` `apply_paste` → `chat_composer.rs`
  `sync_bash_mode_from_text`); submission trims Unicode `White_Space` before the
  `!` check (`chat_composer.rs` `prepare_submission_text_with_options`,
  `chatwidget/input_submission.rs`), so a leading space, tab or U+00A0 does not
  stop it. A paste over 1000 characters becomes a placeholder sent literally.
- `/` — slash commands, judged on untrimmed text with `strip_prefix('/')`
  (`prompt_args.rs` `parse_slash_name`):
  - a bare known command on the first line runs and later lines are dropped
    (`slash_input.rs` `bare_command`);
  - commands that take inline arguments run with the rest of the message as
    arguments (`slash_command.rs` `supports_inline_args`);
  - a partial name runs the highlighted fuzzy match;
  - an unknown `/word` is rejected, stays unsent in the composer and merges
    with the next paste;
  - a name containing `/` (`/usr/bin …`) goes to the model.
- `?` opens the shortcut overlay only as a typed key in an empty composer.
- `$` (skills) and `@` (files) popups depend on the word at the cursor, not the
  first character (source only).

## Neutralizing prefix

A leading U+200B makes `!` and `/` pastes ordinary prompts that submit on the
single discrete Enter, idle and busy. U+200B is not `White_Space` and is not
removed by `sanitize_user_text` (which removes Cc controls and ANSI CSI); the
rollout transcript stores the user text with the U+200B. A leading ASCII space
stops `/` but not `!`.

## Other submission behavior

A discrete Enter after a bracketed paste submits whatever the paste ends with;
the composer has no line-continuation rule for a final `\`
(`bottom_pane/chat_composer.rs`; only an active unbracketed paste burst turns
Enter into a newline). Established from source only; upstream issue #3556
asking for backslash continuation was closed as not planned.

## Sources

- https://github.com/openai/codex/tree/rust-v0.160.0/codex-rs/tui/src
- https://developers.openai.com/codex/cli
