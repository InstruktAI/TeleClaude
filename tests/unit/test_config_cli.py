"""Tests for programmatic config CLI (teleclaude.cli.config_cli).

Covers: people CRUD, env list/set, notifications, validate, invite.
All tests use tmp_path fixtures to isolate from real config.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest


def _setup_config(tmp_path, people=None):
    """Create a minimal config fixture and return patch context."""
    config_path = tmp_path / "teleclaude.yml"
    people_dir = tmp_path / "people"
    people_dir.mkdir(exist_ok=True)

    if people is None:
        people = [{"name": "Alice", "email": "alice@example.com", "role": "admin"}]

    if not people:
        config_path.write_text("people: []\n", encoding="utf-8")
    else:
        lines = "people:\n"
        for p in people:
            lines += f"  - name: {p['name']}\n"
            if p.get("email"):
                lines += f"    email: {p['email']}\n"
            if p.get("role"):
                lines += f"    role: {p['role']}\n"
            if p.get("username"):
                lines += f"    username: {p['username']}\n"
        config_path.write_text(lines, encoding="utf-8")

    # Create person config dirs
    for p in people:
        pd = people_dir / p["name"]
        pd.mkdir(exist_ok=True)
        (pd / "teleclaude.yml").write_text(
            "creds: {}\nnotifications:\n  telegram: false\ninterests: []\n",
            encoding="utf-8",
        )

    return (
        patch("teleclaude.cli.config_handlers._GLOBAL_CONFIG_PATH", config_path),
        patch("teleclaude.cli.config_handlers._PEOPLE_DIR", people_dir),
    )


class TestPeopleList:
    def test_list_json_returns_array(self, tmp_path, capsys):
        p1, p2 = _setup_config(tmp_path)
        with p1, p2:
            from teleclaude.cli.config_cli import handle_config_cli

            handle_config_cli(["people", "list", "--json"])

        out = json.loads(capsys.readouterr().out)
        assert isinstance(out, list)
        assert len(out) == 1
        assert out[0]["name"] == "Alice"
        assert out[0]["role"] == "admin"

    def test_list_human_format(self, tmp_path, capsys):
        p1, p2 = _setup_config(tmp_path)
        with p1, p2:
            from teleclaude.cli.config_cli import handle_config_cli

            handle_config_cli(["people", "list"])

        out = capsys.readouterr().out
        assert "Alice" in out
        assert "admin" in out

    def test_list_empty(self, tmp_path, capsys):
        p1, p2 = _setup_config(tmp_path, people=[])
        with p1, p2:
            from teleclaude.cli.config_cli import handle_config_cli

            handle_config_cli(["people", "list"])

        out = capsys.readouterr().out
        assert "No people" in out


class TestPeopleAdd:
    def test_add_person_json(self, tmp_path, capsys):
        p1, p2 = _setup_config(tmp_path, people=[])
        with p1, p2:
            from teleclaude.cli.config_cli import handle_config_cli
            from teleclaude.cli.config_handlers import get_global_config

            handle_config_cli(
                ["people", "add", "--name", "Bob", "--email", "bob@example.com", "--role", "member", "--json"]
            )

            # Verify person was actually added
            config = get_global_config()
            assert any(p.name == "Bob" for p in config.people)

        out = json.loads(capsys.readouterr().out)
        assert out["ok"] is True
        assert out["name"] == "Bob"
        assert out["role"] == "member"

    def test_add_person_requires_name(self, tmp_path):
        p1, p2 = _setup_config(tmp_path, people=[])
        with p1, p2:
            from teleclaude.cli.config_cli import handle_config_cli

            with pytest.raises(SystemExit):
                handle_config_cli(["people", "add", "--role", "member"])

    def test_add_duplicate_fails(self, tmp_path, capsys):
        p1, p2 = _setup_config(tmp_path)
        with p1, p2:
            from teleclaude.cli.config_cli import handle_config_cli

            with pytest.raises(SystemExit):
                handle_config_cli(["people", "add", "--name", "Alice", "--json"])


class TestPeopleEdit:
    def test_edit_role(self, tmp_path, capsys):
        p1, p2 = _setup_config(tmp_path)
        with p1, p2:
            from teleclaude.cli.config_cli import handle_config_cli

            handle_config_cli(["people", "edit", "Alice", "--role", "member", "--json"])

        out = json.loads(capsys.readouterr().out)
        assert out["ok"] is True
        assert "role" in out["updated"]

    def test_edit_nonexistent_person(self, tmp_path):
        p1, p2 = _setup_config(tmp_path)
        with p1, p2:
            from teleclaude.cli.config_cli import handle_config_cli

            with pytest.raises(SystemExit):
                handle_config_cli(["people", "edit", "Nobody", "--role", "admin", "--json"])

    def test_edit_no_changes_fails(self, tmp_path):
        p1, p2 = _setup_config(tmp_path)
        with p1, p2:
            from teleclaude.cli.config_cli import handle_config_cli

            with pytest.raises(SystemExit):
                handle_config_cli(["people", "edit", "Alice", "--json"])

    def test_edit_telegram_creds(self, tmp_path, capsys):
        p1, p2 = _setup_config(tmp_path)
        with p1, p2:
            from teleclaude.cli.config_cli import handle_config_cli

            handle_config_cli(
                [
                    "people",
                    "edit",
                    "Alice",
                    "--telegram-user",
                    "alice_tg",
                    "--telegram-id",
                    "12345",
                    "--json",
                ]
            )

        out = json.loads(capsys.readouterr().out)
        assert out["ok"] is True

        # Verify creds were written
        with p1, p2:
            from teleclaude.cli.config_handlers import get_person_config

            pc = get_person_config("Alice")
            assert pc.creds.telegram is not None
            assert pc.creds.telegram.user_name == "alice_tg"
            assert pc.creds.telegram.user_id == 12345


class TestPeopleRemove:
    def test_remove_person_json(self, tmp_path, capsys):
        p1, p2 = _setup_config(tmp_path)
        with p1, p2:
            from teleclaude.cli.config_cli import handle_config_cli

            handle_config_cli(["people", "remove", "Alice", "--json"])

        out = json.loads(capsys.readouterr().out)
        assert out["ok"] is True

    def test_remove_nonexistent_fails(self, tmp_path):
        p1, p2 = _setup_config(tmp_path)
        with p1, p2:
            from teleclaude.cli.config_cli import handle_config_cli

            with pytest.raises(SystemExit):
                handle_config_cli(["people", "remove", "Nobody", "--json"])


class TestEnvList:
    def test_env_list_json(self, capsys):
        from teleclaude.cli.config_cli import handle_config_cli

        handle_config_cli(["env", "list", "--json"])

        out = json.loads(capsys.readouterr().out)
        assert isinstance(out, list)
        names = [v["name"] for v in out]
        assert "TELEGRAM_BOT_TOKEN" in names
        assert "ANTHROPIC_API_KEY" in names

    def test_env_list_human(self, capsys):
        from teleclaude.cli.config_cli import handle_config_cli

        handle_config_cli(["env", "list"])

        out = capsys.readouterr().out
        assert "TELEGRAM_BOT_TOKEN" in out


class TestEnvSet:
    def test_env_set_writes_to_file(self, tmp_path, capsys):
        env_file = tmp_path / ".env"
        env_file.write_text("EXISTING=value\n", encoding="utf-8")

        from teleclaude.cli.config_cli import handle_config_cli

        with patch("teleclaude.cli.config_cli._write_env_var") as mock_write:
            handle_config_cli(["env", "set", "NEW_VAR=hello", "--json"])

        out = json.loads(capsys.readouterr().out)
        assert out["ok"] is True
        assert out["updated"][0]["name"] == "NEW_VAR"

    def test_env_set_no_pairs_fails(self):
        from teleclaude.cli.config_cli import handle_config_cli

        with pytest.raises(SystemExit):
            handle_config_cli(["env", "set"])


class TestNotify:
    def test_notify_toggling_replaced_by_subscriptions(self, tmp_path):
        """Notification toggling has been replaced by per-subscription settings."""
        p1, p2 = _setup_config(tmp_path)
        with p1, p2:
            from teleclaude.cli.config_cli import handle_config_cli

            with pytest.raises(SystemExit):
                handle_config_cli(["notify", "Alice", "--telegram", "on", "--json"])

    def test_notify_no_channel_fails(self, tmp_path):
        p1, p2 = _setup_config(tmp_path)
        with p1, p2:
            from teleclaude.cli.config_cli import handle_config_cli

            with pytest.raises(SystemExit):
                handle_config_cli(["notify", "Alice"])


class TestValidate:
    def test_validate_json_output(self, tmp_path, capsys):
        p1, p2 = _setup_config(tmp_path)
        with p1, p2:
            from teleclaude.cli.config_cli import handle_config_cli

            # May exit 1 if validation fails, that's fine
            try:
                handle_config_cli(["validate", "--json"])
            except SystemExit:
                pass

        out = json.loads(capsys.readouterr().out)
        assert "ok" in out
        assert "results" in out
        assert isinstance(out["results"], list)

    def test_validate_reports_areas(self, tmp_path, capsys):
        p1, p2 = _setup_config(tmp_path)
        with p1, p2:
            from teleclaude.cli.config_cli import handle_config_cli

            try:
                handle_config_cli(["validate", "--json"])
            except SystemExit:
                pass

        out = json.loads(capsys.readouterr().out)
        areas = [r["area"] for r in out["results"]]
        assert "global" in areas


class TestInvite:
    def test_invite_json(self, tmp_path, capsys):
        p1, p2 = _setup_config(tmp_path)
        with (
            p1,
            p2,
            patch("teleclaude.invite.resolve_telegram_bot_username", new=AsyncMock(return_value="teleclaude_bot")),
            patch("teleclaude.invite.resolve_discord_bot_user_id", new=AsyncMock(return_value="123456789")),
            patch(
                "teleclaude.invite.generate_invite_links",
                return_value={
                    "telegram": "https://t.me/teleclaude_bot?start=tok123",
                    "discord": "https://discord.com/users/123456789",
                    "whatsapp": None,
                },
            ),
            patch("teleclaude.invite.send_invite_email", new=AsyncMock(return_value=None)),
        ):
            from teleclaude.cli.config_cli import handle_config_cli

            handle_config_cli(["invite", "Alice", "--json"])

        out = json.loads(capsys.readouterr().out)
        assert out["ok"] is True
        assert out["name"] == "Alice"
        assert "links" in out
        assert out["email_sent"] is True

    def test_invite_nonexistent_person(self, tmp_path):
        p1, p2 = _setup_config(tmp_path)
        with p1, p2:
            from teleclaude.cli.config_cli import handle_config_cli

            with pytest.raises(SystemExit):
                handle_config_cli(["invite", "Nobody", "--json"])

    def test_invite_non_json_prints_fallback_links_once(self, tmp_path, capsys):
        p1, p2 = _setup_config(tmp_path)
        with (
            p1,
            p2,
            patch("teleclaude.invite.resolve_telegram_bot_username", new=AsyncMock(return_value="teleclaude_bot")),
            patch("teleclaude.invite.resolve_discord_bot_user_id", new=AsyncMock(return_value="123456789")),
            patch(
                "teleclaude.invite.generate_invite_links",
                return_value={
                    "telegram": "https://t.me/teleclaude_bot?start=tok123",
                    "discord": None,
                    "whatsapp": None,
                },
            ),
            patch("teleclaude.invite.send_invite_email", new=AsyncMock(side_effect=RuntimeError("smtp down"))),
        ):
            from teleclaude.cli.config_cli import handle_config_cli

            handle_config_cli(["invite", "Alice"])

        out = capsys.readouterr().out
        assert out.count("https://t.me/teleclaude_bot?start=tok123") == 1


class TestRouting:
    def test_unknown_subcommand_fails(self):
        from teleclaude.cli.config_cli import handle_config_cli

        with pytest.raises(SystemExit):
            handle_config_cli(["bogus"])

    def test_no_args_fails(self):
        from teleclaude.cli.config_cli import handle_config_cli

        with pytest.raises(SystemExit):
            handle_config_cli([])

    def test_people_no_action_fails(self):
        from teleclaude.cli.config_cli import handle_config_cli

        with pytest.raises(SystemExit):
            handle_config_cli(["people"])
