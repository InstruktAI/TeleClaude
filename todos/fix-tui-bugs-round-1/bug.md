# Bug:

## Symptom

### Previously selected session's agent colors incorreclty used for preview

Right now the selected agent session in the TUI node is not reflected onto the agent preview pane. There is some discrepancy. There is no tight coupling between the statefulness of the session selection and the preview pane colors. They are kept separately and not harmonized correctly. They should be tightly coupled. This leads to artifacts such as me watching one session in the preview, let's say from Claude. Claude has a nice coloring over the preview pane. Then when I start another session from the sessions pop up, and then that agent gets the color of the previous agent I was talking to, which is incorrect.

### Bugs discrepancy with expectations

Bugs are skaffolded to only have a `bug.md` and `state.yaml`, but I guess they also need more as they also go through the review process.
These missing files now also lead to incorrect interpretation of their state as bugs are now incorrrectly shown as `B:started` when their state.yaml says pending

Another issue is that I cannot start a bug because it expects a DOR score. This is potentially regression again because that was already solved. I'm sick and fucking tired of this fucking regression. I'm fucking pissed off about those things. So fuck fuck fuck. So I want to look at what is going wrong here, and I want to know how we can consolidate the best of these past commits and all of this stuff around this, because this is just going back and forth and back and forth. What the fuck?

### TUI not reloading correctly on SIGUSR 1/2

Right now when I change from light to dark mode and vice versa, there are glitches on the screen. The biggest glitch being that the background of the TUI pane is not changed.

### TUI session popup launches and preselects Claude by default, but when it is unavailable that should not be possible

## Discovery Context

Reported by: manual
Session: none
Date: 2026-02-24

## Investigation

<!-- Fix worker fills this during debugging -->

## Root Cause

<!-- Fix worker fills this after investigation -->

## Fix Applied

<!-- Fix worker fills this after committing the fix -->
