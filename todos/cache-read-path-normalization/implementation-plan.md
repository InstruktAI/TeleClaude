# Implementation Plan - cache-read-path-normalization

## Overview

Normalize all REST read paths to read from cache only and rely on the policy matrix for refresh behavior.

## Steps

1) **Inventory Read Endpoints**
   - List all REST read endpoints and their data requirements.
   - Identify any direct remote fetches or endpoint-specific refresh logic.

2) **Cache-Only Reads**
   - Route all reads through cache APIs.
   - Remove special-case refresh or pull logic from handlers.

3) **Output Normalization**
   - Ensure consistent response shapes for sessions, projects, todos, and computers.
   - Centralize any computed fields (e.g., `computer` field injection) in a single layer.

4) **Resource-Only Responses**
   - Remove any aggregate or mixed-resource payloads from read handlers.
   - Align shapes with resource endpoints.

5) **Session Summary Boundary**
   - Ensure REST returns session summaries only.
   - Route session detail and live events to WebSocket subscriptions.

6) **WebSocket Initial State**
   - Align WS initial payloads to cache output shapes.
   - Ensure WS uses cache-only data.

7) **Tests**
   - Verify that endpoints do not call remote fetch methods.
   - Validate response shapes and cache interactions.
