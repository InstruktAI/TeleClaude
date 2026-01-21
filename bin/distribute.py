#!/usr/bin/env -S uv run --quiet
from __future__ import annotations

import argparse
import os
import shutil
from typing import Callable, NotRequired, TypedDict, cast

import frontmatter
from frontmatter import Post

SubstitutionMap = dict[str, str]
Transform = Callable[[Post], str]


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
    return frontmatter.dumps(post)


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
    return frontmatter.dumps(transformed_post)


def transform_skill_to_codex(post: Post, name: str) -> str:
    """Transform a skill post to Codex markdown format."""
    metadata = dict(post.metadata)
    metadata["name"] = name
    metadata["description"] = metadata.get("description", "")
    transformed_post = Post(post.content, **metadata)
    return frontmatter.dumps(transformed_post)


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Transpile and distribute agent markdown files.")
    parser.add_argument("--deploy", action="store_true", help="Sync generated files to their locations.")
    args = parser.parse_args()

    # Get the project root, which is the parent directory of the script's directory
    script_dir = os.path.dirname(os.path.realpath(__file__))
    project_root = os.path.dirname(script_dir)
    agents_root = os.path.join(project_root, "agents")
    os.chdir(project_root)

    dist_dir = "dist"
    if os.path.exists(dist_dir):
        shutil.rmtree(dist_dir)
    os.makedirs(dist_dir)

    master_agents_file = os.path.join(agents_root, "AGENTS.master.md")
    master_commands_dir = os.path.join(agents_root, "commands")
    master_skills_dir = os.path.join(agents_root, "skills")

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
            "transform": lambda p: frontmatter.dumps(p),
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

    # Ensure master files exist
    if not os.path.exists(master_agents_file):
        print(f"Error: Master agents file not found at {master_agents_file}")
        return
    if not os.path.exists(master_commands_dir):
        print(f"Error: Master commands directory not found at {master_commands_dir}")
        return
    if not os.path.exists(master_skills_dir):
        print(f"Error: Master skills directory not found at {master_skills_dir}")
        return

    with open(master_agents_file, "r") as f:
        master_agents_content = f.read()

    command_files = [f for f in os.listdir(master_commands_dir) if f.endswith(".md")]
    skill_dirs = [
        name for name in os.listdir(master_skills_dir) if os.path.isdir(os.path.join(master_skills_dir, name))
    ]

    for agent_name, config in agents_config.items():
        if agent_name != "agents" and not os.path.isdir(config["check_dir"]):
            print(f"Skipping {agent_name}: directory {config['check_dir']} not found.")
            continue

        print(f"Processing {agent_name}...")

        # For "agents", output is in root, not dist
        if agent_name == "agents":
            master_dest_path = config["master_dest"]
            commands_dest_path = config["commands_dest_dir"]
        else:
            master_dest_path = config["master_dest"]
            commands_dest_path = config["commands_dest_dir"]

        master_dest_dir = os.path.dirname(master_dest_path)
        if master_dest_dir:
            os.makedirs(master_dest_dir, exist_ok=True)
        os.makedirs(commands_dest_path, exist_ok=True)
        os.makedirs(config["skills_dest_dir"], exist_ok=True)

        # Process AGENTS.master.md
        agent_specific_file = os.path.join(agents_root, f"PREFIX.{agent_name}.md")
        agent_specific_content = ""
        if os.path.exists(agent_specific_file):
            with open(agent_specific_file, "r") as extra_f:
                raw_agent_specific = extra_f.read()
            agent_specific_content = process_file(raw_agent_specific, config["prefix"])

        processed_agents_content = process_file(master_agents_content, config["prefix"])

        combined_agents_content = "\n\n".join(
            content for content in (agent_specific_content, processed_agents_content) if content
        )

        with open(master_dest_path, "w") as f:
            f.write(combined_agents_content)

        # Process commands/*.md
        for command_file in command_files:
            with open(os.path.join(master_commands_dir, command_file), "r") as f:
                try:
                    post = frontmatter.load(f)

                    # Also substitute in the body of the command
                    post.content = process_file(post.content, config["prefix"])

                    transformed_content = config["transform"](post)

                    base_name = os.path.splitext(command_file)[0]
                    output_filename = f"{base_name}{config['ext']}"

                    with open(os.path.join(commands_dest_path, output_filename), "w") as out_f:
                        out_f.write(transformed_content + "\n")
                except Exception as e:
                    print(f"Error processing file {command_file} for agent {agent_name}: {e}")

        # Process skills/*/SKILL.md
        for skill_dir in skill_dirs:
            skill_path = os.path.join(master_skills_dir, skill_dir, "SKILL.md")
            if not os.path.exists(skill_path):
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
                        transformed_content = transform_skill_to_codex(post, skill_name)
                    else:
                        transformed_content = transform_skill_to_gemini(post, skill_name)

                    output_dir = os.path.join(config["skills_dest_dir"], skill_dir)
                    os.makedirs(output_dir, exist_ok=True)
                    output_filename = f"SKILL{config['skills_ext']}"

                    with open(
                        os.path.join(output_dir, output_filename),
                        "w",
                    ) as out_f:
                        out_f.write(transformed_content + "\n")
                except Exception as e:
                    print(f"Error processing skill {skill_dir} for agent {agent_name}: {e}")

    print("\nTranspilation complete.")

    if args.deploy:
        print("Deploying files...")
        for agent_name, config in agents_config.items():
            if agent_name == "agents":
                continue  # Skip deploying the local "agents" files

            print(f"Deploying {agent_name}...")

            # Merge the full generated tree into the target (cp -R dist/<agent>/* ~/.<agent>/)
            target_root = config["check_dir"]
            os.makedirs(target_root, exist_ok=True)

            dist_agent_root = os.path.dirname(config["master_dest"])
            shutil.copytree(dist_agent_root, target_root, dirs_exist_ok=True)

        print("Deployment complete.")


if __name__ == "__main__":
    main()
