---
visibility: public
number: 80
date: 2026-09-07
description: telec option recognition is derived at runtime from the declared CLI surface through one shared parser; argparse and a third-party CLI framework are not adopted.
---

# CLI Flag Recognition Derives From The Surface Declaration — ADR

## Context

The `telec` command line carries a declarative surface schema: every command
and every option is declared once as data, and that declaration renders the
usage lines, the option lists, the generated documentation, and the shell
completion catalog. Recognition was never wired to it. Each command handler
hand-rolled its own argument loop from literal string comparisons, copied by
hand from whatever the author remembered the declaration to be. Declaration
and recognition were two independently maintained representations of the same
fact, with nothing to detect drift between them.

The drift produced defects in several shapes at once: declared short aliases
that no handler recognized, the same option concept declared several times
with different aliases, and three different unknown-option behaviors depending
on which file a command happened to live in — including silent discard, where
a mistyped option made the command proceed with defaults and no warning. A
census counted roughly two hundred literal option comparisons across more than
twenty handler modules.

The forces in play: the surface schema already exists and is the single source
for every other consumer; the Python standard library ships a full argument
parser; the codebase policy requires closed vocabularies and named owners
rather than inlined literals; and the project verifies through the live CLI
rather than a test suite, so every implicit parsing behavior is a behavior an
operator can hit.

## Decision

Option recognition derives from the declared surface. Each option declaration
states its arity — presence-only, single value, repeated value, or a greedy
run of values — and one shared parser, driven by the command's declared option
list, separates options from operands for every command. Handlers read parsed
results through the declared option objects and never compare argv tokens to
literals.

The parser is purpose-built over the existing declaration. Neither `argparse`
nor a third-party CLI framework is adopted for the `telec` surface.

## Consequences

- An option is recognizable only when it is declared, and every declared form
  of it is recognized everywhere, so help, completion, documentation, and
  recognition cannot disagree.
- Every option declaration must now state its arity. A declaration that
  omits it is a type error, which turns the census of "what does this option
  take" into a compile-time obligation rather than a review question.
- Unknown-option handling is one policy declared per command rather than a
  per-file accident. The strict default rejects with usage; a command whose
  operand is free text opts into literal dash-leading text explicitly.
- The `--` separator and the `--option=value` form become available on every
  command, because the parser implements them once.
- The usage `args` string remains hand-authored beside the option list. It is
  presentation, and this decision does not derive it from the declaration; a
  mismatch between the two is still a review finding rather than an error.
- Short-option clustering, abbreviation matching, and negative-number
  heuristics are not offered. Operators coming from `argparse`-based tools do
  not get them, and that absence is deliberate.
- The greedy arity carries the ambiguity that already existed on the one
  command using it: an operand following a greedy option's values is consumed
  as a value unless the operator separates it with `--`.

## Alternatives Considered

- **Compile the surface declaration into `argparse` parsers.** The standard
  library parser would supply the tokenizer for free, but it carries implicit
  behaviors the surface never declared — prefix abbreviation, short-option
  clustering, a negative-number heuristic, and its own usage and error
  format — each of which is an observable behavior change and a second
  rendering of help beside the one the surface already produces. Disabling
  them one by one is more code than the tokenizer they would replace, and the
  delivered contract that undeclared dash-leading search text is a search term
  is not expressible without parsing "unknown" arguments separately anyway.
  Rejected.
- **Adopt a third-party CLI framework.** Click or Typer would replace the
  surface schema wholesale, moving the single source of truth out of project
  data and into decorator-driven code, and would add a runtime dependency to a
  tool that starts on every agent shell. Rejected.
- **Patch each reported handler.** Recognize the missing aliases at the two
  reported entry points and stop. This treats a structural defect as two
  typos and leaves every other hand-copied comparison free to drift again.
  Rejected.
