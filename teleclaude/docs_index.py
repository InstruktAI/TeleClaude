"""Build and manage doc snippet index.yaml files.

Handles title normalization, index generation, and global collision checking.
Does NOT validate — that's resource_validation.py.

Called by ``telec sync``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Mapping

import frontmatter
import yaml
from instrukt_ai_logging import get_logger
from typing_extensions import NotRequired, TypedDict

from teleclaude.config.loader import load_project_config
from teleclaude.constants import TYPE_SUFFIX
from teleclaude.required_reads import extract_required_reads as _extract_required_reads
from teleclaude.snippet_validation import load_domains  # noqa: F401 — re-exported for callers

__all__ = ["DEFAULT_ROLE", "ROLE_LEVELS", "ROLE_RANK", "load_domains"]

logger = get_logger(__name__)

# Role hierarchy: the minimum role required to see a snippet.
ROLE_LEVELS = ("public", "member", "admin")
ROLE_RANK: dict[str, int] = {level: i for i, level in enumerate(ROLE_LEVELS)}
DEFAULT_ROLE = "member"

_H1_LINE = re.compile(r"^#\s+")


def _teleclaude_root() -> str:
    """Return teleclaude root path with tilde (portable)."""
    return "~/.teleclaude"


def _split_frontmatter_block(content: str) -> tuple[str, str, bool]:
    """Split top-level frontmatter block from body.

    Returns:
        header_with_fences, body, has_frontmatter
    """
    lines = content.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return "", content, False
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return "", content, False
    header = "".join(lines[: end_idx + 1])
    body = "".join(lines[end_idx + 1 :])
    return header, body, True


def _normalize_frontmatter_single_quotes(content: str) -> str:
    """Normalize frontmatter scalars to single-quoted values.

    TODO: GitHub issue openai/codex#11495
    Remove this compatibility normalization once Codex CLI frontmatter false
    positives are fixed upstream.
    """
    header, body, has_frontmatter = _split_frontmatter_block(content)
    if not has_frontmatter:
        return content

    header_lines = header.splitlines(keepends=False)
    if len(header_lines) < 2:
        return content
    raw_frontmatter = "\n".join(header_lines[1:-1])
    try:
        payload = yaml.safe_load(raw_frontmatter)
    except Exception:
        return content
    if not isinstance(payload, dict):
        return content
    if any(isinstance(v, (dict, list, tuple, set)) for v in payload.values()):
        return content

    rendered_lines: list[str] = ["---"]
    for key, value in payload.items():
        value_str = "" if value is None else str(value)
        value_quoted = "'" + value_str.replace("'", "''") + "'"
        rendered_lines.append(f"{key}: {value_quoted}")
    rendered_lines.append("---")
    rendered_header = "\n".join(rendered_lines) + "\n"

    normalized = rendered_header + body
    return normalized if normalized != content else content


# ---------------------------------------------------------------------------
# Type definitions
# ---------------------------------------------------------------------------


class SnippetEntry(TypedDict):
    id: str
    description: str
    type: str
    scope: str
    path: str
    source_project: NotRequired[str]
    role: NotRequired[str]


class IndexPayload(TypedDict):
    project_root: str
    snippets_root: str
    snippets: list[SnippetEntry]


class ThirdPartyEntry(TypedDict):
    """Third-party doc entry - no type field (not part of taxonomy)."""

    id: str
    description: str
    scope: str
    path: str


class ThirdPartyIndexPayload(TypedDict):
    snippets_root: str
    snippets: list[ThirdPartyEntry]


# ---------------------------------------------------------------------------
# Title normalization
# ---------------------------------------------------------------------------


def _normalize_title(file_path: Path, content: str, declared_type: str | None) -> str:
    """Ensure H1 title has the correct type suffix (e.g. '— Policy')."""
    suffix = TYPE_SUFFIX.get((declared_type or "").lower())
    if not suffix:
        inferred = _infer_type_from_path(file_path)
        suffix = TYPE_SUFFIX.get(inferred) if inferred else None
    if not suffix:
        return content
    lines = content.splitlines()
    if not lines or not _H1_LINE.match(lines[0]):
        return content
    title = lines[0].lstrip("#").strip()
    expected = f" — {suffix}"
    if title.endswith(expected):
        return content
    base = title.split(" — ")[0].strip() if " — " in title else title
    lines[0] = f"# {base}{expected}"
    return "\n".join(lines) + ("\n" if content.endswith("\n") else "")


def _infer_type_from_path(file_path: Path) -> str | None:
    parts = list(file_path.parts)
    try:
        baseline_idx = parts.index("baseline")
    except ValueError:
        return None
    if baseline_idx + 1 >= len(parts):
        return None
    folder = parts[baseline_idx + 1]
    return folder if folder in TYPE_SUFFIX else None


def normalize_titles(snippets_root: Path) -> None:
    """Normalize H1 titles in all snippets to include the type suffix."""
    for path in sorted(snippets_root.rglob("*.md")):
        if path.name == "index.yaml" or path.name == "index.md":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception as exc:
            logger.warning("title_read_failed", path=str(path), error=str(exc))
            continue
        normalized_text = _normalize_frontmatter_single_quotes(text)
        declared_type = None
        if normalized_text.lstrip().startswith("---"):
            try:
                post = frontmatter.loads(normalized_text)
                meta = post.metadata or {}
                declared_type = meta.get("type") if isinstance(meta.get("type"), str) else None
                body = post.content
            except Exception:
                body = normalized_text
        else:
            body = normalized_text
        updated = _normalize_title(path, body, declared_type)
        final_content = normalized_text
        if updated != body:
            if normalized_text.lstrip().startswith("---"):
                header, _, has_frontmatter = _split_frontmatter_block(normalized_text)
                final_content = f"{header}{updated}" if has_frontmatter else updated
            else:
                final_content = updated
        if final_content != text:
            try:
                path.write_text(final_content, encoding="utf-8")
            except Exception as exc:
                logger.warning("title_write_failed", path=str(path), error=str(exc))


def write_third_party_index(project_root: Path) -> None:
    """Generate third-party/index.md with @refs to all third-party docs."""
    third_party_root = project_root / "docs" / "third-party"
    if not third_party_root.exists():
        return
    docs_root = project_root / "docs"
    entries: list[str] = []
    for path in sorted(third_party_root.rglob("*.md")):
        if path.name == "index.md":
            continue
        try:
            rel = path.relative_to(docs_root).as_posix()
        except ValueError:
            continue
        entries.append(f"@docs/{rel}")
    if not entries:
        return
    index_path = third_party_root / "index.md"
    content = "\n".join([*entries, ""])
    if index_path.exists():
        existing = index_path.read_text(encoding="utf-8")
        if existing == content:
            return
    index_path.write_text(content, encoding="utf-8")


def _extract_description_from_md(file_path: Path) -> str:
    """Extract description from markdown file (first H1 title or filename)."""
    try:
        text = file_path.read_text(encoding="utf-8")
    except Exception:
        return file_path.stem

    # Try frontmatter first
    if text.lstrip().startswith("---"):
        try:
            post = frontmatter.loads(text)
            desc = post.metadata.get("description") if post.metadata else None
            if isinstance(desc, str) and desc.strip():
                return desc.strip()
        except Exception:
            pass

    # Fall back to first H1 title
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            title = stripped[2:].strip()
            # Remove type suffix if present (e.g., "— Spec")
            if " — " in title:
                title = title.split(" — ")[0].strip()
            return title

    return file_path.stem


def write_third_party_index_yaml(third_party_root: Path, scope: str) -> Path | None:
    """Generate index.yaml for third-party docs.

    Args:
        third_party_root: Path to third-party directory (e.g., docs/third-party or ~/.teleclaude/docs/third-party)
        scope: Either "project" or "global"

    Returns:
        Path to the generated index.yaml, or None if no docs found.
    """
    if not third_party_root.exists():
        return None

    entries: list[ThirdPartyEntry] = []
    for path in sorted(third_party_root.rglob("*.md")):
        if path.name in ("index.md", "index.yaml"):
            continue

        # Build ID from relative path (e.g., "third-party/react/hooks")
        try:
            rel = path.relative_to(third_party_root).as_posix()
        except ValueError:
            continue

        # Remove .md extension for ID
        snippet_id = f"third-party/{rel}"
        if snippet_id.endswith(".md"):
            snippet_id = snippet_id[:-3]

        description = _extract_description_from_md(path)

        # Path relative to snippets_root for loading
        entry: ThirdPartyEntry = {
            "id": snippet_id,
            "description": description,
            "scope": scope,
            "path": rel,
        }
        entries.append(entry)

    index_path = third_party_root / "index.yaml"

    if not entries:
        if index_path.exists():
            index_path.unlink()
        return None

    # Build payload
    home = str(Path.home())
    root_str = str(third_party_root)
    if root_str.startswith(home):
        root_str = root_str.replace(home, "~", 1)

    payload: ThirdPartyIndexPayload = {
        "snippets_root": root_str,
        "snippets": entries,
    }

    rendered = yaml.safe_dump(payload, sort_keys=False, allow_unicode=False)
    if index_path.exists():
        existing = index_path.read_text(encoding="utf-8")
        if existing == rendered:
            return index_path

    index_path.write_text(rendered, encoding="utf-8")
    return index_path


def remove_non_baseline_indexes(snippets_root: Path) -> list[str]:
    """Remove stale index.md files outside baseline/. Returns removed paths."""
    removed: list[str] = []
    for path in sorted(snippets_root.rglob("index.md")):
        if "baseline" in path.parts or "third-party" in path.parts:
            continue
        try:
            path.unlink()
            removed.append(str(path))
            logger.warning("index_removed", path=str(path))
        except Exception as exc:
            logger.warning("index_remove_failed", path=str(path), error=str(exc))
    return removed


# ---------------------------------------------------------------------------
# Required reads extraction
# ---------------------------------------------------------------------------


def extract_required_reads(content: str) -> list[str]:
    """Extract ``@`` paths from the Required Reads section."""
    refs, _ = _extract_required_reads(content)
    return refs


# ---------------------------------------------------------------------------
# Snippet root discovery
# ---------------------------------------------------------------------------


def snippet_files(snippets_root: Path, *, include_baseline: bool) -> list[Path]:
    """List all .md snippet files under a root, optionally including baseline."""
    files = [path for path in snippets_root.rglob("*.md") if path.name != "index.yaml"]
    if include_baseline:
        return files
    return [path for path in files if "baseline" not in path.parts]


def iter_snippet_roots(project_root: Path) -> list[Path]:
    """Find all snippet root directories under the project."""
    roots: list[Path] = []
    candidates = [
        project_root / "docs" / "global",
        project_root / "docs" / "project",
        project_root / "agents" / "docs",
    ]
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            rel_path = candidate.relative_to(project_root)
            include_baseline = str(rel_path) in ("docs/global", "agents/docs")
        except ValueError:
            include_baseline = False
        if snippet_files(candidate, include_baseline=include_baseline):
            roots.append(candidate)
    return roots


# ---------------------------------------------------------------------------
# Project config helpers
# ---------------------------------------------------------------------------


def ensure_project_config(project_root: Path) -> None:
    """Create a minimal teleclaude.yml if one does not exist."""
    config_path = project_root / "teleclaude.yml"
    if config_path.exists():
        return
    config_path.write_text(
        "business:\n  domains:\n    software-development: docs\n",
        encoding="utf-8",
    )


def get_project_name(project_root: Path) -> str:
    """Get project name from config or directory name."""
    config_file = project_root / "teleclaude.yml"
    if config_file.exists():
        config = load_project_config(config_file)
        if config.project_name:
            return config.project_name
    return project_root.name


# ---------------------------------------------------------------------------
# Global collision checking
# ---------------------------------------------------------------------------


def check_global_collisions(
    snippets: list[SnippetEntry],
    project_root: Path,
    snippets_root: Path,
) -> None:
    """Check for ID collisions with global documentation. Raises SystemExit on collision."""
    try:
        rel_path = snippets_root.relative_to(project_root)
        if str(rel_path) != "docs/global" and "agents/docs" not in str(rel_path):
            return
    except ValueError:
        return

    if "baseline" in str(project_root):
        return

    global_index_path = Path.home() / ".teleclaude" / "docs" / "index.yaml"
    if not global_index_path.exists():
        return

    try:
        global_data = yaml.safe_load(global_index_path.read_text(encoding="utf-8"))
    except Exception:
        return

    if not isinstance(global_data, dict) or "snippets" not in global_data:
        return

    global_snippets: dict[str, str] = {}
    for entry in global_data["snippets"]:
        if isinstance(entry, dict):
            snippet_id = entry.get("id")
            source_project = entry.get("source_project", "unknown")
            if snippet_id:
                global_snippets[snippet_id] = source_project

    current_project = get_project_name(project_root)
    collisions = []
    for snippet in snippets:
        snippet_id = snippet["id"]
        if snippet_id in global_snippets:
            owner = global_snippets[snippet_id]
            if owner != current_project:
                collisions.append((snippet_id, owner, snippet.get("path", "")))

    if collisions:
        error_msg = ["", "=" * 80, "ERROR: Global snippet ID collision(s) detected", "=" * 80, ""]
        for snippet_id, owner, path in collisions:
            error_msg.extend(
                [
                    f"ID: {snippet_id}",
                    f"Your project: {current_project}",
                    f"Already owned by: {owner}",
                    f"Your file: {path}",
                    "",
                ]
            )
        error_msg.append("=" * 80)
        raise SystemExit("\n".join(error_msg))


# ---------------------------------------------------------------------------
# Index building
# ---------------------------------------------------------------------------


def build_index_payload(project_root: Path, snippets_root: Path) -> IndexPayload:
    """Build the index.yaml payload for a snippet root. Modifies files as side effects
    (normalizes titles, removes stale indexes)."""
    remove_non_baseline_indexes(snippets_root)
    normalize_titles(snippets_root)

    if not snippets_root.exists():
        return {"project_root": str(project_root), "snippets_root": str(snippets_root), "snippets": []}

    snippet_cache: list[tuple[Path, Mapping[str, object]]] = []
    snippets: list[SnippetEntry] = []

    try:
        rel_path = snippets_root.relative_to(project_root)
        include_baseline = str(rel_path) in ("docs/global", "agents/docs")
    except ValueError:
        include_baseline = False

    files = sorted(snippet_files(snippets_root, include_baseline=include_baseline))
    if not files:
        return {"project_root": str(project_root), "snippets_root": str(snippets_root), "snippets": []}

    baseline_root = snippets_root / "baseline"
    for file_path in files:
        if include_baseline and baseline_root in file_path.parents:
            try:
                rel = file_path.relative_to(baseline_root).as_posix()
            except ValueError:
                rel = file_path.name
            snippet_id = f"baseline/{rel}"
            if snippet_id.endswith(".md"):
                snippet_id = snippet_id[: -len(".md")]
            snippet_type = rel.split("/", 1)[0] if "/" in rel else "principle"
            try:
                text = file_path.read_text(encoding="utf-8")
            except Exception:
                text = ""
            title_line = next(
                (line.strip() for line in text.splitlines() if line.strip().startswith("# ")),
                "",
            )
            description = title_line.lstrip("# ").strip() if title_line else snippet_id
            try:
                relative_path = str(file_path.relative_to(project_root))
            except ValueError:
                relative_path = str(file_path)
            snippets.append(
                {
                    "id": snippet_id,
                    "description": description,
                    "type": snippet_type,
                    "scope": "global",
                    "path": relative_path,
                }
            )
            continue

        post = frontmatter.load(file_path)
        metadata: Mapping[str, object] = post.metadata or {}
        snippet_cache.append((file_path, metadata))

    for file_path, metadata in snippet_cache:
        snippet_id_val = metadata.get("id")
        description = metadata.get("description")
        snippet_type = metadata.get("type")
        snippet_scope = metadata.get("scope")
        if (
            not isinstance(snippet_id_val, str)
            or not isinstance(description, str)
            or not isinstance(snippet_type, str)
            or not isinstance(snippet_scope, str)
        ):
            continue
        try:
            relative_path = str(file_path.relative_to(project_root))
        except ValueError:
            relative_path = str(file_path)
        entry: SnippetEntry = {
            "id": snippet_id_val,
            "description": description,
            "type": snippet_type,
            "scope": snippet_scope,
            "path": relative_path,
        }
        # Store role from frontmatter, or default.
        raw_role = metadata.get("role")
        if isinstance(raw_role, str) and raw_role in ROLE_RANK:
            entry["role"] = raw_role
        else:
            entry["role"] = DEFAULT_ROLE
        snippets.append(entry)

    snippets.sort(key=lambda e: e["id"])
    check_global_collisions(snippets, project_root, snippets_root)

    project_name = get_project_name(project_root)
    for snippet in snippets:
        snippet["source_project"] = project_name

    try:
        rel_path = snippets_root.relative_to(project_root)
        is_global = str(rel_path) in ("docs/global", "agents/docs")
    except ValueError:
        is_global = False

    if is_global:
        root = _teleclaude_root()
        snippets_root_str = f"{root}/docs"
        for snippet in snippets:
            p = snippet["path"]
            if p.startswith("docs/global/"):
                snippet["path"] = p.replace("docs/global/", "docs/", 1)
    else:
        home = str(Path.home())
        project_root_str = str(project_root)
        root = project_root_str.replace(home, "~", 1) if project_root_str.startswith(home) else project_root_str
        snippets_root_str = str(snippets_root)
        if snippets_root_str.startswith(home):
            snippets_root_str = snippets_root_str.replace(home, "~", 1)

    return {"project_root": root, "snippets_root": snippets_root_str, "snippets": snippets}


def write_index_yaml(project_root: Path, snippets_root: Path) -> Path:
    """Build and write index.yaml for a snippet root. Returns the target path."""
    target = snippets_root / "index.yaml"
    # Third-party indexes are handled separately by write_third_party_index_yaml
    if "third-party" in snippets_root.parts:
        return target
    payload = build_index_payload(project_root, snippets_root)
    if not payload["snippets"]:
        if target.exists():
            target.unlink()
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    rendered = yaml.safe_dump(payload, sort_keys=False, allow_unicode=False)
    if target.exists():
        existing = target.read_text(encoding="utf-8")
        if existing == rendered:
            return target
    target.write_text(rendered, encoding="utf-8")
    return target


def build_all_indexes(project_root: Path) -> list[Path]:
    """Build index.yaml for all snippet roots. Main entry point."""
    ensure_project_config(project_root)
    write_third_party_index(project_root)  # Generates index.md with @refs
    roots = iter_snippet_roots(project_root)
    written: list[Path] = []
    for snippets_root in roots:
        written.append(write_index_yaml(project_root, snippets_root))

    # Generate third-party index.yaml (separate from taxonomy)
    third_party_root = project_root / "docs" / "third-party"
    third_party_index = write_third_party_index_yaml(third_party_root, scope="project")
    if third_party_index:
        written.append(third_party_index)

    return written
