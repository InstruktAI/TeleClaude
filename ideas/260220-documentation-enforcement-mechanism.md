# Documentation Enforcement Mechanism

**Pattern identified:** Three memory entries (IDs 3, 22, 24) document documentation quality expectations but lack enforcement. The entries show repeated friction around:

- Module docstrings must be substantive (ID 3), not one-liners
- Artifacts describe target state, never transition state (ID 22)
- Generated files (AGENTS.md) are frequently mistakenly edited instead of sources (ID 24)

**Current state:** These are documented in memory records and CLAUDE.md baseline, but there is no lint, pre-commit, or automated enforcement. Agents continue to write one-liner docstrings and edit wrong files despite documentation.

**Actionable insight:** Create a two-tier enforcement system:

1. **Lint guardrails** - automated checks in pre-commit or CI that fail on:
   - Module docstrings shorter than 50 characters
   - Commits modifying AGENTS.md (should edit AGENTS.master.md)
   - Documentation files with placeholder language ("will be", "not yet", "legacy")
2. **Lint suppression markers** - allow exceptions with `# noqa: doc-` comments where legitimate

**Benefit:** Shifts documentation quality from repeated memory records and user frustration to automated, always-on enforcement. Reduces cognitive load and friction.

**Next step:** Add `docs/lint/docstring-enforcement.md` specification and implement guardrails in linter or pre-commit hook.
