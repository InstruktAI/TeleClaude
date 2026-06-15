"""Rendering and click-handler mixin for ConfigContent."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.style import Style
from rich.text import Text

from teleclaude.cli.config_handlers import EnvVarStatus
from teleclaude.cli.tui.config_components.guidance import FieldGuidance, guidance_registry
from teleclaude.cli.tui.views._config_constants import (
    _DIM,
    _FAIL,
    _GUIDED_STEPS,
    _INFO,
    _OK,
    _SEP,
    _SUBTABS,
    _TAB_ACTIVE,
    _TAB_INACTIVE,
    Subtab,
    _normal_style,
)
from teleclaude.cli.tui.views.reflection import ReflectedField

if TYPE_CHECKING:
    from teleclaude.config.schema import PersonEntry

# Placeholder shown in place of an env-sourced (sensitive) value when not editing.
_MASKED_VALUE = "••••••"


def _segment_label(segment: str) -> str:
    """Human label for one dotted-key segment; list indices render as ``[n]``."""
    return f"[{segment}]" if segment.isdigit() else segment.replace("_", " ").title()


def _root_label(fields: list[ReflectedField], root: str) -> str:
    """Label for a top-level group, taken from the shallowest field's section."""
    members = [f for f in fields if f.key.split(".", 1)[0] == root]
    shallowest = min(members, key=lambda f: f.key.count("."))
    return shallowest.section


class ConfigContentRenderMixin:
    """Rendering, on_click, and watch_* methods for ConfigContent."""

    if TYPE_CHECKING:
        _env_data: list[EnvVarStatus]
        _guided_step_index: int
        _people_data: list[PersonEntry]
        _editing_var_name: str | None
        _edit_buffer: str

        @property
        def person_editable_fields(self) -> list[str]: ...

    def _render_guidance_block(self, result: Text, guidance: FieldGuidance | None) -> None:
        """Render the inline guidance block, only when it has actionable content."""
        if guidance is None:
            return
        # Suppress the frame entirely when there is nothing to show (no steps/link/example/hint).
        if not (guidance.steps or guidance.url or guidance.format_example or guidance.validation_hint):
            return
        result.append("      ┌─ Guidance\n", style=_SEP)
        for idx, step in enumerate(guidance.steps, 1):
            result.append(f"      │ {idx}. {step}\n", style=_DIM)
        if guidance.url:
            url_text = Text()
            url_text.append("      │ Link: ")
            url_text.append(guidance.url, style=Style(color="#87afd7", link=guidance.url))
            url_text.append("\n")
            result.append_text(url_text)
        if guidance.format_example:
            result.append("      │ Format: ", style=_DIM)
            result.append(f"{guidance.format_example}\n", style=Style(color="#87afd7", bold=True))
        if guidance.validation_hint:
            result.append(f"      │ Hint: {guidance.validation_hint}\n", style=_DIM)
        result.append("      └─\n", style=_SEP)

    def _render_tab_bar(self, result: Text, tabs: tuple[str, ...], active: int) -> None:
        """Render the clickable subtab bar."""
        row = result.plain.count("\n")
        x = 0
        for idx, tab in enumerate(tabs):
            style = _TAB_ACTIVE if idx == active else _TAB_INACTIVE
            label = f" {tab} "
            self._tab_click_regions.append((row, x, x + len(label), idx))  # type: ignore[attr-defined]
            result.append(label, style=style)
            x += len(label)
            if idx < len(tabs) - 1:
                result.append(" ", style=_DIM)
                x += 1
        result.append("\n")

    def _render_header(self, result: Text) -> None:
        """Render the guided-step indicator and any active status messages."""
        if self._guided_mode:  # type: ignore[attr-defined]
            step = _GUIDED_STEPS[self._guided_step_index]  # type: ignore[attr-defined]
            result.append(
                (f"Guided Step {self._guided_step_index + 1}/{len(_GUIDED_STEPS)}: {step.step_label}\n"),
                style=_INFO,
            )

        if self._status_message:  # type: ignore[attr-defined]
            status_style = _FAIL if self._status_is_error else _DIM  # type: ignore[attr-defined]
            result.append(f"{self._status_message}\n", style=status_style)  # type: ignore[attr-defined]

    def _render_people(self, result: Text) -> None:
        """Render configured people and any expanded editable fields."""
        result.append("\n")
        result.append("  People\n", style=Style(bold=True))
        if not self._people_data:  # type: ignore[attr-defined]
            result.append("  No people configured\n", style=_FAIL)
            result.append("  Next: telec config people add --name <name> --email <email>\n", style=_DIM)
            return

        cursor = self._current_cursor()  # type: ignore[attr-defined]
        for idx, person in enumerate(self._people_data):  # type: ignore[attr-defined]
            selected = idx == cursor
            prefix = "▶" if selected else " "
            row_style = Style(reverse=True) if selected else _normal_style()

            row = result.plain.count("\n")
            self._row_click_map[row] = ("person_select", person.name)  # type: ignore[attr-defined]

            result.append(f"  {prefix} {person.name}", style=row_style)
            result.append(f" ({person.role})", style=_DIM)
            if person.email:
                result.append(f" <{person.email}>", style=_DIM)
            result.append("\n")

            if selected and self._expanded_person == person.name:  # type: ignore[attr-defined]
                person_fields = self.person_reflected_fields  # type: ignore[attr-defined]

                # Render the overlay as an indented tree (root groups + branch
                # headers), matching the subtab renderer.
                printed: set[str] = set()
                current_root: str | None = None
                for f in person_fields:
                    root = f.key.split(".", 1)[0]
                    if root != current_root:
                        current_root = root
                        result.append(f"  ▼ {_root_label(person_fields, root)}\n", style=Style(bold=True))
                    self._emit_branch_headers(result, f.key, printed)
                    f_idx = person_fields.index(f)
                    field_selected = f_idx == self._person_field_cursor  # type: ignore[attr-defined]
                    field_prefix = "▶" if field_selected else " "
                    field_row_style = Style(reverse=True) if field_selected else _normal_style()
                    field_row = result.plain.count("\n")
                    self._row_click_map[field_row] = ("person_reflected_row", f.key)  # type: ignore[attr-defined]
                    self._render_reflected_field(
                        result, f, selected=field_selected, prefix=field_prefix, row_style=field_row_style
                    )

    def _render_environment(self, result: Text) -> None:
        """Render the global environment variable section."""
        result.append("\n")
        result.append("  Environment Variables\n", style=Style(bold=True))

        if not self._env_data:  # type: ignore[attr-defined]
            result.append("  Could not load env vars\n", style=_FAIL)
            return

        cursor = self._current_cursor()  # type: ignore[attr-defined]
        for idx, status in enumerate(self._env_data):  # type: ignore[attr-defined]
            selected = idx == cursor
            row_style = Style(reverse=True) if selected else _normal_style()
            prefix = "▶" if selected else " "

            row = result.plain.count("\n")
            self._row_click_map[row] = ("env_row", status.info.name)  # type: ignore[attr-defined]

            if self._editing_var_name == status.info.name:  # type: ignore[attr-defined]
                result.append(
                    f"  {prefix} {status.info.name} = {self._edit_buffer}\n",
                    style=row_style,
                )  # type: ignore[attr-defined]
                result.append("      Enter save  Esc cancel  Ctrl+U clear\n", style=_DIM)
                continue

            icon = "✔" if status.is_set else "✖"
            icon_style = _OK if status.is_set else _FAIL
            result.append(f"  {prefix} {icon} ", style=icon_style)
            result.append(f"{status.info.name}", style=row_style)
            result.append(f" ({status.info.adapter})\n", style=_DIM)
            if selected:
                self._render_guidance_block(result, guidance_registry.get_for_env(status.info.name))

    def _render_reflected_field(
        self, result: Text, f: ReflectedField, *, selected: bool, prefix: str, row_style: Style
    ) -> None:
        """Render one reflected field row: bool toggle, list, enum, or text.

        Leaf rows are indented to their depth in the dotted key so they sit beneath
        the branch headers emitted by the caller.
        """
        depth = max(0, f.key.count(".") - 1)
        pad = "  " * (2 + depth)
        subpad = pad + "    "
        if self._editing_var_name == f.key:  # type: ignore[attr-defined]
            result.append(f"{pad}{prefix} {f.name} = {self._edit_buffer}█\n", style=row_style)  # type: ignore[attr-defined]
            result.append(f"{subpad}Enter save  Esc cancel  Ctrl+U clear\n", style=_DIM)
            return

        if f.field_type is bool:
            # A boolean is always a valid state (true or false), so it is always "set".
            result.append(f"{pad}{prefix} ✔ ", style=_OK)
            result.append(f"{f.name}: ", style=_DIM)
            result.append(" TRUE ", style=Style(bold=True, reverse=True) if f.value else _DIM)
            result.append(" ", style=row_style)
            result.append(" FALSE ", style=Style(bold=True, reverse=True) if not f.value else _DIM)
            result.append("  (← → toggle)\n" if selected else "\n", style=_DIM)

        elif f.field_type in (list[str], list):
            items = f.value or []
            result.append(f"{pad}{prefix} {'✔' if items else '○'} ", style=_OK if items else _DIM)
            result.append(f"{f.name}:", style=_DIM)
            if selected and items:
                self._list_element_idx = max(0, min(self._list_element_idx, len(items) - 1))  # type: ignore[attr-defined]
                result.append("  (← → select · [ ] reorder)\n", style=_DIM)
                for item_idx, item in enumerate(items):
                    active = item_idx == self._list_element_idx  # type: ignore[attr-defined]
                    marker = "▶" if active else " "
                    result.append(
                        f"{subpad}{marker} {item}\n", style=Style(bold=True, reverse=True) if active else row_style
                    )
            elif items:
                result.append(f" {', '.join(items)}\n", style=row_style)
            else:
                result.append(" (empty)\n", style=_DIM)

        elif f.choices:
            result.append(f"{pad}{prefix} {'✔' if f.value else '○'} ", style=_OK if f.value else _DIM)
            result.append(f"{f.name}: ", style=_DIM)
            result.append(f"{f.value or '(not set)'}", style=row_style)
            result.append("  (← → cycle)\n" if selected else "\n", style=_DIM)

        else:
            value = str(f.value if f.value is not None else "")
            # An env-sourced value is sensitive; reveal it only while editing (handled above).
            display = _MASKED_VALUE if (f.env_var and value) else (value or "(not set)")
            result.append(f"{pad}{prefix} {'✔' if value else '○'} ", style=_OK if value else _DIM)
            result.append(f"{f.name}: ", style=_DIM)
            result.append(f"{display}\n", style=row_style)

        if f.description:
            result.append(f"{subpad}{f.description}\n", style=_DIM)
        if selected:
            # Env-backed ${VAR} fields carry guidance keyed by the env var, not the field key.
            guidance = guidance_registry.get_for_env(f.env_var) if f.env_var else None
            if guidance is None:
                guidance = guidance_registry.get_for_field_key(f.key)
            self._render_guidance_block(result, guidance)

    def _emit_branch_headers(self, result: Text, key: str, printed: set[str]) -> None:
        """Emit indented headers for any intermediate path segments not yet shown."""
        segments = key.split(".")
        for depth in range(1, len(segments) - 1):
            path = ".".join(segments[: depth + 1])
            if path not in printed:
                printed.add(path)
                result.append("  " * (1 + depth) + _segment_label(segments[depth]) + "\n", style=Style(bold=True))

    def _group_summary(self, group_fields: list[ReflectedField]) -> str:
        """One-line collapsed summary of a group's leaf values."""
        parts: list[str] = []
        for f in group_fields:
            if f.field_type is bool:
                val_str = "yes" if f.value else "no"
            elif f.field_type in (list[str], list):
                val_str = f"[{len(f.value or [])}]"
            elif f.env_var and f.value:
                val_str = _MASKED_VALUE
            else:
                val_str = str(f.value if f.value is not None else "")
                if len(val_str) > 15:
                    val_str = val_str[:12] + "..."
            parts.append(f"{f.name}={val_str}")
        summary = ", ".join(parts)
        return summary[:47] + "..." if len(summary) > 50 else summary

    def _render_reflected_fields(self, result: Text) -> None:
        """Render the active subtab's reflected fields as an indented tree."""
        fields = self.reflected_fields  # type: ignore[attr-defined]
        if not fields:
            result.append("\n  No properties found for this subtab\n", style=_DIM)
            return

        cursor = self._current_cursor()  # type: ignore[attr-defined]
        active_field = fields[max(0, min(cursor, len(fields) - 1))]
        active_root = active_field.key.split(".", 1)[0]

        # Group fields by top-level key segment, preserving order, so nested
        # structures render as a tree rather than colliding into flat sections.
        groups: dict[str, list[ReflectedField]] = {}
        for f in fields:
            groups.setdefault(f.key.split(".", 1)[0], []).append(f)

        for root, group_fields in groups.items():
            result.append("\n")
            label = _root_label(fields, root)
            if root != active_root:
                result.append(f"  ▶ {label} ({self._group_summary(group_fields)})\n", style=_DIM)
                continue

            result.append(f"  ▼ {label}\n", style=Style(bold=True))
            printed: set[str] = set()
            for f in group_fields:
                self._emit_branch_headers(result, f.key, printed)
                f_idx = fields.index(f)
                selected = f_idx == cursor
                prefix = "▶" if selected else " "
                row_style = Style(reverse=True) if selected else _normal_style()
                row = result.plain.count("\n")
                self._row_click_map[row] = ("reflected_row", f.key)  # type: ignore[attr-defined]
                self._render_reflected_field(result, f, selected=selected, prefix=prefix, row_style=row_style)

    def render(self) -> Text:
        """Render the current config content for the active subtab."""
        self._tab_click_regions = []  # type: ignore[attr-defined]
        self._row_click_map = {}  # type: ignore[attr-defined]
        result = Text()

        self._render_tab_bar(result, _SUBTABS, self.active_subtab)  # type: ignore[attr-defined]
        result.append("-" * 78 + "\n", style=_SEP)
        self._render_header(result)

        tab = _SUBTABS[self.active_subtab]  # type: ignore[attr-defined]
        if tab in (Subtab.INFRA, Subtab.ADAPTERS, Subtab.PROVIDERS, Subtab.SUMMARIZER, Subtab.TTS_STT):
            self._render_reflected_fields(result)
        elif tab == Subtab.PEOPLE:
            self._render_people(result)
        elif tab == Subtab.ENV:
            self._render_environment(result)

        return result

    def on_click(self, event: object) -> None:
        """Handle click interactions for tabs, rows, and editable fields."""
        x = getattr(event, "x", -1)
        y = getattr(event, "y", -1)

        for row, x_start, x_end, subtab_idx in self._tab_click_regions:  # type: ignore[attr-defined]
            if y == row and x_start <= x < x_end:
                self.post_message(self.SubtabSelected(subtab_idx))  # type: ignore[attr-defined]
                return

        action = self._row_click_map.get(y)  # type: ignore[attr-defined]
        if action is None:
            return

        action_type = action[0]
        if action_type == "reflected_row":
            field_key = action[1]
            fields = self.reflected_fields  # type: ignore[attr-defined]
            for i, f in enumerate(fields):
                if f.key == field_key:
                    self._set_current_cursor(i)  # type: ignore[attr-defined]
                    # Same as Enter: toggle bool, cycle enum, or edit text.
                    self.activate_current()  # type: ignore[attr-defined]
                    break
        elif action_type == "env_row":
            env_name = action[1]
            rows = self._selectable_env_rows()  # type: ignore[attr-defined]
            for i, status in enumerate(rows):
                if status.info.name == env_name:
                    self._set_current_cursor(i)  # type: ignore[attr-defined]
                    self._begin_edit(status)  # type: ignore[attr-defined]
                    break
        elif action_type == "person_select":
            person_name = action[1]
            for i, p in enumerate(self._people_data):  # type: ignore[attr-defined]
                if p.name == person_name:
                    self._set_current_cursor(i)  # type: ignore[attr-defined]
                    if self._expanded_person == person_name:  # type: ignore[attr-defined]
                        self._expanded_person = None  # type: ignore[attr-defined]
                    else:
                        self._expanded_person = person_name  # type: ignore[attr-defined]
                        self._person_field_cursor = 0  # type: ignore[attr-defined]
                    self.refresh(layout=True)  # type: ignore[attr-defined]
                    break
        elif action_type == "person_reflected_row":
            field_key = action[1]
            fields = self.person_reflected_fields  # type: ignore[attr-defined]
            for idx, f in enumerate(fields):
                if f.key == field_key:
                    self._person_field_cursor = idx  # type: ignore[attr-defined]
                    if f.field_type is bool:
                        self._save_reflected_field(f.key, not f.value)  # type: ignore[attr-defined]
                    elif f.choices:
                        self.cycle_enum_field(1)  # type: ignore[attr-defined]
                    else:
                        self._begin_edit(f)  # type: ignore[attr-defined]
                    break

    def watch_active_subtab(self, _value: int) -> None:
        """Clamp cursor state after the active subtab changes."""
        self._clamp_current_cursor()  # type: ignore[attr-defined]
        self.refresh(layout=True)  # type: ignore[attr-defined]

    def watch_active_adapter_tab(self, _value: int) -> None:
        """Clamp cursor state after the active adapter tab changes."""
        self._clamp_current_cursor()  # type: ignore[attr-defined]
        self.refresh(layout=True)  # type: ignore[attr-defined]
