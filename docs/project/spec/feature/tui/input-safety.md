---
description: 'Input-safety contract for the local TUI control surface: operational bindings stay manual while paste and raw burst input are rejected outside text-entry surfaces.'
visibility: 'public'
---

# Input Safety — Spec

## Required reads

- @docs/project/design/architecture/tui-state-layout.md

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

#### UC-TIS1: Bracketed paste is blocked on the bare TUI surface

```
Given no modal, text field, or paste-safe widget is active
When a bracketed paste event reaches the TUI app
Then the event is stopped before default handling
And the paste-ignored notification is shown
And no pasted content is dispatched to operational bindings
```

#### UC-TIS2: Raw rapid bursts fail closed on the bare TUI surface

```
Given no modal, text field, or paste-safe widget is active
When more than two raw key events arrive inside the burst window
Then the buffered keys are dropped as paste-like input
And the paste-ignored notification is shown
And no buffered key is replayed into operational bindings
```

#### UC-TIS3: Quiet manual command keys keep working

```
Given no modal, text field, or paste-safe widget is active
When one or two raw command keys arrive without crossing the burst threshold
Then the guard releases those keys after the burst window
And the released keys continue through Textual's normal key dispatch
And the guard does not manually invoke active bindings
```

#### UC-TIS4: Text inputs bypass the guard

```
Given a Textual input field is focused
When key or paste input reaches the TUI app
Then the input bypasses paste-guard buffering
And the TUI app does not stop or warn on the event
```

#### UC-TIS5: Modal screens bypass the guard

```
Given a modal screen is open
When key or paste input reaches the TUI app
Then the input bypasses paste-guard buffering
And the TUI app does not stop or warn on the event
```

#### UC-TIS6: Config inline editing bypasses the guard only while editing

```
Given the config view owns a paste-safe inline edit buffer
When the inline edit buffer is active
Then key and paste input bypass paste-guard buffering
And when the inline edit buffer is inactive
Then the config view is treated like the bare control surface
```
