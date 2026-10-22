---
description: Local preview intent and observed viewer identity survive data updates
  and intact reloads while session attachment facts remain daemon-projected.
visibility: internal
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
Background refresh preserves the active artifact's reading position. A changed,
resolved destination replaces only the affected session's viewer; other
surviving viewers retain their identity and placement. When attachment inputs
are unavailable or unresolved, no new viewer appears; any wanted surviving
viewer stays visible and the existing local intent remains.

### Use cases

#### UC-VC1: An operator keeps the chosen preview while the TUI updates

```gherkin
Scenario: Keep the chosen artifact in place during background updates
  Given a human operator is reading an artifact beside a chosen session viewer
  When background updates reach the TUI without an operator routing action
  Then the artifact remains the active preview
```

#### UC-VC2: An operator restores the intended viewer arrangement after reload

```gherkin
Scenario: An intact reload restores the existing arrangement
  Given a human operator reads an artifact beside pinned session viewers
  And the surviving viewer layout already matches the operator's current intent
  When the TUI reloads
  Then it adopts those viewers with their identities and reading positions intact
  And it leaves their existing placement intact

Scenario: Recovery retains a viewer until its owner can be reconciled
  Given a human operator's TUI reload discovers surviving viewers
  When a viewer's owner is known
  Then the viewer is reconciled with the operator's current intent on that pass
  And a viewer whose owner remains unknown is preserved until its owner resolves or its pane disappears
```

#### UC-VC3: Unavailable attachment does not churn or erase intent

#### UC-VC4: A wanted surviving viewer tolerates incomplete attachment inputs

#### UC-VC5: Changed resolved destination replaces only its viewer

#### UC-VC6: Recovery distinguishes known owners from missing information
