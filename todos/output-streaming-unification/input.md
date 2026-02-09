# Output Streaming Unification — Input

## Context

Current outbound behavior mixes two concerns:

- state snapshots (`session_updated`, projects/todos/computers) through cache/API websocket,
- high-frequency agent output and stop/update activity via partially separate paths.

This is acceptable for current operation but is not the right foundation for an upcoming web frontend with rich streaming output.

## Problem

We need one clean outbound model:

- AgentCoordinator as an agent activity hub (event orchestration),
- one distribution boundary for outbound activity (AdapterClient/distributor),
- adapter-edge protocol translation for Telegram, TUI, and Web,
- state snapshots remaining in cache/API websocket without carrying high-frequency stream payloads.

## Intent

Build a target architecture where TUI and Web consume the same canonical activity stream, and where transport/protocol differences are isolated behind adapters.
