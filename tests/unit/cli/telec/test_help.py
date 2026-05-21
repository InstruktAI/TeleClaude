from __future__ import annotations

import importlib
from unittest.mock import MagicMock

import pytest
from syrupy.assertion import SnapshotAssertion

from teleclaude.cli.telec.surface_types import _FLAG_DETACH, CommandDef, Flag

help_mod = importlib.import_module("teleclaude.cli.telec.help")
surface_mod = importlib.import_module("teleclaude.cli.telec.surface")


def _run_completion(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    comp_line: str,
) -> list[str]:
    """Invoke _handle_completion with COMP_LINE and return non-empty stdout rows."""
    monkeypatch.setenv("COMP_LINE", comp_line)
    monkeypatch.setenv("COMP_POINT", str(len(comp_line)))
    help_mod._handle_completion()
    return [line for line in capsys.readouterr().out.splitlines() if line]


def _completion_values(rows: list[str]) -> list[str]:
    """Return the insertable value column (text before the first tab) of each row."""
    return [row.split("\t", 1)[0] for row in rows]


def _collect_completion_contexts() -> list[str]:
    """Every non-hidden command context in CLI_SURFACE that should emit completions."""
    lines: list[str] = []

    def walk(path: list[str], node: CommandDef) -> None:
        if node.hidden:
            return
        if node.subcommands or node.flags or node.args:
            lines.append("telec " + " ".join(path) + " ")
        for sub_name, sub_node in node.subcommands.items():
            walk([*path, sub_name], sub_node)

    for name, cmd_def in surface_mod.CLI_SURFACE.items():
        walk([name], cmd_def)
    return lines


_COMPLETION_CONTEXTS = _collect_completion_contexts()


def test_maybe_show_help_prints_leaf_usage_when_help_follows_subcommand(
    capsys: pytest.CaptureFixture[str],
) -> None:
    shown = help_mod._maybe_show_help("docs", ["get", "--help"])

    assert shown is True
    out = capsys.readouterr().out
    assert "telec docs get" in out
    assert "Fetch full snippet content by ID" in out


def test_maybe_show_help_resolves_nested_subcommands(
    capsys: pytest.CaptureFixture[str],
) -> None:
    shown = help_mod._maybe_show_help("config", ["people", "add", "-h"])

    assert shown is True
    out = capsys.readouterr().out
    assert "telec config people add" in out
    assert "Add a person" in out


def test_maybe_show_help_resolves_intermediate_node(
    capsys: pytest.CaptureFixture[str],
) -> None:
    shown = help_mod._maybe_show_help("config", ["people", "-h"])

    assert shown is True
    out = capsys.readouterr().out
    assert "telec config people list" in out
    assert "telec config people add" in out


def test_complete_flags_only_prints_matching_unused_options(monkeypatch: pytest.MonkeyPatch) -> None:
    printed = MagicMock()

    monkeypatch.setattr(help_mod, "_print_flag", printed)

    help_mod._complete_flags(
        [("-a", "--agent", "Agent"), ("-m", "--mode", "Mode")],
        ["--agent"],
        "--m",
        True,
    )

    printed.assert_called_once_with(("-m", "--mode", "Mode"))


def test_split_args_tokens_keeps_bracketed_flag_docs_and_positionals_atomic() -> None:
    """`[--flag <value>]` and `[<positional>]` must each tokenize as single units."""
    tokens = help_mod._split_args_tokens(
        "<slug> [<message>] [terms...] [--direct] [--agent <name>] [--changed-paths <paths>]"
    )

    assert tokens == [
        "<slug>",
        "[<message>]",
        "[terms...]",
        "[--direct]",
        "[--agent <name>]",
        "[--changed-paths <paths>]",
    ]


def test_flag_detach_hidden_attribute_is_true() -> None:
    """Schema-level anchor: the contract that drives --detach suppression
    is that ``_FLAG_DETACH.hidden`` is True. Snapshots in the rendered-
    output tests below capture the downstream effect; this assertion pins
    the upstream cause as identity, independent of any rendered text."""
    assert _FLAG_DETACH.hidden is True


def test_todo_dump_draft_flag_hidden_attribute_is_true() -> None:
    dump_command = surface_mod.CLI_SURFACE["todo"].subcommands["dump"]
    draft_flag = next(flag for flag in dump_command.flags if flag.long == "--draft")

    assert draft_flag.hidden is True


def test_usage_main_sessions_overview_renders_without_hidden_flags(
    snapshot: SnapshotAssertion,
) -> None:
    """The top-level overview lines for sessions start / sessions run are
    snapshotted in full. Future drift — including any reintroduction of
    --detach to the overview — produces a reviewable snapshot delta."""
    overview = help_mod._usage_main()
    sessions_block = "\n".join(
        line for line in overview.splitlines() if "telec sessions start" in line or "telec sessions run" in line
    )
    assert sessions_block == snapshot


def test_usage_subcmd_todo_dump_renders_without_hidden_flags(
    snapshot: SnapshotAssertion,
) -> None:
    todo_help = help_mod._usage_subcmd("todo")
    dump_line = "\n".join(line for line in todo_help.splitlines() if "telec todo dump" in line)

    assert dump_line == snapshot


def _fixture_surface_with_hidden_sub() -> CommandDef:
    """Minimal CommandDef tree with one visible and one hidden subcommand.

    Used to pin the hidden-subcommand filter independently at each renderer
    site, so future iteration sites that forget to honor ``sub.hidden``
    surface as targeted test failures instead of hiding behind a global
    snapshot."""
    return CommandDef(
        desc="root",
        subcommands={
            "vis": CommandDef(desc="visible sub", args="<x>", flags=[Flag("--alpha", desc="a")]),
            "hid": CommandDef(
                desc="hidden sub",
                args="<y>",
                flags=[Flag("--beta", desc="b")],
                hidden=True,
            ),
        },
    )


def test_memories_save_subcommand_is_hidden() -> None:
    """Schema anchor: ``memories save`` is reserved for the memory scraper
    and must not surface in any subcommand-list renderer or completion."""
    assert surface_mod.CLI_SURFACE["memories"].subcommands["save"].hidden is True


def test_todo_dump_subcommand_is_hidden() -> None:
    """Schema anchor: the deprecated ``todo dump`` alias is hidden from listings."""
    assert surface_mod.CLI_SURFACE["todo"].subcommands["dump"].hidden is True


def _visible_subcommand_count(fixture: CommandDef) -> int:
    return sum(1 for sub in fixture.subcommands.values() if not sub.hidden)


def test_iter_subcommand_entries_skips_hidden_subcommand() -> None:
    """Per-entry count equals the visible-sub count — adding/removing visible
    or hidden subs to the fixture moves the assertion correctly without any
    substring comparison against rendered output."""
    fixture = _fixture_surface_with_hidden_sub()
    entries = help_mod._iter_subcommand_entries("fake", fixture, col=40)
    assert len(entries) == _visible_subcommand_count(fixture)


def test_iter_subcommand_entries_for_skips_hidden_subcommand() -> None:
    fixture = _fixture_surface_with_hidden_sub()
    entries = help_mod._iter_subcommand_entries_for("fake", fixture, col=40)
    assert len(entries) == _visible_subcommand_count(fixture)


def test_usage_main_subcommand_entries_skips_hidden_subcommand() -> None:
    fixture = _fixture_surface_with_hidden_sub()
    hidden_entries = help_mod._usage_main_subcommand_entries("fake", "hid", fixture.subcommands["hid"], col=40)
    visible_entries = help_mod._usage_main_subcommand_entries("fake", "vis", fixture.subcommands["vis"], col=40)
    assert hidden_entries == []
    assert len(visible_entries) == 1


def test_group_subcommand_flags_skips_hidden_subcommand() -> None:
    """Identifier-level set equality (flag long-names are identifiers, not
    human-facing text) pins that only the visible sub's flags reach the
    grouped section, without inspecting any rendered string."""
    fixture = _fixture_surface_with_hidden_sub()
    sections = help_mod._group_subcommand_flags(fixture)
    flag_longs = {flag.long for _, flags in sections for flag in flags}
    assert flag_longs == {"--alpha"}


def test_subcmd_tuples_excludes_hidden_subcommand() -> None:
    """surface_types: ``CommandDef.subcmd_tuples`` powers shell completion."""
    fixture = _fixture_surface_with_hidden_sub()
    names = {name for name, _ in fixture.subcmd_tuples}
    assert names == {"vis"}


def test_usage_leaf_sessions_run_renders_full_output(snapshot: SnapshotAssertion) -> None:
    """Full leaf help for telec sessions run. The snapshot captures the
    Usage line, Options list, Notes warning, and Examples — the entire
    contract surface for the hidden-flag behavior in one assertion."""
    assert help_mod._usage_leaf("sessions", "run") == snapshot


# guard: parametrize-cleanup-pending
@pytest.mark.parametrize("command_line", _COMPLETION_CONTEXTS)
def test_handle_completion_emits_well_formed_tokens_for_every_command_context(
    command_line: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Every non-hidden CLI_SURFACE context must emit balanced, non-flag-doc positional hints."""
    values = _completion_values(_run_completion(monkeypatch, capsys, command_line))

    assert values, f"{command_line!r} emitted no completion rows"
    for value in values:
        assert value.count("[") == value.count("]"), f"{command_line!r} emitted unbalanced brackets in {value!r}"
        assert value.count("<") == value.count(">"), f"{command_line!r} emitted unbalanced angle brackets in {value!r}"
        if value.startswith("["):
            inner = value[1:-1]
            assert not inner.startswith("-"), f"{command_line!r} leaked flag-doc token as positional hint: {value!r}"
