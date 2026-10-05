---
description: Antigravity CLI (agy) 1.2.17 composer control on pasted input — slash commands on paste, shell mode only as a keystroke, the unbracketed fallback, and which leading character neutralizes them.
---

# Antigravity CLI 1.2.17 composer control

## Evidence boundary

Pastes through tmux bracketed paste (`load-buffer`, `paste-buffer -p -r`, then
a separate `send-keys C-m`) into `agy` 1.2.17 (Go binary; embedded changelog
ends at 1.2.16), vendor documentation, and binary strings. The model quota was
exhausted, so routing was judged from agy's own records: `cli.log`
`HandleUserInput` and `Registered shell command` lines, the conversation
database, and the brain transcript. Model replies were not observed.

## Leading characters that act on input

- `/` — command menu; a recognized command, alias or skill runs on submit,
  also when pasted, also when followed by more lines (the message is then
  consumed), and a partial name is completed to the highlighted command. Input
  is trimmed before the check, so a leading space does not stop it.
- `!` — shell mode, toggled only by a typed `!` on an empty prompt. A pasted
  `!` (leading or mid-text) reaches the agent verbatim. When bracketed paste is
  not honoured and text arrives as keystrokes, a leading `!` does start shell
  mode and runs the command.
- `?` — shortcuts panel, only as a typed key on an empty prompt.
- `@` — file and subagent mentions.
- No other leading character has a meaning; Vim editor mode (off by default)
  makes `/` and `!` Normal-mode commands.

## Literal escapes

A pasted `!`, leading or mid-text, reaches the agent verbatim. A `\!` escape
reaches the agent, the conversation database and the transcript as a literal
backslash followed by `!`.

## Neutralizing prefix

A leading U+200B makes `/` pastes and unbracketed `!` keystroke input ordinary
prompts that submit on the single discrete Enter. U+200B is kept in agy's input
log and conversation database and is absent from the brain `transcript.jsonl`.

## Other submission behavior

- A message ending in `\` does not submit: Enter removes the backslash and
  inserts a newline.
- A feedback-survey overlay ("[1] Good [2] Fine [3] Bad [0] Skip") appears
  after some turns; a paste submitted while it shows was lost. Setting:
  `showFeedbackSurvey` (default true).

## Sources

- https://antigravity.google/docs/cli/using/
- https://antigravity.google/docs/cli/reference/
- https://antigravity.google/docs/cli/prompting/
- https://antigravity.google/docs/cli/vim-editor-mode/
