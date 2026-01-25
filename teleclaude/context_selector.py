from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, TypedDict

import yaml
from instrukt_ai_logging import get_logger

from teleclaude.paths import CONTEXT_STATE_PATH, GLOBAL_SNIPPETS_DIR
from teleclaude.utils import expand_env_vars

logger = get_logger(__name__)

SCOPE_ORDER = {"global": 0, "domain": 0, "project": 1}


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

_TEST_ENABLED_ENV = "TELECLAUDE_GET_CONTEXT_TESTING"


def _write_test_output(
    *,
    phase: str,
    areas: list[str],
    index_ids: list[str],
    selected_ids: list[str],
    test_agent: str | None = None,
    test_mode: str | None = None,
    test_request: str | None = None,
    test_csv_path: str | None = None,
) -> None:
    if not os.getenv(_TEST_ENABLED_ENV):
        return
    csv_path = test_csv_path
    agent = test_agent
    mode = test_mode
    request_text = (test_request or "").strip()
    if not csv_path or not agent or not mode or not request_text:
        return
    if mode not in {"fast", "med", "slow"}:
        return
    try:
        rows = []
        with open(csv_path, "r", encoding="utf-8") as handle:
            header = handle.readline().strip().split(",")
            for line in handle:
                rows.append(line.strip().split(","))
    except Exception:
        return
    if not header:
        return

    def _set(row: list[str], col: str, value: str) -> None:
        if col not in header:
            return
        idx = header.index(col)
        while len(row) <= idx:
            row.append("")
        row[idx] = value

    for row in rows:
        if not row:
            continue
        if len(row) <= 2:
            continue
        if row[1] != agent:
            continue
        variants = row[2].split("|") if row[2] else []
        if request_text not in [v.strip() for v in variants]:
            continue
        if phase == "phase1":
            _set(row, f"{mode}_phase1_areas", "|".join(areas))
            _set(row, f"{mode}_phase1_index_ids", "|".join(index_ids))
        if phase == "phase2":
            _set(row, f"{mode}_phase2_selected_ids", "|".join(selected_ids))
        break

    try:
        with open(csv_path, "w", encoding="utf-8") as handle:
            handle.write(",".join(header) + "\n")
            for row in rows:
                handle.write(",".join(row) + "\n")
    except Exception:
        return


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


def _domain_for_snippet(snippet: SnippetMeta, *, project_domains: dict[str, Path]) -> str:
    snippet_id = snippet.snippet_id
    for domain, root in project_domains.items():
        if root in snippet.path.parents or root == snippet.path.parent:
            return domain
    return snippet_id.split("/", 1)[0] if "/" in snippet_id else snippet_id


def _load_project_domains(project_root: Path) -> dict[str, Path]:
    config_path = project_root / "teleclaude.yml"
    if not config_path.exists():
        return {"software-development": project_root / "docs"}
    try:
        payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {"software-development": project_root / "docs"}
    if not isinstance(payload, dict):
        return {"software-development": project_root / "docs"}
    expanded = expand_env_vars(payload)
    if not isinstance(expanded, dict):
        return {"software-development": project_root / "docs"}
    payload = expanded
    business = payload.get("business", {})
    if not isinstance(business, dict):
        return {"software-development": project_root / "docs"}
    domains = business.get("domains", {})
    if isinstance(domains, list):
        clean = [d for d in domains if isinstance(d, str) and d.strip()]
        return {d: project_root / "docs" for d in (clean or ["software-development"])}
    if not isinstance(domains, dict):
        return {"software-development": project_root / "docs"}
    clean_map: dict[str, Path] = {}
    for key, value in domains.items():
        if not isinstance(key, str) or not key.strip():
            continue
        if isinstance(value, str) and value.strip():
            candidate = (project_root / value).resolve()
        else:
            candidate = (project_root / "docs").resolve()
        clean_map[key] = candidate
    return clean_map or {"software-development": project_root / "docs"}


def _output_scope(snippet: SnippetMeta, *, global_snippets_root: Path) -> str:
    if global_snippets_root in snippet.path.parents:
        return "global"
    return "project"


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


def _load_index(index_path: Path) -> list[SnippetMeta]:
    if not index_path.exists():
        logger.warning("snippet_index_missing", path=str(index_path))
        return []

    try:
        payload = yaml.safe_load(index_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.exception("snippet_index_load_failed", path=str(index_path), error=str(exc))
        return []

    if not isinstance(payload, dict):
        return []

    project_root = payload.get("project_root")
    snippets = payload.get("snippets")
    if not isinstance(project_root, str) or not isinstance(snippets, list):
        return []

    root_path = Path(project_root).expanduser().resolve()
    entries: list[SnippetMeta] = []
    for item in snippets:
        if not isinstance(item, dict):
            continue
        snippet_id = item.get("id")
        description = item.get("description")
        snippet_type = item.get("type")
        scope = item.get("scope")
        raw_path = item.get("path")
        requires_raw = item.get("requires", [])
        if (
            not isinstance(snippet_id, str)
            or not isinstance(description, str)
            or not isinstance(snippet_type, str)
            or not isinstance(scope, str)
            or not isinstance(raw_path, str)
        ):
            continue
        requires_list = requires_raw if isinstance(requires_raw, list) else []
        requires: list[str] = [req for req in requires_list if isinstance(req, str)]
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = (root_path / path).resolve()
        entries.append(
            SnippetMeta(
                snippet_id=snippet_id,
                description=description,
                snippet_type=snippet_type,
                scope=scope,
                path=path,
                requires=requires,
            )
        )

    return entries


def _resolve_requires(
    selected_ids: Iterable[str],
    snippets: list[SnippetMeta],
    *,
    global_snippets_root: Path,
) -> list[SnippetMeta]:
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

    resolved.sort(
        key=lambda s: (_scope_rank(_output_scope(s, global_snippets_root=global_snippets_root)), s.snippet_id)
    )
    return resolved


def build_context_output(
    *,
    areas: list[str],
    project_root: Path,
    session_id: str | None,
    snippet_ids: list[str] | None = None,
    test_agent: str | None = None,
    test_mode: str | None = None,
    test_request: str | None = None,
    test_csv_path: str | None = None,
) -> str:
    project_index = project_root / "docs" / "index.yaml"
    global_index = GLOBAL_SNIPPETS_DIR / "index.yaml"
    global_root = GLOBAL_SNIPPETS_DIR.parent.parent
    global_snippets_root = GLOBAL_SNIPPETS_DIR

    # Load global snippets first, then project snippets.
    snippets: list[SnippetMeta] = []
    snippets.extend(_load_index(global_index))
    snippets.extend(_load_index(project_index))

    domains = _load_project_domains(project_root)
    project_domain_roots = {d: p for d, p in domains.items() if p.exists()}
    if not project_domain_roots:
        project_domain_roots = {d: project_root / "docs" for d in domains.keys()}

    def _include_snippet(snippet: SnippetMeta) -> bool:
        if global_snippets_root in snippet.path.parents:
            if snippet.snippet_id.startswith("baseline/"):
                return True
            return any(snippet.snippet_id.startswith(f"{domain}/") for domain in domains)
        if snippet.scope == "project":
            return any(
                root in snippet.path.parents or root == snippet.path.parent for root in project_domain_roots.values()
            )
        return True

    snippets = [snippet for snippet in snippets if _include_snippet(snippet)]

    areas_set = set(areas)
    if areas_set:
        snippets_for_selection = [s for s in snippets if s.snippet_type in areas_set]
    else:
        snippets_for_selection = list(snippets)

    if not snippet_ids:
        parts: list[str] = [
            "# PHASE 1: Snippet Index (Frontmatter Only)",
            "# Review the snippets below and select the IDs you need.",
            "",
        ]
        ordered = sorted(
            snippets_for_selection,
            key=lambda s: (_scope_rank(_output_scope(s, global_snippets_root=global_snippets_root)), s.snippet_id),
        )
        _write_test_output(
            phase="phase1",
            areas=areas,
            index_ids=[snippet.snippet_id for snippet in ordered],
            selected_ids=[],
            test_agent=test_agent,
            test_mode=test_mode,
            test_request=test_request,
            test_csv_path=test_csv_path,
        )
        for snippet in ordered:
            domain = _domain_for_snippet(snippet, project_domains=project_domain_roots)
            scope = _output_scope(snippet, global_snippets_root=global_snippets_root)
            parts.append(
                "\n".join(
                    [
                        "---",
                        f"id: {snippet.snippet_id}",
                        f"type: {snippet.snippet_type}",
                        f"domain: {domain}",
                        f"scope: {scope}",
                        f"description: {snippet.description}",
                        "---",
                    ]
                ).strip()
            )
        parts.extend(
            [
                "",
                "# ⚠️  IMPORTANT: Call teleclaude__get_context again with the snippet IDs of interest!",
            ]
        )
        return "\n".join(parts)

    valid_ids = {s.snippet_id for s in snippets}
    selected_ids = [sid for sid in (snippet_ids or []) if sid in valid_ids]
    resolved = _resolve_requires(selected_ids, snippets, global_snippets_root=global_snippets_root)
    _write_test_output(
        phase="phase2",
        areas=areas,
        index_ids=[],
        selected_ids=selected_ids,
        test_agent=test_agent,
        test_mode=test_mode,
        test_request=test_request,
        test_csv_path=test_csv_path,
    )

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

    logger.debug(
        "context_selector_output_summary",
        selected_ids_count=len(selected_ids),
        resolved_snippets_count=len(resolved),
        new_snippets_count=len(new_snippets),
    )

    if session_id:
        state.setdefault("sessions", {})
        session_ids = set(state["sessions"].get(session_id, {}).get("ids", []))
        session_ids.update(new_ids)
        state["sessions"][session_id] = {"ids": sorted(session_ids)}
        _save_state(state)

    parts: list[str] = []
    if session_id is not None:
        already_lines = "\n".join(f"- {sid}" for sid in sorted(already_ids)) or "- (none)"
        parts.extend(["ALREADY_PROVIDED_IDS:", already_lines, ""])
    parts.append("NEW_SNIPPETS:")

    if not new_snippets:
        parts.append("(none)")
        return "\n".join(parts)

    for snippet in new_snippets:
        try:
            raw = snippet.path.read_text(encoding="utf-8")
            root_path = project_root
            if global_snippets_root in snippet.path.parents:
                root_path = global_root
            content = _resolve_inline_refs(raw, snippet_path=snippet.path, root_path=root_path)
            _, body = _split_frontmatter(content)
        except Exception as exc:
            logger.exception("context_selector_read_failed", path=str(snippet.path), error=str(exc))
            continue
        domain = _domain_for_snippet(snippet, project_domains=project_domain_roots)
        scope = _output_scope(snippet, global_snippets_root=global_snippets_root)
        parts.append(
            "\n".join(
                [
                    "---",
                    f"id: {snippet.snippet_id}",
                    f"type: {snippet.snippet_type}",
                    f"domain: {domain}",
                    f"scope: {scope}",
                    f"description: {snippet.description}",
                    "---",
                ]
            ).strip()
        )
        parts.append(body.lstrip("\n"))

    return "\n".join(parts)
