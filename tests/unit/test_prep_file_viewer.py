"""Unit tests for filepath-based file viewer and editor command."""

from pathlib import Path


def test_editor_command_absolute_path():
    """_build_editor_command produces correct command from absolute filepath."""
    from teleclaude.cli.tui.views.preparation import PreparationView

    view = PreparationView()
    filepath = "/home/user/project/todos/my-slug/requirements.md"
    cmd = view._editor_command(filepath)
    assert filepath in cmd
    assert "teleclaude.cli.editor" in cmd


def test_editor_command_view_flag():
    """_editor_command includes --view flag when requested."""
    from teleclaude.cli.tui.views.preparation import PreparationView

    view = PreparationView()
    filepath = "/home/user/project/todos/roadmap.yaml"
    cmd = view._editor_command(filepath, view=True)
    assert "--view" in cmd
    assert filepath in cmd


def test_editor_command_theme_flag():
    """_editor_command includes --theme flag when theme is set."""
    from teleclaude.cli.tui.views.preparation import PreparationView

    view = PreparationView()
    view.theme = "dark"
    filepath = "/home/user/project/todos/roadmap.yaml"
    cmd = view._editor_command(filepath)
    assert "--theme dark" in cmd
