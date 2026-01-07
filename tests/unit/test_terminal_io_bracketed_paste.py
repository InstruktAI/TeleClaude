from teleclaude.core import terminal_io


def test_wrap_bracketed_paste_skips_slash_only() -> None:
    text = "path/with/slash"
    assert terminal_io.wrap_bracketed_paste(text) == text


def test_wrap_bracketed_paste_wraps_special_chars() -> None:
    text = "can you? update mozbook tmux.conf!"
    wrapped = terminal_io.wrap_bracketed_paste(text)
    assert wrapped == f"\x1b[200~{text}\x1b[201~"


def test_wrap_bracketed_paste_empty() -> None:
    assert terminal_io.wrap_bracketed_paste("") == ""


def test_wrap_bracketed_paste_skips_slash_commands() -> None:
    text = "/prime-architect"
    assert terminal_io.wrap_bracketed_paste(text) == text
