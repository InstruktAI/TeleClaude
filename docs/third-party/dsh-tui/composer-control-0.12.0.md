---
description: dsh-tui 0.12.0 (the DeepSeek Harness TUI profile plugin) composer control on pasted input — shell and slash commands, trimming, and which leading character neutralizes them.
---

# dsh-tui 0.12.0 composer control

## Evidence boundary

The DeepSeek Harness (`dsh` 0.2.0-rc.2) composer is provided by the profile
plugin `@deepseek-harness-tui/dsh-tui` 0.12.0, installed under
`~/.dsh/profiles/dsh-tui/node_modules/`. Findings come from its source
(`lib/types/`) and from pastes through tmux bracketed paste (`load-buffer`,
`paste-buffer -p -r`, then a separate `send-keys C-m`) with model replies
observed.

## Leading characters that act on pasted input

- `!` — after `text.trim()`, a leading `!` runs the rest as a local shell
  command in the workspace shell with no approval prompt, output shown only in
  the TUI; `!!` also sends the output to the model as `<bash-stdout>`
  (`dsh-adapter/channel/input-actions.js`, `channel/local-actions.js`). Local
  runs are not recorded in the session transcript. JavaScript `trim()` removes
  spaces, tabs, line breaks, U+00A0 and U+FEFF, so none of those stop `!`.
  Text steered into a running turn has no `!` handling.
- `/` — judged on untrimmed text (`components/PromptInput.js` `tryRunCommand`,
  `commands.js` `parseCommandName`): a known command name runs with the rest of
  the text, later lines included, as arguments; a partial name opens the menu
  and Enter runs the highlighted command; a bare `/` runs the first command
  (`new`); an unknown `/word` goes to the model.
- `?` opens help only as a typed key in an empty composer.
- `@` mentions expand at delivery; `#` matters only inside `@path#L…`.
- Bracketed paste is enabled by Ink and inserted as plain text before any
  decision; the paste cleaner removes only ANSI and C0 controls.

## Neutralizing prefix

A leading U+200B makes `!` and `/` pastes ordinary prompts that submit on the
single discrete Enter. U+200B is kept in the session's `user/message` entries.

## Sources

- https://github.com/ccch1mneyyy/dsh-TUI
