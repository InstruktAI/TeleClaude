"""Help generation and shell completion for the telec CLI."""

from __future__ import annotations

from teleclaude.cli.telec.surface import CLI_SURFACE, CommandDef, Flag

# Derived constants for completion (from schema)
_COMMANDS = [name for name, cmd in CLI_SURFACE.items() if not cmd.hidden]
_COMMAND_DESCRIPTIONS = {name: cmd.desc for name, cmd in CLI_SURFACE.items() if not cmd.hidden}
_BOOLEAN_FLAGS = {
    "--all",
    "--closed",
    "--clear",
    "--attach",
    "--direct",
    "--close-link",
    "--baseline-only",
    "--third-party",
    "--validate-only",
    "--warn-only",
    "--invalidate-check",
}
_DESC_SAMPLE_RULES = (
    (("json", "payload", "widget expression"), '\'{"key":"value"}\''),
    (("iso8601", "iso 8601", "utc", "expiry"), "2026-01-01T00:00:00Z"),
    (("project root", "project directory", "directory"), "/tmp/project"),
    (("path", "file"), "/tmp/example.txt"),
    (("agent",), "claude"),
    (("thinking mode",), "slow"),
    (("phase",), "build"),
    (("status",), "degraded"),
    (("format",), "markdown"),
    (("reason",), '"example reason"'),
    (("summary",), '"example summary"'),
    (("customer",), '"Jane Doe"'),
    (("channel",), "channel:demo:events"),
)
_LONG_KEY_SAMPLE_RULES = (
    (("session",), "sess-123"),
    (("slug",), "my-slug"),
    (("project", "cwd", "root"), "/tmp/project"),
    (("path", "file"), "/tmp/example.txt"),
    (("agent",), "claude"),
    (("mode",), "slow"),
    (("phase",), "build"),
    (("status",), "degraded"),
    (("format",), "markdown"),
    (("until", "date"), "2026-01-01T00:00:00Z"),
    (("data",), '\'{"key":"value"}\''),
    (("after",), "dep-a"),
    (("before",), "target-slug"),
    (("title",), '"Example Title"'),
    (("description", "message", "content"), '"example"'),
)


__all__ = [
    "_complete_flags",
    "_complete_subcmd",
    "_example_commands",
    "_example_positionals",
    "_flag_matches",
    "_flag_used",
    "_handle_completion",
    "_maybe_show_help",
    "_print_completion",
    "_print_flag",
    "_sample_flag_value",
    "_sample_positional_value",
    "_usage",
    "_usage_leaf",
    "_usage_main",
    "_usage_subcmd",
]


def _usage(command: str | None = None, subcommand: str | None = None) -> str:
    """Generate help text from CLI_SURFACE schema.

    Args:
        command: Top-level command name. None for main overview.
        subcommand: If provided with command, show help for that specific subcommand.
    """
    if command is None:
        return _usage_main()
    if subcommand is not None:
        return _usage_leaf(command, subcommand)
    return _usage_subcmd(command)


def _maybe_show_help(cmd: str, args: list[str]) -> bool:
    """If -h/--help appears anywhere in args, show contextual help and return True."""
    if "-h" not in args and "--help" not in args:
        return False
    positionals = []
    for a in args:
        if a in ("-h", "--help"):
            break
        if not a.startswith("-"):
            positionals.append(a)
    print(_usage(cmd, positionals[0] if positionals else None))
    return True


def _usage_main() -> str:
    """Generate main help overview. Hidden flags are excluded."""
    col = 42
    lines = ["Usage:"]
    lines.append(f"  {'telec':<{col}}# Open TUI (Sessions view)")
    for name, cmd in CLI_SURFACE.items():
        if cmd.hidden:
            continue
        visible_flags = cmd.visible_flags
        flag_str = ""
        if visible_flags:
            parts = [f.short if f.short else f.long for f in visible_flags]
            flag_str = " [" + "|".join(parts) + "]"

        args_str = f" {cmd.args}" if cmd.args else ""

        if cmd.subcommands:
            if cmd.standalone:
                entry = f"telec {name}"
                lines.append(f"  {entry:<{col}}# {cmd.desc}")
            for sub_name, sub_cmd in cmd.subcommands.items():
                if sub_cmd.subcommands:
                    # Two-level nesting: expand leaf subcommands inline
                    for child_name, child_cmd in sub_cmd.subcommands.items():
                        child_args = f" {child_cmd.args}" if child_cmd.args else ""
                        child_flag_str = " [options]" if child_cmd.visible_flags else ""
                        entry = f"telec {name} {sub_name} {child_name}{child_args}{child_flag_str}"
                        lines.append(f"  {entry:<{col}}# {child_cmd.desc}")
                    continue
                sub_args = f" {sub_cmd.args}" if sub_cmd.args else ""
                sub_flag_str = " [options]" if sub_cmd.visible_flags else ""
                entry = f"telec {name} {sub_name}{sub_args}{sub_flag_str}"
                lines.append(f"  {entry:<{col}}# {sub_cmd.desc}")
        else:
            entry = f"telec {name}{args_str}{flag_str}"
            lines.append(f"  {entry:<{col}}# {cmd.desc}")
    return "\n".join(lines) + "\n"


def _sample_positional_value(token: str) -> str:
    """Return a practical sample value for a positional argument token."""
    key = token.strip("<>[]").rstrip(".,").lower()
    if "email" in key:
        return "person@example.com"
    if "session" in key:
        return "sess-123"
    if "slug" in key:
        return "my-slug"
    if "project" in key or "cwd" in key or "root" in key:
        return "/tmp/project"
    if "path" in key or "file" in key:
        return "/tmp/example.txt"
    if "agent" in key:
        return "claude"
    if "phase" in key:
        return "build"
    if "status" in key:
        return "complete"
    if "channel" in key:
        return "channel:demo:events"
    if "json" in key or "data" in key:
        return '\'{"key":"value"}\''
    if "id" in key:
        return "item-1"
    if "description" in key or "message" in key or "content" in key:
        return '"example"'
    return "value"


def _sample_flag_value(flag: Flag) -> str | None:
    """Return a sample value for a flag, or None for boolean/toggle flags."""
    if flag.long in _BOOLEAN_FLAGS:
        return None

    long_key = flag.long.lstrip("-").lower()
    desc = flag.desc.lower()
    desc_match = _match_sample_rule(desc, _DESC_SAMPLE_RULES)
    if desc_match is not None:
        return desc_match
    long_key_match = _match_sample_rule(long_key, _LONG_KEY_SAMPLE_RULES)
    if long_key_match is not None:
        return long_key_match
    return "value"


def _match_sample_rule(text: str, rules: tuple[tuple[tuple[str, ...], str], ...]) -> str | None:
    for needles, sample in rules:
        if any(needle in text for needle in needles):
            return sample
    return None


def _example_positionals(args_spec: str) -> list[str]:
    """Build sample positional arguments from a usage args spec string."""
    values: list[str] = []
    for raw in args_spec.split():
        token = raw.strip()
        if not token:
            continue
        if token.startswith("-"):
            continue
        values.append(_sample_positional_value(token))
    return values


def _example_commands(command_parts: list[str], args_spec: str, flags: list[Flag]) -> list[str]:
    """Generate example command lines that touch positional args and each flag."""
    base = ["telec", *command_parts, *_example_positionals(args_spec)]
    examples: list[str] = [" ".join(base).strip()]
    seen: set[str] = set(examples)

    for flag in flags:
        if flag.long == "--help":
            continue
        value = _sample_flag_value(flag)
        parts = [*base, flag.long]
        if value is not None:
            parts.append(value)
        line = " ".join(parts).strip()
        if line not in seen:
            seen.add(line)
            examples.append(line)

    return examples


def _usage_subcmd(cmd_name: str) -> str:
    """Generate detailed subcommand help. All flags shown."""
    cmd = CLI_SURFACE[cmd_name]
    lines = ["Usage:"]
    if cmd.subcommands:
        _append_grouped_command_usage(lines, cmd_name, cmd)
    else:
        _append_leaf_command_usage(lines, cmd_name, cmd)
    return "\n".join(lines) + "\n"


def _visible_flags(flags: list[Flag] | None) -> list[Flag]:
    return [f for f in flags or [] if f.long != "--help"]


def _append_flag_section(lines: list[str], label: str, flags: list[Flag]) -> None:
    if not flags:
        return
    lines.append(f"\n{label}:")
    for flag in flags:
        flag_label = f"  {flag.short}, {flag.long}" if flag.short else f"  {flag.long}"
        lines.append(f"{flag_label:<25s}{flag.desc}")


def _append_examples(lines: list[str], examples: list[str]) -> None:
    if not examples:
        return
    lines.append("\nExamples:")
    for example in examples:
        lines.append(f"  {example}")


def _append_grouped_command_usage(lines: list[str], cmd_name: str, cmd: CommandDef) -> None:
    col = 49
    visible_cmd_flags = _visible_flags(cmd.flags)
    if cmd.standalone:
        args_str = f" {cmd.args}" if cmd.args else ""
        flag_hints = " [options]" if cmd.flags else ""
        entry = f"telec {cmd_name}{args_str}{flag_hints}"
        lines.append(f"  {entry:<{col}}# {cmd.desc}")
        _append_flag_section(lines, "Options", visible_cmd_flags)
        _append_examples(lines, _example_commands([cmd_name], cmd.args, visible_cmd_flags))

    for entry in _iter_subcommand_entries(cmd_name, cmd, col):
        lines.append(entry)
    for label, flags in _group_subcommand_flags(cmd):
        _append_flag_section(lines, label, flags)

    notes = list(dict.fromkeys([*cmd.notes, *[note for sub_cmd in cmd.subcommands.values() for note in sub_cmd.notes]]))
    if notes:
        lines.append("\nNotes:")
        for note in notes:
            lines.append(f"  {note}")


def _append_leaf_command_usage(lines: list[str], cmd_name: str, cmd: CommandDef) -> None:
    args_str = f" {cmd.args}" if cmd.args else ""
    visible = _visible_flags(cmd.flags)
    lines.append(f"  telec {cmd_name}{args_str}")
    _append_flag_section(lines, "Options", visible)

    notes = cmd.notes or [f"Use this command to {cmd.desc.lower()}."]
    lines.append("\nNotes:")
    for note in notes:
        lines.append(f"  {note}")
    _append_examples(lines, cmd.examples or _example_commands([cmd_name], cmd.args, visible))


def _iter_subcommand_entries(cmd_name: str, cmd: CommandDef, col: int) -> list[str]:
    entries: list[str] = []
    for sub_name, sub_cmd in cmd.subcommands.items():
        if sub_cmd.subcommands:
            for child_name, child_cmd in sub_cmd.subcommands.items():
                child_args = f" {child_cmd.args}" if child_cmd.args else ""
                child_flag_hints = " [options]" if child_cmd.flags else ""
                entry = f"telec {cmd_name} {sub_name} {child_name}{child_args}{child_flag_hints}"
                entries.append(f"  {entry:<{col}}# {child_cmd.desc}")
            continue
        args_str = f" {sub_cmd.args}" if sub_cmd.args else ""
        flag_hints = " [options]" if sub_cmd.flags else ""
        entry = f"telec {cmd_name} {sub_name}{args_str}{flag_hints}"
        entries.append(f"  {entry:<{col}}# {sub_cmd.desc}")
    return entries


def _group_subcommand_flags(cmd: CommandDef) -> list[tuple[str, list[Flag]]]:
    grouped: dict[str, list[tuple[str, list[Flag]]]] = {}
    for sub_name, sub_cmd in cmd.subcommands.items():
        if not sub_cmd.flags:
            continue
        key = "|".join(flag.long for flag in sub_cmd.flags)
        grouped.setdefault(key, []).append((sub_name, sub_cmd.flags))

    sections = []
    for group in grouped.values():
        names = [name for name, _ in group]
        label = "Options" if len(names) == len(cmd.subcommands) else f"{'/'.join(names)} options"
        sections.append((label, group[0][1]))
    return sections


def _usage_leaf(cmd_name: str, sub_name: str) -> str:
    """Generate help for a specific subcommand (e.g. 'roadmap add')."""
    cmd = CLI_SURFACE[cmd_name]
    sub = cmd.subcommands.get(sub_name)
    if not sub:
        return _usage_subcmd(cmd_name)

    args_str = f" {sub.args}" if sub.args else ""
    lines = ["Usage:", f"  telec {cmd_name} {sub_name}{args_str}"]
    lines.append(f"\n  {sub.desc}")

    visible = [f for f in sub.flags if f.long != "--help"] if sub.flags else []
    if visible:
        lines.append("\nOptions:")
        for f in visible:
            flag_label = f"  {f.short}, {f.long}" if f.short else f"  {f.long}"
            lines.append(f"{flag_label:<25s}{f.desc}")

    notes = sub.notes or [f"Use this command to {sub.desc.lower()}."]
    lines.append("\nNotes:")
    for note in notes:
        lines.append(f"  {note}")

    examples = sub.examples or _example_commands([cmd_name, sub_name], sub.args, visible)
    if examples:
        lines.append("\nExamples:")
        for example in examples:
            lines.append(f"  {example}")

    return "\n".join(lines) + "\n"


def _print_completion(value: str, description: str) -> None:
    """Print completion in value<TAB>description format for zsh."""
    print(f"{value}\t{description}")


def _handle_completion() -> None:
    """Handle shell completion requests."""
    import os

    comp_line = os.environ.get("COMP_LINE", "")
    parts = comp_line.split()

    # Remove "telec" from parts if present
    if parts and parts[0] == "telec":
        parts = parts[1:]

    # No command yet - complete commands
    if not parts:
        for cmd in _COMMANDS:
            _print_completion(cmd, _COMMAND_DESCRIPTIONS.get(cmd, ""))
        return

    cmd = parts[0]
    rest = parts[1:]
    current = parts[-1] if parts else ""
    is_partial = not comp_line.endswith(" ")

    # Completing the command itself
    if len(parts) == 1 and is_partial:
        for c in _COMMANDS:
            if c.startswith(current):
                _print_completion(c, _COMMAND_DESCRIPTIONS.get(c, ""))
        return

    # Command-specific completions
    if cmd in ("sync", "watch"):
        if cmd in CLI_SURFACE:
            _complete_flags(CLI_SURFACE[cmd].flag_tuples, rest, current, is_partial)
    elif cmd in (
        "todo",
        "roadmap",
        "config",
        "sessions",
        "agents",
        "channels",
        "docs",
        "computers",
        "projects",
        "bugs",
        "auth",
    ):
        _complete_subcmd(cmd, rest, current, is_partial)


def _flag_used(flag_tuple: tuple[str | None, str, str], used: set[str]) -> bool:
    """Check if a flag (short or long form) was already used."""
    short, long, _ = flag_tuple
    return (short and short in used) or (long in used)


def _flag_matches(flag_tuple: tuple[str | None, str, str], prefix: str) -> bool:
    """Check if a flag matches the current prefix."""
    short, long, _ = flag_tuple
    return (short and short.startswith(prefix)) or long.startswith(prefix)


def _print_flag(flag_tuple: tuple[str | None, str, str]) -> None:
    """Print a flag completion with optional short form."""
    short, long, desc = flag_tuple
    if short:
        _print_completion(f"{short}, {long}", desc)
    else:
        _print_completion(long, desc)


def _complete_flags(
    flags: list[tuple[str | None, str, str]], rest: list[str], current: str, is_partial: bool, args: str = ""
) -> None:
    """Complete commands with flags and optional positional arg hints."""
    used_flags = set(rest)
    if is_partial and current.startswith("-"):
        for flag in flags:
            if _flag_matches(flag, current) and not _flag_used(flag, used_flags):
                _print_flag(flag)
        return

    # Show positional arg hints for args not yet provided
    if args:
        positional_rest = [a for a in rest if not a.startswith("-")]
        for i, arg_hint in enumerate(args.split()):
            if i >= len(positional_rest):
                _print_completion(arg_hint, "required" if arg_hint.startswith("<") else "optional")

    for flag in flags:
        if not _flag_used(flag, used_flags):
            _print_flag(flag)


def _complete_subcmd(cmd_name: str, rest: list[str], current: str, is_partial: bool) -> None:
    """Complete commands with subcommands (todo, roadmap, config, etc.)."""
    cmd_def = CLI_SURFACE[cmd_name]

    # Subcommand completion: no args yet, or partially typing subcommand name
    if not rest or (len(rest) == 1 and is_partial):
        for subcommand, desc in cmd_def.subcmd_tuples:
            if not is_partial or subcommand.startswith(current):
                _print_completion(subcommand, desc)
        return

    # Subcommand-level completion: positional args + flags
    subcmd = rest[0]
    sub_def = cmd_def.subcommands.get(subcmd)
    flags = sub_def.flag_tuples if sub_def and sub_def.flags else cmd_def.flag_tuples

    # Count non-flag args provided after the subcommand
    positional_rest = [a for a in rest[1:] if not a.startswith("-")]
    expected_positionals = sub_def.args.split() if sub_def and sub_def.args else []

    used = set(rest[1:])
    if is_partial and current.startswith("-"):
        for flag in flags:
            if _flag_matches(flag, current) and not _flag_used(flag, used):
                _print_flag(flag)
        return

    # Show positional arg hints for args not yet provided
    for i, arg_hint in enumerate(expected_positionals):
        if i >= len(positional_rest):
            _print_completion(arg_hint, "required" if arg_hint.startswith("<") else "optional")

    for flag in flags:
        if not _flag_used(flag, used):
            _print_flag(flag)
