#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "python-frontmatter",
#     "pyyaml",
#     "pydantic",
#     "aiohttp",
#     "dateparser",
#     "munch",
#     "instruktai-python-logger",
#     "python-dotenv",
# ]
# ///
"""Transpile and deploy agent artifacts and generated documentation."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Literal, NamedTuple, NotRequired, cast

import frontmatter
import yaml
from frontmatter import Post
from frontmatter.default_handlers import YAMLHandler
from typing_extensions import TypedDict

# Allow running from any working directory by anchoring imports at repo root.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from teleclaude.doc_body import apply_planned_change_sections, apply_planned_sections
from teleclaude.domains import publishes_for_root
from teleclaude.paths import COMMANDS_DIR, GLOBAL_DOCS_DIR
from teleclaude.project_manifest import load_roots
from teleclaude.required_reads import extract_required_reads, normalize_required_refs
from teleclaude.resource_validation import INCLUDE_DIRECTIVE_RE, resolve_ref_path, validate_artifact
from teleclaude.slug import normalize_slug
from teleclaude.snippet_validation import derive_snippet_classification, load_domains

Transform = Callable[[Post], str]

INLINE_REF_RE = re.compile(r"@([\w./~\-]+\.md)")
EXEC_DIRECTIVE_RE = re.compile(r"<!--\s*@exec:\s*(.+?)\s*-->")
CONTEXT_PRESERVATION_START = "<!-- TELECLAUDE_CONTEXT_PRESERVATION_START -->"
CONTEXT_PRESERVATION_END = "<!-- TELECLAUDE_CONTEXT_PRESERVATION_END -->"


class StableYAMLHandler(YAMLHandler):  # type: ignore[misc]
    """Frontmatter YAML handler with stable ordering and wide line width."""

    def export(self, metadata: dict[str, object], **kwargs: object) -> str:  # guard: loose-dict - frontmatter contract
        return yaml.safe_dump(  # type: ignore[no-any-return]
            metadata,
            sort_keys=False,
            width=1000,
            default_flow_style=False,
            allow_unicode=True,
        ).rstrip()


_FRONTMATTER_HANDLER = StableYAMLHandler()


def wrap_with_context_markers(content: str, *, is_markdown: bool) -> str:
    """Wrap markdown content with TeleClaude context-preservation markers."""
    if not is_markdown:
        return content
    separator = "" if not content or content.endswith("\n") else "\n"
    return f"{CONTEXT_PRESERVATION_START}\n{content}{separator}{CONTEXT_PRESERVATION_END}\n"


def dump_frontmatter(post: Post) -> str:
    """Serialize frontmatter using the stable YAML handler.

    When the post has a ``parameters`` field, the preamble is injected
    into the body and the field is stripped from emitted frontmatter.
    """
    parameters = post.metadata.pop("parameters", None)
    if parameters:
        post.content = _inject_parameter_preamble(post.content, parameters)
    return str(frontmatter.dumps(post, handler=_FRONTMATTER_HANDLER))


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


def _normalize_frontmatter_single_quotes_for_codex(content: str) -> str:
    """Normalize Codex frontmatter scalars to explicit single-quoted values.

    Note: GitHub issue openai/codex#11495 tracks removal of this workaround.
    Remove this Codex-only compatibility path once upstream frontmatter parsing
    false positives are fixed.
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
    except yaml.YAMLError:
        return content
    if not isinstance(payload, dict):
        return content

    rendered_lines: list[str] = ["---"]
    for key, value in payload.items():
        if isinstance(value, (dict, list, tuple, set)):
            nested = yaml.safe_dump(
                {key: value},
                sort_keys=False,
                width=1000,
                default_flow_style=False,
                allow_unicode=True,
            ).rstrip()
            rendered_lines.extend(nested.splitlines())
            continue
        value_str = "" if value is None else str(value)
        value_quoted = "'" + value_str.replace("'", "''") + "'"
        rendered_lines.append(f"{key}: {value_quoted}")
    rendered_lines.append("---")
    rendered_header = "\n".join(rendered_lines) + "\n"

    normalized = rendered_header + body
    return normalized if normalized != content else content


def _format_markdown(paths: list[str]) -> None:
    """Format markdown outputs using the repo prettier setup."""
    md_files = [p for p in paths if p.endswith(".md") and os.path.exists(p)]
    if not md_files:
        return
    prettier = shutil.which("prettier")
    if prettier:
        subprocess.run([prettier, "--write", *md_files], check=False)
        return
    subprocess.run(["npx", "--yes", "prettier", "--write", *md_files], check=False)


ArtifactFrontmatter = TypedDict(
    "ArtifactFrontmatter",
    {
        "description": str,
        "name": str,
        "argument-hint": str,
        "domain": str,
        "hooks": object,
        "parameters": list[
            dict[str, object]  # guard: loose-dict - TOML parsed data — pyproject config
        ],  # guard: loose-dict - Parameter dicts have variable schema per artifact type
    },
    total=False,
)


class SnippetIndexEntry(TypedDict, total=False):
    """Snippet entry loaded from docs index.yaml."""

    id: str
    description: str
    type: str
    scope: str
    domain: str
    activation_trigger: str | None
    needs_domain_baseline: bool
    path: str


class AgentConfig(TypedDict):
    """Agent-specific output and deploy paths."""

    check_dir: str
    prefix: str
    master_dest: str
    commands_dest_dir: str
    agents_dest_dir: str
    skills_dest_dir: str
    skills_ext: str
    ext: str
    transform: Transform
    deploy_master_dest: NotRequired[str]
    deploy_commands_dest: NotRequired[str]
    deploy_agents_dest: NotRequired[str]
    deploy_skills_dest: NotRequired[str]


class FileArtifactType(NamedTuple):
    """Artifact type metadata for source, dist, and deploy phases."""

    name: str
    source_dir_key: str
    dest_dir_key: str
    deploy_dir_key: str
    ext_key: str
    kind: Literal["file", "skill"]
    artifact_kind: str  # "agent", "command", or "skill" — passed to validate_artifact


def _mirror_exclusions_for_agent(
    config: AgentConfig,
    specs: list[FileArtifactType],
) -> frozenset[str]:
    """Staging basenames whose explicit ``deploy_*_dest`` lands outside the agent's home root.

    The per-agent mirror copies ``dist/<agent>/`` into ``~/.{agent}/`` (global
    phase) or ``project_root/.{agent}/`` (local phase). When a spec's explicit
    deploy target lives OUTSIDE the agent's home root (``config["check_dir"]``)
    — Codex commands route to ``~/.teleclaude/commands`` (outside ``~/.codex``)
    — mirroring the staging subdir into the home root produces a dead duplicate.
    Such basenames are reported here so the blanket copytree can skip them while
    the explicit deploy still writes them to the external destination.

    Other artifacts whose deploy target lives under ``check_dir`` (Claude/Gemini
    commands) are NOT excluded — the blanket mirror places them correctly in
    both phases.
    """
    excluded: set[str] = set()
    agent_home = os.path.normpath(config["check_dir"])
    for spec in specs:
        deploy_dest = str(config.get(spec.deploy_dir_key) or "")
        if not deploy_dest:
            continue
        dest_basename = os.path.basename(str(config.get(spec.dest_dir_key) or ""))
        if not dest_basename:
            continue
        deploy_norm = os.path.normpath(deploy_dest)
        if deploy_norm != agent_home and not deploy_norm.startswith(agent_home + os.sep):
            excluded.add(dest_basename)
    return frozenset(excluded)


def _deploy_agent(
    *,
    dist_agent_root: str,
    target_root: str,
    config: AgentConfig,
    specs: list[FileArtifactType],
) -> None:
    """Mirror ``dist/<agent>/`` into ``target_root`` and route externally-deployed subdirs.

    Blanket-mirrors the staging tree, skipping any artifact subdir whose explicit
    deploy lands outside the agent's home root (see ``_mirror_exclusions_for_agent``).
    Then walks the specs and explicitly copies each artifact whose deploy target
    differs from the mirror destination — preserving the existing dual-write for
    artifacts that map both into the agent home and an external location.
    """
    os.makedirs(target_root, exist_ok=True)
    excluded_basenames = _mirror_exclusions_for_agent(config, specs)

    def _ignore(
        directory: str,
        _names: list[str],
        _root: str = dist_agent_root,
        _excluded: frozenset[str] = excluded_basenames,
    ) -> frozenset[str]:
        return _excluded if directory == _root else frozenset()

    shutil.copytree(dist_agent_root, target_root, dirs_exist_ok=True, ignore=_ignore)

    for spec in specs:
        deploy_dest = str(config.get(spec.deploy_dir_key) or "")
        if not deploy_dest:
            continue
        dest_dir_basename = os.path.basename(str(config.get(spec.dest_dir_key) or ""))
        dist_src = os.path.join(dist_agent_root, dest_dir_basename)
        copytree_dest = os.path.join(target_root, dest_dir_basename)
        if os.path.normpath(deploy_dest) != os.path.normpath(copytree_dest) and os.path.isdir(dist_src):
            os.makedirs(deploy_dest, exist_ok=True)
            shutil.copytree(dist_src, deploy_dest, dirs_exist_ok=True)


def transform_to_codex(post: Post) -> str:
    """Transform a post to the Codex format (same as Claude - standard YAML frontmatter).

    Parameter preamble injection is handled by ``dump_frontmatter``.
    """
    # Codex uses Markdown with YAML frontmatter. Force explicit scalar quotes as
    # a compatibility workaround for intermittent frontmatter false positives.
    # Note: GitHub issue openai/codex#11495 tracks removal of this workaround.
    content = _normalize_frontmatter_single_quotes_for_codex(dump_frontmatter(post))
    return content


def transform_to_gemini(post: Post) -> str:
    """Transform a post to the Gemini TOML format.

    Injects the parameter preamble (identical to Claude/Codex) before the
    body content when ``parameters`` is present.
    """
    description = post.metadata.get("description", "")
    parameters = post.metadata.get("parameters")

    description_str = f'"""{description}"""'

    # replace $ARGUMENTS for {{args}} in gemini format
    content = post.content.replace("$ARGUMENTS", "{{args}}").strip()

    if parameters:
        content = _inject_parameter_preamble(content, parameters)

    return f"description = {description_str}\nprompt = '''\n{content}\n'''\n"


def transform_skill_to_claude(post: Post, name: str) -> str:
    """Transform a skill post to Claude format."""
    description = post.metadata.get("description", "")
    transformed_post = Post(post.content, name=name, description=description)
    return dump_frontmatter(transformed_post)


def transform_skill_to_codex(post: Post, name: str) -> str:
    """Transform a skill post to Codex markdown format."""
    metadata = dict(post.metadata)
    metadata["name"] = name
    metadata["description"] = metadata.get("description", "")
    transformed_post = Post(post.content, **metadata)
    content = _normalize_frontmatter_single_quotes_for_codex(dump_frontmatter(transformed_post))
    return content


def transform_skill_to_gemini(post: Post, name: str) -> str:
    """Transform a skill post to Gemini SKILL.md format.

    Same YAML frontmatter as Claude but strips hooks (not supported by Gemini).
    """
    metadata = {"name": name, "description": post.metadata.get("description", "")}
    # Preserve any other metadata except hooks (Gemini doesn't support them)
    for key, value in post.metadata.items():
        if key not in ("name", "description", "hooks"):
            metadata[key] = value
    transformed_post = Post(post.content, **metadata)
    return dump_frontmatter(transformed_post)


def _should_expand_inline(agent_name: str) -> bool:
    return agent_name in {"claude", "codex", "gemini"}


# guard: loose-dict-func - Parameter dicts have variable schema per artifact type
def _build_parameter_preamble(parameters: list[dict[str, object]]) -> str:
    """Build an HTML-comment preamble mapping named parameters to positions.

    Position is derived from list order (index). The preamble does NOT
    reference $ARGUMENTS or {{args}} to avoid empty-string rendering
    when no arguments are provided.
    """
    if not parameters:
        return ""
    lines: list[str] = []
    for idx, param in enumerate(parameters):
        name = param["name"]
        qualifiers: list[str] = []
        if param.get("required"):
            qualifiers.append("required")
        if "default" in param:
            qualifiers.append(f'default: "{param["default"]}"')
        suffix = f" ({', '.join(qualifiers)})" if qualifiers else ""
        lines.append(f"<!-- ${name} = argument at position {idx}{suffix} -->")
    return "\n".join(lines)


# guard: loose-dict-func - Parameter dicts have variable schema per artifact type
def _inject_parameter_preamble(content: str, parameters: list[dict[str, object]]) -> str:
    """Prepend parameter preamble to content if parameters are declared."""
    preamble = _build_parameter_preamble(parameters)
    if not preamble:
        return content
    return f"{preamble}\n\n{content}"


def _filter_frontmatter(metadata: ArtifactFrontmatter, agent_name: str) -> ArtifactFrontmatter:
    filtered = cast(ArtifactFrontmatter, dict(metadata))
    if agent_name != "claude":
        filtered.pop("hooks", None)
    filtered.pop("parameters", None)
    return filtered


def _load_index_entries(index_path: Path) -> dict[str, SnippetIndexEntry]:
    entries: dict[str, SnippetIndexEntry] = {}
    if not index_path.exists():
        return entries
    payload = yaml.safe_load(index_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return entries
    snippets = payload.get("snippets")
    if not isinstance(snippets, list):
        return entries
    for item in snippets:
        if not isinstance(item, dict):
            continue
        snippet_id = item.get("id")
        if isinstance(snippet_id, str):
            entries[snippet_id] = cast(SnippetIndexEntry, dict(item))
    return entries


def _load_snippet_index_entries(project_root: Path) -> dict[str, SnippetIndexEntry]:
    entries: dict[str, SnippetIndexEntry] = {}
    for index_path in (
        project_root / "docs" / "global" / "index.yaml",
        project_root / "docs" / "project" / "index.yaml",
    ):
        entries.update(_load_index_entries(index_path))
    return entries


def _index_entry_for_path(
    path: Path,
    *,
    project_root: Path,
    entries_by_id: dict[str, SnippetIndexEntry],
) -> SnippetIndexEntry | None:
    logical_path = _logical_snippet_path(path, project_root=project_root)
    classification, _ = derive_snippet_classification(
        logical_path, project_root=project_root, domains=load_domains(project_root)
    )
    if classification is None:
        return None
    return entries_by_id.get(classification.id)


def _logical_snippet_path(path: Path, *, project_root: Path) -> Path:
    """Return a project-local logical snippet path for deployed global refs."""
    try:
        path.resolve().relative_to(project_root.resolve())
        return path
    except ValueError:
        pass

    parts = path.resolve().parts
    for scope in ("global", "project"):
        marker = ("docs", scope)
        for index in range(len(parts) - 1):
            if parts[index : index + 2] != marker:
                continue
            tail = Path(*parts[index + 2 :])
            return project_root / "docs" / scope / tail
    return path


def _needs_domain_baseline_domain(content: str, *, project_root: Path, current_path: Path) -> str | None:
    """Domain to stamp on a command whose role procedure requests baseline injection.

    Read from the source content *before* inline expansion strips the `@`-refs:
    if a required-read procedure declares ``needs_domain_baseline: true``, return
    its ``domain`` so the deployed command frontmatter carries it. Dispatch reads
    that frontmatter at SessionStart (frontmatter survives inlining; refs do not).
    """
    entries_by_id = _load_snippet_index_entries(project_root)
    for match in INLINE_REF_RE.finditer(content):
        resolved = resolve_ref_path(match.group(1), root_path=project_root, current_path=current_path)
        if not resolved or not resolved.exists():
            continue
        entry = _index_entry_for_path(resolved, project_root=project_root, entries_by_id=entries_by_id)
        if entry is None:
            continue
        if entry.get("needs_domain_baseline") is True:
            domain = entry.get("domain")
            if isinstance(domain, str) and domain:
                return domain
    return None


def _prepare_post(
    post: Post,
    *,
    agent_prefix: str,
    agent_name: str,
    project_root: Path,
    current_path: Path,
    warn_only: bool,
    kind: str,
) -> Post:
    stamped_domain = (
        _needs_domain_baseline_domain(post.content, project_root=project_root, current_path=current_path)
        if kind == "command"
        else None
    )
    content = process_file(post.content, agent_prefix, agent_name)
    if _should_expand_inline(agent_name):
        content = expand_inline_refs(
            content,
            project_root=project_root,
            current_path=current_path,
            warn_only=warn_only,
        )
    metadata = _filter_frontmatter(post.metadata, agent_name)
    if stamped_domain:
        metadata["domain"] = stamped_domain
    return Post(content, **metadata)


def resolve_skill_name(post: Post, dirname: str) -> str:
    """Resolve the skill name from metadata and validate its directory."""
    name = cast(str, post.metadata.get("name"))
    if not name:
        raise ValueError(f"Skill {dirname} is missing frontmatter 'name'")
    if name != dirname:
        raise ValueError(f"Skill name '{name}' must match folder '{dirname}'")
    return name


def process_file(content: str, agent_prefix: str, agent_name: str) -> str:
    """Apply substitutions to the file content."""
    content = content.replace("{AGENT_PREFIX}", agent_prefix)
    content = content.replace("{{agent}}", agent_name)
    return content


def _render_progressive_index(
    ref_file: Path,
    *,
    project_root: Path,
    entries_by_id: dict[str, SnippetIndexEntry] | None = None,
    warn_only: bool = False,
) -> str:
    """Render a baseline-progressive.md file as a compact index block.

    Instead of inlining full snippet content, reads each referenced file's
    frontmatter to extract snippet ID and description, then renders a scannable
    bullet list that agents can use with ```telec docs get <id>```.
    """
    entries, _ = _collect_progressive_index_entries(
        ref_file, project_root=project_root, entries_by_id=entries_by_id, warn_only=warn_only
    )

    if not entries:
        return ""

    header = "## Baseline index — load via `telec docs get <id>` when relevant\n\n"
    return header + "\n".join(entries)


def _collect_progressive_index_entries(
    ref_file: Path,
    *,
    project_root: Path,
    entries_by_id: dict[str, SnippetIndexEntry] | None = None,
    warn_only: bool = False,
) -> tuple[list[str], list[tuple[str, str]]]:
    content = ref_file.read_text(encoding="utf-8")
    baseline_entries: list[str] = []
    activatable_entries: list[tuple[str, str]] = []
    entries_by_id = entries_by_id or _load_snippet_index_entries(project_root)

    for match in INLINE_REF_RE.finditer(content):
        ref = match.group(1)
        resolved = resolve_ref_path(ref, root_path=project_root, current_path=ref_file)
        if not resolved or not resolved.exists():
            if warn_only:
                print(f"WARNING: Progressive index ref not found: {ref}")
                continue
            raise ValueError(f"Progressive index ref not found: {ref}")

        entry = _index_entry_for_path(resolved, project_root=project_root, entries_by_id=entries_by_id)
        if entry is None:
            if warn_only:
                print(f"WARNING: Progressive index ref missing from index: {ref}")
                continue
            raise ValueError(f"Progressive index ref missing from index: {ref}")
        snippet_id = entry.get("id")
        description = entry.get("description")
        snippet_type = entry.get("type")
        activation_trigger = entry.get("activation_trigger")

        if (
            snippet_type == "procedure"
            and isinstance(snippet_id, str)
            and isinstance(activation_trigger, str)
            and activation_trigger.strip()
        ):
            activatable_entries.append((snippet_id, activation_trigger.strip()))
            continue

        if isinstance(snippet_id, str) and isinstance(description, str) and description:
            baseline_entries.append(f"- `{snippet_id}` — {description}")
        elif isinstance(snippet_id, str) and snippet_id:
            baseline_entries.append(f"- `{snippet_id}`")

    return baseline_entries, activatable_entries


def _render_activatable_procedures(*, project_root: Path, warn_only: bool = False) -> str:
    _ = warn_only
    activatable_by_id: dict[str, str] = {}
    for entry in _load_snippet_index_entries(project_root).values():
        snippet_id = entry.get("id")
        snippet_type = entry.get("type")
        activation_trigger = entry.get("activation_trigger")
        if (
            snippet_type == "procedure"
            and isinstance(snippet_id, str)
            and isinstance(activation_trigger, str)
            and activation_trigger.strip()
        ):
            activatable_by_id[snippet_id] = activation_trigger.strip()
    activatable_entries = sorted(activatable_by_id.items(), key=lambda item: item[0])
    if not activatable_entries:
        return ""
    lines = [f"- `{snippet_id}` — {trigger}" for snippet_id, trigger in activatable_entries]
    header = "## Activatable Procedures — load via `telec docs get <id>` before acting\n\n"
    return header + "\n".join(lines)


def _exec_directive_env(project_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    path_entries = [
        str(project_root / ".venv" / "bin"),
        str(_REPO_ROOT / ".venv" / "bin"),
    ]
    existing_path = env.get("PATH", "")
    if existing_path:
        path_entries.extend(existing_path.split(os.pathsep))
    deduped_entries: list[str] = []
    seen_entries: set[str] = set()
    for entry in path_entries:
        if not entry or entry in seen_entries:
            continue
        seen_entries.add(entry)
        deduped_entries.append(entry)
    env["PATH"] = os.pathsep.join(deduped_entries)
    return env


# Process-lifetime cache: ``@exec`` commands are pure CLI help-text invocations
# that re-running within one ``distribute.py`` run cannot change. The same set
# of directives is expanded once per agent (claude/codex/gemini) and once per
# phase (global + local), so without caching the same ``telec -h``-style
# subprocess fires 20-30+ times and dominates wall time.
_EXEC_DIRECTIVE_CACHE: dict[tuple[str, str], str | None] = {}


def expand_exec_directives(content: str, *, project_root: Path, warn_only: bool = False) -> str:
    """Expand ``<!-- @exec: command -->`` directives by running the command and inserting stdout."""

    def _run(match: re.Match[str]) -> str:
        cmd = match.group(1)
        cache_key = (str(project_root), cmd)
        cached = _EXEC_DIRECTIVE_CACHE.get(cache_key)
        if cached is not None:
            return cached
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=10,
                cwd=project_root,
                env=_exec_directive_env(project_root),
                check=False,
            )
            output = result.stdout.strip()
            if result.returncode != 0:
                msg = f"@exec failed ({result.returncode}): {cmd}"
                if warn_only:
                    print(f"WARNING: {msg}")
                    rendered = match.group(0)
                    _EXEC_DIRECTIVE_CACHE[cache_key] = rendered
                    return rendered
                raise RuntimeError(msg)
            rendered = "" if not output else f"```\n{output}\n```"
            _EXEC_DIRECTIVE_CACHE[cache_key] = rendered
            return rendered
        except subprocess.TimeoutExpired:
            msg = f"@exec timed out: {cmd}"
            if warn_only:
                print(f"WARNING: {msg}")
                rendered = match.group(0)
                _EXEC_DIRECTIVE_CACHE[cache_key] = rendered
                return rendered
            raise RuntimeError(msg) from None

    return EXEC_DIRECTIVE_RE.sub(_run, content)


def expand_include_directives(
    content: str,
    *,
    project_root: Path,
    current_path: Path,
    warn_only: bool = False,
) -> str:
    """Expand ``<!-- @include: path.md -->`` directives by inlining the snippet body at that point.

    Unlike a ``## Required reads`` ``@``-ref — which is hoisted to the top of the
    compiled artifact — an ``@include`` lands the snippet exactly where the comment
    sits, keeping the content adjacent to the instruction that needs it. The
    included body is recursively expanded so it may itself carry ``@``-refs.
    """

    def _render(match: re.Match[str]) -> str:
        ref = match.group(1)
        resolved = resolve_ref_path(ref, root_path=project_root, current_path=current_path)
        if not resolved or not resolved.exists():
            msg = f"@include not found: {ref}"
            if warn_only:
                print(f"WARNING: {msg}")
                return match.group(0)
            raise ValueError(msg)
        post = frontmatter.loads(resolved.read_text(encoding="utf-8"))
        return expand_inline_refs(
            post.content,
            project_root=project_root,
            current_path=resolved,
            warn_only=warn_only,
        ).strip()

    return INCLUDE_DIRECTIVE_RE.sub(_render, content)


def _progressive_block(resolved: Path, *, project_root: Path, warn_only: bool) -> str | None:
    """Render a baseline-progressive ref as its index + activatable list.

    Returns None for non-progressive refs so callers fall through to normal
    inlining; an empty string means a progressive ref that rendered nothing.
    """
    if not resolved.name.startswith("baseline-progressive"):
        return None
    blocks = [
        _render_progressive_index(resolved, project_root=project_root, warn_only=warn_only),
        _render_activatable_procedures(project_root=project_root, warn_only=warn_only),
    ]
    rendered = [block for block in blocks if block]
    return "\n\n".join(rendered) if rendered else ""


def _snippet_body(resolved: Path, *, expand: Callable[[str, Path], str]) -> str | None:
    """Recursively-expanded body of a resolved snippet."""
    post = frontmatter.loads(resolved.read_text(encoding="utf-8"))
    return expand(post.content, resolved).strip()


def expand_inline_refs(
    content: str,
    *,
    project_root: Path,
    current_path: Path,
    warn_only: bool = False,
) -> str:
    """Inline @path.md references into the content (Codex speedup)."""
    seen: set[Path] = set()

    def _expand_document(text: str, *, current_path: Path, depth: int) -> str:
        if depth <= 0:
            return text

        # Mirror the reader contract (context_selector.py): a plain read drops pending
        # planned blocks so baselines ground in current truth, not unbuilt behavior.
        text = apply_planned_change_sections(text, None)
        text = apply_planned_sections(text, None)

        required_refs, stripped = extract_required_reads(text)
        required_refs = normalize_required_refs(required_refs)
        required_sections: list[str] = []
        for ref in required_refs:
            resolved = resolve_ref_path(ref, root_path=project_root, current_path=current_path)
            if not resolved or not resolved.exists():
                message = f"Required read not found: {ref}"
                if warn_only:
                    print(f"WARNING: {message}")
                    continue
                raise ValueError(message)
            if resolved in seen:
                continue
            seen.add(resolved)

            progressive = _progressive_block(resolved, project_root=project_root, warn_only=warn_only)
            if progressive is not None:
                if progressive:
                    required_sections.append(progressive)
                continue

            body = _snippet_body(
                resolved,
                expand=lambda text, cur: _expand_document(text, current_path=cur, depth=depth - 1),
            )
            if body is None:
                continue
            expanded = _strip_leading_separators(_strip_specific_h1(body, "Project baseline").strip())
            if expanded:
                required_sections.append(expanded)

        def _replace(match: re.Match[str]) -> str:
            ref = match.group(1)
            resolved = resolve_ref_path(ref, root_path=project_root, current_path=current_path)
            if not resolved or not resolved.exists():
                return match.group(0)
            if resolved in seen:
                return ""
            seen.add(resolved)

            progressive = _progressive_block(resolved, project_root=project_root, warn_only=warn_only)
            if progressive is not None:
                return f"{progressive}\n" if progressive else ""

            body = _snippet_body(
                resolved,
                expand=lambda text, cur: _expand_document(text, current_path=cur, depth=depth - 1),
            )
            if body is None:
                return ""
            if resolved.name == "index.md":
                return f"{body}\n" if body else ""
            expanded = _strip_leading_separators(_strip_specific_h1(body, "Project baseline").strip())
            return f"---\n\n{expanded}\n" if expanded else ""

        expanded_body = INLINE_REF_RE.sub(_replace, stripped)
        expanded_body = _strip_leading_separators(expanded_body)
        if required_sections:
            required_block = "\n\n---\n\n".join(required_sections).strip()
            if expanded_body.strip():
                return f"{required_block}\n\n---\n\n{expanded_body}"
            return required_block
        return expanded_body

    expanded = _expand_document(content, current_path=current_path, depth=20)
    return _expand_point_directives(expanded, project_root=project_root, current_path=current_path, warn_only=warn_only)


def _expand_point_directives(
    content: str,
    *,
    project_root: Path,
    current_path: Path,
    warn_only: bool = False,
) -> str:
    """Run the in-place directive passes (``@include`` then ``@exec``) over expanded content."""
    if INCLUDE_DIRECTIVE_RE.search(content):
        content = expand_include_directives(
            content, project_root=project_root, current_path=current_path, warn_only=warn_only
        )
    if EXEC_DIRECTIVE_RE.search(content):
        content = expand_exec_directives(content, project_root=project_root, warn_only=warn_only)
    return content


def _inflate_domain_baseline(
    baseline_src: Path,
    domain_src: Path,
    *,
    project_root: Path,
    entries_by_id: dict[str, SnippetIndexEntry] | None = None,
) -> str:
    """Inflate a baseline manifest and append its sibling progressive index.

    The generic baseline-assembly routine, shared by every scope that owns a
    baseline: fully expands ``baseline.md``, then — when a sibling
    ``baseline-progressive.md`` exists — appends its catalogue index so an
    injected worker is aware of every load-on-demand snippet. The progressive
    sibling is optional; where there is a baseline, there is usually (not
    necessarily) a progressive alongside it.
    """
    inflated = expand_inline_refs(
        baseline_src.read_text(encoding="utf-8"),
        project_root=project_root,
        current_path=baseline_src,
    )
    progressive_src = domain_src / "baseline-progressive.md"
    if progressive_src.exists():
        progressive_index = _render_progressive_index(
            progressive_src, project_root=project_root, entries_by_id=entries_by_id
        )
        if progressive_index:
            inflated = f"{inflated.rstrip()}\n\n---\n\n{progressive_index}\n"
    return inflated


# Cross-cutting top-level docs dir always contributed by every publisher that
# has it (not gated by ``publishes``); domains are gated by ``publishes``.
_DOMAIN_AGNOSTIC_DIR = "general"


def _project_slug(project_root: Path) -> str:
    """Canonical slug for a project root, read minimally from ``teleclaude.yml``.

    Mirrors ``teleclaude.docs_index.get_project_slug`` — ``project_slug``, then
    slugified ``project_name``, then slugified directory name — but reads the
    config with a plain ``yaml.safe_load`` so this script does not import the
    index/config-loader chain at module load. That keeps the standalone
    ``uv run`` invocation self-contained instead of dragging in the full app
    dependency graph (per ``scripts``' standalone-execution policy).
    """
    config_file = project_root / "teleclaude.yml"
    if config_file.is_file():
        try:
            payload = yaml.safe_load(config_file.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            payload = None
        if isinstance(payload, dict):
            slug = payload.get("project_slug")
            if isinstance(slug, str) and slug.strip():
                return slug.strip()
            name = payload.get("project_name")
            if isinstance(name, str) and name.strip():
                return normalize_slug(name)
    return normalize_slug(project_root.name)


class _Publisher(NamedTuple):
    """A registered project's global-docs contribution."""

    slug: str
    docs_global: Path
    publishes: frozenset[str]


def gather_publishers(project_root: Path, current_docs_global: Path) -> list[_Publisher]:
    """Collect every registered project that contributes global docs.

    The current project (the one being synced) contributes via
    ``current_docs_global`` — the live checkout, so a worktree's edits compose
    rather than the registered repo's stale copy. Its registered root (and the
    shared git common root, for worktree syncs) is skipped in the manifest sweep
    so it is never counted twice.
    """
    publishers = [
        _Publisher(_project_slug(project_root), current_docs_global, frozenset(publishes_for_root(project_root)))
    ]
    seen = {project_root.resolve(), _resolve_git_common_root(project_root).resolve()}
    for root in load_roots():
        resolved = root.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        docs_global = root / "docs" / "global"
        if not docs_global.is_dir():
            continue
        publishers.append(_Publisher(_project_slug(root), docs_global, frozenset(publishes_for_root(root))))
    return publishers


def _find_mother_publisher(publishers: list[_Publisher]) -> _Publisher | None:
    """The publisher whose global-docs dir is the Mother repo's source tree.

    The cross-cutting ``general`` domain is owned by the Mother repo, identified
    by matching a publisher's ``docs_global`` against ``_REPO_ROOT/docs/global``
    (the same root anchor used elsewhere in this script). When the synced project
    is itself the Mother, its live-checkout ``docs_global`` resolves to that path.
    """
    mother_docs = (_REPO_ROOT / "docs" / "global").resolve()
    for pub in publishers:
        if pub.docs_global.resolve() == mother_docs:
            return pub
    return None


def domain_owners(publishers: list[_Publisher]) -> dict[str, _Publisher]:
    """Map every owned domain to its single owning publisher; block on a split.

    One owner per domain is structural: if two registered publishers declare the
    same domain in ``business.publishes``, the deploy hard-blocks with a
    ``split domain ownership`` error and composes nothing. The cross-cutting
    ``general`` domain is owned by the Mother repo (when it carries a ``general``
    tree), not by any ``publishes`` declaration.
    """
    owner: dict[str, _Publisher] = {}
    # `general` is Mother-owned by definition; reserve it before processing the
    # declarations so a side project that declares `general` in business.publishes
    # is hard-blocked as a split, not silently overridden by Mother afterwards.
    mother = _find_mother_publisher(publishers)
    if mother is not None:
        owner[_DOMAIN_AGNOSTIC_DIR] = mother
    for pub in publishers:
        for domain in sorted(pub.publishes):
            existing = owner.get(domain)
            if existing is not None and existing.slug != pub.slug:
                raise SystemExit(f"split domain ownership: {domain} claimed by {existing.slug} and {pub.slug}")
            owner[domain] = pub
    # Drop the reservation when Mother carries no `general` tree, so composition
    # never tries to link a non-existent source dir.
    if mother is not None and not (mother.docs_global / _DOMAIN_AGNOSTIC_DIR).is_dir():
        owner.pop(_DOMAIN_AGNOSTIC_DIR, None)
    return owner


def compose_docs_root(owner_by_domain: dict[str, _Publisher], deploy_docs_root: Path) -> None:
    """Compose ``~/.teleclaude/docs`` as one directory symlink per owned domain.

    The deployed root is a real directory; each owned domain is a single symlink
    ``<root>/<domain>`` pointing at its owning publisher's ``docs/global/<domain>``
    source folder (a live view). One owner per domain makes this structural — a
    symlink has exactly one target — so a removed or renamed source snippet
    vanishes through the directory symlink with no per-file relink. Build outputs
    (the merged ``index.yaml`` and each domain's ``domain-baseline-bundle.md``)
    are written by their own steps.
    """
    if deploy_docs_root.is_symlink():
        deploy_docs_root.unlink()
    elif deploy_docs_root.is_dir():
        shutil.rmtree(deploy_docs_root)
    elif os.path.lexists(deploy_docs_root):
        deploy_docs_root.unlink(missing_ok=True)
    deploy_docs_root.mkdir(parents=True, exist_ok=True)

    linked = 0
    for domain in sorted(owner_by_domain):
        src = owner_by_domain[domain].docs_global / domain
        if not src.is_dir():
            continue
        (deploy_docs_root / domain).symlink_to(src)
        linked += 1
    print(f"  Composed docs root: {deploy_docs_root} ({linked} domain symlink(s))")


def write_merged_index(publishers: list[_Publisher], deploy_docs_root: Path) -> None:
    """Write the union of every publisher's global ``index.yaml`` to the root.

    One owner per domain (enforced structurally by ``domain_owners`` /
    split detection) makes a cross-owner id collision impossible, so the union is
    a plain first-wins merge — no id-collision guard. Per-domain split detection
    is the single integrity gate, and it runs before composition.
    """
    merged: list[dict[str, object]] = []  # guard: loose-dict - opaque index entries merged from external yaml
    seen_ids: set[str] = set()
    for pub in publishers:
        index_path = pub.docs_global / "index.yaml"
        if not index_path.exists():
            continue
        payload = yaml.safe_load(index_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            continue
        snippets = payload.get("snippets")
        if not isinstance(snippets, list):
            continue
        for item in snippets:
            if not isinstance(item, dict):
                continue
            snippet_id = item.get("id")
            if not isinstance(snippet_id, str) or snippet_id in seen_ids:
                continue
            seen_ids.add(snippet_id)
            merged.append(cast("dict[str, object]", item))  # guard: loose-dict - opaque external index entry
    merged.sort(key=lambda entry: str(entry.get("id", "")))
    out = {"project_root": "~/.teleclaude", "snippets_root": "~/.teleclaude/docs", "snippets": merged}
    (deploy_docs_root / "index.yaml").write_text(
        yaml.safe_dump(out, sort_keys=False, width=1000, allow_unicode=True), encoding="utf-8"
    )
    print(f"  Merged docs index: {deploy_docs_root / 'index.yaml'} ({len(merged)} snippet(s))")


def generate_domain_baselines(
    owner_by_domain: dict[str, _Publisher], deploy_docs_root: Path, project_root: Path
) -> None:
    """Write each owned domain's ``domain-baseline-bundle.md`` into its source dir.

    One owner per domain means a single contributor: each domain's
    ``baseline.md`` is inflated once and written as
    ``<owner>/docs/global/<domain>/domain-baseline-bundle.md`` in the owner's
    source tree (gitignored). Because ``~/.teleclaude/docs/<domain>`` is a
    symlink to that folder, the SessionStart hook path
    ``~/.teleclaude/docs/<domain>/domain-baseline-bundle.md`` resolves through it
    to the same file. The cross-cutting ``general`` domain carries no bundle.
    """
    header_template = "# {name} — Platform Baseline\n\n"
    entries_by_id = _load_index_entries(deploy_docs_root / "index.yaml")
    failures: list[tuple[str, str]] = []
    for domain in sorted(owner_by_domain):
        if domain == _DOMAIN_AGNOSTIC_DIR:
            continue
        domain_src = owner_by_domain[domain].docs_global / domain
        baseline_src = domain_src / "baseline.md"
        if not baseline_src.exists():
            continue
        try:
            inflated = _inflate_domain_baseline(
                baseline_src, domain_src, project_root=project_root, entries_by_id=entries_by_id
            )
        except Exception as e:
            failures.append((domain, str(e)))
            continue
        bundle_dst = domain_src / "domain-baseline-bundle.md"
        bundle_dst.parent.mkdir(parents=True, exist_ok=True)
        bundle_dst.write_text(header_template.format(name=domain) + inflated, encoding="utf-8")
        print(f"  Generated domain bundle: {bundle_dst}")
    if failures:
        lines = ["", "=" * 80, "ERROR: Domain baseline bundle generation failed", "=" * 80, ""]
        lines.extend(f"{domain}: {error}" for domain, error in failures)
        lines.append("=" * 80)
        raise SystemExit("\n".join(lines))


def ensure_global_snippets_link(deploy_docs_root: Path) -> None:
    """Expose global support fragments under the legacy deployed snippets path."""
    source = _REPO_ROOT / "docs" / "global" / "snippets"
    if not source.is_dir():
        return

    target = deploy_docs_root / "snippets"
    if target.is_symlink() and target.resolve() == source.resolve():
        return
    if target.is_symlink() or target.is_file():
        target.unlink()
    elif target.exists():
        shutil.rmtree(target)
    target.symlink_to(source)


def _render_domain_awareness(deploy_docs_root: Path) -> str:
    """Render one awareness line per published domain from the merged index.

    Each line names the domain, its snippet count, and the path to its baseline
    bundle, so every project's entrypoint surfaces every published domain with
    on-demand depth. Sources the deployed merged ``index.yaml``.
    """
    index_path = deploy_docs_root / "index.yaml"
    if not index_path.exists():
        return ""
    payload = yaml.safe_load(index_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return ""
    snippets = payload.get("snippets")
    if not isinstance(snippets, list):
        return ""
    counts: dict[str, int] = {}
    for item in snippets:
        if not isinstance(item, dict):
            continue
        domain = item.get("domain")
        if not isinstance(domain, str) or domain in ("baseline", "general", "project", ""):
            continue
        counts[domain] = counts.get(domain, 0) + 1
    if not counts:
        return ""
    lines = [
        f"- `{domain}` — {counts[domain]} snippet(s); bundle: `~/.teleclaude/docs/{domain}/domain-baseline-bundle.md`"
        for domain in sorted(counts)
    ]
    header = "## Published Domains — load a domain's bundle for depth\n\n"
    return header + "\n".join(lines)


def deploy_documentation(project_root: Path, docs_source_dir: Path, *, deploy_docs_root: Path | None = None) -> None:
    """The documentation deployment step: compose the single-owner docs root.

    Gathers every contributing publisher (the current project contributes from
    ``docs_source_dir``, its live checkout, so a worktree's edits compose),
    resolves the one owner per domain — hard-blocking on a split before anything
    is composed — then rebuilds the deployed root as one directory symlink per
    domain, writes the merged index, and regenerates each owned domain's
    ``domain-baseline-bundle.md``. A split domain ownership and bundle-inflation
    failures abort the deploy.
    """
    if not docs_source_dir.is_dir():
        return
    target = deploy_docs_root if deploy_docs_root is not None else GLOBAL_DOCS_DIR
    print("\nDeploying documentation...")
    publishers = gather_publishers(project_root, docs_source_dir.resolve())
    owner_by_domain = domain_owners(publishers)
    compose_docs_root(owner_by_domain, target)
    ensure_global_snippets_link(target)
    write_merged_index(publishers, target)
    generate_domain_baselines(owner_by_domain, target, project_root)


def _strip_specific_h1(content: str, title: str) -> str:
    """Remove a specific leading H1 heading to avoid redundant titles in inlined docs."""
    lines = content.splitlines()
    if not lines:
        return content
    if lines[0].strip() == f"# {title}":
        return "\n".join(lines[1:]).lstrip("\n")
    return content


def _strip_leading_separators(content: str) -> str:
    """Remove leading markdown separators to avoid stacked '---' blocks."""
    lines = content.splitlines()
    idx = 0
    while idx < len(lines) and lines[idx].strip() == "---":
        idx += 1
        while idx < len(lines) and not lines[idx].strip():
            idx += 1
    return "\n".join(lines[idx:]).lstrip("\n")


def _iter_project_agent_masters(project_root: Path) -> list[Path]:
    """Find AGENTS.master.md files in the project (excluding tool-managed dirs)."""
    skip_dirs = {
        ".git",
        ".agents",
        ".history",
        "templates",
        "trees",
        "__pycache__",
        "dist",
        "node_modules",
        ".venv",
        "venv",
    }
    matches: list[Path] = []
    for root, dirs, files in os.walk(project_root):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        if "AGENTS.master.md" in files:
            matches.append(Path(root) / "AGENTS.master.md")
    return sorted(matches)


def _write_project_agents(master_path: Path, *, project_root: Path, warn_only: bool) -> None:
    """Generate AGENTS.md and CLAUDE.md next to a project AGENTS.master.md."""
    raw = master_path.read_text(encoding="utf-8")
    inflated = expand_inline_refs(
        raw,
        project_root=project_root,
        current_path=master_path,
        warn_only=warn_only,
    )
    awareness = _render_domain_awareness(GLOBAL_DOCS_DIR)
    if awareness:
        inflated = f"{inflated.rstrip()}\n\n---\n\n{awareness}\n"
    agents_path = master_path.parent / "AGENTS.md"
    agents_path.write_text(inflated, encoding="utf-8")
    claude_path = master_path.parent / "CLAUDE.md"
    claude_path.write_text("@./AGENTS.md\n", encoding="utf-8")


def _resolve_git_common_root(project_root: Path) -> Path:
    """Resolve canonical repo root from git common dir when available.

    In git worktrees, this returns the main repository root (parent of `.git`),
    preventing shared runtime artifacts from being bound to ephemeral worktree paths.
    """
    result = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return project_root

    common_dir = result.stdout.strip()
    if not common_dir:
        return project_root

    common_path = Path(common_dir).resolve()
    if common_path.name != ".git":
        return project_root
    return common_path.parent


def main() -> None:  # noqa: C901
    """Transpile and optionally deploy agent artifacts for supported CLIs."""
    parser = argparse.ArgumentParser(description="Transpile and distribute agent markdown files.")
    parser.add_argument("--deploy", action="store_true", help="Sync generated files to their locations.")
    parser.add_argument(
        "--project-root",
        required=True,
        help="Project root to read agents/.agents from (default: script parent).",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate artifact schema without generating outputs.",
    )
    parser.add_argument(
        "--warn-only",
        action="store_true",
        help="Emit validation warnings but exit successfully.",
    )
    args = parser.parse_args()

    # Get the project root and main TeleClaude repo root.
    script_dir = os.path.dirname(os.path.realpath(__file__))
    teleclaude_root = os.path.dirname(script_dir)
    project_root = os.path.abspath(os.path.expanduser(args.project_root))
    is_mother_project = Path(project_root).resolve() == Path(teleclaude_root).resolve()
    project_root_path = Path(project_root)
    agents_root = os.path.join(teleclaude_root, "agents")
    dot_agents_root = os.path.join(project_root, ".agents")
    os.chdir(project_root)

    for master_path in _iter_project_agent_masters(project_root_path):
        _write_project_agents(master_path, project_root=project_root_path, warn_only=args.warn_only)

    validate_only = args.validate_only
    dist_dir = "dist"

    master_agents_file = os.path.join(agents_root, "AGENTS.global.md")
    master_agents_dir = os.path.join(agents_root, "agents")
    master_commands_dir = os.path.join(agents_root, "commands")
    master_skills_dir = os.path.join(agents_root, "skills")

    dot_master_agents_dir = os.path.join(dot_agents_root, "agents")
    dot_master_commands_dir = os.path.join(dot_agents_root, "commands")
    dot_master_skills_dir = os.path.join(dot_agents_root, "skills")
    canonical_root = _resolve_git_common_root(project_root_path)
    master_docs_dir = os.path.join(project_root, "docs", "global")
    canonical_docs_dir = os.path.join(canonical_root, "docs", "global")
    # Prefer the current checkout (worktree) docs so that telec sync deploys
    # the docs being edited, not stale content from the main repo root.
    docs_source_dir = master_docs_dir if os.path.isdir(master_docs_dir) else canonical_docs_dir

    agents_config: dict[str, AgentConfig] = {
        "claude": {
            "check_dir": os.path.expanduser("~/.claude"),
            "prefix": "/",
            "master_dest": os.path.join(dist_dir, "claude", "CLAUDE.md"),
            "commands_dest_dir": os.path.join(dist_dir, "claude", "commands"),
            "agents_dest_dir": os.path.join(dist_dir, "claude", "agents"),
            "skills_dest_dir": os.path.join(dist_dir, "claude", "skills"),
            "skills_ext": ".md",
            "deploy_master_dest": os.path.join(os.path.expanduser("~/.claude"), "CLAUDE.md"),
            "deploy_commands_dest": os.path.join(os.path.expanduser("~/.claude"), "commands"),
            "deploy_agents_dest": os.path.join(os.path.expanduser("~/.claude"), "agents"),
            "deploy_skills_dest": os.path.join(os.path.expanduser("~/.claude"), "skills"),
            "ext": ".md",
            "transform": dump_frontmatter,
        },
        "codex": {
            "check_dir": os.path.expanduser("~/.codex"),
            "prefix": "~/.teleclaude/commands/",
            "master_dest": os.path.join(dist_dir, "codex", "AGENTS.md"),
            "commands_dest_dir": os.path.join(dist_dir, "codex", "prompts"),
            "agents_dest_dir": os.path.join(dist_dir, "codex", "agents"),
            "skills_dest_dir": os.path.join(dist_dir, "codex", "skills"),
            "skills_ext": ".md",
            "deploy_master_dest": os.path.join(os.path.expanduser("~/.codex"), "AGENTS.md"),
            "deploy_commands_dest": str(COMMANDS_DIR),
            "deploy_agents_dest": os.path.join(os.path.expanduser("~/.codex"), "agents"),
            "deploy_skills_dest": os.path.join(os.path.expanduser("~/.codex"), "skills"),
            "ext": ".md",
            "transform": transform_to_codex,
        },
        "gemini": {
            "check_dir": os.path.expanduser("~/.gemini"),
            "prefix": "/",
            "master_dest": os.path.join(dist_dir, "gemini", "GEMINI.md"),
            "commands_dest_dir": os.path.join(dist_dir, "gemini", "commands"),
            "agents_dest_dir": os.path.join(dist_dir, "gemini", "agents"),
            "skills_dest_dir": os.path.join(dist_dir, "gemini", "skills"),
            "skills_ext": ".md",
            "deploy_master_dest": os.path.join(os.path.expanduser("~/.gemini"), "GEMINI.md"),
            "deploy_commands_dest": os.path.join(os.path.expanduser("~/.gemini"), "commands"),
            "deploy_agents_dest": os.path.join(os.path.expanduser("~/.gemini"), "agents"),
            "deploy_skills_dest": os.path.join(os.path.expanduser("~/.gemini"), "skills"),
            "ext": ".toml",
            "transform": transform_to_gemini,
        },
    }

    artifact_specs: list[FileArtifactType] = [
        FileArtifactType(
            name="agents",
            source_dir_key="agents_dir",
            dest_dir_key="agents_dest_dir",
            deploy_dir_key="deploy_agents_dest",
            ext_key="ext",
            kind="file",
            artifact_kind="agent",
        ),
        FileArtifactType(
            name="commands",
            source_dir_key="commands",
            dest_dir_key="commands_dest_dir",
            deploy_dir_key="deploy_commands_dest",
            ext_key="ext",
            kind="file",
            artifact_kind="command",
        ),
        FileArtifactType(
            name="skills",
            source_dir_key="skills",
            dest_dir_key="skills_dest_dir",
            deploy_dir_key="deploy_skills_dest",
            ext_key="skills_ext",
            kind="skill",
            artifact_kind="skill",
        ),
    ]

    global_sources = []
    if is_mother_project:
        global_sources = [
            {
                "label": "agents",
                "master": master_agents_file,
                "agents_dir": master_agents_dir,
                "commands": master_commands_dir,
                "skills": master_skills_dir,
            }
        ]
    local_sources = [
        {
            "label": ".agents",
            "master": os.path.join(project_root, ".agents", "__none__"),
            "agents_dir": dot_master_agents_dir,
            "commands": dot_master_commands_dir,
            "skills": dot_master_skills_dir,
        },
    ]

    def _existing_sources(source_list: list[dict[str, str]]) -> list[dict[str, str]]:
        existing: list[dict[str, str]] = []
        for source in source_list:
            if source["label"] in {"agents", ".agents"}:
                existing.append(source)
                continue
            if os.path.isfile(source["master"]) or os.path.isdir(source["commands"]) or os.path.isdir(source["skills"]):
                existing.append(source)
        return existing

    global_sources = _existing_sources(global_sources)
    local_sources = _existing_sources(local_sources)

    def _validate_sources(sources: list[dict[str, str]]) -> list[str]:
        errors: list[str] = []
        artifact_items: dict[str, list[str]] = {spec.name: [] for spec in artifact_specs}
        for source in sources:
            for spec in artifact_specs:
                source_dir = source.get(spec.source_dir_key)
                if not isinstance(source_dir, str) or not os.path.isdir(source_dir):
                    continue
                if spec.kind == "file":
                    artifact_items[spec.name].extend([f for f in os.listdir(source_dir) if f.endswith(".md")])
                else:
                    artifact_items[spec.name].extend(
                        [f for f in os.listdir(source_dir) if os.path.isdir(os.path.join(source_dir, f))]
                    )
        for spec in artifact_specs:
            artifact_items[spec.name] = sorted(set(artifact_items[spec.name]))

        for spec in artifact_specs:
            items = artifact_items[spec.name]
            for item in items:
                item_path = ""
                for source in sources:
                    source_dir = source.get(spec.source_dir_key)
                    if not isinstance(source_dir, str):
                        continue
                    if spec.kind == "file":
                        candidate = os.path.join(source_dir, item)
                    else:
                        candidate = os.path.join(source_dir, item, "SKILL.md")
                    if os.path.exists(candidate):
                        item_path = candidate
                        break
                if not item_path:
                    continue
                try:
                    with open(item_path, encoding="utf-8") as f:
                        post = frontmatter.load(f)
                    validate_artifact(post, item_path, kind=spec.artifact_kind, project_root=Path(project_root))
                    if spec.kind == "skill":
                        resolve_skill_name(post, item)
                except Exception as e:
                    errors.append(str(e))
        return errors

    errors: list[str] = []
    errors.extend(_validate_sources(global_sources))
    errors.extend(_validate_sources(local_sources))
    if errors:
        for error in errors:
            print(error)
        if not args.warn_only:
            raise SystemExit(1)
    if validate_only:
        return

    dist_dir = "dist"
    if os.path.exists(dist_dir):
        shutil.rmtree(dist_dir)
    os.makedirs(dist_dir)

    def _run_phase(  # noqa: C901
        *,
        sources: list[dict[str, str]],
        prefix_root: str,
        dist_dir: str,
        deploy_root: str,
        emit_repo_codex: bool,
        deploy_enabled: bool,
    ) -> None:
        if os.path.exists(dist_dir):
            shutil.rmtree(dist_dir)
        os.makedirs(dist_dir)

        agent_master_contents: list[str] = []
        markdown_outputs: list[str] = []
        artifact_items: dict[str, list[str]] = {spec.name: [] for spec in artifact_specs}
        for source in sources:
            if os.path.isfile(source["master"]) and source["label"] != ".agents":
                with open(source["master"], encoding="utf-8") as f:
                    agent_master_contents.append(f.read())
            for spec in artifact_specs:
                source_dir = source.get(spec.source_dir_key)
                if not isinstance(source_dir, str) or not os.path.isdir(source_dir):
                    continue
                if spec.kind == "file":
                    artifact_items[spec.name].extend([f for f in os.listdir(source_dir) if f.endswith(".md")])
                else:
                    artifact_items[spec.name].extend(
                        [name for name in os.listdir(source_dir) if os.path.isdir(os.path.join(source_dir, name))]
                    )
        for spec in artifact_specs:
            artifact_items[spec.name] = sorted(set(artifact_items[spec.name]))

        built_agents: list[str] = []
        for agent_name, config in agents_config.items():
            if agent_name != "agents" and not os.path.isdir(config["check_dir"]):
                print(f"Skipping {agent_name}: directory {config['check_dir']} not found.")
                continue

            print(f"Processing {agent_name}...")

            agent_specific_file = os.path.join(prefix_root, f"{agent_name.upper()}.addendum.md")
            agent_specific_content = ""
            if os.path.exists(agent_specific_file):
                with open(agent_specific_file, encoding="utf-8") as extra_f:
                    raw_agent_specific = extra_f.read()
                agent_specific_content = process_file(raw_agent_specific, config["prefix"], agent_name)

            has_any_content = bool(
                agent_master_contents
                or any(artifact_items[spec.name] for spec in artifact_specs)
                or agent_specific_content
            )
            if not has_any_content:
                print(f"Skipping {agent_name}: no agent content found.")
                continue

            master_dest_path = os.path.join(dist_dir, agent_name, os.path.basename(config["master_dest"]))
            processed_contents = [
                process_file(content, config["prefix"], agent_name) for content in agent_master_contents
            ]
            addendum_suffix = f"\n---\n\n{agent_specific_content}" if agent_specific_content else ""
            combined_agents_content = "\n\n".join(content for content in (*processed_contents,) if content)
            if _should_expand_inline(agent_name) and processed_contents:
                expanded_body = expand_inline_refs(
                    "\n\n".join(content for content in processed_contents if content),
                    project_root=Path(project_root),
                    current_path=Path(project_root) / "AGENTS.md",
                    warn_only=args.warn_only,
                )
                combined_agents_content = expanded_body
            if combined_agents_content:
                combined_agents_content = combined_agents_content.rstrip() + addendum_suffix
                awareness = _render_domain_awareness(GLOBAL_DOCS_DIR)
                if awareness:
                    combined_agents_content = f"{combined_agents_content.rstrip()}\n\n---\n\n{awareness}\n"
            if combined_agents_content:
                master_dest_dir = os.path.dirname(master_dest_path)
                if master_dest_dir:
                    os.makedirs(master_dest_dir, exist_ok=True)
                with open(master_dest_path, "w", encoding="utf-8") as f:
                    f.write(wrap_with_context_markers(combined_agents_content, is_markdown=True))
                markdown_outputs.append(master_dest_path)
                if emit_repo_codex and agent_name == "codex":
                    repo_override_path = os.path.join(project_root, "AGENTS.override.md")
                    with open(repo_override_path, "w", encoding="utf-8") as f:
                        f.write(combined_agents_content)
                    markdown_outputs.append(repo_override_path)

            for spec in artifact_specs:
                items = artifact_items[spec.name]
                if not items:
                    continue
                dest_dir = os.path.join(
                    dist_dir,
                    agent_name,
                    os.path.basename(config[spec.dest_dir_key]),  # type: ignore[literal-required]
                )
                os.makedirs(dest_dir, exist_ok=True)
                for item in items:
                    item_path = ""
                    for source in sources:
                        source_dir = source.get(spec.source_dir_key)
                        if not isinstance(source_dir, str):
                            continue
                        if spec.kind == "file":
                            candidate = os.path.join(source_dir, item)
                        else:
                            candidate = os.path.join(source_dir, item, "SKILL.md")
                        if os.path.exists(candidate):
                            item_path = candidate
                            break
                    if not item_path:
                        continue
                    with open(item_path, encoding="utf-8") as f:
                        try:
                            post = frontmatter.load(f)
                            validate_artifact(post, item_path, kind=spec.artifact_kind, project_root=Path(project_root))
                            prepared = _prepare_post(
                                post,
                                agent_prefix=config["prefix"],
                                agent_name=agent_name,
                                kind=spec.artifact_kind,
                                project_root=Path(project_root),
                                current_path=Path(item_path),
                                warn_only=args.warn_only,
                            )
                            output_dir = ""
                            if spec.kind == "skill":
                                skill_name = resolve_skill_name(prepared, item)
                                if agent_name == "claude":
                                    transformed_content = transform_skill_to_claude(prepared, skill_name)
                                elif agent_name == "codex":
                                    transformed_content = transform_skill_to_codex(prepared, skill_name)
                                else:
                                    transformed_content = transform_skill_to_gemini(prepared, skill_name)
                                output_dir = os.path.join(dest_dir, item)
                                os.makedirs(output_dir, exist_ok=True)
                                output_filename = f"SKILL{config[spec.ext_key]}"  # type: ignore[literal-required]
                                output_path = os.path.join(output_dir, output_filename)
                            else:
                                transformed_content = config["transform"](prepared)
                                base_name = os.path.splitext(item)[0]
                                output_filename = f"{base_name}{config[spec.ext_key]}"  # type: ignore[literal-required]
                                output_path = os.path.join(dest_dir, output_filename)
                            with open(output_path, "w", encoding="utf-8") as out_f:
                                out_f.write(transformed_content.rstrip("\n") + "\n")
                            if output_filename.endswith(".md"):
                                markdown_outputs.append(output_path)
                            # Copy supporting files/dirs from skill source (everything except SKILL.md)
                            if spec.kind == "skill" and output_dir:
                                skill_source_dir = os.path.dirname(item_path)
                                for entry in os.listdir(skill_source_dir):
                                    if entry == "SKILL.md" or entry.startswith((".", "__")):
                                        continue
                                    src_entry = os.path.join(skill_source_dir, entry)
                                    dst_entry = os.path.join(output_dir, entry)
                                    if os.path.isdir(src_entry):
                                        if os.path.exists(dst_entry):
                                            shutil.rmtree(dst_entry)
                                        shutil.copytree(src_entry, dst_entry)
                                    else:
                                        shutil.copy2(src_entry, dst_entry)
                        except Exception as e:
                            print(f"Error processing {spec.name} item {item} for agent {agent_name}: {e}")

            built_agents.append(agent_name)

        _format_markdown(markdown_outputs)

        print("\nTranspilation complete.")

        if args.deploy and deploy_enabled:
            print("Deploying files...")
            for agent_name in built_agents:
                config = agents_config[agent_name]

                print(f"Deploying {agent_name}...")

                target_root = os.path.join(deploy_root, os.path.basename(config["check_dir"]))
                dist_agent_root = os.path.join(dist_dir, agent_name)
                _deploy_agent(
                    dist_agent_root=dist_agent_root,
                    target_root=target_root,
                    config=config,
                    specs=artifact_specs,
                )

            print("Deployment complete.")

    def _deploy_documentation(source_dir: str) -> None:
        deploy_documentation(Path(project_root), Path(source_dir))

    if args.deploy:
        with tempfile.TemporaryDirectory(prefix="teleclaude-dist-global-") as global_dist:
            if global_sources:
                _run_phase(
                    sources=global_sources,
                    prefix_root=agents_root,
                    dist_dir=global_dist,
                    deploy_root=os.path.expanduser("~"),
                    emit_repo_codex=False,
                    deploy_enabled=True,
                )
        with tempfile.TemporaryDirectory(prefix="teleclaude-dist-local-") as local_dist:
            if local_sources:
                _run_phase(
                    sources=local_sources,
                    prefix_root=dot_agents_root,
                    dist_dir=local_dist,
                    deploy_root=project_root,
                    emit_repo_codex=True,
                    deploy_enabled=True,
                )

        # Deploy docs exactly once after all agent transpilation
        _deploy_documentation(docs_source_dir)
    else:
        if global_sources:
            _run_phase(
                sources=global_sources,
                prefix_root=agents_root,
                dist_dir=os.path.join(project_root, "dist", "global"),
                deploy_root=os.path.expanduser("~"),
                emit_repo_codex=False,
                deploy_enabled=False,
            )

        if local_sources:
            _run_phase(
                sources=local_sources,
                prefix_root=dot_agents_root,
                dist_dir=os.path.join(project_root, "dist", "local"),
                deploy_root=project_root,
                emit_repo_codex=True,
                deploy_enabled=False,
            )


if __name__ == "__main__":
    main()
