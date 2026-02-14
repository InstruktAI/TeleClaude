# Review Findings: release-arbiter

**Reviewer:** Claude (Consensus Review)
**Round:** 1
**Verdict:** REQUEST CHANGES

---

## Critical

### 1. `|| true` swallows fatal arbiter errors — silent workflow corruption

**File:** `.github/workflows/release.yaml:342`

The arbiter script defines exit codes 0 (success), 1 (fatal), and 2 (needs human). The `|| true` suppresses all non-zero exits, including fatal errors (exit 1). When the script crashes, `arbiter-decision.json` may not exist or be incomplete. The subsequent `jq` commands extract `null` values that propagate as the string `"null"` into `GITHUB_OUTPUT`, causing the `authorized-tag` job to silently skip for the wrong reason. No alert is raised.

**Fix:** Replace `|| true` with explicit exit code handling:

```yaml
python scripts/release_consolidator.py \
  --claude-report claude-report.json \
  --codex-report codex-report.json \
  --gemini-report gemini-report.json \
  -o arbiter-decision.json
EXIT_CODE=$?
if [ "$EXIT_CODE" -eq 1 ]; then
  echo "ERROR: Arbiter fatal error"
  exit 1
fi
```

### 2. Shell injection via AI-generated content in unquoted heredoc

**File:** `.github/workflows/release.yaml:388-407`

`RATIONALE` and `LANE_SUMMARY` originate from AI-generated JSON. The heredoc delimiter `NOTES` is unquoted, so variables undergo full shell expansion. If any AI report contains backticks or `$(...)` in its rationale, they execute as command substitution during the `cat <<NOTES` expansion.

**Fix:** Build release notes safely via `jq` and use `--notes-file`:

```yaml
jq -r '"## AI Consensus Release\n\n**Version:** \(.target_version)\n**Rationale:** \(.authoritative_rationale)\n\n### Lane Summary\n\(.lane_summary | to_entries | map("\(.key): \(.value)") | join(", "))\n\n---\n*Release authorized by AI consensus arbiter.*"' arbiter-decision.json > release-notes.md
gh release create "$NEXT_TAG" --title "$NEXT_TAG" --notes-file release-notes.md
```

### 3. Version parsing breaks on pre-release tags

**File:** `.github/workflows/release.yaml:372`

`git describe --tags --abbrev=0` may return a pre-release tag like `v0.5.0-beta.1`. The `IFS='.' read` splits this so `patch` becomes `0-beta.1`, and the arithmetic `patch=$((patch + 1))` crashes with a bash error, failing the entire release step.

**Fix:** Strip pre-release suffix before splitting:

```bash
CLEAN_VER="${LAST_TAG#v}"
CLEAN_VER="${CLEAN_VER%%-*}"
IFS='.' read -r major minor patch <<< "$CLEAN_VER"
```

---

## Important

### 4. Fail-safe threshold contradicts prompt specification

**File:** `scripts/release_consolidator.py:95` vs `docs/prompts/release-arbiter.md` rule 3

The prompt states: "If any report is missing, malformed, or cannot be parsed, set `release_authorized` to `false`." The code uses `len(valid_reports) < 2`, allowing release authorization with only 2 valid reports. This is a spec-vs-implementation divergence that needs an explicit decision. Either update the threshold to `< 3` or update the prompt to match the 2-of-3 intent.

### 5. `argparse` import inside function body

**File:** `scripts/release_consolidator.py:193`

Project policy requires all imports at module top level. The `import argparse` inside `main()` violates this.

**Fix:** Move to module-level imports.

### 6. Two-valid-report consensus paths are untested

**File:** `tests/unit/test_release_consolidator.py`

No test exercises exactly 2 valid reports + 1 None. This is the most likely real-world failure mode (one AI lane crashes). Missing cases:

- Two agreeing reports + one None: should produce majority consensus.
- Two disagreeing reports + one None: falls through to `_pick_most_detailed` with only 2 reports, producing a "three-way split" rationale which is misleading.

### 7. Conservative override only tested for `minor` minority

**File:** `tests/unit/test_release_consolidator.py:110-120`

The override triggers for any non-"none" classification with contract changes, but only the `minor` case is tested. A `patch` minority with contract changes should also trigger the override but is not verified.

---

## Suggestions

### 8. Use direct key access on TypedDict fields

**File:** `scripts/release_consolidator.py:115`

`report.get("contract_changes")` uses `.get()` on a required TypedDict field. Prefer `report["contract_changes"]` for consistency with the type contract.

### 9. Add tied non-zero counts test for `_pick_most_detailed`

**File:** `scripts/release_consolidator.py:160-170`

The tie-breaking logic is tested only with all-zero counts. A case with tied non-zero counts (e.g., all lanes have 2 contract changes) would verify the function returns None on ties.

### 10. Unquoted `$LAST_TAG` in pre-existing code

**File:** `.github/workflows/release.yaml:250`

Lines 26 and 88 correctly quote `"$LAST_TAG"` but line 250 does not. Pre-existing but inconsistent — worth fixing while touching the file.

---

## Summary

| Severity   | Count |
| ---------- | ----- |
| Critical   | 3     |
| Important  | 4     |
| Suggestion | 3     |

The Python consolidator logic is well-structured with clean types and solid consensus algorithm. The critical issues are all in the workflow YAML: silent error masking (`|| true`), shell injection from AI-generated content, and fragile version parsing. These must be fixed before merge as they affect production safety.

---

## Fixes Applied

| #   | Severity   | Issue                                         | Fix                                                                                  | Commit     |
| --- | ---------- | --------------------------------------------- | ------------------------------------------------------------------------------------ | ---------- |
| 1   | Critical   | `\|\| true` swallows fatal arbiter errors     | Replaced with `set +e` / explicit exit code check; exit 1 = fatal, exit 2 = continue | `2a48d5e3` |
| 2   | Critical   | Shell injection via unquoted heredoc          | Build release notes with `jq`, pass via `--notes-file`                               | `f622cc3c` |
| 3   | Critical   | Version parsing breaks on pre-release tags    | Strip pre-release suffix (`${CLEAN_VER%%-*}`) before `IFS='.' read`                  | `ce817258` |
| 4   | Important  | Fail-safe threshold contradicts spec          | Changed threshold from `< 2` to `< 3` to match spec requirement                      | `d5bfe563` |
| 5   | Important  | `argparse` import inside function body        | Moved to module-level imports, sorted alphabetically                                 | `5c620b00` |
| 6   | Important  | Two-valid-report consensus paths untested     | Added tests: two agreeing + one None, two disagreeing + one None                     | `97e7b7dc` |
| 7   | Important  | Conservative override only tested for `minor` | Added test: `patch` minority with contract changes triggers override                 | `97e7b7dc` |
| 8   | Suggestion | `.get()` on required TypedDict fields         | Changed to direct key access (`report["contract_changes"]`)                          | `5c620b00` |
| 9   | Suggestion | No tied non-zero counts test                  | Added test: all lanes with 2 contract changes returns None                           | `97e7b7dc` |
| 10  | Suggestion | Unquoted `$LAST_TAG` on line 250              | Added quotes for consistency                                                         | `999dc278` |

---

## Round 2 Re-review

**Reviewer:** Claude (Opus 4.6)
**Round:** 2
**Verdict:** APPROVE

### Fix Verification

All 10 round 1 findings verified as correctly resolved:

| #   | Finding                                     | Verified | Commit     |
| --- | ------------------------------------------- | -------- | ---------- |
| 1   | `\|\| true` → explicit exit code handling   | OK       | `2a48d5e3` |
| 2   | Heredoc shell injection → jq + --notes-file | OK       | `f622cc3c` |
| 3   | Pre-release version parsing → strip suffix  | OK       | `ce817258` |
| 4   | Fail-safe threshold < 2 → < 3               | OK       | `d5bfe563` |
| 5   | argparse import → module level              | OK       | `5c620b00` |
| 6   | Two-report fail-safe tests added            | OK       | `97e7b7dc` |
| 7   | Patch override test added                   | OK       | `97e7b7dc` |
| 8   | .get() → direct key access                  | OK       | `5c620b00` |
| 9   | Tied non-zero counts test added             | OK       | `97e7b7dc` |
| 10  | Unquoted $LAST_TAG → quoted                 | OK       | `999dc278` |

### Quality Gates

- **Tests:** All release_consolidator tests pass (2 pre-existing unrelated failures in `test_diagram_extractors` and `test_tui_sessions_view`)
- **Lint:** Clean (ruff format, ruff check, pyright — 0 errors)
- **Implementation plan:** All 4 tasks checked
- **Build checklist:** Fully checked
- **Deferrals:** None

### New Findings (Round 2)

None critical or important.

#### Suggestions

**11. Residual `.get()` on TypedDict field in `main()`**

**File:** `scripts/release_consolidator.py:217`

`decision.get("needs_human")` uses `.get()` on `ArbiterDecision` TypedDict field. Inconsistent with finding #8's fix that changed all `.get()` to direct key access. Not a bug — `needs_human` is always present.

**Fix (optional):** `decision["needs_human"]`
