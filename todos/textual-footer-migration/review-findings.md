# Review Findings: textual-footer-migration

## Critical

- Dynamic footer context is not implemented for tree cursor movement, and `SessionsView` does not implement the required computer-level restart action. `SessionsView` keeps static bindings for `n/k/R` (`teleclaude/cli/tui/views/sessions.py:70`, `teleclaude/cli/tui/views/sessions.py:79`, `teleclaude/cli/tui/views/sessions.py:80`, `teleclaude/cli/tui/views/sessions.py:81`) and has no `restart_all` binding/action path (only `new_session` fallback from headers in `teleclaude/cli/tui/views/sessions.py:595` and `teleclaude/cli/tui/views/sessions.py:689`). `PreparationView` also keeps static context-sensitive bindings always visible (`teleclaude/cli/tui/views/preparation.py:50`, `teleclaude/cli/tui/views/preparation.py:55`, `teleclaude/cli/tui/views/preparation.py:61`, `teleclaude/cli/tui/views/preparation.py:62`, `teleclaude/cli/tui/views/preparation.py:63`). This does not satisfy the required per-node footer behavior.

- The modal-first workflow requirement is not met for prepare/start actions. `action_prepare` still dispatches a session immediately via `CreateSessionRequest` instead of opening `StartSessionModal` (`teleclaude/cli/tui/views/preparation.py:570`). `action_start_work` only runs on a selected todo row and returns otherwise (`teleclaude/cli/tui/views/preparation.py:600`), so project-node modal behavior (including slug omission) is not implemented.

## Important

- Footer styling does not follow Textual Footer component structure and default-action emphasis is not implemented. TCSS targets `Footer > .footer--*` selectors (`teleclaude/cli/tui/telec.tcss:131`, `teleclaude/cli/tui/telec.tcss:135`, `teleclaude/cli/tui/telec.tcss:140`) rather than `FooterKey .footer-key--key` / `.footer-key--description` classes required by Textual Footer internals. Additionally, explicit `enter` hints remain in bindings (`teleclaude/cli/tui/views/sessions.py:74`, `teleclaude/cli/tui/views/preparation.py:55`) with no per-context default-action styling mechanism.

- In-scope cleanup is incomplete: legacy `teleclaude/cli/tui/widgets/footer.py` still exists and was not removed.

- Test coverage for this migration is insufficient and regressed. Footer-specific tests were deleted (`tests/unit/test_tui_footer_widget.py`, `tests/unit/test_tui_app_footer_separator.py`) and no replacement `tests/unit/test_tui_footer_migration.py` (or equivalent behavior tests) was added. Executed targeted checks show no executable coverage for this area: `uv run pytest tests/unit/test_tui_app.py -q` reported 9 skipped, and `uv run pytest tests/unit/test_tui_sessions_view.py tests/unit/test_tui_preparation_view.py -q` reported 84 skipped.

- Manual UI verification evidence is missing for this user-facing change. Interactive verification of footer rendering/context switching was not demonstrated in this review environment.

## Paradigm-Fit Assessment

- Data flow: The switch to Textual `Footer` in app composition follows the established Textual widget architecture (`teleclaude/cli/tui/app.py:183`).
- Component reuse: Existing view actions and widgets are reused; no copy-paste component forks were introduced.
- Pattern consistency: The previous context-aware behavior was removed without a replacement in the established reactive/action pattern (`check_action` + binding refresh on cursor movement), creating a mismatch with the intended interaction model.

## Verdict

REQUEST CHANGES
