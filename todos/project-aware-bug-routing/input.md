# Input

Need one controlled todo that consolidates all bug-handling loose ends into a
single coherent route, without ad-hoc changes and without pretending bugs are
full todos.

Requested outcomes:

1. Keep one bug runner only.
2. Route by slug prefix: `bug-*` uses the bug route; non-`bug-*` stays on normal flow.
3. Keep bug handling lightweight: do not require per-bug todo artifact files.
4. Enforce atomic behavior per bug:
   - fix by one agent,
   - immediate review by a different agent/session,
   - if review fails, re-fix by another fixer agent,
   - repeat until pass or retry limit.
5. Keep bug offload/reporting friction low:
   - default to current context without mandatory project argument,
   - support explicit TeleClaude bug-target flag.
6. Keep process safe:
   - bug runner does not bypass review hygiene,
   - bug runner does not do unsafe direct landing behavior.
7. Produce one clear human-facing report for blocked/needs-human bug items.
