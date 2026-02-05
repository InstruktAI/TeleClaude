# AGENTS.md

## Purpose

This file provides guidance to agents when working with code in this repository.

## Required reads

- @docs/project/baseline.md

## TUI work

- After any TUI code change, send SIGUSR2 to the running TUI to reload. (SIGUSR1 is reserved for appearance/theme refresh.)
- Do not restart the daemon and do not instruct the user to restart telec.
- Verify the change in the TUI after reload.
