"""The artifact viewer pane's identity, in both directions.

A viewer pane runs the editor module against one todo artifact, and the command
that starts it names that artifact in full. tmux reports a pane's start command
verbatim, so the pane carries its own identity and a reload can recover what it
is showing by reading it back — the same way a session pane is recovered from
the attach command it was started with.

Building the command and reading it back are one piece of knowledge, so the flag
vocabulary and the document id live here and both directions use them.
"""

from __future__ import annotations

import re
import shlex

from teleclaude.cli.tui.types import DocPreviewState
from teleclaude.todo_artifacts import artifact_display_filename

EDITOR_MODULE = "teleclaude.cli.editor"
FLAG_MODULE = "-m"
FLAG_PROJECT_ROOT = "--project-root"
FLAG_ARTIFACT_SLUG = "--artifact-slug"
FLAG_ARTIFACT_NAME = "--artifact-name"
FLAG_VIEW = "--view"
FLAG_THEME = "--theme"

_DOC_ID_PREFIX = "artifact"
DOC_PANE_PREFIX = "doc:"
_DOC_ID_SEPARATOR = ":"
_EDIT_TITLE = "Editing: %s"
_WRAPPING_QUOTES = ('"', "'")
_EDITOR_MODULE_RE = re.compile(re.escape(FLAG_MODULE) + r"\s+" + re.escape(EDITOR_MODULE) + r"(?:\s|$)")

__all__ = [
    "DOC_PANE_PREFIX",
    "EDITOR_MODULE",
    "FLAG_ARTIFACT_NAME",
    "FLAG_ARTIFACT_SLUG",
    "FLAG_MODULE",
    "FLAG_PROJECT_ROOT",
    "FLAG_THEME",
    "FLAG_VIEW",
    "artifact_doc_id",
    "doc_pane_key",
    "parse_doc_pane_command",
]


def artifact_doc_id(project_path: str, slug: str, artifact_name: str) -> str:
    """Build the stable document id for a todo artifact."""
    return _DOC_ID_SEPARATOR.join((_DOC_ID_PREFIX, project_path, slug, artifact_name))


def doc_pane_key(doc_id: str) -> str:
    """The pane-map key a viewer occupies, distinct from any session id."""
    return DOC_PANE_PREFIX + doc_id


def parse_doc_pane_command(command: str) -> DocPreviewState | None:
    """Recover what a viewer pane is showing from the command that started it.

    Matched against the raw string rather than a tokenization of it: tmux
    reports a pane's start command wrapped as a single quoted argument, which
    a shell tokenizer collapses into one token and no flag survives. The
    session-pane matcher beside this one reads its attach target the same way.

    Returns ``None`` for any command that is not this editor invocation, which
    is how a caller tells an adoptable viewer pane from a pane it cannot place.
    """
    unwrapped = _without_report_wrapper(command)
    if not _EDITOR_MODULE_RE.search(unwrapped):
        return None
    try:
        tokens = shlex.split(unwrapped)
    except ValueError:
        return None
    project_path = _flag_value(tokens, FLAG_PROJECT_ROOT)
    slug = _flag_value(tokens, FLAG_ARTIFACT_SLUG)
    artifact_name = _flag_value(tokens, FLAG_ARTIFACT_NAME)
    if not project_path or not slug or not artifact_name:
        return None
    filename = artifact_display_filename(artifact_name)
    return DocPreviewState(
        doc_id=artifact_doc_id(project_path, slug, artifact_name),
        command=unwrapped,
        title=filename if FLAG_VIEW in tokens else _EDIT_TITLE % filename,
    )


def _without_report_wrapper(command: str) -> str:
    """Drop the single pair of quotes tmux wraps a reported command in.

    Only the outer pair is removed, so the quoting the command builder applied
    to its own arguments survives for the tokenizer to reverse.
    """
    stripped = command.strip()
    for quote in _WRAPPING_QUOTES:
        if len(stripped) > 1 and stripped.startswith(quote) and stripped.endswith(quote):
            return stripped[1:-1]
    return stripped


def _flag_value(tokens: list[str], flag: str) -> str | None:
    """The value following ``flag``, or ``None`` when it is absent or trailing."""
    try:
        index = tokens.index(flag)
    except ValueError:
        return None
    if index + 1 >= len(tokens):
        return None
    return tokens[index + 1] or None
