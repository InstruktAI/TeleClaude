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
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, cast

import frontmatter
import yaml
from frontmatter import Post
from frontmatter.default_handlers import YAMLHandler
from typing_extensions import NotRequired, TypedDict

# Allow running from any working directory by anchoring imports at repo root.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from teleclaude.docs_index import write_third_party_index_yaml
from teleclaude.required_reads import (
    extract_required_reads,
    normalize_required_refs,
)
from teleclaude.resource_validation import (
    resolve_ref_path,
    validate_artifact,
)

Transform = Callable[[Post], str]

INLINE_REF_RE = re.compile(r"@([\w./~\-]+\.md)")
CODEX_NEXT_COMMAND_RE = re.compile(
    r"(^|[\s`'\"(\[])\/(next-[a-z0-9-]+)(?=$|[\s`'\"),.:;!?])",
    re.MULTILINE,
)


class StableYAMLHandler(YAMLHandler):
    """Frontmatter YAML handler with stable ordering and wide line width."""

    def export(self, metadata: dict[str, object], **kwargs: object) -> str:  # guard: loose-dict - frontmatter contract
        return yaml.safe_dump(
            metadata,
            sort_keys=False,
            width=1000,
            default_flow_style=False,
            allow_unicode=True,
        ).rstrip()


_FRONTMATTER_HANDLER = StableYAMLHandler()


def dump_frontmatter(post: Post) -> str:
    """Serialize frontmatter using the stable YAML handler."""
    return frontmatter.dumps(post, handler=_FRONTMATTER_HANDLER)


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

    TODO: GitHub issue openai/codex#11495
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
    except Exception:
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


def _rewrite_codex_next_prompt_tokens(content: str) -> str:
    """Rewrite executable /next-* command tokens for Codex custom prompts.

    This intentionally rewrites command tokens only and avoids touching path-like
    references such as /Users/.../next-prepare.md.
    """

    def _replace(match: re.Match[str]) -> str:
        prefix = match.group(1)
        command = match.group(2)
        return f"{prefix}/prompts:{command}"

    return CODEX_NEXT_COMMAND_RE.sub(_replace, content)


ArtifactFrontmatter = TypedDict(
    "ArtifactFrontmatter",
    {
        "description": str,
        "name": str,
        "argument-hint": str,
        "hooks": object,
    },
    total=False,
)


class AgentConfig(TypedDict):
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


@dataclass(frozen=True)
class FileArtifactType:
    name: str
    source_dir_key: str
    dest_dir_key: str
    deploy_dir_key: str
    ext_key: str
    kind: Literal["file", "skill"]
    artifact_kind: str  # "agent", "command", or "skill" — passed to validate_artifact


def transform_to_codex(post: Post) -> str:
    """Transform a post to the Codex format (same as Claude - standard YAML frontmatter)."""
    # Codex uses Markdown with YAML frontmatter. Force explicit scalar quotes as
    # a compatibility workaround for intermittent frontmatter false positives.
    # TODO: GitHub issue openai/codex#11495 — remove when fixed upstream.
    content = _normalize_frontmatter_single_quotes_for_codex(dump_frontmatter(post))
    return _rewrite_codex_next_prompt_tokens(content)


def transform_to_gemini(post: Post) -> str:
    """Transform a post to the Gemini TOML format."""
    description = post.metadata.get("description", "")

    description_str = f'"""{description}"""'

    # replace $ARGUMENTS for {{args}} in gemini format
    content = post.content.replace("$ARGUMENTS", "{{args}}").strip()

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
    return _rewrite_codex_next_prompt_tokens(content)


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


def _filter_frontmatter(metadata: ArtifactFrontmatter, agent_name: str) -> ArtifactFrontmatter:
    filtered = cast(ArtifactFrontmatter, dict(metadata))
    if agent_name != "claude":
        filtered.pop("hooks", None)
    return filtered


def _prepare_post(
    post: Post,
    *,
    agent_prefix: str,
    agent_name: str,
    project_root: Path,
    current_path: Path,
    warn_only: bool,
) -> Post:
    content = process_file(post.content, agent_prefix, agent_name)
    if _should_expand_inline(agent_name):
        content = expand_inline_refs(
            content,
            project_root=project_root,
            current_path=current_path,
            warn_only=warn_only,
        )
    metadata = _filter_frontmatter(post.metadata, agent_name)
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
    content = ref_file.read_text(encoding="utf-8")
    entries: list[str] = []

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
        snippet_id = post.metadata.get("id", "")
        description = post.metadata.get("description", "")

        if snippet_id and description:
            entries.append(f"- `{snippet_id}` — {description}")
        elif snippet_id:
            entries.append(f"- `{snippet_id}`")

    if not entries:
        return ""

    header = "## Baseline index — load via get_context when relevant\n\n"
    return header + "\n".join(entries)


def expand_inline_refs(content: str, *, project_root: Path, current_path: Path, warn_only: bool = False) -> str:
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

            # Progressive baseline: render as index instead of inlining
            if resolved.name.startswith("baseline-progressive"):
                index_block = _render_progressive_index(
                    resolved,
                    project_root=project_root,
                    warn_only=warn_only,
                )
                if index_block:
                    required_sections.append(index_block)
                continue

            raw = resolved.read_text(encoding="utf-8")
            post = frontmatter.loads(raw)
            body = post.content
            expanded = _expand_document(body, current_path=resolved, depth=depth - 1).strip()
            expanded = _strip_specific_h1(expanded, "Project baseline").strip()
            expanded = _strip_leading_separators(expanded)
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

            # Progressive baseline: render as index instead of inlining
            if resolved.name.startswith("baseline-progressive"):
                index_block = _render_progressive_index(
                    resolved,
                    project_root=project_root,
                    warn_only=warn_only,
                )
                return f"{index_block}\n" if index_block else ""

            raw = resolved.read_text(encoding="utf-8")
            post = frontmatter.loads(raw)
            body = post.content
            expanded = _expand_document(body, current_path=resolved, depth=depth - 1).strip()
            if resolved.name == "index.md":
                expanded = _expand_document(body, current_path=resolved, depth=depth - 1).strip()
                return f"{expanded}\n" if expanded else ""
            expanded = _strip_specific_h1(expanded, "Project baseline").strip()
            expanded = _strip_leading_separators(expanded)
            if not expanded:
                return ""
            return f"---\n\n{expanded}\n"

        expanded_body = INLINE_REF_RE.sub(_replace, stripped)
        expanded_body = _strip_leading_separators(expanded_body)
        if required_sections:
            required_block = "\n\n---\n\n".join(required_sections).strip()
            if expanded_body.strip():
                return f"{required_block}\n\n---\n\n{expanded_body}"
            return required_block
        return expanded_body

    return _expand_document(content, current_path=current_path, depth=20)


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


def main() -> None:
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
    docs_source_dir = canonical_docs_dir if os.path.isdir(canonical_docs_dir) else master_docs_dir

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
            "prefix": "~/.codex/prompts/",
            "master_dest": os.path.join(dist_dir, "codex", "CODEX.md"),
            "commands_dest_dir": os.path.join(dist_dir, "codex", "prompts"),
            "agents_dest_dir": os.path.join(dist_dir, "codex", "agents"),
            "skills_dest_dir": os.path.join(dist_dir, "codex", "skills"),
            "skills_ext": ".md",
            "deploy_master_dest": os.path.join(os.path.expanduser("~/.codex"), "CODEX.md"),
            "deploy_commands_dest": os.path.join(os.path.expanduser("~/.codex"), "prompts"),
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
                    with open(item_path, "r") as f:
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

    def _run_phase(
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
                with open(source["master"], "r") as f:
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

            agent_specific_file = os.path.join(prefix_root, f"{agent_name.upper()}.primer.md")
            agent_specific_content = ""
            if os.path.exists(agent_specific_file):
                with open(agent_specific_file, "r") as extra_f:
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
            primer_suffix = f"\n---\n\n{agent_specific_content}" if agent_specific_content else ""
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
                combined_agents_content = combined_agents_content.rstrip() + primer_suffix
            if combined_agents_content and agent_name == "codex":
                combined_agents_content = _rewrite_codex_next_prompt_tokens(combined_agents_content)
            if combined_agents_content:
                master_dest_dir = os.path.dirname(master_dest_path)
                if master_dest_dir:
                    os.makedirs(master_dest_dir, exist_ok=True)
                with open(master_dest_path, "w") as f:
                    f.write(combined_agents_content)
                markdown_outputs.append(master_dest_path)
                if emit_repo_codex and agent_name == "codex":
                    repo_override_path = os.path.join(project_root, "AGENTS.override.md")
                    with open(repo_override_path, "w") as f:
                        f.write(combined_agents_content)
                    markdown_outputs.append(repo_override_path)

            for spec in artifact_specs:
                items = artifact_items[spec.name]
                if not items:
                    continue
                dest_dir = os.path.join(dist_dir, agent_name, os.path.basename(config[spec.dest_dir_key]))
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
                    with open(item_path, "r") as f:
                        try:
                            post = frontmatter.load(f)
                            validate_artifact(post, item_path, kind=spec.artifact_kind, project_root=Path(project_root))
                            prepared = _prepare_post(
                                post,
                                agent_prefix=config["prefix"],
                                agent_name=agent_name,
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
                                output_filename = f"SKILL{config[spec.ext_key]}"
                                output_path = os.path.join(output_dir, output_filename)
                            else:
                                transformed_content = config["transform"](prepared)
                                base_name = os.path.splitext(item)[0]
                                output_filename = f"{base_name}{config[spec.ext_key]}"
                                output_path = os.path.join(dest_dir, output_filename)
                            with open(output_path, "w") as out_f:
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
                os.makedirs(target_root, exist_ok=True)

                dist_agent_root = os.path.join(dist_dir, agent_name)
                shutil.copytree(dist_agent_root, target_root, dirs_exist_ok=True)

            print("Deployment complete.")

    def _deploy_documentation(source_dir: str, deploy_root: str) -> None:
        """Robustly deploy documentation using atomic symlink replacement."""
        if not os.path.isdir(source_dir):
            return

        print("\nDeploying documentation...")
        deploy_docs_root = Path(deploy_root).expanduser() / ".teleclaude" / "docs"
        source_docs_root = Path(source_dir).resolve()

        if source_docs_root == deploy_docs_root.resolve():
            print("Error: deploy docs target resolves to source docs/global. Refusing deploy.")
            return

        deploy_docs_root.mkdir(parents=True, exist_ok=True)

        for entry in os.listdir(source_dir):
            if entry.startswith("."):
                continue

            src_path = source_docs_root / entry
            dst_path = deploy_docs_root / entry

            # Skip creating links for things that shouldn't be linked (only dirs and selected files)
            if not src_path.is_dir() and entry not in {"index.yaml", "baseline.md"}:
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
        _deploy_documentation(docs_source_dir, os.path.expanduser("~"))
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
