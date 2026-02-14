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
