"""``telec code disclaim`` — the symmetric answer to ``telec code add``."""

from __future__ import annotations

import sys

from teleclaude.cli.telec.handlers._code_invocation import resolve_invocation_state
from teleclaude.hooks.checkpoint_disclaimers import record_disclaimed_paths
from teleclaude.quality.scope import ContextPathResolutionMode, validate_context_paths
from teleclaude.session_identity import get_session_id


def handle_code_disclaim(args: list[str]) -> None:
    """Record paths as not this session's work, for the next checkpoint evaluation.

    Symmetric answer to `telec code add`: `add` says this is mine, `disclaim`
    says this is not. Neither asks the agent to work out whose it is — sorting
    a reported path stays the agent's judgment, and this command resolves no
    ownership of its own. It stages nothing, touches no index, and writes no
    declaration; it records a session-scoped advisory exemption for that exact
    dirty state. The exemption lapses when the path is committed, goes clean,
    or materially changes.
    """
    positionals: list[str] = []
    for token in args:
        if token.startswith("-"):
            print(
                f"ERROR: unknown flag: {token}\nUsage: telec code disclaim <path> [<path> ...]",
                file=sys.stderr,
            )
            raise SystemExit(2)
        positionals.append(token)

    if not positionals:
        print(
            "Usage: telec code disclaim <path> [<path> ...]\n"
            "\n"
            "Marks paths as not this session's work, for the next checkpoint evaluation.\n"
            "Sorting whose work a reported path is stays the agent's judgment; this\n"
            "command never resolves ownership on its own.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    state = resolve_invocation_state()
    project_root = state.project_root
    validated_positionals = validate_context_paths(
        positionals,
        project_root,
        state.context_root,
        resolution_mode=ContextPathResolutionMode.PRESERVE_TERMINAL,
    )
    if len(validated_positionals) != len(positionals):
        print("ERROR: one or more paths were rejected outside the invocation context", file=sys.stderr)
        raise SystemExit(1)
    positionals = validated_positionals

    session_id = get_session_id()
    if not session_id:
        print("ERROR: no session identity resolved for this invocation", file=sys.stderr)
        raise SystemExit(1)

    try:
        record_disclaimed_paths(session_id, project_root, positionals)
    except OSError as exc:
        print(f"ERROR: failed to record disclaimed path(s): {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print(f"Disclaimed {len(positionals)} path(s):")
    for path in positionals:
        print(f"  {path}")
