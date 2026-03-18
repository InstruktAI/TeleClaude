"""Action, check_action, and focus mixin for PreparationView."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

from teleclaude.cli.tui.messages import DocEditRequest, DocPreviewRequest
from teleclaude.cli.tui.views._footer_actions import (
    refresh_footer_bindings,
    sync_default_footer_action,
)
from teleclaude.cli.tui.views._project_actions import save_new_project
from teleclaude.cli.tui.widgets.computer_header import ComputerHeader
from teleclaude.cli.tui.widgets.group_separator import GroupSeparator
from teleclaude.cli.tui.widgets.modals import ConfirmModal, CreateSlugModal, NewProjectModal, NewProjectResult
from teleclaude.cli.tui.widgets.project_header import ProjectHeader
from teleclaude.cli.tui.widgets.todo_file_row import TodoFileRow
from teleclaude.cli.tui.widgets.todo_row import TodoRow
from teleclaude.constants import SlashCommand
from teleclaude.core.next_machine.core import DOR_READY_THRESHOLD, freeze_to_icebox
from teleclaude.core.next_machine.worktrees import _ensure_todo_on_remote_main
from teleclaude.todo_scaffold import create_bug_skeleton, create_todo_skeleton, remove_todo

if TYPE_CHECKING:
    from teleclaude.cli.models import ProjectWithTodosInfo  # pylint: disable=import-outside-toplevel,ungrouped-imports


class PreparationViewActionsMixin:  # pylint: disable=too-many-public-methods,protected-access
    """Keyboard actions, check_action, watch_cursor_index, on_focus for PreparationView."""

    if TYPE_CHECKING:
        app: Any
        _projects_with_todos: list[ProjectWithTodosInfo]

    @staticmethod
    def _next_command(base: str, slug: str | None) -> str:
        """Build /next-* command with optional slug."""
        return f"/{base} {slug}" if slug else f"/{base}"

    def action_cursor_up(self) -> None:
        """Move the cursor to the previous preparation item."""
        if self._nav_items and self.cursor_index > 0:  # type: ignore[attr-defined]
            self.cursor_index -= 1  # type: ignore[attr-defined]
            self._update_cursor_highlight()  # type: ignore[attr-defined]
            if 0 <= self.cursor_index < len(self._nav_items):  # type: ignore[attr-defined]
                self._nav_items[self.cursor_index].scroll_visible()  # type: ignore[attr-defined]

    def action_cursor_down(self) -> None:
        """Move the cursor to the next preparation item."""
        if self._nav_items and self.cursor_index < len(self._nav_items) - 1:  # type: ignore[attr-defined]
            self.cursor_index += 1  # type: ignore[attr-defined]
            self._update_cursor_highlight()  # type: ignore[attr-defined]
            if 0 <= self.cursor_index < len(self._nav_items):  # type: ignore[attr-defined]
                self._nav_items[self.cursor_index].scroll_visible()  # type: ignore[attr-defined]

    def _current_computer_header(self) -> ComputerHeader | None:
        """Return the selected computer header, if the cursor is on one."""
        item = self._current_item()  # type: ignore[attr-defined]
        return item if isinstance(item, ComputerHeader) else None

    def _find_root_todo_neighbors(self) -> tuple[str | None, str | None]:
        """Return (prev_root_slug, next_root_slug) relative to the current cursor.

        Search stops at ProjectHeader or ComputerHeader boundaries so reordering
        is scoped to the current project's roadmap.
        """
        current_idx = self.cursor_index  # type: ignore[attr-defined]
        prev_slug: str | None = None
        next_slug: str | None = None

        for i in range(current_idx - 1, -1, -1):
            widget = self._nav_items[i]  # type: ignore[attr-defined]
            if isinstance(widget, (ProjectHeader, ComputerHeader, GroupSeparator)):
                break
            if isinstance(widget, TodoRow) and not widget._tree_lines:
                prev_slug = widget.slug
                break

        for i in range(current_idx + 1, len(self._nav_items)):  # type: ignore[attr-defined]
            widget = self._nav_items[i]  # type: ignore[attr-defined]
            if isinstance(widget, (ProjectHeader, ComputerHeader, GroupSeparator)):
                break
            if isinstance(widget, TodoRow) and not widget._tree_lines:
                next_slug = widget.slug
                break

        return prev_slug, next_slug

    def action_move_todo_up(self) -> None:
        """Shift+Up: move current root todo one position up in the roadmap."""
        current = self._current_todo_row()  # type: ignore[attr-defined]
        if not current or current._tree_lines:
            return

        slug = current.slug
        prev_slug, _ = self._find_root_todo_neighbors()
        if prev_slug is None:
            return

        project_path = self._slug_to_project_path.get(slug, "")  # type: ignore[attr-defined]
        if not project_path:
            return

        try:
            subprocess.run(
                ["telec", "roadmap", "move", slug, "--before", prev_slug],
                check=True,
                cwd=project_path,
                capture_output=True,
            )
        except subprocess.CalledProcessError as exc:
            self.app.notify(
                f"Reorder failed: {exc.stderr.decode()[:80]}",
                severity="error",
            )  # type: ignore[attr-defined]
            return

        self.cursor_index -= 1  # type: ignore[attr-defined]
        self.app._refresh_data()  # type: ignore[attr-defined]

    def action_move_todo_down(self) -> None:
        """Shift+Down: move current root todo one position down in the roadmap."""
        current = self._current_todo_row()  # type: ignore[attr-defined]
        if not current or current._tree_lines:
            return

        slug = current.slug
        _, next_slug = self._find_root_todo_neighbors()
        if next_slug is None:
            return

        project_path = self._slug_to_project_path.get(slug, "")  # type: ignore[attr-defined]
        if not project_path:
            return

        try:
            subprocess.run(
                ["telec", "roadmap", "move", slug, "--after", next_slug],
                check=True,
                cwd=project_path,
                capture_output=True,
            )
        except subprocess.CalledProcessError as exc:
            self.app.notify(
                f"Reorder failed: {exc.stderr.decode()[:80]}",
                severity="error",
            )  # type: ignore[attr-defined]
            return

        self.cursor_index += 1  # type: ignore[attr-defined]
        self.app._refresh_data()  # type: ignore[attr-defined]

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Enable/hide actions based on current tree node type."""
        del parameters
        item = self._current_item()  # type: ignore[attr-defined]
        computer_only = {
            "new_todo",
            "new_bug",
            "remove_todo",
            "activate",
            "preview_file",
            "prepare",
            "start_work",
            "refine",
            "freeze",
            "move_todo_up",
            "move_todo_down",
        }
        project_disallowed = {
            "remove_todo",
            "activate",
            "preview_file",
            "new_project",
            "refine",
            "freeze",
            "move_todo_up",
            "move_todo_down",
        }
        file_disallowed = {"new_todo", "new_bug", "new_project", "freeze", "move_todo_up", "move_todo_down"}

        if isinstance(item, ComputerHeader):
            return action not in computer_only

        if isinstance(item, ProjectHeader):
            return action not in project_disallowed

        if isinstance(item, TodoRow):
            if action in {"preview_file", "new_project"}:
                return False
            return action not in {"move_todo_up", "move_todo_down"} or not item._tree_lines

        if isinstance(item, TodoFileRow):
            return action not in file_disallowed

        return True

    def watch_cursor_index(self, _index: int) -> None:
        """Refresh key bindings when node context changes."""
        if self.is_attached:  # type: ignore[attr-defined]
            self.app.refresh_bindings()  # type: ignore[attr-defined]
            self.call_after_refresh(self._sync_default_footer_action)  # type: ignore[attr-defined]

    def _default_footer_action(self) -> str | None:
        """Return the primary action for the selected node."""
        item = self._current_item()  # type: ignore[attr-defined]
        if isinstance(item, ComputerHeader):
            return "new_project"
        if isinstance(item, ProjectHeader):
            return "new_todo"
        if isinstance(item, (TodoRow, TodoFileRow)):
            return "activate"
        return None

    def _sync_default_footer_action(self) -> None:
        """Mark the active default action in Footer."""
        sync_default_footer_action(self, self._default_footer_action())

    def on_focus(self) -> None:
        """Sync default footer styling when the view receives focus."""
        refresh_footer_bindings(self, self._sync_default_footer_action)

    def action_expand(self) -> None:
        """Right: expand todo to show files."""
        row = self._current_todo_row()  # type: ignore[attr-defined]
        if row:
            self._expand_todo(row)  # type: ignore[attr-defined]

    def action_collapse(self) -> None:
        """Left: collapse todo or jump to parent todo from file row."""
        row = self._current_todo_row()  # type: ignore[attr-defined]
        if row:
            self._collapse_todo(row)  # type: ignore[attr-defined]
            return
        file_row = self._current_file_row()  # type: ignore[attr-defined]
        if file_row:
            parent = self._find_parent_todo(file_row)  # type: ignore[attr-defined]
            if parent:
                self._collapse_todo(parent)  # type: ignore[attr-defined]
                # Move cursor to parent
                try:
                    self.cursor_index = self._nav_items.index(parent)  # type: ignore[attr-defined]
                except ValueError:
                    pass
                self._update_cursor_highlight()  # type: ignore[attr-defined]

    def action_activate(self) -> None:
        """Enter: toggle expand/collapse on todo, open editor on file."""
        row = self._current_todo_row()  # type: ignore[attr-defined]
        if row:
            if self._is_expanded(row.slug):  # type: ignore[attr-defined]
                self._collapse_todo(row)  # type: ignore[attr-defined]
            else:
                self._expand_todo(row)  # type: ignore[attr-defined]
            return
        file_row = self._current_file_row()  # type: ignore[attr-defined]
        if file_row:
            self.post_message(  # type: ignore[attr-defined]
                DocEditRequest(
                    doc_id=file_row.filepath,
                    command=self._editor_command(file_row.filepath),  # type: ignore[attr-defined]
                    title=f"Editing: {file_row.filename}",
                )
            )

    def action_expand_all(self) -> None:
        """Expand every todo row in the current list."""
        for widget in list(self._nav_items):  # type: ignore[attr-defined]
            if isinstance(widget, TodoRow) and not self._is_expanded(widget.slug):  # type: ignore[attr-defined]
                self._expand_todo(widget)  # type: ignore[attr-defined]

    def action_collapse_all(self) -> None:
        """Collapse every expanded todo row in the current list."""
        for widget in list(self._nav_items):  # type: ignore[attr-defined]
            if isinstance(widget, TodoRow) and self._is_expanded(widget.slug):  # type: ignore[attr-defined]
                self._collapse_todo(widget)  # type: ignore[attr-defined]

    def action_preview_file(self) -> None:
        """Space: preview the current file in view mode (no focus)."""
        file_row = self._current_file_row()  # type: ignore[attr-defined]
        if file_row:
            self.post_message(  # type: ignore[attr-defined]
                DocPreviewRequest(
                    doc_id=file_row.filepath,
                    command=self._editor_command(file_row.filepath, view=True),  # type: ignore[attr-defined]
                    title=file_row.filename,
                )
            )

    def _resolve_project_root(self) -> str:
        """Resolve project root from known project paths or cwd."""
        for path in self._slug_to_project_path.values():  # type: ignore[attr-defined]
            return path
        return os.getcwd()

    def _create_item(self, slug: str, *, kind: str) -> None:
        """Scaffold a todo or bug and open its primary file in the editor."""
        project_root = self._resolve_project_root()

        if kind == "bug":
            try:
                todo_dir = create_bug_skeleton(Path(project_root), slug, description="")
            except ValueError as exc:
                self.app.notify(str(exc), severity="error")  # type: ignore[attr-defined]
                return
            filename = "bug.md"
        else:
            try:
                todo_dir = create_todo_skeleton(Path(project_root), slug)
            except ValueError as exc:
                self.app.notify(str(exc), severity="error")  # type: ignore[attr-defined]
                return
            filename = "input.md"

        # --- Commit and push scaffold to remote ---
        pushed, reason = _ensure_todo_on_remote_main(str(project_root), slug)
        if pushed:
            self.app.notify(
                f"Scaffold for {slug} pushed to remote",
                severity="information",
            )  # type: ignore[attr-defined]
        elif reason not in ("already_on_remote", "no_local_artifacts", "not_a_repo"):
            self.app.notify(
                f"Warning: Scaffold for {slug} not pushed to remote: {reason}",
                severity="warning",
            )  # type: ignore[attr-defined]

        filepath = str(todo_dir / filename)
        self.post_message(  # type: ignore[attr-defined]
            DocEditRequest(
                doc_id=filepath,
                command=self._editor_command(filepath),  # type: ignore[attr-defined]
                title=f"Editing: {todo_dir.name}/{filename}",
            )
        )

    def action_new_project(self) -> None:
        """n on computer header: open New Project modal."""
        item = self._current_item()  # type: ignore[attr-defined]
        if not isinstance(item, ComputerHeader):
            return

        comp_name = item.data.computer.name
        existing_projects = [  # type: ignore[attr-defined]
            p for p in self._projects_with_todos if (p.computer or "local") == comp_name
        ]
        existing_names = {p.name for p in existing_projects}
        existing_paths = {p.path for p in existing_projects}

        def on_result(result: NewProjectResult | None) -> None:
            if not result:
                return
            save_new_project(self.app, result)  # type: ignore[attr-defined]

        self.app.push_screen(  # type: ignore[attr-defined]
            NewProjectModal(existing_names=existing_names, existing_paths=existing_paths),
            on_result,
        )

    def action_new_todo(self) -> None:
        """n: create a new todo via modal."""

        def _on_result(slug: str | None) -> None:
            if slug:
                self._create_item(slug, kind="todo")

        self.app.push_screen(  # type: ignore[attr-defined]
            CreateSlugModal(title="New Todo"),
            callback=_on_result,
        )

    def action_new_bug(self) -> None:
        """b: create a new bug via modal."""

        def _on_result(slug: str | None) -> None:
            if slug:
                self._create_item(slug, kind="bug")

        self.app.push_screen(  # type: ignore[attr-defined]
            CreateSlugModal(title="New Bug", placeholder="my-new-bug"),
            callback=_on_result,
        )

    def action_remove_todo(self) -> None:
        """R: remove a todo and all its files."""
        # Resolve slug from current row (todo or file)
        row = self._current_todo_row()  # type: ignore[attr-defined]
        slug = row.slug if row else None
        if not slug:
            file_row = self._current_file_row()  # type: ignore[attr-defined]
            if file_row:
                slug = file_row.slug
        if not slug:
            return

        # Resolve project root
        project_path = self._slug_to_project_path.get(slug, "")  # type: ignore[attr-defined]
        if not project_path:
            return
        project_root = Path(project_path)

        def _on_confirm(confirmed: bool | None) -> None:
            if not confirmed:
                return
            try:
                remove_todo(project_root, slug)
                self.app.notify(f"Removed {slug}")  # type: ignore[attr-defined]
            except (ValueError, RuntimeError, FileNotFoundError) as exc:
                self.app.notify(str(exc), severity="error")  # type: ignore[attr-defined]

        self.app.push_screen(  # type: ignore[attr-defined]
            ConfirmModal(
                title="Remove Todo",
                message=f"Remove todo '{slug}' and all its files?\n\nThis action cannot be undone.",
            ),
            _on_confirm,
        )

    def action_prepare(self) -> None:
        """p: open session modal prefilled with /next-prepare [slug]."""
        context = self._resolve_cursor_context()  # type: ignore[attr-defined]
        if not context:
            return
        computer, project_path, slug = context
        self._open_session_modal(  # type: ignore[attr-defined]
            computer=computer,
            project_path=project_path,
            default_message=self._next_command(SlashCommand.NEXT_PREPARE.value, slug),
        )

    def action_start_work(self) -> None:
        """s: open session modal prefilled with /next-work [slug].

        Gated on DOR readiness when a specific todo is selected.
        """
        context = self._resolve_cursor_context()  # type: ignore[attr-defined]
        if not context:
            return
        computer, project_path, slug = context

        if slug:
            todo_row = self._resolve_todo_for_cursor()  # type: ignore[attr-defined]
            if not todo_row:
                return
            file_names = {name.lower() for name in todo_row.todo.files}
            is_bug = "bug.md" in file_names
            if not is_bug:
                is_bug = (Path(project_path) / "todos" / slug / "bug.md").exists()
            if not is_bug:
                dor = todo_row.todo.dor_score
                if dor is None or dor < DOR_READY_THRESHOLD:
                    self.app.notify(
                        f"DOR score too low ({dor or 0}/{DOR_READY_THRESHOLD})",
                        severity="warning",
                    )  # type: ignore[attr-defined]
                    return

        self._open_session_modal(  # type: ignore[attr-defined]
            computer=computer,
            project_path=project_path,
            default_message=self._next_command(SlashCommand.NEXT_WORK.value, slug),
        )

    def action_refine(self) -> None:
        """r: open session modal prefilled with /next-refine-input [slug]."""
        context = self._resolve_cursor_context()  # type: ignore[attr-defined]
        if not context:
            return
        computer, project_path, slug = context
        self._open_session_modal(  # type: ignore[attr-defined]
            computer=computer,
            project_path=project_path,
            default_message=self._next_command(SlashCommand.NEXT_REFINE_INPUT.value, slug),
        )

    def action_freeze(self) -> None:
        """f: freeze a todo to the icebox."""
        row = self._current_todo_row()  # type: ignore[attr-defined]
        slug = row.slug if row else None
        if not slug:
            return

        project_path = self._slug_to_project_path.get(slug, "")  # type: ignore[attr-defined]
        if not project_path:
            return

        def _on_confirm(confirmed: bool | None) -> None:
            if not confirmed:
                return
            try:
                if freeze_to_icebox(project_path, slug):
                    self.app.notify(f"Frozen '{slug}' to icebox")  # type: ignore[attr-defined]
                    self.app._refresh_data()  # type: ignore[attr-defined]
                else:
                    self.app.notify(
                        f"Failed to freeze '{slug}'",
                        severity="error",
                    )  # type: ignore[attr-defined]
            except (ValueError, RuntimeError, FileNotFoundError) as exc:
                self.app.notify(str(exc), severity="error")  # type: ignore[attr-defined]

        self.app.push_screen(  # type: ignore[attr-defined]
            ConfirmModal(
                title="Freeze Todo",
                message=f"Freeze '{slug}' to icebox?",
            ),
            _on_confirm,
        )
