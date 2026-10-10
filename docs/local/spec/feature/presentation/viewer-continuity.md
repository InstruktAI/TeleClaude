---
description: Local preview intent and observed viewer identity survive data updates and intact reloads while session attachment facts remain daemon-projected.
visibility: internal
delivered_by:
  - stabilize-tui-viewers
---

# Viewer Continuity — Spec

## What it is

Presentation holds one local preview intent: a session, an artifact, or none.
The session view, bridge, and reload reconciliation consume that same intent.
The pane renderer compares it with observed viewer identity and placement.
Background state changes update the displayed facts without choosing another
preview on the operator's behalf.

Session attachment facts come from
`local/projects/teleclaude/spec/feature/integration/viewer-attachment-projection`;
the local renderer creates viewers from those answers and preserves wanted
surviving viewers. `sdlc/policy/domain-ownership` governs that separation.
The interaction, sticky selection, and close gestures remain governed by
`local/projects/teleclaude/design/ux/session-preview-sticky` and
`local/projects/teleclaude/spec/feature/tui/session-actions`.

## Canonical fields

Preview intent and observed pane placement are local presentation state.
Fresh attachment availability and destination are published facts. Logical
preview and sticky intent survive a temporarily unavailable rendered viewer;
the published closure or an explicit operator action releases that intent.

### Use cases

#### UC-VC1: An artifact survives background refresh

```gherkin
Given a human operator opens an artifact after previewing a session
When resource refreshes or unrelated session changes reach the TUI without an operator routing action
Then the artifact remains the active preview
And its viewer keeps its identity and reading position
```

#### UC-VC2: An intact reload preserves viewer placement

```gherkin
Given a human operator reads an artifact beside any pinned session viewers
And the surviving viewer layout already matches the operator's current intent
When the TUI reloads
Then it adopts those viewers with their identities and reading positions intact
And it leaves their existing placement intact
```

#### UC-VC3: Unavailable attachment does not churn or erase intent

```gherkin
Given a human operator has a session selected or pinned
When its existing viewer disappears and the daemon's current attachment answer permits no fresh viewer
Then background updates create no replacement attachment for that session
And the operator's local selection or pin is retained until explicit release or confirmed closure
```

#### UC-VC4: A wanted surviving viewer tolerates incomplete attachment inputs

```gherkin
Given a human operator has a live viewer they still want to inspect
When the daemon's projected fresh-attachment inputs are unavailable or unresolved
Then that surviving viewer remains visible
And the TUI preserves the operator's local intent
```

#### UC-VC5: Changed resolved destination replaces only its viewer

```gherkin
Given a human operator views several sessions
And the daemon admits a fresh attachment for the affected session
When the daemon supplies a changed resolved attachment destination for one of them
Then the TUI replaces only the affected viewer's attachment
And the other surviving viewers retain their identities
```

#### UC-VC6: Recovery distinguishes known owners from missing information

```gherkin
Given a human operator's TUI reload discovers surviving viewers
When the current projection identifies a viewer's owner
Then that viewer is reconciled with the operator's current intent on that pass
And a viewer whose owner remains unknown is preserved until its owner resolves or its pane disappears
```
