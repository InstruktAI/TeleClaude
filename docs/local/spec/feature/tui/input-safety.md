---
description: 'Input-safety contract for the local TUI control surface: operational bindings stay manual while paste and raw burst input are rejected outside text-entry surfaces.'
visibility: 'public'
---

# Input Safety — Spec

## Required reads

- @docs/local/design/architecture/tui-state-layout.md

## What it is

The TUI input-safety surface protects operational controls from clipboard
contents and raw key bursts that arrive in the TUI pane. It applies only to the
bare control surface: Sessions, Preparation, Jobs, footer/global bindings, and
other non-text-entry widgets. Text fields, modal popups, and config inline
editing surfaces remain paste-capable and receive key input without guard
buffering.

The contract has two layers. Bracketed paste events that reach the bare control
surface are blocked immediately and emit the standard paste-ignored
notification. Raw key input that looks like a rapid burst is held briefly and
then rejected as a group before any operational binding can fire. Quiet manual
command keys are released through Textual's normal key-dispatch path; the guard
does not invoke binding actions directly.

## Canonical fields

### Use cases

#### UC-TIS1: An operator uses the TUI without accidental actions from pasted or burst input

```gherkin
Scenario: Pasting on the bare control surface does not trigger an operation
  Given no modal, text field, or paste-safe widget is active
  When the operator pastes content into the TUI
  Then no pasted content triggers an operational binding
  And the paste-ignored notification is shown

Scenario: A rapid key burst does not trigger operations
  Given no modal, text field, or paste-safe widget is active
  When raw key input arrives as a rapid burst
  Then the burst is rejected as paste-like input
  And the paste-ignored notification is shown
  And none of its keys triggers an operational binding

Scenario: Ordinary manual command input remains available
  Given no modal, text field, or paste-safe widget is active
  When the operator enters ordinary command keys without a rapid burst
  Then the TUI processes them through its normal command behavior

Scenario: Text-entry surfaces accept operator input
  Given a text field, modal, or config inline editor is active
  When the operator types or pastes content
  Then that surface receives the input without paste-guard buffering or warning
```

#### UC-TIS2: Raw rapid bursts fail closed on the bare TUI surface

#### UC-TIS3: Quiet manual command keys keep working

#### UC-TIS4: Text inputs bypass the guard

#### UC-TIS5: Modal screens bypass the guard

#### UC-TIS6: Config inline editing bypasses the guard only while editing
