---
description: 'Every telec command recognizes exactly the options its published surface
  declares: each declared short alias behaves as its long form, an undeclared option
  is rejected with usage, a missing value is rejected, `--` ends option parsing, `--option=value`
  is accepted, and shell completion offers alias forms as separate candidates.'
---

# CLI Flag Recognition — Spec

## Required reads

- @docs/local/spec/domain/context-map.md

## What it is

The `telec` command line publishes one surface: the usage lines, option
lists, generated documentation, and shell completion all render from a single
declaration of what each command accepts. This spec binds the recognition
side of that surface to the same declaration. What a command's help says it
accepts is what the command accepts, on every command, for every declared
form of every option.

The observers are the human operator at a terminal and the agent session
invoking `telec` from its shell. Both read the command's terminal output and
exit status directly; the CLI's own text is the evidence.

Two option policies exist and both are declared per command, never improvised
by a handler:

- **Strict** — the default. A dash-leading token that is not a declared
  option, and does not follow a `--` separator, is a usage error.
- **Literal free text** — declared only by a command whose positional operand
  is free text that may itself begin with a dash. On such a command an
  undeclared dash-leading token is that operand's text. Historical
  conversation search is the one such command today.

## Canonical fields

Zsh completion groups short and long option forms under one description when
the shell's native grouping style is enabled. Each form remains independently
selectable and inserts only that form. Completion consumes the shared option
declarations; the shell owns display grouping and alignment
(`sdlc/principle/design-fundamentals`, DRY and separation of responsibilities).

### Use cases

#### UC-CFR-1: An operator runs a command with the options its surface publishes

```gherkin
Scenario: Published option forms work as declared
  Given an operator or an agent acting for them wants to run a documented telec command
  When they invoke it with a declared short or long option, a long-option value attached with `=`, a separate option value, or a dash-leading operand after `--`
  Then declared options behave according to the published command surface
  And a declared short alias behaves exactly as its long form
  And `--option=value` behaves exactly as `--option value`
  And a short option takes its value from the next token
  And the separator leaves following tokens as operand text
  And the command performs its normal behavior with that operand

Scenario: Invalid strict-option forms are refused before the command acts
  Given a command uses the strict option policy
  When the caller supplies an undeclared option or omits a required option value
  Then the refusal identifies the rejected option or missing value and prints that command's usage
  And the refusal exits with a non-zero status
  And the command does not perform its requested action

Scenario: Literal free text accepts a dash-leading operand
  Given a command declares the literal free-text policy
  When the caller supplies an undeclared dash-leading token as its free-text operand
  Then the token is accepted as operand text
  And every declared option is still recognized as an option
```

#### UC-CFR-2: An undeclared option is rejected with usage

#### UC-CFR-3: An option that requires a value rejects its absence

#### UC-CFR-4: A double-dash separator ends option parsing

#### UC-CFR-5: An option value may be attached with an equals sign

#### UC-CFR-6: Shell completion offers alias forms as separate candidates

```gherkin
Given an operator is completing a telec command whose published options declare a short alias
When the operator requests shell completion for that command's options
Then the short form and the long form are offered as two separate candidates
And selecting either inserts only that form
```

#### UC-CFR-7: A free-text command keeps undeclared dash-leading text as its operand

## Known caveats

- A value-taking option consumes the token that follows it even when that
  token begins with a dash; an operand that must begin with a dash on a
  strict command is passed after `--`.
- Short options are not clustered: `-ab` is not `-a -b`, and a short option
  takes its value as the next token, never attached.
- Operand count and meaning remain each command's own contract; this spec
  governs only which tokens are options.
