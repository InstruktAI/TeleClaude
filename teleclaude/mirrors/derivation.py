"""Deterministic launch-command detection and title derivation for mirrors.

This module is the single source of truth for turning a session's raw turns
into the mirror's derived classification fields (``command``, ``slug``,
``is_worker``) and its ``title``. It is reused by the live generation
path (``generator.generate_mirror_sync``) and the self-healing reconciliation
sweep (``worker``) so historical and freshly generated rows derive identically.

Every parser here keys on deterministic structural transcript markers — launch
tags, the codex loader phrase, a leading slash command — never on free-text
semantics. Bumping :data:`DERIVATION_VERSION` forces a fleet-wide re-derivation
through the reconciliation loop.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable
from dataclasses import dataclass

from teleclaude import paths as tc_paths
from teleclaude.constants import COMMAND_ROLE_MAP, WORKER_COMMANDS
from teleclaude.utils.transcript import StructuredMessage

# Bump to force every existing mirror to re-derive through the reconciliation loop.
# Note that a bump re-runs full generation per transcript, summarizer call included,
# so it is not the cheap route for a classification-only change.
DERIVATION_VERSION = 1

_TITLE_MAX_CHARS = 120


# Claude Code builtins are not launch commands; a session that opens with one is human.
_BUILTIN_COMMANDS: frozenset[str] = frozenset(
    {
        "clear",
        "compact",
        "config",
        "cost",
        "doctor",
        "help",
        "init",
        "login",
        "logout",
        "memory",
        "model",
        "review",
        "status",
        "fast",
        "vim",
        "terminal-setup",
    }
)

_CLAUDE_COMMAND_NAME_RE = re.compile(r"<command-name>\s*/?([\w-]+)\s*</command-name>")
_CLAUDE_COMMAND_ARGS_RE = re.compile(r"<command-args>([\s\S]*?)</command-args>")
_LOADER_RE = re.compile(
    r"Read\s+\S*?commands/([\w-]+)\.md\s+and follow it exactly as the active instruction set",
)
_LOADER_SLUG_RE = re.compile(r"provided inputs to that instruction set:\s*\n+\s*(\S+)")
_LEADING_SLASH_RE = re.compile(r"^/([\w-]+)(?:\s+(\S+))?")

_INJECTED_BLOCK_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL),
    re.compile(r"<environment_context>.*?</environment_context>", re.DOTALL),
    re.compile(r"<hook_context>.*?</hook_context>", re.DOTALL),
    re.compile(r"<command-message>.*?</command-message>", re.DOTALL),
    re.compile(r"<command-name>.*?</command-name>", re.DOTALL),
    re.compile(r"<command-args>.*?</command-args>", re.DOTALL),
    re.compile(r"<INSTRUCTIONS>.*?</INSTRUCTIONS>", re.DOTALL),
    re.compile(r"^# AGENTS\.md instructions for .*$", re.MULTILINE),
)

_SERIALIZED_CONTENT_RE = re.compile(r"^\s*\[\s*\{.*['\"]text['\"]\s*:", re.DOTALL)

# First user turn inside a rendered conversation_text block ("[<ts>] User: ..." or "User: ...").
_RENDERED_USER_TURN_RE = re.compile(r"^(?:\[[^\]]*\]\s*)?User:\s*(.*)", re.DOTALL)
# Block boundary in a rendered conversation_text: a blank line before the next "[<ts>] Role:" header.
_RENDERED_BLOCK_SPLIT_RE = re.compile(r"\n\n(?=(?:\[[^\]]*\]\s*)?(?:User|Assistant):)")


def _rendered_user_turns(conversation_text: str) -> list[str]:
    """Yield each user turn's raw text from a rendered conversation_text, blocks intact."""
    turns: list[str] = []
    for block in _RENDERED_BLOCK_SPLIT_RE.split(conversation_text):
        match = _RENDERED_USER_TURN_RE.match(block.strip())
        if match:
            turns.append(match.group(1))
    return turns


@dataclass(frozen=True)
class LaunchInfo:
    """The launch command detected from a session's raw turns, if any."""

    command: str | None = None
    slug: str | None = None
    via: str | None = None  # "claude-tag" | "loader" | "leading-slash"


def is_worker_command(command: str | None) -> bool:
    """Return whether a command marks a dispatched lifecycle worker.

    A command carrying no worker role — an orchestrator, tasker, integrator, or any
    command outside the lifecycle map — is not a worker, so an unrecognized command
    stays visible rather than disappearing from search on a naming accident.
    """
    if not command:
        return False
    return command in WORKER_COMMANDS


def _humanize(command: str) -> str:
    """Render an unknown/historical command as a human-readable heading."""
    stem = command.removeprefix("next-")
    return stem.replace("-", " ").title()


def _load_wrapper_titles() -> dict[str, str]:
    """Map each command stem to its wrapper's level-1 heading.

    Reads the deployed command artifacts first, falling back to the repository
    ``agents/commands`` sources so derivation works before deployment.
    """
    titles: dict[str, str] = {}
    heading_re = re.compile(r"^# (.+)$", re.MULTILINE)
    for directory in (tc_paths.COMMANDS_DIR, tc_paths.REPO_ROOT / "agents" / "commands"):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.md")):
            if path.stem in titles:
                continue
            # Deployed command files inline their required-reads above the command's
            # own heading, so the command title is the last level-1 heading.
            headings = heading_re.findall(path.read_text(encoding="utf-8"))
            if headings:
                titles[path.stem] = headings[-1].strip()
    return titles


_ROLE_COMMANDS: frozenset[str] = frozenset(command.value for command in COMMAND_ROLE_MAP)

_wrapper_title_cache: dict[str, str] | None = None


def _wrapper_title_map() -> dict[str, str]:
    global _wrapper_title_cache
    if _wrapper_title_cache is None:
        _wrapper_title_cache = _load_wrapper_titles()
    return _wrapper_title_cache


def is_known_launch_command(command: str | None) -> bool:
    """Return whether a command names a real deployed command artifact or lifecycle role.

    Live detection keys on structural transcript markers, which also fire on path
    fragments and prose (`/Users/...`, `/bin`, a sentence opening with a slash), so a
    stored `command` is not by itself evidence that a command was launched. Checking the
    name against the deployed wrapper headings and the role map separates a real launch
    from that noise — which matters when repairing stored rows, where a false positive
    would otherwise overwrite a real title with a humanized path fragment.
    """
    if not command:
        return False
    return command in _wrapper_title_map() or command in WORKER_COMMANDS or command in _ROLE_COMMANDS


def _unwrap_serialized_content(text: str) -> str:
    """Recover plain text from a transcript that leaked serialized content blocks.

    Some gemini rows store a Python-repr of a content list (``[{'text': '...'}]``)
    rather than the message text. Parse it back to the concatenated text values.
    """
    if not _SERIALIZED_CONTENT_RE.match(text):
        return text
    try:
        parsed: object = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return text
    if not isinstance(parsed, list):
        return text
    chunks: list[str] = []
    for block in parsed:
        if isinstance(block, dict):
            value = block.get("text")
            if isinstance(value, str):
                chunks.append(value)
    return "\n\n".join(chunks) if chunks else text


def strip_injected_blocks(text: str) -> str:
    """Remove injected machine-context from user text and whitespace-strip the rest."""
    cleaned = _unwrap_serialized_content(text)
    for pattern in _INJECTED_BLOCK_RES:
        cleaned = pattern.sub("", cleaned)
    return cleaned.strip()


def detect_launch_in_text(text: str) -> LaunchInfo:
    """Detect a launch command in a single user-turn text, by marker priority."""
    name_match = _CLAUDE_COMMAND_NAME_RE.search(text)
    if name_match:
        command = name_match.group(1)
        if command not in _BUILTIN_COMMANDS:
            args_match = _CLAUDE_COMMAND_ARGS_RE.search(text)
            slug = args_match.group(1).strip().split()[0] if args_match and args_match.group(1).strip() else None
            return LaunchInfo(command=command, slug=slug, via="claude-tag")

    loader_match = _LOADER_RE.search(text)
    if loader_match:
        slug_match = _LOADER_SLUG_RE.search(text)
        slug = slug_match.group(1).strip() if slug_match else None
        return LaunchInfo(command=loader_match.group(1), slug=slug, via="loader")

    leading_match = _LEADING_SLASH_RE.match(text.lstrip())
    if leading_match:
        command = leading_match.group(1)
        if command not in _BUILTIN_COMMANDS:
            return LaunchInfo(command=command, slug=leading_match.group(2), via="leading-slash")

    return LaunchInfo()


def detect_launch(messages: Iterable[StructuredMessage]) -> LaunchInfo:
    """Scan user turns in order and return the first launch command detected."""
    for message in messages:
        if message.type != "text" or message.role != "user":
            continue
        info = detect_launch_in_text(message.text)
        if info.command is not None:
            return info
    return LaunchInfo()


def detect_launch_in_rendered(conversation_text: str, fallback_title: str = "") -> LaunchInfo:
    """Detect a launch command from a row's stored rendered conversation_text.

    Splits the "[<ts>] User: ..." blocks and runs detection on each user turn so
    a leading slash command survives the rendered role prefix; falls back to the
    stored title.
    """
    for turn in _rendered_user_turns(conversation_text):
        info = detect_launch_in_text(turn)
        if info.command is not None:
            return info
    return detect_launch_in_text(fallback_title)


def render_title(command: str | None, slug: str | None) -> str:
    """Render a launch-command title from the command's wrapper heading and slug."""
    if not command:
        return ""
    heading = _wrapper_title_map().get(command) or _humanize(command)
    return f"{heading}: {slug}" if slug else heading


def _truncate_title(text: str) -> str:
    title = text.split("\n", 1)[0].strip()
    if len(title) <= _TITLE_MAX_CHARS:
        return title
    return title[: _TITLE_MAX_CHARS - 3].rstrip() + "..."


def derive_human_title(messages: Iterable[StructuredMessage]) -> str:
    """Derive a human title from the first user message: first line, length-capped."""
    for message in messages:
        if message.role == "user" and message.text.strip():
            return _truncate_title(message.text)
    return ""


def derive_human_title_from_rendered(conversation_text: str, fallback_title: str) -> str:
    """Derive a human title from a row's stored rendered conversation_text.

    Splits the rendered "[<ts>] User: ..." blocks, takes the first user turn,
    strips injected machine-context, and falls back to the stored title when no
    usable user turn survives.
    """
    for turn in _rendered_user_turns(conversation_text):
        cleaned = strip_injected_blocks(turn)
        if cleaned:
            return _truncate_title(cleaned)
    return _truncate_title(strip_injected_blocks(fallback_title))
