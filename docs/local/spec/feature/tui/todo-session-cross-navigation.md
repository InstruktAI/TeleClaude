---
description: Author/human chips, claim-state highlighting, and bidirectional todo↔session
  navigation in the TUI, with a shared per-human filter resolved from todo and session
  ownership.
---

# Todo–Session Cross-Navigation — Spec

## What it is

The TUI surfaces the human behind each unit of work and lets the operator move
between a todo and the agent session driving it without hunting by session id.
Two row families participate: todo rows in the Preparation view and agent
session rows in the Sessions view. Each row carries a **person chip** — the
uppercase initials of its owning human, painted in that human's configured
colors. A claimed todo (one with a live `active_runner`) renders its text status
columns boldly and turns them into a one-click jump to the runner session; a
session row turns its work slug into a one-click jump back to that todo.
Without a live `active_runner`, those columns remain normal and have no jump.
Claim styling and its jump affordance apply only to the text status columns;
the schedule badge, autonomous-creation marker, owner chip, and hold glyph keep
their own visual rules.

A single shared **human focus** lets the operator click any chip to narrow the
Preparation view to that person's work and highlights that person's chips in
both views. The Sessions view always retains every open session, including
ownerless sessions; human focus never becomes a second session-visibility rule.

The owning human is resolved from data already present: a todo's
`created_by_principal` (`human:<email>`) and a session's `human_email`, both
mapped to a person — and thus to initials and chip colors — through the identity
resolver. A session's work slug is its `working_slug`, present for orchestrator
and worker roles alike. The chip's colors come from the per-person overlay
schema documented in `local/projects/teleclaude/spec/feature/config/person-chip-color`; this spec
governs how those cells are rendered, including the theme-derived defaults for
unset cells. The resting chip is a low-contrast fill — the theme `subtle`
background (the stop nearest the terminal background) under `highlight` text.
Weight encodes selection alone: the chip is bold only while its row is selected
or previewed, normal weight otherwise. Color encodes the rest: a highlighted
chip takes the row's selection text pole (black in dark mode, white in light)
over its fill — a custom hue kept, a neutral chip using the opposite pole (the
sticky-badge look). The same extreme applies whenever the chip is active — its
person is the live filter (on) or its row is highlighted — and only the weight
differs: bold under selection, normal under the filter alone.
On a todo row the chip occupies a dedicated state column (next-to-last, before
the hold column); on a session row it sits just after the agent/mode segment.
When no registered person resolves, no person chip is rendered and its column
space is not reserved.
Each present work slug is shown once in one highlighted component in the
session's command tail; a session with no work slug has no slug component.

A rendering invariant governs every chip and every highlighted span: **the
styled span contains only its own content — never a leading or trailing space.**
Separating whitespace is rendered in the base style, outside the styled region.

An agent-originated todo may also expose the session that created it in the
expanded todo details. The creator-session row is a navigation affordance, not
an authorship claim: it renders only when the todo creation lineage carries an
acting TeleClaude session id, and it lets the operator jump to or revive that
session from the Preparation view. Provenance detail rows remain mouse-clickable
but do not become keyboard selection stops in the Preparation tree.

On a todo row, the state column contains the schedule badge, the
autonomous-creation marker when present, the owner chip, and the hold glyph.

## Canonical fields

### GitHub issue navigation

A session assigned to a GitHub issue shows the assigned issue number as a
separate clickable span beside its work subject. Clicking that number opens the
assigned issue URL in the default browser. The slug retains its existing
styling, click region, and navigation behavior. The issue link consumes only
clicks inside the number's own span.

Issue identity comes from the session's structured assignment, carried by its
owning computer in the session snapshot. Digits in a title or slug do not
establish a GitHub assignment. A session without a GitHub issue reference shows
no issue-number link.

### Use cases

#### UC-XNAV-1: Chip color resolves with theme-default fallback

#### UC-XNAV-2: Todo author chip resolves from created_by_principal

#### UC-XNAV-3: Session human chip resolves from the session's lineage root

#### UC-XNAV-4: Unresolvable human renders no chip

#### UC-XNAV-5: Session work slug is one highlighted component

#### UC-XNAV-6: Worker rows render identically to orchestrator rows

#### UC-XNAV-7: Sessions without a work slug render no slug component

#### UC-XNAV-8: Highlighted spans carry no padding

#### UC-XNAV-9: Claimed todo text columns render bold and clickable

#### UC-XNAV-10: Unclaimed todo text columns render normal and inert

#### UC-XNAV-11: The state column is excluded from the claim regime

#### UC-XNAV-12: Clicking a claimed text column jumps to the session

```
Given a claimed todo row is displayed in the Preparation view
When the operator clicks one of its bold text status columns
Then the TUI activates the Sessions tab
And selects and previews the active_runner session
```

#### UC-XNAV-13: Clicking a session slug jumps to the todo

```
Given a session row with a highlighted work slug is displayed in the Sessions view
When the operator clicks the slug span
Then the TUI activates the Preparation tab
And selects the todo whose slug matches the work slug
```

#### UC-XNAV-14: An operator focuses the Preparation view on a person's work

```
Scenario: The operator filters to a person's work
  Given no human filter is active
  When the operator chooses a person's owner chip
  Then the Preparation view shows only rows belonging to that person
  And the Sessions view continues to show every open session, including rows with no human

Scenario: The operator clears the active person filter
  Given a human filter is active
  When the operator chooses the filtered person's owner chip again
  Then the full set of Preparation rows is restored
  And the Sessions view continues to show every open session

Scenario: The operator's human focus is shared and retained
  Given the operator has set a human filter in either view
  When the operator switches views or restarts the TUI
  Then the same focus is reflected in both views and remains selected
  And each view retains its own visibility contract
```

#### UC-XNAV-15: Clicking the active chip clears the filter

#### UC-XNAV-16: The human filter is one shared, persisted setting

#### UC-XNAV-17: Chip weight tracks selection; highlight snaps to the extreme

#### UC-XNAV-18: An active-filter chip takes the extreme without bold

#### UC-XNAV-19: An operator recognizes work created without human involvement

```
Given a todo whose creation record has entry_point="agent"
And human_involved=false
When the todo row is rendered
Then the state column renders the autonomous-creation marker beside the owner chip
```

```
Given a todo whose creation record has human_involved=true
When the todo row is rendered
Then the state column renders no autonomous-creation marker
```

```
Given a todo whose creation record has entry_point other than "agent"
When the todo row is rendered
Then the state column renders no autonomous-creation marker
```

#### UC-XNAV-20: An operator returns to the session that created a todo

```
Given a todo whose creation lineage carries an acting TeleClaude session id
When the operator expands it to find the session that created it
Then the first detail row reads "created in: <session_id>"
And no native session id is rendered
```

```
Given a todo whose creation lineage carries no acting TeleClaude session id
When the todo is expanded in the Preparation view
Then no creator-session detail row is rendered
```

```gherkin
Scenario: A live creator session opens directly
  Given an expanded todo shows the session that created it
  And that creator session is live in the TUI session cache
  When the operator chooses its session id
  Then the Sessions tab opens with that session selected and previewed

Scenario: A retained closed creator session can be revived
  Given an expanded todo shows the session that created it
  And that creator session is closed but still retained
  When the operator chooses its revive affordance
  Then the TUI revives the TeleClaude session by its session id
  And opens the Sessions tab and selects and previews it once attachable

Scenario: An absent creator session has no revive action
  Given an expanded todo shows the session that created it
  And that creator session no longer exists in the session ledger
  When the operator views its provenance row
  Then the session id remains visible without a revive affordance or native-id fallback

Scenario: A retained creator session remains revivable beyond the listing window
  Given an expanded todo shows a creator session that closed before the closed-session listing window
  And that session is still retained
  When the operator views its provenance row
  Then the row offers the same revive action as any retained closed session
```

#### UC-XNAV-21: Live creator session jumps directly

#### UC-XNAV-22: Retained closed creator session offers revive

#### UC-XNAV-23: Hard-deleted creator session is inert

#### UC-XNAV-24: An operator returns to the session that prepared a todo

```gherkin
Given a todo whose preparation provenance carries a TeleClaude session id
When the operator expands it to find the session that prepared it
Then the detail row immediately after the creator-session row reads "prepped in: <session_id>"
And no native session id is rendered

Given a todo whose preparation provenance carries no TeleClaude session id
When the operator expands it to find the session that prepared it
Then no prepared-session detail row is rendered
```

```gherkin
Scenario: A preparation session can be reached according to its liveness
  Given an expanded todo shows the session that prepared it
  When that session is live, retained closed, or absent from the ledger
  Then the row offers direct navigation, revive, or an inert session id, respectively
  And its action matches the creator-session row for the same liveness state

Scenario: Re-preparation identifies the latest completing session
  Given a todo was prepared in one TeleClaude session
  And later re-enters preparation because its prepared contract changed
  When another TeleClaude session completes preparation
  Then the prepared-session detail row identifies the later completing session
```

#### UC-XNAV-25: Prepared-session navigation follows session liveness

#### UC-XNAV-26: Session metadata rows do not consume keyboard navigation

#### UC-XNAV-27: An operator checks an artifact's recency before opening it

```gherkin
Given an operator expands a todo with a stored artifact that has a last-edited timestamp
When the operator reviews the artifact row in the Preparation view
Then the row shows when the artifact was last edited in local time and date
And the operator can select and open that artifact
```

#### UC-XNAV-28: Re-preparation identifies the latest completing session

#### UC-XNAV-29: An operator recognizes work owned by the system

```
Given a human operator is viewing work whose lineage roots at a system principal
When the ownership row appears
Then a chip showing the single letter "S" is rendered in the chip's place
And the chip carries no person's colors and does not act as a person filter
```

#### UC-XNAV-30: An operator spots sessions needing attention

```
Given a human operator is scanning session rows in the TUI
And one session is blocked or stalled
When the operator looks for sessions needing attention
Then the blocked row has an orange leading marker and the stalled row has a red leading marker
And active, idle, and unknown rows have no attention marker
And the rest of each row stays aligned with or without the marker
```

#### UC-XNAV-31: Provenance session state is resolved by id, independent of any listing window

#### UC-XNAV-32: Open the assigned GitHub issue from a session row

```gherkin
Given a human operator views a session assigned to a GitHub issue
When the operator clicks the session's displayed issue number
Then the assigned issue opens in the default browser
And the slug retains its existing navigation behavior
```

## Known caveats

- **Legacy todos show no chip.** Todos created before `created_by_principal`
  was stamped carry a null principal; they render chip-less and are hidden from
  the Preparation view while any human filter is active. Ownerless session rows
  remain visible.
- **Single-active filter is emergent, not enforced.** While a filter is active,
  only the filtered person's chips are visible, so no second person's chip is
  reachable to click — the shared setting holds exactly one person or none.

## See Also

- docs/local/spec/feature/config/person-chip-color.md — the PersonConfig.color
  overlay schema (the four optional background/text × light/dark cells) this
  spec renders.
