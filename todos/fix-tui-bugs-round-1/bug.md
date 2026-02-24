# Bug:

## Symptom

### Previously selected session's agent colors incorreclty used for preview

Right now the selected agent session in the TUI node is not reflected onto the agent preview pane. There is some discrepancy. There is no tight coupling between the statefulness of the session selection and the preview pane colors. They are kept separately and not harmonized correctly. They should be tightly coupled. This leads to artifacts such as me watching one session in the preview, let's say from Claude. Claude has a nice coloring over the preview pane. Then when I start another session from the sessions pop up, and then that agent gets the color of the previous agent I was talking to, which is incorrect.

### Bugs discrepancy with expectations

Bugs are skaffolded to only have a `bug.md` and `state.yaml`, but I guess they also need more as they also go through the review process.
These missing files now also lead to incorrect interpretation of their state as bugs are now incorrrectly shown as `B:started` when their state.yaml says pending

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
