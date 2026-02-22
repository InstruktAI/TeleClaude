# Bug: Agent theme primary/secondary set to Claude brown — leaks into Textual default active/focus/hover states for all agents. Two fixes: (1) Replace Claude-specific primary/secondary in teleclaude-dark-agent and teleclaude-light-agent with neutral grays matching the neutral theme variants. (2) Eliminate all implicit Textual framework active/focus/hover/double-click states in TCSS — we have our own tree navigation, highlights, and selection UX. No Textual default interaction styling should ever be visible.

## Symptom

Agent theme primary/secondary set to Claude brown — leaks into Textual default active/focus/hover states for all agents. Two fixes: (1) Replace Claude-specific primary/secondary in teleclaude-dark-agent and teleclaude-light-agent with neutral grays matching the neutral theme variants. (2) Eliminate all implicit Textual framework active/focus/hover/double-click states in TCSS — we have our own tree navigation, highlights, and selection UX. No Textual default interaction styling should ever be visible.

## Discovery Context

Reported by: manual
Session: none
Date: 2026-02-22

## Investigation

**Evidence gathered:**

1. **Agent themes use Claude-specific colors** (`theme.py:420-452`):
   - Dark agent: `primary="#d7af87"` (Claude orange), `secondary="#af875f"` (Claude brown)
   - Light agent: `primary="#875f00"` (Claude brown), `secondary="#af875f"` (Claude brown)

2. **Neutral themes use grays** (`theme.py:323-418`):
   - Dark: `primary="#808080"`, `secondary="#626262"`
   - Light: `primary="#808080"`, `secondary="#9e9e9e"`

3. **TCSS coverage** (`telec.tcss`):
   - Good suppression for `:hover`, `:focus`, `:focus-within` (lines 20-43)
   - Explicit styling for Button, Input, Select (lines 232-278)
   - Missing: `:active` state suppression for mouse-down interactions

## Root Cause

The agent theme variants (`teleclaude-dark-agent`, `teleclaude-light-agent`) used Claude-specific brown/orange colors for `primary` and `secondary`. When Textual framework widgets don't have explicit style overrides, they fall back to these theme colors for default interaction states (hover, focus, active). This caused Claude browns to leak into UI chrome for ALL agents, not just Claude sessions.

The TCSS file had good coverage for `:hover` and `:focus` suppression, but was missing `:active` state suppression, allowing mouse-down interactions to potentially show default Textual styling.

## Fix Applied

**1. Neutralized agent theme colors** (`teleclaude/cli/tui/theme.py`):

- `_TELECLAUDE_DARK_AGENT_THEME`: Changed `primary` from `#d7af87` to `#808080`, `secondary` from `#af875f` to `#626262`
- `_TELECLAUDE_LIGHT_AGENT_THEME`: Changed `primary` from `#875f00` to `#808080`, `secondary` from `#af875f` to `#9e9e9e`
- Now matches neutral theme colors exactly

**2. Suppressed `:active` states** (`teleclaude/cli/tui/telec.tcss`):

- Added `Widget:active { background: transparent; }` to global suppression section (line 28-30)
- Completes coverage of all Textual framework default interaction states
