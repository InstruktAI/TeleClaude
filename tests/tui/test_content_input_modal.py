"""Functional tests for ContentInputModal multiline support."""

from __future__ import annotations

import pytest
from textual.app import App
from textual.widgets import Label, TextArea

from teleclaude.cli.tui.widgets.modals import ContentInputModal

pytestmark = pytest.mark.functional

PLACEHOLDER = "Write something..."
MULTILINE_CONTENT_CTRL_S = "Hello multiline\nThis is line 2"
MULTILINE_CONTENT_CTRL_J = "Second test\nMulti line"
VALIDATION_ERROR = "Content is required"
VALID_CONTENT = "Now valid"


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
async def test_content_input_modal_multiline_creation_via_ctrl_s() -> None:
    app = ModalTestApp(placeholder=PLACEHOLDER)
    async with app.run_test() as pilot:
        text_area = app.screen.query_one("#content-input", TextArea)
        assert text_area.placeholder == PLACEHOLDER
        assert text_area.has_focus

        # Input multiline text
        text_area.text = MULTILINE_CONTENT_CTRL_S

        # Submit via ctrl+s
        await pilot.press("ctrl+s")
        await pilot.pause()

    assert app.result == MULTILINE_CONTENT_CTRL_S


@pytest.mark.asyncio
async def test_content_input_modal_multiline_creation_via_ctrl_j() -> None:
    app = ModalTestApp()
    async with app.run_test() as pilot:
        text_area = app.screen.query_one("#content-input", TextArea)
        text_area.text = MULTILINE_CONTENT_CTRL_J

        # Submit via ctrl+j
        await pilot.press("ctrl+j")
        await pilot.pause()

    assert app.result == MULTILINE_CONTENT_CTRL_J


@pytest.mark.asyncio
async def test_content_input_modal_validation_on_empty() -> None:
    app = ModalTestApp()
    async with app.run_test() as pilot:
        text_area = app.screen.query_one("#content-input", TextArea)
        text_area.text = "   "  # Whitespace only

        # Try to submit via ctrl+s
        await pilot.press("ctrl+s")
        await pilot.pause()

        # The error label should display validation error
        error_label = app.screen.query_one("#content-error", Label)
        assert str(error_label.render()) == VALIDATION_ERROR
        assert app.result is None  # Should not have dismissed

        # Enter valid text and submit via button click
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

        # Dismiss via Escape key
        await pilot.press("escape")
        await pilot.pause()

    assert app.result is None


@pytest.mark.asyncio
async def test_content_input_modal_cancel_via_button() -> None:
    app = ModalTestApp()
    async with app.run_test() as pilot:
        # Dismiss via click on Cancel button
        await pilot.click("#cancel-btn")
        await pilot.pause()

    assert app.result is None
