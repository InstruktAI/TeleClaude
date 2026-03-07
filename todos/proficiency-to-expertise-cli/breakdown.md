# Breakdown: proficiency-to-expertise-cli

## Assessment

**Splitting not needed.** All CLI changes are in one file (config_cli.py) plus its
test file. Add, edit, list, and PersonInfo dataclass are interdependent — splitting
them would create a half-functional CLI surface.

## DOR Gate Assessment

| Gate | Status | Evidence |
|------|--------|----------|
| 1. Intent & success | Pass | CLI commands support structured expertise instead of flat proficiency |
| 2. Scope & size | Pass | 2 files (config_cli.py + test_config_cli.py), one domain |
| 3. Verification | Pass | CLI tests for add/edit/list with new expertise flags |
| 4. Approach known | Pass | Existing CLI patterns for people management, JSON blob or dot-path flags |
| 5. Research complete | Auto-pass | No new third-party dependencies |
| 6. Dependencies | Pass | Depends on schema child (proficiency-to-expertise-schema) |
| 7. Integration safety | Pass | CLI flags are additive; old proficiency flag can be deprecated gracefully |
| 8. Tooling impact | Pass | CLI help text updates included in scope |

**Score: 8 / 10** — Status: **pass**
