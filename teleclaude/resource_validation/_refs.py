"""Resolve an ``@`` reference written in a snippet to the file it names."""

from __future__ import annotations

from pathlib import Path

from teleclaude.docs_publishers import resolve_global_doc_source

_URL_MARKER = "://"
_DOCS_DIRNAME = "docs"
_DOCS_PREFIX = f"{_DOCS_DIRNAME}/"
_LOCAL_HALF = "local"
_GLOBAL_HALF = "global"


def resolve_ref_path(ref: str, *, root_path: Path, current_path: Path) -> Path | None:
    """Resolve an ``@`` reference to an absolute path.

    Handles absolute paths, ``~/`` expansion, ``docs/`` relative paths with
    local/global fallback, and paths relative to the referencing file.
    """
    if _URL_MARKER in ref:
        return None
    candidate = Path(ref).expanduser()
    if not candidate.is_absolute():
        if str(candidate).startswith(_DOCS_PREFIX):
            candidate = (root_path / candidate).resolve()
            if not candidate.exists():
                tail = Path(ref).relative_to(_DOCS_DIRNAME)
                project_candidate = (root_path / _DOCS_DIRNAME / _LOCAL_HALF / tail).resolve()
                if project_candidate.exists():
                    candidate = project_candidate
                else:
                    global_candidate = (root_path / _DOCS_DIRNAME / _GLOBAL_HALF / tail).resolve()
                    if global_candidate.exists():
                        candidate = global_candidate
        else:
            candidate = (current_path.parent / candidate).resolve()
    else:
        raw_candidate = candidate
        candidate = candidate.resolve()
        mapped_candidate = resolve_global_doc_source(root_path, raw_candidate)
        return mapped_candidate if mapped_candidate != raw_candidate else candidate
    return resolve_global_doc_source(root_path, candidate)
