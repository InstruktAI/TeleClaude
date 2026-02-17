# Widget SDK — Quality Checklist

## Build Gates (Builder)

- [x] All implementation-plan tasks checked off
- [x] Tests pass (`make test`) — 1754 pass, 21 pre-existing failures in unrelated modules
- [x] Lint passes (`make lint`) — ruff, pyright, format all clean
- [x] Working tree clean for build-scope changes
- [x] TypeScript compiles clean for frontend changes

## Review Gates (Reviewer)

- [ ] Code matches requirements
- [ ] No regressions in existing functionality
- [ ] Error handling adequate
- [ ] Types accurate and complete

## Finalize Gates (Finalizer)

- [ ] Branch merged cleanly
- [ ] No orphaned files
