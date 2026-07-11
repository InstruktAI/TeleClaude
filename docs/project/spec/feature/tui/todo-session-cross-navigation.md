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

A single shared **human filter** lets the operator click any chip to narrow the
view to that person's work; the same setting is honored by both views.

The owning human is resolved from data already present: a todo's
`created_by_principal` (`human:<email>`) and a session's `human_email`, both
mapped to a person — and thus to initials and chip colors — through the identity
resolver. A session's work slug is its `working_slug`, present for orchestrator
and worker roles alike. The chip's colors come from the per-person overlay
schema documented in `project/spec/feature/config/person-chip-color`; this spec
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

A rendering invariant governs every chip and every highlighted span: **the
styled span contains only its own content — never a leading or trailing space.**
Separating whitespace is rendered in the base style, outside the styled region.

<!-- planned:tui-creator-session-link -->

An agent-originated todo may also expose the session that created it in the
expanded todo details. The creator-session row is a navigation affordance, not
an authorship claim: it renders only when the todo creation lineage carries an
acting TeleClaude session id, and it lets the operator jump to or revive that
session from the Preparation view.

On a todo row, the state column contains the schedule badge, the
autonomous-creation marker when present, the owner chip, and the hold glyph.
<!-- /planned:tui-creator-session-link -->

## Canonical fields

### Use cases

#### UC-XNAV-1: Chip color resolves with theme-default fallback

```
Given a person whose color.background.dark and color.text.dark are unset
And the active theme is dark mode
When the person's chip is rendered
Then the background uses the theme subtle-grey default (the low-contrast stop nearest the terminal background)
And the text uses the theme highlight default (white)
And a set cell, when present, is used instead of the default
```

#### UC-XNAV-2: Todo author chip resolves from created_by_principal

```
Given a todo whose created_by_principal is "human:alice@example.com"
And alice is a registered person named "Alice Smith"
When the todo row is rendered
Then the chip shows the uppercase initials "AS"
And the chip colors resolve from alice's PersonConfig.color
```

#### UC-XNAV-3: Session human chip resolves from human_email

```
Given an agent session whose human_email is "alice@example.com"
When the session row title line is rendered
Then a chip shows alice's initials after the agent/mode segment
And the chip colors resolve from alice's PersonConfig.color
```

#### UC-XNAV-4: Unresolvable human renders no chip

```
Given a todo with a null created_by_principal, or a principal whose email matches no registered person
When the row is rendered
Then no chip is rendered
And the row layout closes the gap rather than reserving chip width
```

#### UC-XNAV-5: Session work slug is one highlighted component

```
Given an orchestrator session with working_slug "config-public-surface-contract"
And title "/next-work config-public-surface-contract"
When the session row title line is rendered
Then the slug is rendered once as a single highlighted span
And the slug token is stripped from the title text so it is not duplicated
And the title carries no surrounding quotes
And the rendered line reads: [N] ▶ claude/med <chip> /next-work config-public-surface-contract
```

#### UC-XNAV-6: Worker rows render identically to orchestrator rows

```
Given a worker session with working_slug "config-public-surface-contract"
And title "/next-build config-public-surface-contract"
When the session row title line is rendered
Then it uses the same chip + command + single highlighted slug layout as an orchestrator row
And the slug appears once with no duplication and no double-space before the command tail
And the rendered line reads: [N] ▶ claude/med <chip> /next-build config-public-surface-contract
```

#### UC-XNAV-7: Sessions without a work slug render no slug component

```
Given a session whose working_slug is null (e.g. an integrator or shell session)
When the session row title line is rendered
Then no highlighted slug span is rendered
And the title renders as-is without quotes
```

#### UC-XNAV-8: Highlighted spans carry no padding

```
Given any chip or highlighted slug span on any row
When the span is rendered
Then the styled region contains only its own glyphs
And any separating space sits outside the styled region in the base style
```

#### UC-XNAV-9: Claimed todo text columns render bold and clickable

```
Given a todo whose active_runner is a live session id
When the todo row columns are rendered
Then the text status columns (K, P/I, B, R, D) render bold
And each carries a click target that jumps to the active_runner session
```

#### UC-XNAV-10: Unclaimed todo text columns render normal and inert

```
Given a todo with no active_runner
When the todo row columns are rendered
Then the text status columns render at normal weight
And they carry no jump click target
```

#### UC-XNAV-11: The state column is excluded from the claim regime

```
Given a claimed todo
When the row is rendered
Then the row status glyph and the state column (schedule badge, owner chip, hold glyph) are neither bold-toggled by the claim nor made claim-clickable
And they retain their own semantic color and weight (the schedule badge gold and bold, the hold glyph gold)
```

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

#### UC-XNAV-14: Clicking a chip sets the shared human filter

```
Given no human filter is active
When the operator clicks a person chip in the active view
Then the shared human filter is set to that person
And the active view shows only rows belonging to that person
And the clicked person's chip renders with inverted colors
And rows with no matching human are hidden
```

#### UC-XNAV-15: Clicking the active chip clears the filter

```
Given a human filter is active
When the operator clicks the (inverted) chip of the filtered person
Then the shared human filter is cleared
And the full set of rows is restored
And chips render in their normal (non-inverted) colors
```

#### UC-XNAV-16: The human filter is one shared, persisted setting

```
Given the operator set the human filter while in one view
When the operator switches to the other participating view
Then the same human filter is already applied there
And the setting is persisted once as a single source of truth across both views and process restarts
```

#### UC-XNAV-17: Chip weight tracks selection; highlight snaps to the extreme

```
Given a person chip on a row
When the row is selected or previewed
Then the chip renders bold
And its text takes the row's selection pole (black in dark mode, white in light)
And a neutral chip's background is the opposite pole while a custom chip keeps its hue
And this holds even when the chip's person is also the live filter (selection dominates)
```

#### UC-XNAV-18: An active-filter chip takes the extreme without bold

```
Given the chip's person is the live filter and its row is not selected or previewed
When the chip is rendered
Then its text takes the row's selection pole (black in dark mode, white in light) over a pole/hue fill, identical to the highlighted chip's colors
And its weight stays normal (weight is reserved for selection)
```

<!-- planned:tui-creator-session-link -->

#### UC-XNAV-19: Autonomous marker renders only for no-human agent creation

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

#### UC-XNAV-20: Creator-session row renders only from creation lineage

```
Given a todo whose creation lineage carries an acting TeleClaude session id
When the todo is expanded in the Preparation view
Then the first detail row reads "created in: <session_id>"
And no native session id is rendered
```

```
Given a todo whose creation lineage carries no acting TeleClaude session id
When the todo is expanded in the Preparation view
Then no creator-session detail row is rendered
```

#### UC-XNAV-21: Live creator session jumps directly

```
Given an expanded todo renders "created in: <session_id>"
And the creator session is live in the TUI session cache
When the detail row is rendered
Then the session id is bold
And clicking the session id activates the Sessions tab
And selects and previews that session
```

#### UC-XNAV-22: Retained closed creator session offers revive

```
Given an expanded todo renders "created in: <session_id>"
And the creator session is closed but still retained in the agent_runtime session ledger
When the detail row is rendered
Then the session id is normal weight
And the row appends " - revive"
And "revive" is bold and clickable
When the operator clicks "revive"
Then the TUI revives the TeleClaude session by that session id
And activates the Sessions tab
And waits until the revived session is attachable before selecting and previewing it
```

#### UC-XNAV-23: Hard-deleted creator session is inert

```
Given an expanded todo renders "created in: <session_id>"
And the creator session no longer exists in the agent_runtime session ledger
When the detail row is rendered
Then the row renders only "created in: <session_id>"
And no revive affordance is rendered
And no native session id fallback is rendered
```

<!-- /planned:tui-creator-session-link -->

## Known caveats

- **Legacy todos show no chip.** Todos created before `created_by_principal`
  was stamped carry a null principal; they render chip-less and are hidden while
  any human filter is active.
- **Single-active filter is emergent, not enforced.** While a filter is active,
  only the filtered person's chips are visible, so no second person's chip is
  reachable to click — the shared setting holds exactly one person or none.

## See Also

- docs/project/spec/feature/config/person-chip-color.md — the PersonConfig.color
  overlay schema (the four optional background/text × light/dark cells) this
  spec renders.
