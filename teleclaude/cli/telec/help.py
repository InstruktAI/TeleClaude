"""Help generation and shell completion for the telec CLI."""

from __future__ import annotations

import os
import shlex

from teleclaude.cli.telec.surface import CLI_SURFACE, CommandDef, Flag
from teleclaude.cli.telec.surface_types import strip_hidden_flag_tokens

# Derived constants for completion (from schema)
_COMMANDS = [name for name, cmd in CLI_SURFACE.items() if not cmd.hidden]
_COMMAND_DESCRIPTIONS = {name: cmd.desc for name, cmd in CLI_SURFACE.items() if not cmd.hidden}


__all__ = [
    "_complete_flags",
    "_complete_subcmd",
    "_flag_matches",
    "_flag_used",
    "_handle_completion",
    "_maybe_show_help",
    "_print_completion",
    "_print_flag",
    "_usage",
    "_usage_leaf",
    "_usage_main",
    "_usage_subcmd",
]


def _resolve_command_path(cmd: str, positionals: list[str]) -> tuple[list[str], CommandDef]:
    """Walk the CommandDef tree and return the full path and deepest matching node."""
    node = CLI_SURFACE.get(cmd)
    if node is None:
        return [cmd], CLI_SURFACE[cmd]  # let KeyError propagate naturally
    path = [cmd]
    for token in positionals:
        child = node.subcommands.get(token) if node.subcommands else None
        if child is None:
            break
        path.append(token)
        node = child
    return path, node


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


def _usage_resolved(path: list[str], node: CommandDef) -> str:
    """Render help for a resolved CommandDef node at any depth."""
    if node.subcommands:
        return _usage_node_with_subcommands(path, node)
    return _usage_node_leaf(path, node)


def _usage_node_with_subcommands(path: list[str], node: CommandDef) -> str:
    """Render subcmd-style help for a node that has children."""
    prefix = " ".join(path)
    col = 49
    lines = ["Usage:"]
    lines.extend(_iter_subcommand_entries_for(prefix, node, col))

    if node.notes:
        lines.append("\nNotes:")
        for note in node.notes:
            lines.append(f"  {note}")
    return "\n".join(lines) + "\n"


def _iter_subcommand_entries_for(prefix: str, node: CommandDef, col: int) -> list[str]:
    """Build usage entries for a node's subcommands."""
    entries: list[str] = []
    for sub_name, sub_cmd in node.subcommands.items():
        if sub_cmd.subcommands:
            for child_name, child_cmd in sub_cmd.subcommands.items():
                args = f" {child_cmd.args}" if child_cmd.args else ""
                entry = f"telec {prefix} {sub_name} {child_name}{args}{_inline_flags(child_cmd.flags)}"
                entries.append(f"  {entry:<{col}}# {child_cmd.desc}")
        else:
            args = f" {sub_cmd.args}" if sub_cmd.args else ""
            entry = f"telec {prefix} {sub_name}{args}{_inline_flags(sub_cmd.flags)}"
            entries.append(f"  {entry:<{col}}# {sub_cmd.desc}")
    return entries


def _usage_node_leaf(path: list[str], node: CommandDef) -> str:
    """Render leaf-style help for a node without children."""
    prefix = " ".join(path)
    cleaned_args = strip_hidden_flag_tokens(node.args, node.flags)
    args_str = f" {cleaned_args}" if cleaned_args else ""
    visible = _visible_flags(node.flags)
    lines = ["Usage:", f"  telec {prefix}{args_str}", f"\n  {node.desc}"]

    if visible:
        lines.append("\nOptions:")
        for f in visible:
            flag_label = f"  {f.short}, {f.long}" if f.short else f"  {f.long}"
            lines.append(f"{flag_label:<25s}{f.desc}")

    notes = node.notes or [f"Use this command to {node.desc.lower()}."]
    lines.append("\nNotes:")
    for note in notes:
        lines.append(f"  {note}")

    if node.examples:
        lines.append("\nExamples:")
        for example in node.examples:
            lines.append(f"  {example}")

    return "\n".join(lines) + "\n"


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
    path, node = _resolve_command_path(cmd, positionals)
    if len(path) > 1 and not node.subcommands:
        # Resolved to a leaf deeper than top-level — use resolved renderer.
        print(_usage_resolved(path, node))
    elif len(path) > 1 and node.subcommands:
        # Resolved to an intermediate node with children.
        print(_usage_resolved(path, node))
    else:
        # Top-level command — use existing renderers.
        print(_usage(cmd, positionals[0] if positionals else None))
    return True


def _inline_flags(flags: list[Flag]) -> str:
    """Format visible flags compactly for inline display in usage lines.

    Honors ``flag.hidden`` so hidden flags (including ``--help`` and
    ``--detach``) never surface in the trailing usage summary. The leaf
    Options/Notes/Examples sections remain unaffected — only the inline
    overview is suppressed.
    """
    visible = [f for f in flags if not f.hidden]
    if not visible:
        return ""
    names = " ".join(f.long for f in visible)
    return f" [{names}]"


def _usage_main() -> str:
    """Generate main help overview. Hidden flags are excluded."""
    col = 42
    lines = ["Usage:", f"  {'telec':<{col}}# Open TUI (Sessions view)"]
    for name, cmd in CLI_SURFACE.items():
        if cmd.hidden:
            continue
        lines.extend(_usage_main_entries(name, cmd, col))
    return "\n".join(lines) + "\n"


def _usage_main_entries(cmd_name: str, cmd: CommandDef, col: int) -> list[str]:
    visible_flags = cmd.visible_flags
    flag_str = ""
    if visible_flags:
        parts = [flag.short if flag.short else flag.long for flag in visible_flags]
        flag_str = " [" + "|".join(parts) + "]"

    cleaned_args = strip_hidden_flag_tokens(cmd.args, cmd.flags)
    args_str = f" {cleaned_args}" if cleaned_args else ""
    if not cmd.subcommands:
        entry = f"telec {cmd_name}{args_str}{flag_str}"
        return [f"  {entry:<{col}}# {cmd.desc}"]

    entries: list[str] = []
    if cmd.standalone:
        entry = f"telec {cmd_name}"
        entries.append(f"  {entry:<{col}}# {cmd.desc}")

    for sub_name, sub_cmd in cmd.subcommands.items():
        entries.extend(_usage_main_subcommand_entries(cmd_name, sub_name, sub_cmd, col))
    return entries


def _usage_main_subcommand_entries(cmd_name: str, sub_name: str, sub_cmd: CommandDef, col: int) -> list[str]:
    if sub_cmd.subcommands:
        return [
            _format_usage_entry((cmd_name, sub_name, child_name), child_cmd.args, child_cmd.flags, child_cmd.desc, col)
            for child_name, child_cmd in sub_cmd.subcommands.items()
        ]
    return [_format_usage_entry((cmd_name, sub_name), sub_cmd.args, sub_cmd.flags, sub_cmd.desc, col)]


def _format_usage_entry(
    command_parts: tuple[str, ...],
    args_spec: str,
    flags: list[Flag],
    desc: str,
    col: int,
) -> str:
    cleaned_args = strip_hidden_flag_tokens(args_spec, flags)
    args_str = f" {cleaned_args}" if cleaned_args else ""
    entry = f"telec {' '.join(command_parts)}{args_str}{_inline_flags(flags)}"
    return f"  {entry:<{col}}# {desc}"


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
    return [f for f in flags or [] if not f.hidden]


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
        flag_hints = _inline_flags(cmd.flags)
        entry = f"telec {cmd_name}{args_str}{flag_hints}"
        lines.append(f"  {entry:<{col}}# {cmd.desc}")
        _append_flag_section(lines, "Options", visible_cmd_flags)
        _append_examples(lines, cmd.examples or [])

    for entry in _iter_subcommand_entries(cmd_name, cmd, col):
        lines.append(entry)
    for label, flags in _group_subcommand_flags(cmd):
        _append_flag_section(lines, label, flags)

    if cmd.notes:
        lines.append("\nNotes:")
        for note in cmd.notes:
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
    _append_examples(lines, cmd.examples or [])


def _iter_subcommand_entries(cmd_name: str, cmd: CommandDef, col: int) -> list[str]:
    entries: list[str] = []
    for sub_name, sub_cmd in cmd.subcommands.items():
        if sub_cmd.subcommands:
            for child_name, child_cmd in sub_cmd.subcommands.items():
                child_args = f" {child_cmd.args}" if child_cmd.args else ""
                child_flag_hints = _inline_flags(child_cmd.flags)
                entry = f"telec {cmd_name} {sub_name} {child_name}{child_args}{child_flag_hints}"
                entries.append(f"  {entry:<{col}}# {child_cmd.desc}")
            continue
        args_str = f" {sub_cmd.args}" if sub_cmd.args else ""
        flag_hints = _inline_flags(sub_cmd.flags)
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

    if sub.examples:
        lines.append("\nExamples:")
        for example in sub.examples:
            lines.append(f"  {example}")

    return "\n".join(lines) + "\n"


def _print_completion(value: str, description: str) -> None:
    """Print completion in value<TAB>description format for zsh."""
    print(f"{value}\t{description}")


def _handle_completion() -> None:
    """Handle shell completion requests."""
    comp_line = os.environ.get("COMP_LINE", "")
    try:
        parts = shlex.split(comp_line, posix=True)
    except ValueError:
        # Unbalanced quote while the user is still typing — fall back to naive split.
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

    # Schema-driven dispatch: hand off to the right completer based on the command shape.
    cmd_def = CLI_SURFACE.get(cmd)
    if cmd_def is None or cmd_def.hidden:
        return
    if cmd_def.subcommands:
        _complete_subcmd(cmd, rest, current, is_partial)
    elif cmd_def.flags:
        _complete_flags(cmd_def.flag_tuples, rest, current, is_partial)


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
    """Complete commands with (possibly nested) subcommands."""
    # Walk as deep as possible into the subcommand tree, matching only child keys.
    node: CommandDef = CLI_SURFACE[cmd_name]
    consumed = 0
    for token in rest:
        child = node.subcommands.get(token) if node.subcommands else None
        if child is None:
            break
        node = child
        consumed += 1

    remaining = rest[consumed:]

    if node.subcommands:
        if not remaining or (len(remaining) == 1 and is_partial):
            for subcommand, desc in node.subcmd_tuples:
                if not is_partial or not remaining or subcommand.startswith(current):
                    _print_completion(subcommand, desc)
        return

    _complete_leaf_command(node, remaining, current, is_partial)


def _split_args_tokens(args: str) -> list[str]:
    """Bracket-aware tokenizer for CommandDef.args strings.

    Keeps `<name>` and balanced `[...]` (including nested `[--flag <value>]`)
    atomic so downstream hint rendering can distinguish real positionals from
    flag documentation.
    """
    tokens: list[str] = []
    i = 0
    length = len(args)
    while i < length:
        char = args[i]
        if char.isspace():
            i += 1
            continue
        if char == "[":
            depth = 1
            j = i + 1
            while j < length and depth > 0:
                if args[j] == "[":
                    depth += 1
                elif args[j] == "]":
                    depth -= 1
                j += 1
            tokens.append(args[i:j])
            i = j
        elif char == "<":
            close = args.find(">", i + 1)
            end = length if close == -1 else close + 1
            tokens.append(args[i:end])
            i = end
        else:
            j = i
            while j < length and not args[j].isspace():
                j += 1
            tokens.append(args[i:j])
            i = j
    return tokens


def _is_positional_hint(token: str) -> bool:
    """True when a tokenized args entry represents a positional, not flag documentation."""
    inner = token[1:-1] if token.startswith("[") and token.endswith("]") else token
    return not inner.startswith("-")


def _complete_leaf_command(node: CommandDef, remaining: list[str], current: str, is_partial: bool) -> None:
    """Emit positional hints and flag completions for a leaf command node."""
    positional_rest = [arg for arg in remaining if not arg.startswith("-")]
    expected_positionals = [t for t in _split_args_tokens(node.args) if _is_positional_hint(t)]
    used = set(remaining)
    flags = node.flag_tuples

    if is_partial and current.startswith("-"):
        for flag in flags:
            if _flag_matches(flag, current) and not _flag_used(flag, used):
                _print_flag(flag)
        return

    for i, arg_hint in enumerate(expected_positionals):
        if i >= len(positional_rest):
            _print_completion(arg_hint, "required" if arg_hint.startswith("<") else "optional")

    for flag in flags:
        if not _flag_used(flag, used):
            _print_flag(flag)
