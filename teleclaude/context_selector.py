from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, TypedDict

import httpx
from instrukt_ai_logging import get_logger

from teleclaude.paths import CONTEXT_STATE_PATH, GLOBAL_SNIPPETS_DIR

logger = get_logger(__name__)

SCOPE_ORDER = {"global": 0, "domain": 1, "project": 2}


@dataclass(frozen=True)
class SnippetMeta:
    snippet_id: str
    description: str
    snippet_type: str
    scope: str
    path: Path
    requires: list[str]


class SessionState(TypedDict):
    ids: list[str]


class ContextState(TypedDict):
    sessions: dict[str, SessionState]


def _empty_state() -> ContextState:
    return {"sessions": {}}


def _scope_rank(scope: str | None) -> int:
    if not scope:
        return 3
    return SCOPE_ORDER.get(scope, 3)


def _load_state() -> ContextState:
    if not CONTEXT_STATE_PATH.exists():
        return _empty_state()
    try:
        data = json.loads(CONTEXT_STATE_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.exception("context_state_load_failed", error=str(exc))
        return _empty_state()
    if not isinstance(data, dict):
        return _empty_state()
    sessions = data.get("sessions")
    if not isinstance(sessions, dict):
        return _empty_state()
    clean_sessions: dict[str, SessionState] = {}
    for key, value in sessions.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            continue
        ids = value.get("ids")
        if not isinstance(ids, list):
            continue
        clean_ids = [sid for sid in ids if isinstance(sid, str)]
        clean_sessions[key] = {"ids": clean_ids}
    return {"sessions": clean_sessions}


def _save_state(state: ContextState) -> None:
    try:
        CONTEXT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONTEXT_STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.exception("context_state_save_failed", error=str(exc))


_INLINE_REF_RE = re.compile(r"@([\w./~\-]+\.md)")


def _split_frontmatter(content: str) -> tuple[str, str]:
    """Split frontmatter header from body, preserving header verbatim."""
    if not content.startswith("---"):
        return "", content
    lines = content.splitlines(keepends=True)
    if not lines:
        return "", content
    # Find the closing frontmatter fence.
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            head = "".join(lines[: idx + 1])
            body = "".join(lines[idx + 1 :])
            return head, body
    return "", content


def _resolve_inline_refs(content: str, *, snippet_path: Path, root_path: Path) -> str:
    """Expand @<path>.md references to absolute paths for tool consumption."""
    head, body = _split_frontmatter(content)

    def _expand(match: re.Match[str]) -> str:
        ref = match.group(1)
        if "://" in ref:
            return match.group(0)
        candidate = Path(ref).expanduser()
        if not candidate.is_absolute():
            if str(candidate).startswith("docs/"):
                candidate = (root_path / candidate).resolve()
            else:
                candidate = (snippet_path.parent / candidate).resolve()
        else:
            candidate = candidate.resolve()
        return f"@{candidate}"

    return f"{head}{_INLINE_REF_RE.sub(_expand, body)}"


def _parse_snippets(snippets_dir: Path, default_scope: str) -> list[SnippetMeta]:
    if not snippets_dir.exists():
        return []

    try:
        import frontmatter  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        logger.warning("frontmatter_missing; skipping snippet parsing", path=str(snippets_dir))
        return []

    snippets: list[SnippetMeta] = []
    for path in sorted(snippets_dir.rglob("*.md")):
        if "baseline" in str(path):
            continue
        try:
            post = frontmatter.load(path)
        except Exception as exc:
            logger.exception("snippet_parse_failed", path=str(path), error=str(exc))
            continue
        metadata = post.metadata or {}
        snippet_id = metadata.get("id")
        description = metadata.get("description")
        snippet_type = metadata.get("type")
        scope = metadata.get("scope", default_scope)
        if (
            not isinstance(snippet_id, str)
            or not isinstance(description, str)
            or not isinstance(snippet_type, str)
            or not isinstance(scope, str)
        ):
            continue
        requires_raw = metadata.get("requires", [])
        requires_list = requires_raw if isinstance(requires_raw, list) else []
        resolved_requires: list[str] = []
        for req in requires_list:
            if not isinstance(req, str):
                continue
            resolved_requires.append(req)
        snippets.append(
            SnippetMeta(
                snippet_id=snippet_id,
                description=description,
                snippet_type=snippet_type,
                scope=scope,
                path=path.resolve(),
                requires=resolved_requires,
            )
        )
    return snippets


def _select_ids(corpus: str, metadata: list[dict[str, str]]) -> list[str]:
    llm_url = "http://192.168.1.247:1234/v1/chat/completions"
    system_prompt = (
        "You are a context selector. Given a user request and a list of documentation snippets "
        "(id, description, type), select ONLY the IDs of the snippets that are relevant to the request.\n"
        "Respond ONLY with a JSON array of strings (the snippet IDs).\n"
        "Do NOT return indices or numbers. Return the exact id values.\n"
        "If no snippets are relevant, respond with [].\n"
        "Do not include any explanation or other text.\n"
        "If both a framework-specific scaffold and a generic scaffold match, select the framework-specific one "
        "and omit the generic unless the user explicitly asks for general guidance."
    )

    payload = {
        "model": "local-model",
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": f"User Request: {corpus}\n\nAvailable Snippets:\n{json.dumps(metadata, indent=2)}",
            },
        ],
        "temperature": 0,
    }

    logger.debug("context_selector_llm_request", snippet_count=len(metadata))

    try:
        response = httpx.post(llm_url, json=payload, timeout=30.0)
        response.raise_for_status()
        result = response.json()
        content = result["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        logger.exception("context_selector_llm_failed", error=str(exc))
        return []

    if "```json" in content:
        content = content.split("```json")[1].split("```")[0].strip()
    elif "```" in content:
        content = content.split("```")[1].split("```")[0].strip()

    try:
        parsed = json.loads(content)
    except Exception:
        logger.error("context_selector_invalid_json", content=content)
        return []

    if not isinstance(parsed, list):
        logger.error("context_selector_invalid_list", content=content)
        return []

    if all(isinstance(item, str) and item.isdigit() for item in parsed) and parsed:
        mapped: list[str] = []
        for item in parsed:
            idx = int(item)
            if 1 <= idx <= len(metadata):
                mapped.append(metadata[idx - 1]["id"])
        logger.warning("context_selector_returned_indices", original=parsed, mapped=mapped)
        return mapped

    return [item for item in parsed if isinstance(item, str)]


def _resolve_requires(selected_ids: Iterable[str], snippets: list[SnippetMeta]) -> list[SnippetMeta]:
    snippets_by_id = {s.snippet_id: s for s in snippets}
    snippets_by_path = {str(s.path): s for s in snippets}

    resolved: list[SnippetMeta] = []
    seen: set[str] = set()
    stack: list[SnippetMeta] = []

    for sid in selected_ids:
        snippet = snippets_by_id.get(sid)
        if snippet:
            stack.append(snippet)

    while stack:
        current = stack.pop()
        if str(current.path) in seen:
            continue
        seen.add(str(current.path))
        resolved.append(current)
        for req in current.requires:
            req_snippet = snippets_by_id.get(req)
            if not req_snippet:
                req_snippet = snippets_by_path.get(str(req))
            if not req_snippet and req.endswith(".md"):
                req_path = (current.path.parent / req).resolve()
                req_snippet = snippets_by_path.get(str(req_path))
            if req_snippet and str(req_snippet.path) not in seen:
                stack.append(req_snippet)

    resolved.sort(key=lambda s: (_scope_rank(s.scope), s.snippet_id))
    return resolved


def build_context_output(
    *,
    corpus: str,
    areas: list[str] | None,
    project_root: Path,
    session_id: str | None,
) -> str:
    project_snippets_dir = project_root / "docs" / "snippets"

    snippets = []
    snippets.extend(_parse_snippets(GLOBAL_SNIPPETS_DIR, default_scope="domain"))
    snippets.extend(_parse_snippets(project_snippets_dir, default_scope="project"))

    if areas:
        areas_set = set(areas)
        snippets_for_selection = [s for s in snippets if s.snippet_type in areas_set]
    else:
        snippets_for_selection = snippets

    metadata: list[dict[str, str]] = [
        {"id": s.snippet_id, "description": s.description, "type": s.snippet_type} for s in snippets_for_selection
    ]
    metadata.sort(key=lambda item: item["id"])

    selected_ids = _select_ids(corpus, metadata) if metadata else []
    resolved = _resolve_requires(selected_ids, snippets)

    state = _load_state()
    already_ids: set[str] = set()
    if session_id:
        session_entry = state.get("sessions", {}).get(session_id, {})
        ids = session_entry.get("ids", [])
        already_ids = set(ids)

    new_snippets: list[SnippetMeta] = []
    new_ids: list[str] = []
    for snippet in resolved:
        if snippet.snippet_id in already_ids:
            continue
        new_snippets.append(snippet)
        new_ids.append(snippet.snippet_id)

    if session_id:
        state.setdefault("sessions", {})
        session_ids = set(state["sessions"].get(session_id, {}).get("ids", []))
        session_ids.update(new_ids)
        state["sessions"][session_id] = {"ids": sorted(session_ids)}
        _save_state(state)

    already_lines = "\n".join(f"- {sid}" for sid in sorted(already_ids)) or "- (none)"
    parts: list[str] = ["ALREADY_PROVIDED_IDS:", already_lines, "", "NEW_SNIPPETS:"]

    if not new_snippets:
        parts.append("(none)")
        return "\n".join(parts)

    for snippet in new_snippets:
        try:
            raw = snippet.path.read_text(encoding="utf-8")
            root_path = project_root
            if GLOBAL_SNIPPETS_DIR in snippet.path.parents:
                root_path = GLOBAL_SNIPPETS_DIR.parent.parent
            content = _resolve_inline_refs(raw, snippet_path=snippet.path, root_path=root_path)
        except Exception as exc:
            logger.exception("context_selector_read_failed", path=str(snippet.path), error=str(exc))
            continue
        parts.append(f"--- SNIPPET: {snippet.snippet_id} (scope: {snippet.scope}) ---")
        parts.append(content)

    return "\n".join(parts)
