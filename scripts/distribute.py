#!/usr/bin/env -S uv run --quiet
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable, NotRequired, TypedDict, cast

import frontmatter
import yaml
from frontmatter import Post
from frontmatter.default_handlers import YAMLHandler

SubstitutionMap = dict[str, str]
Transform = Callable[[Post], str]

INLINE_REF_RE = re.compile(r"@([\w./~\-]+\.md)")


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


class AgentConfig(TypedDict):
    check_dir: str
    prefix: str
    master_dest: str
    commands_dest_dir: str
    skills_dest_dir: str
    skills_ext: str
    ext: str
    transform: Transform
    deploy_master_dest: NotRequired[str]
    deploy_commands_dest: NotRequired[str]
    deploy_skills_dest: NotRequired[str]


def transform_to_codex(post: Post) -> str:
    """Transform a post to the Codex format (same as Claude - standard YAML frontmatter)."""
    # Codex uses the same format as Claude: standard Markdown with YAML frontmatter
    return dump_frontmatter(post)


def transform_to_gemini(post: Post) -> str:
    """Transform a post to the Gemini TOML format."""
    description = post.metadata.get("description", "")

    description_str = f'"""{description}"""'

    # replace $ARGUMENTS for {{args}} in gemini format
    content = post.content.replace("$ARGUMENTS", "{{args}}")

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
    return dump_frontmatter(transformed_post)


def transform_skill_to_gemini(post: Post, name: str) -> str:
    """Transform a skill post to Gemini TOML format."""
    description = post.metadata.get("description", "")
    description_str = f'"""{description}"""'
    content = post.content
    return f"name = \"{name}\"\ndescription = {description_str}\nprompt = '''\n{content}\n'''\n"


def resolve_skill_name(post: Post, dirname: str) -> str:
    """Resolve the skill name from metadata and validate its directory."""
    name = cast(str, post.metadata.get("name"))
    if not name:
        raise ValueError(f"Skill {dirname} is missing frontmatter 'name'")
    if name != dirname:
        raise ValueError(f"Skill name '{name}' must match folder '{dirname}'")
    return name


def process_file(content: str, agent_prefix: str) -> str:
    """Apply substitutions to the file content."""
    content = content.replace("{AGENT_PREFIX}", agent_prefix)
    return content


def _resolve_ref_path(ref: str, *, root_path: Path, current_path: Path) -> Path | None:
    if "://" in ref:
        return None
    candidate = Path(ref).expanduser()
    if not candidate.is_absolute():
        if str(candidate).startswith("docs/"):
            candidate = (root_path / candidate).resolve()
            if not candidate.exists():
                tail = Path(ref).relative_to("docs")
                project_candidate = (root_path / "docs" / "project" / tail).resolve()
                if project_candidate.exists():
                    candidate = project_candidate
                else:
                    global_candidate = (root_path / "docs" / "global" / tail).resolve()
                    if global_candidate.exists():
                        candidate = global_candidate
        else:
            candidate = (current_path.parent / candidate).resolve()
    else:
        candidate = candidate.resolve()
    return candidate


def expand_inline_refs(content: str, *, project_root: Path, current_path: Path) -> str:
    """Inline @path.md references into the content (Codex speedup)."""
    seen: set[Path] = set()
    content = _strip_required_reads(content)

    def _expand(text: str, *, current_path: Path, depth: int) -> str:
        if depth <= 0:
            return text

        def _replace(match: re.Match[str]) -> str:
            ref = match.group(1)
            resolved = _resolve_ref_path(ref, root_path=project_root, current_path=current_path)
            if not resolved or not resolved.exists():
                return match.group(0)
            if resolved in seen:
                return ""
            seen.add(resolved)
            raw = resolved.read_text(encoding="utf-8")
            post = frontmatter.loads(raw)
            body = post.content
            if resolved.name == "index.md":
                expanded = _expand(body, current_path=resolved, depth=depth - 1).strip()
                expanded = _strip_required_reads(expanded).strip()
                return f"{expanded}\n" if expanded else ""
            expanded = _expand(body, current_path=resolved, depth=depth - 1).strip()
            expanded = _strip_required_reads(expanded)
            expanded = _strip_specific_h1(expanded, "Project baseline").strip()
            if not expanded:
                return ""
            return f"---\n\n{expanded}\n"

        return INLINE_REF_RE.sub(_replace, text)

    expanded = _expand(content, current_path=current_path, depth=20)
    expanded = expanded.replace("@~/.teleclaude/docs/", "~/.teleclaude/docs/")
    expanded = expanded.replace("@docs/", "docs/")
    return expanded


def _strip_required_reads(content: str) -> str:
    """Remove Required Reads section after inlining references."""
    lines = content.splitlines()
    output: list[str] = []
    in_required_reads = False

    for line in lines:
        if not in_required_reads and line.strip().lower() == "## required reads":
            in_required_reads = True
            continue
        if in_required_reads:
            stripped = line.strip()
            if stripped:
                # End the section once we hit the first non-empty line after the header.
                in_required_reads = False
                output.append(line)
            continue
        output.append(line)

    return "\n".join(output).rstrip() + "\n"


def _strip_specific_h1(content: str, title: str) -> str:
    """Remove a specific leading H1 heading to avoid redundant titles in inlined docs."""
    lines = content.splitlines()
    if not lines:
        return content
    if lines[0].strip() == f"# {title}":
        return "\n".join(lines[1:]).lstrip("\n")
    return content


def _merge_global_index(deploy_docs_root: str) -> None:
    """Merge index.yaml files from multiple projects into single global index.

    When multiple projects publish to ~/.teleclaude/docs/, each brings its own
    index.yaml with snippets. This merges them, preserving source_project metadata.
    """
    import yaml

    # Note: After copytree with dirs_exist_ok=True, only the most recent
    # project's index.yaml remains. To truly merge, we'd need to track indexes
    # before copy. For now, just ensure the final index is correct.

    # The current index.yaml should already have source_project from sync_resources.py
    # Just rewrite paths to match deployed location
    index_path = os.path.join(deploy_docs_root, "index.yaml")
    if not os.path.exists(index_path):
        return

    try:
        with open(index_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if isinstance(data, dict):
            # Use tilde for portability (git filters will expand in working copy)
            data["project_root"] = "~/.teleclaude"
            data["snippets_root"] = "~/.teleclaude/docs"
            snippets = data.get("snippets")
            if isinstance(snippets, list):
                for entry in snippets:
                    if not isinstance(entry, dict):
                        continue
                    path = entry.get("path")
                    if not isinstance(path, str):
                        continue
                    if path.startswith("docs/global/"):
                        entry["path"] = path.replace("docs/global/", "docs/", 1)

            with open(index_path, "w", encoding="utf-8") as f:
                yaml.dump(data, f, sort_keys=False, allow_unicode=True)
    except Exception as e:
        print(f"Warning: Could not process global index: {e}")


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Transpile and distribute agent markdown files.")
    parser.add_argument("--deploy", action="store_true", help="Sync generated files to their locations.")
    parser.add_argument(
        "--project-root",
        required=True,
        help="Project root to read agents/.agents from (default: script parent).",
    )
    args = parser.parse_args()

    # Get the project root and main TeleClaude repo root.
    script_dir = os.path.dirname(os.path.realpath(__file__))
    teleclaude_root = os.path.dirname(script_dir)
    project_root = os.path.abspath(os.path.expanduser(args.project_root))
    agents_root = os.path.join(teleclaude_root, "agents")
    dot_agents_root = os.path.join(project_root, ".agents")
    os.chdir(project_root)

    dist_dir = "dist"
    if os.path.exists(dist_dir):
        shutil.rmtree(dist_dir)
    os.makedirs(dist_dir)

    master_agents_file = os.path.join(agents_root, "AGENTS.master.md")
    master_commands_dir = os.path.join(agents_root, "commands")
    master_skills_dir = os.path.join(agents_root, "skills")

    dot_master_agents_file = os.path.join(dot_agents_root, "AGENTS.master.md")
    dot_master_commands_dir = os.path.join(dot_agents_root, "commands")
    dot_master_skills_dir = os.path.join(dot_agents_root, "skills")
    master_docs_dir = os.path.join(project_root, "docs", "global")

    agents_config: dict[str, AgentConfig] = {
        "claude": {
            "check_dir": os.path.expanduser("~/.claude"),
            "prefix": "/",
            "master_dest": os.path.join(dist_dir, "claude", "CLAUDE.md"),
            "commands_dest_dir": os.path.join(dist_dir, "claude", "commands"),
            "skills_dest_dir": os.path.join(dist_dir, "claude", "skills"),
            "skills_ext": ".md",
            "deploy_master_dest": os.path.join(os.path.expanduser("~/.claude"), "CLAUDE.md"),
            "deploy_commands_dest": os.path.join(os.path.expanduser("~/.claude"), "commands"),
            "deploy_skills_dest": os.path.join(os.path.expanduser("~/.claude"), "skills"),
            "ext": ".md",
            "transform": dump_frontmatter,
        },
        "codex": {
            "check_dir": os.path.expanduser("~/.codex"),
            "prefix": "~/.codex/prompts/",
            "master_dest": os.path.join(dist_dir, "codex", "CODEX.md"),
            "commands_dest_dir": os.path.join(dist_dir, "codex", "prompts"),
            "skills_dest_dir": os.path.join(dist_dir, "codex", "skills"),
            "skills_ext": ".md",
            "deploy_master_dest": os.path.join(os.path.expanduser("~/.codex"), "CODEX.md"),
            "deploy_commands_dest": os.path.join(os.path.expanduser("~/.codex"), "prompts"),
            "deploy_skills_dest": os.path.join(os.path.expanduser("~/.codex"), "skills"),
            "ext": ".md",
            "transform": transform_to_codex,
        },
        "gemini": {
            "check_dir": os.path.expanduser("~/.gemini"),
            "prefix": "/",
            "master_dest": os.path.join(dist_dir, "gemini", "GEMINI.md"),
            "commands_dest_dir": os.path.join(dist_dir, "gemini", "commands"),
            "skills_dest_dir": os.path.join(dist_dir, "gemini", "skills"),
            "skills_ext": ".toml",
            "deploy_master_dest": os.path.join(os.path.expanduser("~/.gemini"), "GEMINI.md"),
            "deploy_commands_dest": os.path.join(os.path.expanduser("~/.gemini"), "commands"),
            "deploy_skills_dest": os.path.join(os.path.expanduser("~/.gemini"), "skills"),
            "ext": ".toml",
            "transform": transform_to_gemini,
        },
    }

    global_sources = [
        {
            "label": "agents",
            "master": master_agents_file,
            "commands": master_commands_dir,
            "skills": master_skills_dir,
        }
    ]
    local_sources = [
        {
            "label": ".agents",
            "master": dot_master_agents_file,
            "commands": dot_master_commands_dir,
            "skills": dot_master_skills_dir,
        },
        {
            "label": "AGENTS.md",
            "master": os.path.join(project_root, "AGENTS.md"),
            "commands": os.path.join(project_root, ".agents", "__none__"),
            "skills": os.path.join(project_root, ".agents", "__none__"),
        },
    ]

    def _existing_sources(source_list: list[dict[str, str]]) -> list[dict[str, str]]:
        existing: list[dict[str, str]] = []
        for source in source_list:
            if os.path.isfile(source["master"]) or os.path.isdir(source["commands"]) or os.path.isdir(source["skills"]):
                existing.append(source)
        return existing

    global_sources = _existing_sources(global_sources)
    local_sources = _existing_sources(local_sources)

    def _run_phase(
        *,
        sources: list[dict[str, str]],
        prefix_root: str,
        dist_dir: str,
        deploy_root: str,
        include_docs: bool,
        emit_repo_codex: bool,
        deploy_enabled: bool,
    ) -> None:
        if os.path.exists(dist_dir):
            shutil.rmtree(dist_dir)
        os.makedirs(dist_dir)

        agent_master_contents: list[str] = []
        command_files: list[str] = []
        skill_dirs: list[str] = []
        markdown_outputs: list[str] = []
        for source in sources:
            if os.path.isfile(source["master"]) and source["label"] != ".agents":
                with open(source["master"], "r") as f:
                    agent_master_contents.append(f.read())
            if os.path.isdir(source["commands"]):
                command_files.extend([f for f in os.listdir(source["commands"]) if f.endswith(".md")])
            if os.path.isdir(source["skills"]):
                skill_dirs.extend(
                    [
                        name
                        for name in os.listdir(source["skills"])
                        if os.path.isdir(os.path.join(source["skills"], name))
                    ]
                )
        command_files = sorted(set(command_files))
        skill_dirs = sorted(set(skill_dirs))

        built_agents: list[str] = []
        for agent_name, config in agents_config.items():
            if agent_name != "agents" and not os.path.isdir(config["check_dir"]):
                print(f"Skipping {agent_name}: directory {config['check_dir']} not found.")
                continue

            print(f"Processing {agent_name}...")

            agent_specific_file = os.path.join(prefix_root, f"PREFIX.{agent_name}.md")
            agent_specific_content = ""
            if os.path.exists(agent_specific_file):
                with open(agent_specific_file, "r") as extra_f:
                    raw_agent_specific = extra_f.read()
                agent_specific_content = process_file(raw_agent_specific, config["prefix"])

            has_any_content = bool(agent_master_contents or command_files or skill_dirs or agent_specific_content)
            if not has_any_content:
                print(f"Skipping {agent_name}: no agent content found.")
                continue

            master_dest_path = os.path.join(dist_dir, agent_name, os.path.basename(config["master_dest"]))
            commands_dest_path = os.path.join(dist_dir, agent_name, os.path.basename(config["commands_dest_dir"]))
            skills_dest_path = os.path.join(dist_dir, agent_name, os.path.basename(config["skills_dest_dir"]))

            processed_contents = [process_file(content, config["prefix"]) for content in agent_master_contents]
            combined_agents_content = "\n\n".join(
                content for content in (agent_specific_content, *processed_contents) if content
            )
            if agent_name == "codex":
                expanded_body = expand_inline_refs(
                    "\n\n".join(content for content in processed_contents if content),
                    project_root=Path(project_root),
                    current_path=Path(project_root) / "AGENTS.md",
                )
                combined_agents_content = "\n\n".join(
                    content for content in (agent_specific_content, expanded_body) if content
                )
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

            if command_files:
                os.makedirs(commands_dest_path, exist_ok=True)

            for command_file in command_files:
                command_path = ""
                for source in sources:
                    candidate = os.path.join(source["commands"], command_file)
                    if os.path.exists(candidate):
                        command_path = candidate
                        break
                if not command_path:
                    continue
                with open(command_path, "r") as f:
                    try:
                        post = frontmatter.load(f)
                        post.content = process_file(post.content, config["prefix"])
                        if agent_name == "codex":
                            post.content = expand_inline_refs(
                                post.content,
                                project_root=Path(project_root),
                                current_path=Path(command_path),
                            )
                        transformed_content = config["transform"](post)
                        base_name = os.path.splitext(command_file)[0]
                        output_filename = f"{base_name}{config['ext']}"
                        output_path = os.path.join(commands_dest_path, output_filename)
                        with open(output_path, "w") as out_f:
                            out_f.write(transformed_content + "\n")
                        if output_filename.endswith(".md"):
                            markdown_outputs.append(output_path)
                    except Exception as e:
                        print(f"Error processing file {command_file} for agent {agent_name}: {e}")

            if skill_dirs:
                os.makedirs(skills_dest_path, exist_ok=True)

            for skill_dir in skill_dirs:
                skill_path = ""
                for source in sources:
                    candidate = os.path.join(source["skills"], skill_dir, "SKILL.md")
                    if os.path.exists(candidate):
                        skill_path = candidate
                        break
                if not skill_path:
                    print(f"Skipping skill {skill_dir}: SKILL.md not found.")
                    continue
                with open(skill_path, "r") as f:
                    try:
                        post = frontmatter.load(f)
                        post.content = process_file(post.content, config["prefix"])
                        skill_name = resolve_skill_name(post, skill_dir)

                        if agent_name == "claude":
                            transformed_content = transform_skill_to_claude(post, skill_name)
                        elif agent_name == "codex":
                            post.content = expand_inline_refs(
                                post.content,
                                project_root=Path(project_root),
                                current_path=Path(skill_path),
                            )
                            transformed_content = transform_skill_to_codex(post, skill_name)
                        else:
                            transformed_content = transform_skill_to_gemini(post, skill_name)

                        output_dir = os.path.join(skills_dest_path, skill_dir)
                        os.makedirs(output_dir, exist_ok=True)
                        output_filename = f"SKILL{config['skills_ext']}"
                        output_path = os.path.join(output_dir, output_filename)
                        with open(output_path, "w") as out_f:
                            out_f.write(transformed_content + "\n")
                        if output_filename.endswith(".md"):
                            markdown_outputs.append(output_path)
                    except Exception as e:
                        print(f"Error processing skill {skill_dir} for agent {agent_name}: {e}")

            built_agents.append(agent_name)

        if include_docs and os.path.isdir(master_docs_dir):
            docs_dist = os.path.join(dist_dir, "teleclaude", "docs")
            if os.path.exists(docs_dist):
                shutil.rmtree(docs_dist)
            shutil.copytree(master_docs_dir, docs_dist)
            rewrite_global_index(
                os.path.join(docs_dist, "index.yaml"),
                os.path.join(dist_dir, "teleclaude"),
            )

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

            if include_docs and os.path.isdir(master_docs_dir):
                deploy_docs_root = os.path.join(os.path.expanduser("~/.teleclaude"), "docs")

                # Remove old symlink if it exists
                if os.path.islink(deploy_docs_root):
                    os.unlink(deploy_docs_root)

                # Copy docs (overwriting files from this project)
                os.makedirs(deploy_docs_root, exist_ok=True)
                shutil.copytree(master_docs_dir, deploy_docs_root, dirs_exist_ok=True)

                # Merge index.yaml files (combine snippets from multiple projects)
                _merge_global_index(deploy_docs_root)

            print("Deployment complete.")

    if global_sources:
        _run_phase(
            sources=global_sources,
            prefix_root=agents_root,
            dist_dir=os.path.join(project_root, "dist", "global"),
            deploy_root=os.path.expanduser("~"),
            include_docs=True,
            emit_repo_codex=False,
            deploy_enabled=True,
        )

    if local_sources:
        _run_phase(
            sources=local_sources,
            prefix_root=dot_agents_root,
            dist_dir=os.path.join(project_root, "dist", "local"),
            deploy_root=project_root,
            include_docs=False,
            emit_repo_codex=True,
            deploy_enabled=False,
        )


if __name__ == "__main__":
    main()
