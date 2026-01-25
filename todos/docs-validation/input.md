# Docs Validation Cleanup Plan

## Goal

Make all docs conform to the new snippet validation rules as quickly and safely as possible.

## Scope

- TeleClaude repo docs under `docs/`.
- Global docs mirror under `agents/docs/` (if required by tooling).
- Baseline + software-development taxonomies.

## Plan (fast + safe)

1. Triage warnings into buckets
   - Missing H1 / H2
   - Required section missing
   - Unknown section (header not in schema)
   - Required reads header level/order

2. Automate safe fixes where possible
   - H1 titles already auto-normalized by the script.
   - Add missing `Required reads` header if absent (empty is allowed).
   - Add missing required H2 sections with minimal placeholder text.

3. Manual pass for high-value docs
   - Prioritize baseline policies + principles.
   - Then references/procedures/guides.
   - Ensure section names match schema exactly.

4. Re-run validation
   - Iterate until warnings are near zero.

## Decision needed

- Confirm whether we should auto-insert missing required sections with placeholders,
  or do manual edits only.
