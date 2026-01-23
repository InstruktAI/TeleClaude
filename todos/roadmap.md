# Roadmap

> **Last Updated**: 2026-01-16
> **Status Legend**: `[ ]` = Pending | `[.]` = Ready | `[>]` = In Progress
> (DONE work is tracked in [delivered.md](./delivered.md))

---

## TUI Asccii banner

- [ ] tui-ascii-banner:

I want the letters of the ASCII banner to rotate their colors like the rainbow. And it should be a routine. And I want that routine also to be having random patterns. So let's say some of them start on the inside of the word and fan out to the outside. Some of them start on the left and then they wave to the right and from right to left. And sometimes it's just the word tella blinking and clawed blinking. There are also some animations that involve only the agent colors. So it can demonstrate activity of one agent type. Codex, Claude, or Gemini. I envision blinking word on off the normal foreground color to the agent color. And using the three agent colors from muted normal and highlight. So it can fade in and fade out, or wave its colors from left or right. So I have now already given you enough input for many different animations, and I want you to complete this list and make it into a matrix that shows on one dimension whether they are general animations or agent specific animations. All of these animations involving colors should take into account that when they are triggered for an agent that they will be given only that agent color palette and use that for their animations, which means they are likely having to deal with the number of colors in the spectrum in order to cycle through that or take random colors from that. So anything related any animation involving colors should just be built against the set of colors it is given. But could of course involve all animations. Do you get what I'm after?
The routine will be activated randomly once every minute with ALL colors, and when there is session activity detected on the web socket using just the AGENT colors.

## Test Suite Quality Cleanup

- [ ] repo-cleanup

Refactor test suite to verify observable behavior, add docstrings, document system boundaries.
