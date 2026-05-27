"""Rendering and click-handler mixin for ConfigContent."""

from __future__ import annotations

import json
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
    _PERSON_EDITABLE_FIELDS,
    _SEP,
    _SUBTABS,
    _TAB_ACTIVE,
    _TAB_INACTIVE,
    _VALID_ROLES,
    _WARN,
    Subtab,
    _normal_style,
    get_allowed_values_for_field,
)
from teleclaude.cli.tui.views.reflection import ReflectedField

if TYPE_CHECKING:
    from teleclaude.cli.tui.views._config_constants import AdapterSectionProjection
    from teleclaude.config.schema import PersonEntry


class ConfigContentRenderMixin:
    """Rendering, on_click, and watch_* methods for ConfigContent."""

    if TYPE_CHECKING:
        _adapter_sections: list[AdapterSectionProjection]
        _env_data: list[EnvVarStatus]
        _guided_step_index: int
        _people_data: list[PersonEntry]

        @property
        def person_editable_fields(self) -> list[str]: ...

    def _render_guidance_block(self, result: Text, guidance: FieldGuidance | None) -> None:
        """Render the inline guidance block for a resolved guidance entry."""
        if guidance is None:
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
                (f"Guided Step {self._guided_step_index + 1}/{len(_GUIDED_STEPS)}: {step.title}\n"),
                style=_INFO,
            )

        if self._status_message:  # type: ignore[attr-defined]
            status_style = _FAIL if self._status_is_error else _DIM  # type: ignore[attr-defined]
            result.append(f"{self._status_message}\n", style=status_style)  # type: ignore[attr-defined]

    def _status_style(self, status: object) -> Style:
        """Map adapter status values to Rich styles."""
        if status == "configured":
            return _OK
        if status == "partial":
            return _WARN
        return _FAIL

    def _render_adapters(self, result: Text) -> None:
        """Render the adapter overview cards and active adapter vars."""
        result.append("\n")
        result.append("  Adapter Cards\n", style=Style(bold=True))

        for idx, section in enumerate(self._adapter_sections):  # type: ignore[attr-defined]
            selected = idx == self.active_adapter_tab  # type: ignore[attr-defined]
            prefix = "▶" if selected else " "
            card_style = Style(reverse=True) if selected else _normal_style()
            row = result.plain.count("\n")
            self._row_click_map[row] = ("adapter_tab", idx)  # type: ignore[attr-defined]
            result.append(f"  {prefix} {section.label:<11} ", style=card_style)
            result.append(section.status.upper(), style=self._status_style(section.status))
            result.append(f"  ({section.configured_count}/{section.total_count})\n", style=_DIM)

        section = self._get_active_adapter_section()  # type: ignore[attr-defined]
        if section is None:
            result.append("\n  No adapters available\n", style=_DIM)
            return

        result.append("\n")
        result.append(f"  {section.label} Variables\n", style=Style(bold=True))
        if not section.env_statuses:
            result.append("  No environment variables registered for this adapter\n", style=_DIM)
            return

        cursor = self._current_cursor()  # type: ignore[attr-defined]
        for idx, status in enumerate(section.env_statuses):
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
            result.append(f"{status.info.name}\n", style=row_style)
            result.append(f"      {status.info.description}\n", style=_DIM)
            if selected:
                self._render_guidance_block(result, guidance_registry.get_for_env(status.info.name))

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
                for field_idx, field in enumerate(self.person_editable_fields):
                    field_selected = field_idx == self._person_field_cursor  # type: ignore[attr-defined]
                    field_prefix = "▶" if field_selected else " "
                    field_row_style = Style(reverse=True) if field_selected else _DIM

                    field_row = result.plain.count("\n")
                    self._row_click_map[field_row] = ("person_field", field)  # type: ignore[attr-defined]

                    if self._editing_person_field == field:  # type: ignore[attr-defined]
                        display_name = field
                        indent = "      "
                        if ":" in field:
                            _, child = field.split(":", 1)
                            display_name = child
                            indent = "          "
                        result.append(
                            f"{indent}{field_prefix} {display_name} = {self._edit_buffer}█\n",
                            style=field_row_style,
                        )  # type: ignore[attr-defined]
                        result.append(f"{indent}    Enter save  Esc cancel  Ctrl+U clear\n", style=_DIM)
                    elif field == "role":
                        value = str(getattr(person, field, "") or "")
                        result.append(f"      {field_prefix} ", style=_DIM)
                        result.append("role: ", style=_DIM)
                        for opt in _VALID_ROLES:
                            opt_style = _TAB_ACTIVE if opt == value else _TAB_INACTIVE
                            result.append(f" {opt} ", style=opt_style)
                        if field_selected:
                            result.append("  ← → cycle", style=_DIM)
                        result.append("\n")
                    elif ":" in field:
                        parent, child = field.split(":", 1)
                        raw_parent = getattr(person, parent, None)
                        val = raw_parent.get(child, None) if isinstance(raw_parent, dict) else None

                        icon = "✔" if val else "○"
                        icon_style = _OK if val else _DIM

                        result.append(f"          {field_prefix} {icon} ", style=icon_style)
                        result.append(f"{child}: ", style=_DIM)

                        allowed = get_allowed_values_for_field(field)
                        if allowed and field_selected:
                            result.append(f"{val or '(not set)'}", style=field_row_style)
                            result.append("  ← → cycle\n", style=_DIM)
                        else:
                            result.append(f"{val or '(not set)'}\n", style=field_row_style)
                    else:
                        raw_val = getattr(person, field, None)
                        if isinstance(raw_val, dict):
                            icon = "📁"
                            result.append(f"      {field_prefix} {icon} {field}:\n", style=field_row_style)
                            if field_selected:
                                result.append("          [Press Enter to add new key]\n", style=_INFO)
                        elif isinstance(raw_val, list):
                            value = json.dumps(raw_val)
                            icon = "✔" if value != "[]" else "○"
                            icon_style = _OK if value != "[]" else _DIM
                            result.append(f"      {field_prefix} {icon} ", style=icon_style)
                            result.append(f"{field}: ", style=_DIM)
                            result.append(f"{value or '(not set)'}\n", style=field_row_style)
                        else:
                            value = str(raw_val or "")
                            icon = "✔" if value else "○"
                            icon_style = _OK if value else _DIM
                            result.append(f"      {field_prefix} {icon} ", style=icon_style)
                            result.append(f"{field}: ", style=_DIM)
                            result.append(f"{value or '(not set)'}\n", style=field_row_style)

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
        """Render one reflected field row: bool toggle, list, enum, or text."""
        if self._editing_var_name == f.key:  # type: ignore[attr-defined]
            result.append(f"    {prefix} {f.name} = {self._edit_buffer}█\n", style=row_style)  # type: ignore[attr-defined]
            result.append("        Enter save  Esc cancel  Ctrl+U clear\n", style=_DIM)
            return

        if f.field_type is bool:
            # A boolean is always a valid state (true or false), so it is always "set".
            result.append(f"    {prefix} ✔ ", style=_OK)
            result.append(f"{f.name}: ", style=_DIM)
            result.append(" TRUE ", style=Style(bold=True, reverse=True) if f.value else _DIM)
            result.append(" ", style=row_style)
            result.append(" FALSE ", style=Style(bold=True, reverse=True) if not f.value else _DIM)
            result.append("  (← → toggle)\n" if selected else "\n", style=_DIM)

        elif f.field_type in (list[str], list):
            items = f.value or []
            result.append(f"    {prefix} {'✔' if items else '○'} ", style=_OK if items else _DIM)
            result.append(f"{f.name}:", style=_DIM)
            if selected and items:
                self._list_element_idx = max(0, min(self._list_element_idx, len(items) - 1))  # type: ignore[attr-defined]
                result.append("  (← → select · [ ] reorder)\n", style=_DIM)
                for item_idx, item in enumerate(items):
                    active = item_idx == self._list_element_idx  # type: ignore[attr-defined]
                    marker = "▶" if active else " "
                    result.append(
                        f"        {marker} {item}\n", style=Style(bold=True, reverse=True) if active else row_style
                    )
            elif items:
                result.append(f" {', '.join(items)}\n", style=row_style)
            else:
                result.append(" (empty)\n", style=_DIM)

        elif f.choices:
            result.append(f"    {prefix} {'✔' if f.value else '○'} ", style=_OK if f.value else _DIM)
            result.append(f"{f.name}: ", style=_DIM)
            result.append(f"{f.value or '(not set)'}", style=row_style)
            result.append("  (← → cycle)\n" if selected else "\n", style=_DIM)

        else:
            value = str(f.value if f.value is not None else "")
            result.append(f"    {prefix} {'✔' if value else '○'} ", style=_OK if value else _DIM)
            result.append(f"{f.name}: ", style=_DIM)
            result.append(f"{value or '(not set)'}\n", style=row_style)

        if f.description:
            result.append(f"        {f.description}\n", style=_DIM)
        if selected:
            self._render_guidance_block(result, guidance_registry.get_for_field_key(f.key))

    def _render_reflected_fields(self, result: Text) -> None:
        """Render the dynamically reflected fields for the active subtab."""
        fields = self.reflected_fields  # type: ignore[attr-defined]
        if not fields:
            result.append("\n  No properties found for this subtab\n", style=_DIM)
            return

        cursor = self._current_cursor()  # type: ignore[attr-defined]
        active_field = fields[max(0, min(cursor, len(fields) - 1))]
        active_section = active_field.section

        # Group fields by section preserving order
        sections: dict[str, list[ReflectedField]] = {}
        for f in fields:
            sections.setdefault(f.section, []).append(f)

        for sec_name, sec_fields in sections.items():
            result.append("\n")
            is_active = sec_name == active_section

            if is_active:
                result.append(f"  ▼ {sec_name}\n", style=Style(bold=True))

                for f in sec_fields:
                    f_idx = fields.index(f)
                    selected = f_idx == cursor
                    prefix = "▶" if selected else " "
                    row_style = Style(reverse=True) if selected else _normal_style()
                    row = result.plain.count("\n")
                    self._row_click_map[row] = ("reflected_row", f.key)  # type: ignore[attr-defined]
                    self._render_reflected_field(result, f, selected=selected, prefix=prefix, row_style=row_style)
            else:
                summary_parts = []
                for f in sec_fields:
                    if f.field_type is bool:
                        val_str = "yes" if f.value else "no"
                    elif f.field_type in (list[str], list):
                        val_str = f"[{len(f.value or [])}]"
                    else:
                        val_str = str(f.value if f.value is not None else "")
                        if len(val_str) > 15:
                            val_str = val_str[:12] + "..."
                    summary_parts.append(f"{f.name}={val_str}")
                summary_str = ", ".join(summary_parts)
                if len(summary_str) > 50:
                    summary_str = summary_str[:47] + "..."
                result.append(f"  ▶ {sec_name} ({summary_str})\n", style=_DIM)

    def render(self) -> Text:
        """Render the current config content for the active subtab."""
        self._tab_click_regions = []  # type: ignore[attr-defined]
        self._row_click_map = {}  # type: ignore[attr-defined]
        result = Text()

        self._render_tab_bar(result, _SUBTABS, self.active_subtab)  # type: ignore[attr-defined]
        result.append("-" * 78 + "\n", style=_SEP)
        self._render_header(result)

        tab = _SUBTABS[self.active_subtab]  # type: ignore[attr-defined]
        if tab in (Subtab.COMPUTER, Subtab.ADAPTERS, Subtab.PROVIDERS, Subtab.TTS_STT):
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
            if self._editing_person_field is not None:  # type: ignore[attr-defined]
                self._editing_person_field = None  # type: ignore[attr-defined]
                self._edit_buffer = ""  # type: ignore[attr-defined]
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
        elif action_type == "person_field":
            field = action[1]
            for field_idx, f in enumerate(_PERSON_EDITABLE_FIELDS):
                if f == field:
                    self._person_field_cursor = field_idx  # type: ignore[attr-defined]
                    person = next(  # type: ignore[attr-defined]
                        (p for p in self._people_data if p.name == self._expanded_person),
                        None,
                    )
                    if person is not None:
                        if field == "role":
                            self._cycle_person_role(person)  # type: ignore[attr-defined]
                        else:
                            self._begin_person_field_edit(person, field)  # type: ignore[attr-defined]
                    break

    def watch_active_subtab(self, _value: int) -> None:
        """Clamp cursor state after the active subtab changes."""
        self._clamp_current_cursor()  # type: ignore[attr-defined]
        self.refresh(layout=True)  # type: ignore[attr-defined]

    def watch_active_adapter_tab(self, _value: int) -> None:
        """Clamp cursor state after the active adapter tab changes."""
        self._clamp_current_cursor()  # type: ignore[attr-defined]
        self.refresh(layout=True)  # type: ignore[attr-defined]
