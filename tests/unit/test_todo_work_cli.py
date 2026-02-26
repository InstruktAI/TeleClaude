from __future__ import annotations

from teleclaude.cli import tool_commands


def test_todo_work_uses_shell_cwd_when_slug_omitted(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    captured = {}

    def fake_tool_api_call(method: str, path: str, *, json_body=None, params=None):
        captured["method"] = method
        captured["path"] = path
        captured["json_body"] = json_body
        return {"ok": True}

    monkeypatch.setattr(tool_commands, "tool_api_call", fake_tool_api_call)
    monkeypatch.setattr(tool_commands, "print_json", lambda _data: None)

    tool_commands.handle_todo_work([])

    assert captured["method"] == "POST"
    assert captured["path"] == "/todos/work"
    json_body = captured["json_body"]
    assert isinstance(json_body, dict)
    assert json_body.get("cwd") == str(tmp_path)
    assert "slug" not in json_body


def test_todo_work_uses_shell_cwd_with_slug(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    captured = {}

    def fake_tool_api_call(method: str, path: str, *, json_body=None, params=None):
        captured["json_body"] = json_body
        return {"ok": True}

    monkeypatch.setattr(tool_commands, "tool_api_call", fake_tool_api_call)
    monkeypatch.setattr(tool_commands, "print_json", lambda _data: None)

    tool_commands.handle_todo_work(["mature-deployment"])

    json_body = captured["json_body"]
    assert isinstance(json_body, dict)
    assert json_body.get("slug") == "mature-deployment"
    assert json_body.get("cwd") == str(tmp_path)


def test_todo_work_ignores_legacy_cwd_flag(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    captured = {}

    def fake_tool_api_call(method: str, path: str, *, json_body=None, params=None):
        captured["json_body"] = json_body
        return {"ok": True}

    monkeypatch.setattr(tool_commands, "tool_api_call", fake_tool_api_call)
    monkeypatch.setattr(tool_commands, "print_json", lambda _data: None)

    tool_commands.handle_todo_work(["mature-deployment", "--cwd", "/tmp/not-used"])

    json_body = captured["json_body"]
    assert isinstance(json_body, dict)
    assert json_body.get("slug") == "mature-deployment"
    assert json_body.get("cwd") == str(tmp_path)
