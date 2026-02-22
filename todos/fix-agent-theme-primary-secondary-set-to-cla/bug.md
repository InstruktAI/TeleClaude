# Bug: Agent theme primary/secondary set to Claude brown colors — leaks into Textual default active/focus/hover states for all agents. Two fixes required: (1) Replace Claude-specific primary/secondary in teleclaude-dark-agent and teleclaude-light-agent themes with neutral grays matching the neutral theme variants. Dark agent: dark gray close to surface. Light agent: light gray close to surface. (2) Eliminate all implicit Textual framework active/focus/hover/double-click states in TCSS. We have our own tree navigation, highlights, and selection UX. Textual built-in $primary/$secondary-based states on widgets are unwanted artifacts. Override them all to be invisible or match our neutral surface colors. No Textual default interaction styling should ever be visible.

## Symptom

Agent theme primary/secondary set to Claude brown colors — leaks into Textual default active/focus/hover states for all agents. Two fixes required: (1) Replace Claude-specific primary/secondary in teleclaude-dark-agent and teleclaude-light-agent themes with neutral grays matching the neutral theme variants. Dark agent: dark gray close to surface. Light agent: light gray close to surface. (2) Eliminate all implicit Textual framework active/focus/hover/double-click states in TCSS. We have our own tree navigation, highlights, and selection UX. Textual built-in $primary/$secondary-based states on widgets are unwanted artifacts. Override them all to be invisible or match our neutral surface colors. No Textual default interaction styling should ever be visible.

## Discovery Context

Reported by: manual
Session: none
Date: 2026-02-22

## Investigation

<!-- Fix worker fills this during debugging -->

## Root Cause

<!-- Fix worker fills this after investigation -->

## Fix Applied

<!-- Fix worker fills this after committing the fix -->
