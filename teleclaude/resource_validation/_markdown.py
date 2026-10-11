"""Read and parse Markdown once within one validation pass."""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

import frontmatter

_UTF8 = "utf-8"
_READ_SCOPE = "markdown_validation_reads"


@dataclass(frozen=True)
class ParsedMarkdown:
    """The read-only frontmatter and body shared by validation predicates."""

    metadata: Mapping[str, object]
    content: str


@dataclass
class _MarkdownReads:
    texts: dict[Path, str] = field(default_factory=dict)
    parsed: dict[str, ParsedMarkdown] = field(default_factory=dict)


_READS: ContextVar[_MarkdownReads | None] = ContextVar(_READ_SCOPE, default=None)


@contextmanager
def markdown_read_scope() -> Iterator[None]:
    """Reuse an enclosing validation scope or own fresh, call-local read state."""
    if _READS.get() is not None:
        yield
        return
    token = _READS.set(_MarkdownReads())
    try:
        yield
    finally:
        _READS.reset(token)


def read_markdown(path: Path) -> str:
    """Read a source image once; failed reads keep their original exceptions."""
    reads = _READS.get()
    if reads is not None and path in reads.texts:
        return reads.texts[path]
    text = path.read_text(encoding=_UTF8)
    if reads is not None:
        reads.texts[path] = text
    return text


def parse_markdown(content: str) -> ParsedMarkdown:
    """Reuse successful parsing of identical source bytes within the active pass."""
    reads = _READS.get()
    if reads is not None and content in reads.parsed:
        return reads.parsed[content]
    post = frontmatter.loads(content)
    parsed = ParsedMarkdown(MappingProxyType(post.metadata or {}), post.content)
    if reads is not None:
        reads.parsed[content] = parsed
    return parsed
