---
description: TUI Sessions-view row action gestures — the mouse and key gestures that
  preview, focus, revive, and close a session row, and the guarantee that closing
  a headless session does not revive it.
---

# Session Actions — Spec

## What it is

The TUI Sessions view turns row gestures into session-lifecycle actions. A single
click previews a session and focuses its pane; Shift-click previews without pane
focus; double-click toggles the row's sticky pane; the Option+Shift-click chord
fast-closes the clicked session. On a headless row — one with no live pane — a
plain click, Shift-click, Space, or Enter revives the session instead of
previewing it. The keyboard `k` binding closes the selected session through a
confirmation modal.

Close and revive are distinct destinations that must not fire from one gesture.
The fast-close chord routes to the session-close funnel; the headless-revive
gestures route to revival. Because a single physical chord can reach the row as
more than one input event, closing a headless session must not also revive it —
the fast-close chord and a same-session revive are mutually exclusive within the
gesture, so fast-closing a headless session behaves identically to the keyboard
`k` close: the session closes and is not revived.

## Canonical fields

### Use cases

#### UC-SACT-1: Fast-closing a headless session closes it without reviving

```
Given a headless session row in the TUI Sessions view
When the operator fast-closes it with the Option+Shift-click chord
Then the view requests exactly one close for that session
And the view requests no revive for that session
```

#### UC-SACT-2: An open session's pane remains inspectable during startup

```
Given a human operator selects an open session in the TUI Sessions view
And the session has a bound host pane
When the operator requests a preview or pane focus
Then the view opens that pane regardless of whether the agent has started
And the operator can inspect startup prompts, errors, and a returned shell
And opening the pane does not report the agent as active
```

A new session remains listed while its host pane is being created. A pending
selection is retained until the pane is bound; it does not trigger headless
revival or wait for the agent's first runtime event.

#### UC-SACT-3: Plain-clicking a headless session revives it

```
Given a headless session row in the TUI Sessions view
When the operator plain-clicks that row
Then the view requests exactly one revive for that session
And the view requests no preview for that session
And the view requests no close for that session
```
