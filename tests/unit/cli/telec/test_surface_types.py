"""CLI surface type tests."""

from __future__ import annotations

import importlib

from syrupy.assertion import SnapshotAssertion

from teleclaude.cli.telec.surface_types import Flag
from teleclaude.constants import HUMAN_ROLE_MEMBER, ROLE_SYSTEM

surface_types = importlib.import_module("teleclaude.cli.telec.surface_types")


def test_command_auth_prefers_system_roles_for_agent_callers() -> None:
    auth = surface_types.CommandAuth(system=frozenset({"orch"}), human=frozenset({"member"}))

    assert auth.allows("orch", None) is True
    assert auth.allows("worker", "member") is False
    assert auth.allows(None, "member") is True


def test_flag_as_tuple_preserves_short_long_and_description() -> None:
    flag = surface_types.Flag("--project", "-p", "Project path")

    assert flag.as_tuple() == ("-p", "--project", "Project path")


def test_command_def_visible_flags_omits_hidden_flags() -> None:
    command = surface_types.CommandDef(
        desc="visible flags",
        flags=[surface_types.Flag("--project"), surface_types.Flag("--help", hidden=True)],
    )

    assert [flag.long for flag in command.visible_flags] == ["--project"]


def test_command_def_tuples_reflect_flags_and_subcommands() -> None:
    command = surface_types.CommandDef(
        desc="root",
        flags=[surface_types.Flag("--project", "-p", "Project path")],
        subcommands={"show": surface_types.CommandDef(desc="Show data")},
    )

    assert command.flag_tuples == [("-p", "--project", "Project path")]
    assert command.subcmd_tuples == [("show", "Show data")]


def test_auth_shorthand_sets_include_expected_roles() -> None:
    assert ROLE_SYSTEM in surface_types._SYS_ORCH
    assert HUMAN_ROLE_MEMBER in surface_types._HR_MEMBER


def _strip(args: str, flags: list[Flag]) -> str:
    return surface_types.strip_hidden_flag_tokens(args, flags)


class TestStripHiddenFlagTokens:
    def test_returns_args_unchanged_when_no_flags(self, snapshot: SnapshotAssertion) -> None:
        assert _strip("<slug>", []) == snapshot

    def test_returns_empty_for_empty_args(self, snapshot: SnapshotAssertion) -> None:
        assert _strip("", [Flag("--x", hidden=True)]) == snapshot

    def test_noop_when_no_flag_is_hidden(self, snapshot: SnapshotAssertion) -> None:
        assert _strip("[--a] [--b <val>]", [Flag("--a"), Flag("--b")]) == snapshot

    def test_strips_boolean_token_at_end_of_string(self, snapshot: SnapshotAssertion) -> None:
        flags = [Flag("--a"), Flag("--detach", hidden=True)]
        assert _strip("[--a] [--detach]", flags) == snapshot

    def test_strips_value_token_mid_string(self, snapshot: SnapshotAssertion) -> None:
        flags = [Flag("--a"), Flag("--token", hidden=True), Flag("--b")]
        assert _strip("[--a] [--token <secret>] [--b]", flags) == snapshot

    def test_strips_token_at_start_of_string(self, snapshot: SnapshotAssertion) -> None:
        flags = [Flag("--secret", hidden=True), Flag("--b")]
        assert _strip("[--secret] [--b]", flags) == snapshot

    def test_strips_multiple_hidden_tokens(self, snapshot: SnapshotAssertion) -> None:
        flags = [
            Flag("--x", hidden=True),
            Flag("--a"),
            Flag("--y", hidden=True),
        ]
        assert _strip("[--x] [--a] [--y]", flags) == snapshot

    def test_preserves_required_positionals(self, snapshot: SnapshotAssertion) -> None:
        flags = [Flag("--detach", hidden=True)]
        assert _strip("<slug> [--detach]", flags) == snapshot
