# Requirements Review Findings: config-independent-schemas

Verdict: **APPROVE** — no Critical or Important findings. Two suggestions below.

---

## Suggestion 1: "Transition period" for checkout_root backward compat is undefined

**Location:** Constraints section — "If the YAML key path changes, the old path must still be
accepted during a transition period. [inferred]"

**Issue:** "Transition period" has no defined endpoint or observable signal. The builder has no
way to determine when the shim can be removed or whether to log a deprecation warning.

**Suggestion:** When implementing the backward-compat shim for the old `git.checkout_root` path,
log a deprecation warning so users know to migrate. Note a follow-up cleanup task in the commit
message. This does not require a requirements change — it is implementation guidance.

---

## Suggestion 2: GlobalConfig consumer verification is implicit

**Location:** Risks section — "Any code that reads these fields from a GlobalConfig instance
will break. The builder must verify all GlobalConfig consumers."

**Issue:** This risk is documented but not tied to an explicit success criterion. The builder
might miss non-obvious callers outside the named pipeline.

**Suggestion:** When implementing Req #1, run the type checker (`mypy`/`pyright`) against the
full codebase immediately after breaking the inheritance — do not wait for pre-commit hooks.
Attribute access on now-absent GlobalConfig fields will produce type errors that serve as the
audit mechanism. This is fully covered by "pre-commit hooks pass" but running it early narrows
the fix/test loop.
