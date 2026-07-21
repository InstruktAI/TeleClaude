---
description: 'Post-work verification for frontend changes: availability check, dev login, then a Playwright smoke of the changed flow.'
visibility: 'internal'
activation_trigger: 'Use after changing frontend code, before claiming the change works.'
---

# Frontend Verification — Procedure

## Goal

Prove a frontend change actually works in the browser — reaching the changed behavior
itself, not just the surrounding shell or the login screen.

## Preconditions

- The frontend dev server is running via `pnpm dev` (WebSocket-capable; raw `next dev`
  leaves live features broken).
- `frontend/.env` is present with `TEST_EMAIL` set.

## Steps

1. **Do not use `pnpm build` as the smoke test.** A successful build is not proof the
   changed UI works.
2. **Availability check (only).** Confirm the app is up with real HTTP checks — a `200`
   or redirect is availability, not correctness:
   ```bash
   curl -I http://localhost:3000/
   curl -I http://localhost:3000/login
   ```
3. **Log in past auth (setup, not the smoke test).** For protected UI in development:
   - use the plain email login form, not `/api/people`
   - read `TEST_EMAIL` from `frontend/.env`
   - request the verification code
   - read the OTP from the running server logs — in development the server logs
     `[AUTH DEV] Verification code for <email>: <token>` instead of sending email
   - paste that code into the login form and continue past auth into the changed feature
4. **Playwright smoke the changed flow.** Authentication is setup; do not stop there:
   - navigate to the page or route affected by the change
   - perform the exact interaction that was changed
   - assert the expected visible outcome in the browser
   - if the change is stateful, reload or restart the browser and verify the state
     persists or restores correctly
   - if the change affects an error, loading, or empty state, exercise that branch too
     when practical

## Outputs

- A browser smoke that reaches the changed behavior itself, confirming the expected
  visible outcome.

## Recovery

- If live session-tree activity looks broken, the dev server was started with raw
  `next dev`; restart with `pnpm dev`.
- Keep verification proportional: targeted tests support the smoke check but do not
  replace curl + browser validation of the changed feature. Do not claim frontend work
  is verified unless the browser smoke reached the changed behavior.
