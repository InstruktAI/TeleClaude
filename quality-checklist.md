## Build Gates (Builder)

- [x] Task 1: Refactor `useAgentTheming` to an external-store hook
- [x] Task 2: Remove effect-driven query snapshot syncing from live hooks
- [x] Task 3: Move render-phase ref writes to commit-safe locations
- [x] Task 4: Correct `useSessionTree` memoization dependencies
- [x] Task 5: Resolve layout stylesheet and exhaustive-deps warnings
- [x] Task 6: Add executable verification commands and browser smoke evidence

### Browser Smoke Verification
- Path: `frontend/e2e/react19-cleanup.spec.ts` was added to test the chat page rendering, session tree navigation, and theming toggle functionality.
- Observed result: `DATABASE_URL="/tmp/teleclaude-react19-smoke-main-lint.db" AUTH_SECRET='teleclaude-e2e-secret-for-local-smoke' AUTH_URL='http://localhost:3000' pnpm run test:e2e e2e/react19-cleanup.spec.ts` passed in Chromium under Node.js v22.22.3 after rebuilding `better-sqlite3`.

### Local Dependency Installation
- **Issue**: `pnpm install` fails locally due to Node.js v26 incompatibility with `better-sqlite3@11.10.0` (specifically a `GetPrototype` missing member in `v8::Object` in `node-gyp`).
- **Result**: The ambient Node.js v26 install/build failure remains separate from the React lint cleanup result, as instructed by the PRD. Local browser verification was completed with pnpm-managed Node.js v22.22.3 and a rebuilt `better-sqlite3` native binding.
