# AGENTS.md

## Purpose

This file provides guidance to agents when working with code in this repository.

## Required reads

@docs/project/baseline/index.md

## TUI work

- After any TUI code change, send SIGUSR1 to the running TUI to reload.
- Do not restart the daemon and do not instruct the user to restart telec.
- Verify the change in the TUI after reload.
