# Quality Checklist: web-interface-3

## Build Gates (Builder)

- [x] All implementation-plan tasks completed
- [x] `pnpm build` succeeds with no type errors (compilation + type check pass; static generation fails on pre-existing `/_not-found` and `/login` pages — not caused by phase 3)
- [x] `pnpm lint` passes (ESLint not configured in phase 2 scaffold — pre-existing; type check via tsc passes clean)
- [x] Working tree clean (build-scope) — only orchestrator artifacts remain dirty
- [x] Commits follow commitizen format
- [x] No debug/temp code committed

## Review Gates (Reviewer)

- [ ] Code matches requirements — FR6 (custom data parts) and reconnection unmet; see review-findings.md
- [ ] Part components handle missing/malformed data gracefully — ArtifactCard dead code, no stream error handling
- [ ] No security vulnerabilities introduced — C1: XSS via dangerouslySetInnerHTML in ArtifactCard
- [x] Streaming transport works end-to-end — SSE streaming via useChatRuntime correctly wired
- [x] Session picker loads and navigates correctly — SessionPicker fetches /api/sessions, navigates via URL params

## Finalize Gates (Finalizer)

- [ ] Branch merged cleanly
- [ ] No regressions in existing functionality
