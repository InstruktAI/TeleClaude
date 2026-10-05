---
description: Claude Code 2.1.289 composer control on pasted input — which leading characters start shell mode or a slash command, how invisible characters block submission, and which leading characters neutralize a control character.
---

# Claude Code 2.1.289 composer control

## Evidence boundary

Observed on `claude` 2.1.289 (macOS arm64) by pasting through tmux bracketed
paste (`load-buffer`, `paste-buffer -p -r`, then a separate `send-keys C-m`),
launched with `--setting-sources ""`, plus vendor documentation and string
inspection of the shipped binary. Model replies were observed.

## Leading characters that act on pasted input

- `!` — shell mode. A pasted text beginning with `!` runs as a shell command
  in the user's shell, outside the agent sandbox and permission rules; this
  holds for multi-line pastes that collapse into a pasted-text block, and a
  `!` paste made while the agent is busy is queued and run after the turn.
  Shell-mode input fires no `UserPromptSubmit` hook and is stored as
  `<bash-input>`/`<bash-stdout>`.
- `/` — slash command or skill, recognized only at the start of the message.
  Slash commands fire no `UserPromptSubmit` hook and are stored as
  `system`/`local_command` entries. A paste over 800 characters or more than
  three lines collapses to `[Pasted text #N]` and is sent as a prompt.
- `?` (help panel), `#` (removed memory shortcut, 2.0.70), `:` (emoji
  shortcode) and `&` (background prefix, hint removed in 2.1.154) do not act
  on pasted text; `&` was established statically only.
- The binary's input-mode classifier recognizes only `!` (bash) versus prompt.

## Invisible characters block submission

Since 2.1.277 an Enter that strips any invisible character sends nothing: the
cleaned text stays in the composer with "Removed N invisible character · review
and press Enter to send", and the next Enter submits it. The stripped set
includes C0/C1 controls, U+00AD, U+061C, U+200B–U+200F, U+2028/2029,
U+202A–U+202E, U+2060–U+2069, U+FE00–U+FE0F, U+FEFF, U+FFF9–U+FFFB, U+16FE4
and the tag characters; U+00A0 is not in it. A U+200B prefix therefore does not
neutralize `/`: the cleaned `/command` runs on the next Enter.

## Neutralizing prefixes

A leading U+00A0 or ASCII space makes a `!` or `/` paste an ordinary prompt
that submits on the single discrete Enter. U+00A0 is stored byte-exact in the
transcript and the `UserPromptSubmit` payload.

## Other submission behavior

A message ending in `\` does not submit: Enter removes the backslash and
inserts a newline, so the next pasted text is appended. A run of backslashes is
no escape: `\\` loses one backslash the same way.

A character after the final backslash makes the single discrete Enter submit:
an ASCII space, U+00A0, or a line break, also when the backslash is itself
followed by whitespace. A normal prompt is recorded with its trailing
whitespace trimmed, so the `UserPromptSubmit` payload and the transcript hold
the text with its final backslash and without that character. A trailing
U+200B does not help: it is stripped and that Enter sends nothing.

A paste over 800 characters or more than three lines collapses into a pasted
block, which submits even when it ends in `\`; the block keeps a trailing space
but not a trailing line break, and is recorded inside
`<pasted_content id="…">` framing. An appended character counts toward both
limits: a line break turns a three-line paste into a collapsed one, and any
character turns an 800-character paste into one. A model may treat a collapsed
block as pasted content rather than as the person's own request.

## Sources

- https://code.claude.com/docs/en/interactive-mode
- https://code.claude.com/docs/en/commands
- https://code.claude.com/docs/en/terminal-config
- https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md
