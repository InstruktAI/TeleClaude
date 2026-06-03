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

from teleclaude.docs_index import write_third_party_index_yaml
from teleclaude.paths import COMMANDS_DIR, GLOBAL_SNIPPETS_DIR
from teleclaude.required_reads import extract_required_reads, normalize_required_refs
from teleclaude.resource_validation import INCLUDE_DIRECTIVE_RE, resolve_ref_path, validate_artifact
from teleclaude.snippet_roots import iter_snippet_roots, snippet_files

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


def _is_truthy_flag(value: object) -> bool:
    """Treat a frontmatter boolean flag as true whether it survives as bool or string.

    YAML reserializers (e.g. the Codex single-quote normalizer) can stringify a
    ``true`` into ``'True'``; accept both so the flag's meaning is robust.
    """
    return value is True or (isinstance(value, str) and value.strip().lower() == "true")


def _needs_domain_baseline_domain(content: str, *, project_root: Path, current_path: Path) -> str | None:
    """Domain to stamp on a command whose role procedure requests baseline injection.

    Read from the source content *before* inline expansion strips the `@`-refs:
    if a required-read procedure declares ``needs_domain_baseline: true``, return
    its ``domain`` so the deployed command frontmatter carries it. Dispatch reads
    that frontmatter at SessionStart (frontmatter survives inlining; refs do not).
    """
    for match in INLINE_REF_RE.finditer(content):
        resolved = resolve_ref_path(match.group(1), root_path=project_root, current_path=current_path)
        if not resolved or not resolved.exists():
            continue
        try:
            metadata = frontmatter.loads(resolved.read_text(encoding="utf-8")).metadata
        except Exception:  # pylint: disable=broad-exception-caught
            continue
        if _is_truthy_flag(metadata.get("needs_domain_baseline")):
            domain = metadata.get("domain")
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
    warn_only: bool = False,
) -> str:
    """Render a baseline-progressive.md file as a compact index block.

    Instead of inlining full snippet content, reads each referenced file's
    frontmatter to extract snippet ID and description, then renders a scannable
    bullet list that agents can use with ``get_context``.
    """
    entries, _ = _collect_progressive_index_entries(ref_file, project_root=project_root, warn_only=warn_only)

    if not entries:
        return ""

    header = "## Baseline index — load via get_context when relevant\n\n"
    return header + "\n".join(entries)


def _collect_progressive_index_entries(
    ref_file: Path,
    *,
    project_root: Path,
    warn_only: bool = False,
) -> tuple[list[str], list[tuple[str, str]]]:
    content = ref_file.read_text(encoding="utf-8")
    baseline_entries: list[str] = []
    activatable_entries: list[tuple[str, str]] = []

    for match in INLINE_REF_RE.finditer(content):
        ref = match.group(1)
        resolved = resolve_ref_path(ref, root_path=project_root, current_path=ref_file)
        if not resolved or not resolved.exists():
            if warn_only:
                print(f"WARNING: Progressive index ref not found: {ref}")
                continue
            raise ValueError(f"Progressive index ref not found: {ref}")

        raw = resolved.read_text(encoding="utf-8")
        post = frontmatter.loads(raw)
        snippet_id = post.metadata.get("id")
        description = post.metadata.get("description")
        snippet_type = post.metadata.get("type")
        activation_trigger = post.metadata.get("activation_trigger")

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
    activatable_by_id: dict[str, str] = {}
    for snippets_root in iter_snippet_roots(project_root):
        for snippet_path in sorted(snippet_files(snippets_root, include_baseline=False)):
            raw = snippet_path.read_text(encoding="utf-8")
            try:
                post = frontmatter.loads(raw)
            except Exception:
                if warn_only:
                    print(f"WARNING: failed to parse frontmatter: {snippet_path}")
                    continue
                raise
            snippet_id = post.metadata.get("id")
            snippet_type = post.metadata.get("type")
            activation_trigger = post.metadata.get("activation_trigger")
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


def _inflate_domain_baseline(baseline_src: Path, domain_src: Path, *, project_root: Path) -> str:
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
        progressive_index = _render_progressive_index(progressive_src, project_root=project_root)
        if progressive_index:
            inflated = f"{inflated.rstrip()}\n\n---\n\n{progressive_index}\n"
    return inflated


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
    agents_path = master_path.parent / "AGENTS.md"
    agents_path.write_text(inflated, encoding="utf-8")
    claude_path = master_path.parent / "CLAUDE.md"
    claude_path.write_text("@./AGENTS.md\n", encoding="utf-8")


def rewrite_global_index(index_path: str, deploy_root: str) -> None:
    """Rewrite global docs index to match deployed paths."""
    index_file = Path(index_path)
    if not index_file.exists():
        return
    lines = index_file.read_text(encoding="utf-8").splitlines()
    new_lines: list[str] = []
    for line in lines:
        if line.startswith("project_root:"):
            new_lines.append(f"project_root: {deploy_root}")
            continue
        if line.startswith("snippets_root:"):
            new_lines.append(f"snippets_root: {os.path.join(deploy_root, 'docs')}")
            continue
        if "path: agents/docs/" in line:
            new_lines.append(line.replace("path: agents/docs/", "path: docs/"))
            continue
        if "path: docs/global/" in line:
            new_lines.append(line.replace("path: docs/global/", "path: docs/"))
            continue
        new_lines.append(line)
    index_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


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


def _repair_symlinked_deploy_root(deploy_root: Path) -> bool:
    """Unlink a deploy root that is a symlink so it can be recreated as a real dir.

    A deploy root must be a real directory of per-domain symlinks. If it is itself
    a symlink (e.g. pointing back at the repo's docs/global from a botched setup),
    the deploy resolves onto its own source and is refused forever. Removing the
    symlink lets the caller recreate a real directory and self-heals the checkout
    on the next sync. Returns True if a symlink was removed.
    """
    if not deploy_root.is_symlink():
        return False
    print(f"  Repairing symlinked deploy root: {deploy_root} -> {os.readlink(deploy_root)}")
    deploy_root.unlink()
    return True


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

    def _replace_domain_folder_with_real_dir(domain_src: Path, domain_dst: Path) -> None:
        """Break the whole-folder symlink and rebuild with per-child symlinks.

        Required so a real `baseline.md` file can override what would otherwise
        be a symlink to the source manifest. Per-child symlinks preserve normal
        access to every other file in the domain folder.
        """
        if os.path.lexists(domain_dst):
            if domain_dst.is_symlink() or not domain_dst.is_dir():
                domain_dst.unlink(missing_ok=True)
            else:
                shutil.rmtree(domain_dst)
        domain_dst.mkdir(parents=True, exist_ok=True)
        for child in os.listdir(domain_src):
            # baseline.md is written as the real inflated artifact; baseline-progressive.md
            # is folded into that artifact and must never deploy as a standalone file.
            if child.startswith(".") or child in {"baseline.md", "baseline-progressive.md"}:
                continue
            child_src = domain_src / child
            child_dst = domain_dst / child
            if os.path.lexists(child_dst):
                child_dst.unlink(missing_ok=True)
            child_dst.symlink_to(child_src)

    def _deploy_domain_baselines(
        source_dir: str,
        source_docs_root: Path,
        deploy_docs_root: Path,
        project_root: str,
    ) -> None:
        """Emit fully-inflated `baseline.md` per source `docs/global/<domain>/baseline.md`.

        Any source `docs/global/<domain>/baseline.md` produces a fully-expanded
        deployed artifact at `~/.teleclaude/docs/<domain>/baseline.md`. The
        domain folder switches from whole-folder symlink to per-child symlinks
        so the inflated file can override the source manifest at the deployed
        path. Cross-file deduplication is handled at the source by curating
        each snippet's `## Required reads` list so no snippet auto-pulls
        content the global baseline already inflates into CLAUDE.md.
        """
        header_template = "# {name} — Platform Baseline\n\n"
        for entry in os.listdir(source_dir):
            if entry.startswith(".") or entry in {"index.yaml", "baseline.md", "third-party"}:
                continue
            domain_src = source_docs_root / entry
            if not domain_src.is_dir():
                continue
            baseline_src = domain_src / "baseline.md"
            if not baseline_src.exists():
                continue
            domain_dst = deploy_docs_root / entry
            _replace_domain_folder_with_real_dir(domain_src, domain_dst)
            try:
                inflated = _inflate_domain_baseline(baseline_src, domain_src, project_root=Path(project_root))
            except Exception as e:
                print(f"  Error inflating {entry}/baseline.md: {e}")
                continue
            (domain_dst / "baseline.md").write_text(header_template.format(name=entry) + inflated, encoding="utf-8")
            print(f"  Inflated baseline: {domain_dst / 'baseline.md'}")

    def _deploy_documentation(source_dir: str) -> None:
        """Robustly deploy documentation using atomic symlink replacement."""
        if not os.path.isdir(source_dir):
            return

        print("\nDeploying documentation...")
        deploy_docs_root = GLOBAL_SNIPPETS_DIR
        source_docs_root = Path(source_dir).resolve()

        # Self-heal a deploy root that is itself a symlink (it would resolve onto
        # its own source below). Once removed, the mkdir recreates a real dir.
        _repair_symlinked_deploy_root(deploy_docs_root)

        if source_docs_root == deploy_docs_root.resolve():
            print("Error: deploy docs target resolves to source docs/global. Refusing deploy.")
            return

        deploy_docs_root.mkdir(parents=True, exist_ok=True)

        # Remove any previously-deployed raw baseline manifest at the global root.
        # Domain baselines are inflated and deployed separately by
        # `_deploy_domain_baselines`; the global root manifest is a build-time
        # input only and must not be exposed at the deploy path because agents
        # that read it directly mistake the @-ref list for missing inflation.
        legacy_global_baseline = deploy_docs_root / "baseline.md"
        if os.path.lexists(legacy_global_baseline):
            legacy_global_baseline.unlink(missing_ok=True)

        for entry in os.listdir(source_dir):
            if entry.startswith("."):
                continue

            src_path = source_docs_root / entry
            dst_path = deploy_docs_root / entry

            # Skip creating links for things that shouldn't be linked (only dirs and selected files).
            # baseline.md is deliberately excluded: domain baselines are deployed
            # inflated by `_deploy_domain_baselines`, and the global root manifest
            # is build-time-only.
            if not src_path.is_dir() and entry not in {"index.yaml"}:
                continue

            # Robust cleanup using lexists (detects broken symlinks)
            if os.path.lexists(dst_path):
                if dst_path.is_dir() and not dst_path.is_symlink():
                    if entry == "third-party":
                        continue
                    shutil.rmtree(dst_path)
                else:
                    dst_path.unlink(missing_ok=True)

            try:
                dst_path.symlink_to(src_path)
                print(f"  Synced: {dst_path} -> {src_path}")
            except Exception as e:
                print(f"  Error syncing {entry}: {e}")

        # Generate index.yaml for global third-party docs
        global_third_party = deploy_docs_root / "third-party"
        if global_third_party.exists():
            third_party_index = write_third_party_index_yaml(global_third_party, scope="global")
            if third_party_index:
                print(f"  Generated: {third_party_index}")

        # Rewrite global index to match deployed path (~/.teleclaude/docs)
        rewrite_global_index(str(deploy_docs_root / "index.yaml"), str(deploy_docs_root.parent))

        # Domain baseline inflation: emit fully-expanded artifacts per domain.
        _deploy_domain_baselines(source_dir, source_docs_root, deploy_docs_root, project_root)

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
