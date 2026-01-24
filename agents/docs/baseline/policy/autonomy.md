# Autonomy and Escalation Policy

This is the single source of truth for when to proceed autonomously and when to ask.
If any other instruction conflicts with this policy, this policy wins.

## Default Behavior

Proceed autonomously on any action that is required to fulfill the user request and is safe, reversible, and within the stated scope.

## Escalate Only When One of These Is True

1. **Destructive or irreversible**
   Actions that delete data, overwrite protected files, perform irreversible migrations, or cannot be rolled back quickly and safely.

2. **Security or access changes**
   Actions that change authentication, authorization, secrets, encryption, credentials, network exposure, or access control boundaries.

3. **High-impact or costly**
   Actions that incur cost, provision paid resources, or risk extended downtime beyond a brief, expected restart window.

4. **Out of scope**
   Actions that are not required to fulfill the request, expand scope, or introduce unrelated changes or refactors.

5. **Ambiguous intent**
   Multiple valid interpretations with real tradeoffs where the user's preference is unknown.

**If none of the above are true, do it without asking.**

## No Stalls for Routine Git Diffs

Do not pause for unexpected or unrelated git changes. Fix forward, keep working, and commit all changes with clean hygiene.

## Commit After Completing Work

If your task produces new artifacts or edits, finish with a clean, atomic commit once the work is complete and verified.

## Use teleclaude\_\_get_context When Context Matters

When you sense missing information that could change decisions or edits, call `teleclaude__get_context` immediately before changing files or executing work.
Always supply the `areas` parameter using the taxonomy already loaded in the system context; do not restate the taxonomy, just pick the best-fitting areas.
Use the two-phase flow:

1. Call with empty `corpus` to get the filtered index (frontmatter only).
2. Call again with selected snippet ids to fetch full snippet bodies.

## Unexpected Changes Are Not a Blocker

If you notice unrelated or pre-existing changes in the repo, **do not stop**.
Proceed with the requested work and ignore unrelated diffs.
Only mention them **after** completion if they are truly relevant.

If your task touches the same files, treat those changes as part of the working context and continue.
