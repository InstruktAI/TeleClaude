# Quality Checklist: web-interface-3

## Build Gates (Builder)

- [ ] All implementation-plan tasks completed
- [ ] `pnpm build` succeeds with no type errors
- [ ] `pnpm lint` passes
- [ ] Working tree clean (build-scope)
- [ ] Commits follow commitizen format
- [ ] No debug/temp code committed

## Review Gates (Reviewer)

- [ ] Code matches requirements
- [ ] Part components handle missing/malformed data gracefully
- [ ] No security vulnerabilities introduced
- [ ] Streaming transport works end-to-end
- [ ] Session picker loads and navigates correctly

## Finalize Gates (Finalizer)

- [ ] Branch merged cleanly
- [ ] No regressions in existing functionality
