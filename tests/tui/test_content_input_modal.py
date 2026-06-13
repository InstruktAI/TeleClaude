"""Functional tests for ContentInputModal multiline support."""

from __future__ import annotations

import pytest
from textual.app import App
from textual.widgets import Label, TextArea

from teleclaude.cli.tui.widgets.modals import ContentInputModal

pytestmark = pytest.mark.functional

PLACEHOLDER = "Write something..."
MULTILINE_CONTENT = "Hello multiline\nThis is line 2"
VALIDATION_ERROR = "Content is required"
VALID_CONTENT = "Now valid"
NEWLINE = "\n"
TYPED_MULTILINE_RESULT = "a\nb"


class ModalTestApp(App[str | None]):
    def __init__(self, placeholder: str = "Enter description...") -> None:
        super().__init__()
        self.placeholder = placeholder
        self.result: str | None = None

    def on_mount(self) -> None:
        def on_dismiss(value: str | None) -> None:
            self.result = value
            self.exit()

        self.push_screen(ContentInputModal(placeholder=self.placeholder), on_dismiss)


@pytest.mark.asyncio
async def test_content_input_modal_multiline_creation_via_button() -> None:
    app = ModalTestApp(placeholder=PLACEHOLDER)
    async with app.run_test() as pilot:
        text_area = app.screen.query_one("#content-input", TextArea)
        assert text_area.placeholder == PLACEHOLDER
        assert text_area.has_focus

        text_area.text = MULTILINE_CONTENT

        # Tab navigates from the field to the Create button; Enter activates it.
        await pilot.press("tab")
        await pilot.press("enter")
        await pilot.pause()

    assert app.result == MULTILINE_CONTENT


@pytest.mark.asyncio
async def test_enter_in_field_inserts_newline_without_submitting() -> None:
    app = ModalTestApp()
    async with app.run_test() as pilot:
        text_area = app.screen.query_one("#content-input", TextArea)

        await pilot.press("a")
        await pilot.press("enter")
        await pilot.press("b")
        await pilot.pause()

        assert text_area.text == TYPED_MULTILINE_RESULT
        assert NEWLINE in text_area.text
        assert app.result is None


@pytest.mark.asyncio
async def test_content_input_modal_empty_shows_error_without_submitting() -> None:
    app = ModalTestApp()
    async with app.run_test() as pilot:
        text_area = app.screen.query_one("#content-input", TextArea)
        text_area.text = "   "  # Whitespace only

        await pilot.click("#create-btn")
        await pilot.pause()

        error_label = app.screen.query_one("#content-error", Label)
        assert str(error_label.render()) == VALIDATION_ERROR
        assert app.result is None  # Should not have dismissed


@pytest.mark.asyncio
async def test_content_input_modal_submit_via_button_click() -> None:
    app = ModalTestApp()
    async with app.run_test() as pilot:
        text_area = app.screen.query_one("#content-input", TextArea)
        text_area.text = VALID_CONTENT

        await pilot.click("#create-btn")
        await pilot.pause()

    assert app.result == VALID_CONTENT


@pytest.mark.asyncio
async def test_content_input_modal_cancel_via_escape() -> None:
    app = ModalTestApp()
    async with app.run_test() as pilot:
        text_area = app.screen.query_one("#content-input", TextArea)
        text_area.text = "Draft content"

        await pilot.press("escape")
        await pilot.pause()

    assert app.result is None


@pytest.mark.asyncio
async def test_content_input_modal_cancel_via_button() -> None:
    app = ModalTestApp()
    async with app.run_test() as pilot:
        await pilot.click("#cancel-btn")
        await pilot.pause()

    assert app.result is None
