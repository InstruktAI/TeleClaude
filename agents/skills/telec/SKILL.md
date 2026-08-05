---
name: telec
description: Load and follow a TeleClaude command document inside the current session. Use this whenever you need to run a TeleClaude command by name — lifecycle commands such as next-prepare, next-build, next-review-build, next-finalize, next-integrate, or any other document in the TeleClaude command corpus. This is the single invocation surface for TeleClaude commands; there are no native per-command slash commands. It loads a command into the session you are already in and never starts a new session.
teleclaude_taxonomy: true
---

# Telec

## Purpose

Load one TeleClaude command document from the shared command corpus and follow it as the
active instruction set for the current session.

## Scope

This skill loads a command into the **current** session. It is not a dispatcher.

- In scope: resolving a TeleClaude command by name and following the document it names.
- Not in scope: starting a session. Dispatching a worker is `telec sessions run --command
/<name> --args <args>`, which creates a **new** session preloaded with that command.
  Loading a command here and dispatching one there are different operations; do not
  substitute one for the other.
- Not in scope: reading arbitrary files. Only a command name resolves, and only inside the
  command corpus.

## Inputs

- `command` — a TeleClaude command name, such as `next-prepare`. A leading `/` is
  tolerated and stripped. It is a name, never a path.
- `args` — everything after the command name, passed through verbatim as the provided
  inputs to the loaded document. Most lifecycle commands take a todo slug.

## Outputs

- The selected command document becomes the active instruction set for this session, with
  `args` treated as its provided inputs.
- On invalid input: a visible failure and no file read. Nothing is loaded and no
  instruction set changes.

## Procedure

1. Separate the invocation into the command name and the remaining arguments.
2. Strip a single leading `/` from the name if present.
3. Reject the invocation, without reading anything, when the name is empty, is `.` or
   `..`, contains a path separator, contains control characters, or is otherwise not a
   plain command-name token. A name that tries to traverse is refused, not normalized.
4. Resolve the name against the command corpus at `~/.teleclaude/commands/<name>.md` and
   confirm the resolved path is still inside that directory.
5. Fail visibly when no such command document exists. Do not guess a near match and do not
   fall back to another file.
6. Read the resolved document and follow it exactly as the active instruction set for this
   session, treating `args` as the inputs it names.

## See Also

- ~/.teleclaude/docs/general/spec/tools/telec-cli.md — the `telec` CLI surface, including
  `telec sessions run` for dispatching a new session with a command.
