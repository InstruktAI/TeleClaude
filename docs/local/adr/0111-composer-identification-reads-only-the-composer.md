---
visibility: internal
number: 0111
date: 2026-10-04
description: Input readiness rests on settled agent activity, and the live composer is identified by its own markers alone; no row outside the composer, such as a footer, status line, hint or warning, takes part in identifying it or deciding whether it holds input.
---

# Composer Identification Reads Only The Composer — ADR

## Context

Pane-based agent runtimes accept input only when a live composer can be
identified as empty or occupied. A composer can be confused with a screen that
merely shares its marker glyph, such as a selection list or an earlier prompt
echoed in the transcript, so the identification has to say where the live
composer is and where it ends.

Codex draws no border under its composer. Its end was inferred from the rows
that follow it: the composer counted as complete only when a recognized footer
row closed it. Gemini went further, locating its composer by a footer hint
string and accepting the footer as chrome only when it parsed as a known model
and effort label. Startup readiness then consulted that classification before
measuring whether the pane had settled, and reset its settle measurement
whenever the classification was inconclusive.

Footers are presentation the agent CLIs change freely: a user's status-line
choice, a configuration deploy, a version upgrade or a model rename alters
them. Each change outside the recognized vocabulary made an available composer
unidentifiable and blocked readiness until timeout. Within thirty days the
recognized vocabulary had been extended five times, and one more footer order
then stopped every Codex startup delivery on a machine.

## Decision

- **Readiness rests on settled activity.** An agent is ready for input only
  after its visible activity has settled; composer classification is consulted
  on the settled surface and never restarts the settle measurement.
- **The composer is identified by its own markers.** Each runtime declares the
  markers that belong to its composer: the prompt glyph and the frame, padding
  or border the CLI draws as part of the composer itself. Identification and the
  empty or occupied decision read only what those markers enclose.
- **Rows outside the composer take no part.** Footers, status lines, hints,
  warnings, model and context labels and animation are never read for what they
  say, and a row outside the composer's frame is never a candidate composer.

## Consequences

- A footer, status-line or label change in an agent CLI no longer affects input
  readiness or delivery.
- A runtime whose composer has no closing border is bounded by the padding its
  CLI renders as part of the composer; when that composer is empty, the CLI's
  placeholder marks it as empty.
- An agent that is still producing output is held back by unsettled activity,
  not by a heuristic about the rows around the prompt.
- Onboarding a runtime means verifying its composer's own markers from a pane
  capture. A runtime whose composer cannot be bounded by its own markers is not
  pane-ready until it can be.

## Alternatives Considered

- **Keep footer recognition and extend its vocabulary.** Rejected: every CLI
  footer change becomes a readiness outage, and the vocabulary only ever grows.
- **Identify the composer by its marker row alone.** Rejected: a lone marker row
  cannot be told apart from a selection list or a transcript echo that uses the
  same glyph.
