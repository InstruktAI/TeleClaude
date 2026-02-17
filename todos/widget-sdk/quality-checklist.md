# Widget SDK — Quality Checklist

## Build Gates (Builder)

- [ ] All implementation-plan tasks checked off
- [ ] Tests pass (`make test`)
- [ ] Lint passes (`make lint`)
- [ ] Working tree clean for build-scope changes
- [ ] TypeScript compiles clean for frontend changes

## Review Gates (Reviewer)

- [ ] Code matches requirements
- [ ] No regressions in existing functionality
- [ ] Error handling adequate
- [ ] Types accurate and complete

## Finalize Gates (Finalizer)

- [ ] Branch merged cleanly
- [ ] No orphaned files
