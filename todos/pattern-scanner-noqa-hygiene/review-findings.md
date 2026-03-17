# Review Findings: pattern-scanner-noqa-hygiene

**Review type:** Ad-hoc review (via from-main)
**Review round:** 1

---

## Code Lane

No bugs or pattern violations found. The table-driven refactor correctly preserves behavioral
equivalence for the two migrated rules (`debug-probes`, `stash-in-artifacts`). The `invalid-noqa`
regex `#\s*noqa:\s*[a-z]` correctly targets custom/invalid noqa directives (lowercase codes like
`raw-sql`, `loose-dict`) while passing all legitimate ruff codes (`E501`, `F401`, etc.). Marker
migration from `noqa: raw-sql` to `guard: raw-sql` is complete across all 5 source files. No
remaining `noqa: raw-sql` markers in the codebase. The `check-raw-sql.sh` file list correctly
reflects the current module structure.

No logging policy findings — this is lint tooling, not runtime code.

## Paradigm Lane

Clean. The table-driven approach follows existing patterns in `guardrails.py` (e.g.,
`_check_module_sizes` collects violations into a list; config invariant checks use frozen
baselines). The `PatternRule` NamedTuple is a clean, self-contained data declaration. The
refactor correctly reduces duplication (scan/match/report loop) without introducing new
abstraction layers.

## Principles Lane

No unjustified fallbacks. The `except OSError: continue` and `if not root.exists(): continue`
patterns are pre-existing (inherited from the old functions) and appropriate for lint tooling
that scans filesystem trees. No DIP, coupling, SRP, or YAGNI violations. The table-driven
design is proportional to 3 rules — not over-engineered.

## Security Lane

Clean. No secrets, injection vectors, authorization gaps, or information leakage. This is lint
tooling operating on source files with hardcoded regex patterns. No user input is processed.

## Tests Lane

**Finding T1 — Important**: No tests for new `invalid-noqa` rule behavior.

The `invalid-noqa` pattern rule is net-new functionality that did not exist before this change.
Testing policy requires tests for new behavior. While `guardrails.py` has zero pre-existing
tests (the old `_warn_for_debug_probes` and `_fail_on_stash_commands_in_agent_artifacts` were
also untested), the addition of new behavior without tests violates the testing policy.

Minimum coverage needed:

- `invalid-noqa` regex matches `# noqa: something` (lowercase custom directive)
- `invalid-noqa` regex does NOT match `# noqa: E501` (valid ruff code, uppercase)
- `exclude_prefixes` correctly skips `tools/lint/` files
- Exception marker suppression works for same-line and previous-line
- Clean files produce no failure

Location: `tools/lint/guardrails.py:377-405` (new rule + scanner function)

## Errors Lane

No findings. The `except OSError: continue` and `if not root.exists(): continue` patterns are
pre-existing, inherited from the old code, and not introduced by this change. The first-rule-wins
`_fail()` exit behavior is also pre-existing — the old separate functions each called `_fail()`
which exits immediately, so the sequential evaluation was already present. The table-driven
refactor does not worsen this behavior.

## Types Lane

No findings. The `PatternRule` NamedTuple is well-structured with clear field semantics.
The `list[str]` vs `tuple[str, ...]` inconsistency between `scan_dirs` and `exclude_prefixes`
is noted as a suggestion below.

## Comments Lane

No findings. All comments in changed code accurately describe current behavior. The
`check-raw-sql.sh` header and error messages correctly use `guard` terminology. The stale
usage path on line 3 (`scripts/check-raw-sql.sh`) is pre-existing and outside the scope
of this change.

---

## Resolved During Review

- **T1** (Important): Added 18 tests in `tests/unit/tools/lint/test_guardrails.py` covering
  all three `SOURCE_PATTERN_RULES`, exclusion prefixes, exception marker suppression, and
  structural rule integrity. Commit: `11203610c`.

## Summary

### Critical

(none)

### Important

(none — T1 resolved)

### Suggestions

- **S1**: `PatternRule.scan_dirs` uses `list[str]` while `exclude_prefixes` uses `tuple[str, ...]`.
  For immutability consistency on a NamedTuple used as a constant, both should use
  `tuple[str, ...]`. (`tools/lint/guardrails.py:370`)

- **S2**: The `_check_source_patterns` call in `main()` (line 49) runs before
  `_warn_for_loose_dicts` (line 53). If a `# noqa: loose-dict` marker were reintroduced,
  the generic "invalid noqa directive" message would fire instead of the more specific
  "legacy loose-dict marker" message. Currently no such markers exist, so this is latent.

- **S3**: Stale usage comment in `check-raw-sql.sh:3` reads `scripts/check-raw-sql.sh` but file
  lives at `tools/checks/check-raw-sql.sh`. Pre-existing, not introduced by this change.

- **S4**: Stale TODO on `guardrails.py:515` — `max_allowed` is already 0, so the TODO
  "Reduce to 0" describes a completed goal. Pre-existing.

---

**Verdict: APPROVE**

Unresolved Critical: 0 | Unresolved Important: 0 | Suggestions: 4
