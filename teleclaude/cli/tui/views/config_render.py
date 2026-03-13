"""Rendering and click-handler mixin for ConfigContent."""

from __future__ import annotations

from rich.style import Style
from rich.text import Text

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
    _normal_style,
    completion_summary,
    get_guidance_for_env,
)


class ConfigContentRenderMixin:
    """Rendering, on_click, and watch_* methods for ConfigContent."""

    def _render_guidance(self, result: Text, env_name: str) -> None:
        """Render inline guidance block for the given env var."""
        guidance = get_guidance_for_env(env_name)
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
        env_complete = all(status.is_set for status in self._env_data) if self._env_data else True  # type: ignore[attr-defined]
        configured, total = completion_summary(
            self._adapter_sections,  # type: ignore[attr-defined]
            has_people=bool(self._people_data),  # type: ignore[attr-defined]
            notifications_configured=self._notification_projection.configured,  # type: ignore[attr-defined]
            environment_configured=env_complete,
        )
        summary_style = _OK if configured == total else _WARN
        result.append(f"Setup Progress: {configured}/{total} sections configured\n", style=summary_style)

        if self._guided_mode:  # type: ignore[attr-defined]
            step = _GUIDED_STEPS[self._guided_step_index]  # type: ignore[attr-defined]
            result.append(
                f"Guided Step {self._guided_step_index + 1}/{len(_GUIDED_STEPS)}: {step.title}\n",  # type: ignore[attr-defined]
                style=_INFO,
            )

        if self._status_message:  # type: ignore[attr-defined]
            status_style = _FAIL if self._status_is_error else _DIM  # type: ignore[attr-defined]
            result.append(f"{self._status_message}\n", style=status_style)  # type: ignore[attr-defined]

    def _status_style(self, status: object) -> Style:
        if status == "configured":
            return _OK
        if status == "partial":
            return _WARN
        return _FAIL

    def _render_adapters(self, result: Text) -> None:
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
                result.append(f"  {prefix} {status.info.name} = {self._edit_buffer}\n", style=row_style)  # type: ignore[attr-defined]
                result.append("      Enter save  Esc cancel  Ctrl+U clear\n", style=_DIM)
                continue

            icon = "✔" if status.is_set else "✖"
            icon_style = _OK if status.is_set else _FAIL
            result.append(f"  {prefix} {icon} ", style=icon_style)
            result.append(f"{status.info.name}\n", style=row_style)
            result.append(f"      {status.info.description}\n", style=_DIM)
            if selected:
                self._render_guidance(result, status.info.name)

    def _render_people(self, result: Text) -> None:
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
            result.append(f" [{getattr(person, 'proficiency', 'intermediate')}]", style=_DIM)
            result.append("\n")

            if selected and self._expanded_person == person.name:  # type: ignore[attr-defined]
                for field_idx, field in enumerate(_PERSON_EDITABLE_FIELDS):
                    field_selected = field_idx == self._person_field_cursor  # type: ignore[attr-defined]
                    field_prefix = "▶" if field_selected else " "
                    field_row_style = Style(reverse=True) if field_selected else _DIM

                    field_row = result.plain.count("\n")
                    self._row_click_map[field_row] = ("person_field", field)  # type: ignore[attr-defined]

                    if self._editing_person_field == field:  # type: ignore[attr-defined]
                        result.append(f"      {field_prefix} {field} = {self._edit_buffer}█\n", style=field_row_style)  # type: ignore[attr-defined]
                        result.append("          Enter save  Esc cancel  Ctrl+U clear\n", style=_DIM)
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
                    else:
                        value = str(getattr(person, field, "") or "")
                        icon = "✔" if value else "○"
                        icon_style = _OK if value else _DIM
                        result.append(f"      {field_prefix} {icon} ", style=icon_style)
                        result.append(f"{field}: ", style=_DIM)
                        result.append(f"{value or '(not set)'}\n", style=field_row_style)

    def _render_notifications(self, result: Text) -> None:
        projection = self._notification_projection  # type: ignore[attr-defined]
        result.append("\n")
        result.append("  Notifications\n", style=Style(bold=True))
        result.append(
            f"  People with subscriptions: {projection.people_with_subscriptions}/{projection.total_people}\n"
        )
        result.append(f"  Total subscriptions: {projection.total_subscriptions}\n", style=_DIM)
        status = "CONFIGURED" if projection.configured else "NEEDS ATTENTION"
        result.append(f"  Status: {status}\n", style=_OK if projection.configured else _WARN)
        result.append(f"  Next action: {projection.next_action}\n", style=_DIM)

    def _render_environment(self, result: Text) -> None:
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
                result.append(f"  {prefix} {status.info.name} = {self._edit_buffer}\n", style=row_style)  # type: ignore[attr-defined]
                result.append("      Enter save  Esc cancel  Ctrl+U clear\n", style=_DIM)
                continue

            icon = "✔" if status.is_set else "✖"
            icon_style = _OK if status.is_set else _FAIL
            result.append(f"  {prefix} {icon} ", style=icon_style)
            result.append(f"{status.info.name}", style=row_style)
            result.append(f" ({status.info.adapter})\n", style=_DIM)
            if selected:
                self._render_guidance(result, status.info.name)

    def render(self) -> Text:
        self._tab_click_regions = []  # type: ignore[attr-defined]
        self._row_click_map = {}  # type: ignore[attr-defined]
        result = Text()

        self._render_tab_bar(result, _SUBTABS, self.active_subtab)  # type: ignore[attr-defined]
        result.append("-" * 78 + "\n", style=_SEP)
        self._render_header(result)

        tab = _SUBTABS[self.active_subtab]  # type: ignore[attr-defined]
        if tab == "adapters":
            self._render_adapters(result)
        elif tab == "people":
            self._render_people(result)
        elif tab == "notifications":
            self._render_notifications(result)
        elif tab == "environment":
            self._render_environment(result)

        return result

    def on_click(self, event: object) -> None:
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
        if action_type == "adapter_tab":
            self.post_message(self.AdapterTabSelected(action[1]))  # type: ignore[attr-defined]
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
                    person = next((p for p in self._people_data if p.name == self._expanded_person), None)  # type: ignore[attr-defined]
                    if person is not None:
                        if field == "role":
                            self._cycle_person_role(person)  # type: ignore[attr-defined]
                        else:
                            self._begin_person_field_edit(person, field)  # type: ignore[attr-defined]
                    break

    def watch_active_subtab(self, _value: int) -> None:
        self._clamp_current_cursor()  # type: ignore[attr-defined]
        self.refresh(layout=True)  # type: ignore[attr-defined]

    def watch_active_adapter_tab(self, _value: int) -> None:
        self._clamp_current_cursor()  # type: ignore[attr-defined]
        self.refresh(layout=True)  # type: ignore[attr-defined]
