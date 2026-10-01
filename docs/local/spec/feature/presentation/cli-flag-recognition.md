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

### Use cases

#### UC-CFR-1: A declared short alias behaves as its long form on every command

```gherkin
Given a telec command whose published options declare a short alias for an option
When an operator or an agent invokes the command using the short alias where the long form is documented
Then the command behaves exactly as it does with the long form
And no command on the surface treats a declared alias as an unknown option or as operand text
```

#### UC-CFR-2: An undeclared option is rejected with usage

```gherkin
Given a telec command under the strict option policy
When an operator or an agent passes a dash-leading token the command does not declare
Then the command names the rejected token as an unknown option
And prints that command's usage
And exits with a non-zero status without performing the command
```

#### UC-CFR-3: An option that requires a value rejects its absence

```gherkin
Given a telec command whose declared option takes a value
When an operator or an agent passes the option as the last token, or followed directly by another option
Then the command names the option that is missing its value
And prints that command's usage
And exits with a non-zero status without performing the command
```

#### UC-CFR-4: A double-dash separator ends option parsing

```gherkin
Given a telec command under the strict option policy
When an operator or an agent passes `--` followed by a dash-leading token
Then every token after the separator is treated as operand text
And the command performs its normal behavior with that text
```

#### UC-CFR-5: An option value may be attached with an equals sign

```gherkin
Given a telec command whose declared option takes a value
When an operator or an agent passes the option as `--option=value`
Then the command behaves exactly as it does with `--option value`
```

#### UC-CFR-6: Shell completion offers alias forms as separate candidates

```gherkin
Given a telec command whose published options declare a short alias for an option
When an operator requests shell completion for that command's options
Then the short form and the long form are offered as two separate candidates
And selecting either inserts only that form
```

#### UC-CFR-7: A free-text command keeps undeclared dash-leading text as its operand

```gherkin
Given a telec command declared under the literal free-text policy
When an operator or an agent passes a dash-leading token the command does not declare
Then the token is accepted as operand text rather than rejected as an unknown option
And every option the command does declare is still recognized as an option
```

## Known caveats

- A value-taking option consumes the token that follows it even when that
  token begins with a dash; an operand that must begin with a dash on a
  strict command is passed after `--`.
- Short options are not clustered: `-ab` is not `-a -b`, and a short option
  takes its value as the next token, never attached.
- Operand count and meaning remain each command's own contract; this spec
  governs only which tokens are options.
