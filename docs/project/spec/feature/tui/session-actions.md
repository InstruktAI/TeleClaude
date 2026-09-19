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

Three keyboard gestures hand a session to a different agent. `o` on a session
row hands that session off with the successor chosen automatically; `o` on a
project header asks the operator to choose an agent and hands off every live
session of that project currently running on it; `O` on a session row opens the
existing start-session modal with the session fixed and the agent selector live,
so the operator names the successor. The handoff itself is owned by
`project/spec/feature/agent_runtime/agent-handoff`; the view only requests it.

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

#### UC-SACT-4: Pressing `o` on a session row hands the session off automatically

```gherkin
Given a human operator selects a session row in the TUI Sessions view
When the operator presses `o`
Then the view requests exactly one handoff for that session with no successor named
And the view requests no restart, revive, preview, or close for that session
And the operator is told which successor was selected or why the handoff was refused
```

#### UC-SACT-5: Pressing `o` on a project header hands off every live session on a chosen agent

```gherkin
Given a human operator selects a project header in the TUI Sessions view
When the operator presses `o`
Then the view asks the operator to choose an agent
And on confirmation the view requests one handoff with no successor named for every live session of that project running on the chosen agent
And sessions running on other agents and closed sessions receive no request
And dismissing the choice sends no request
```

#### UC-SACT-6: Pressing `O` on a session row opens the start-session modal for an explicit successor

```gherkin
Given a human operator selects a session row in the TUI Sessions view
When the operator presses `O`
Then the existing start-session modal opens with the session fixed and the agent selector live
And confirming with an agent chosen requests exactly one handoff for that session naming that agent
And dismissing the modal sends no request
```

<!-- planned:session-handoff-state-convergence -->
#### UC-SACT-7: A handoff refreshes the visible session row without another gesture

```gherkin
Given the TUI displays a session row and its attached or sticky pane
When a session update reports that a handoff successor is now the active agent
Then the row displays the successor and the session's current thinking mode
And the operator does not need to reselect the row or reload the TUI
```
<!-- /planned:session-handoff-state-convergence -->
