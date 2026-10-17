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

Three keyboard gestures request handoff only for open sessions. `o` on an open
session row requests automatic successor selection; `o` on a project header
asks the operator to choose a source agent and requests handoff for every open
session of that project currently running on it; `O` on an open session row
opens a handoff form containing only the successor selector. Closed rows receive
no handoff request. The view reports request acceptance as started, never as
completed, and the handoff itself remains owned by
`local/projects/teleclaude/spec/feature/agent_runtime/agent-handoff`.

Every row belongs to one computer, and the actions taken from it address that
computer alone. `R` on a project header restarts the sessions of that project on
the header's computer; a project at the same path on another computer is another
row. Starting a session by path on another computer sends the entered path
without judging it on the computer running the TUI: the computer that runs the
session decides and answers
(`local/projects/teleclaude/spec/feature/integration/computer-addressed-execution`).

Close and revive are distinct destinations that must not fire from one gesture.
The fast-close chord routes to the session-close funnel; the headless-revive
gestures route to revival. Because a single physical chord can reach the row as
more than one input event, closing a headless session must not also revive it —
the fast-close chord and a same-session revive are mutually exclusive within the
gesture, so fast-closing a headless session behaves identically to the keyboard
`k` close: the session closes and is not revived.

## Canonical fields

### Use cases

#### UC-SACT-1: An operator closes a headless session without reopening it

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

#### UC-SACT-3: An operator returns to a headless session

```
Given a headless session row in the TUI Sessions view
When the operator plain-clicks that row
Then the view requests exactly one revive for that session
And the view requests no preview for that session
And the view requests no close for that session
```

#### UC-SACT-4: An operator hands an open session to an automatic successor

```gherkin
Given a human operator selects an open session row in the TUI Sessions view
When the operator presses `o`
Then the view requests exactly one handoff for that session with no successor named
And the view requests no restart, revive, preview, or close for that session
And the operator is told which successor was selected and that handoff started
And a closed session row receives no handoff request
```

#### UC-SACT-5: An operator hands off a project's live sessions from a chosen agent

```gherkin
Given a human operator selects a project header in the TUI Sessions view
When the operator presses `o`
Then the view asks the operator to choose an agent
And on confirmation the view requests one handoff with no successor named for every live session of that project running on the chosen agent
And sessions running on other agents and closed sessions receive no request
And dismissing the choice sends no request
```

#### UC-SACT-6: An operator directs a handoff to a chosen successor

```gherkin
Given a human operator selects an open session row in the TUI Sessions view
When the operator presses `O`
Then a handoff form opens with the session fixed and only the agent selector and action buttons visible
And confirming with an agent chosen requests exactly one handoff for that session naming that agent
And dismissing the modal sends no request
And a closed session row opens no handoff form
```

#### UC-SACT-7: An operator sees the new successor after handoff

```gherkin
Given an operator has handed off a session displayed in the TUI
When the successor takes over that session
Then the row displays the successor and the session's current thinking mode
And any attached or sticky pane uses the successor's agent palette
And the operator sees the updated session without reselecting the row or reloading the TUI
```

#### UC-SACT-8: An operator restarts a project's sessions on one computer

```gherkin
Given a human operator selects a project header under one computer in the TUI Sessions view
And another computer has sessions in a project at the same path
When the operator presses `R`
Then the confirmation counts only the sessions of that project on the header's computer
And on confirmation the view requests one restart for each of those sessions, addressed to that computer
And sessions on any other computer receive no request
```

#### UC-SACT-9: An operator starts a session by path on another computer

```gherkin
Given a human operator opens the start-session form in path mode for a computer other than the one running the TUI
When the operator enters a path and confirms
Then the view sends the path as entered to that computer without checking it on the computer running the TUI
But for the computer running the TUI, a path that is not a directory there is refused in the form and no request is sent
```
