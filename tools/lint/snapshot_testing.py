#!/usr/bin/env -S uv run --quiet
"""Detect forbidden string assertions in test files."""

from __future__ import annotations

import ast
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

AUTHORING_GUIDE = (
    "software-development/procedure/snapshot-testing (docs/global/software-development/procedure/snapshot-testing.md)"
)
EXEMPTIONS_PATH = Path(".teleclaude/snapshot-testing-exemptions.txt")
STRING_METHODS = frozenset({"startswith", "endswith", "find", "index", "__contains__"})
REGEX_METHODS = frozenset({"match", "search", "fullmatch"})


@dataclass(frozen=True)
class Finding:
    """One snapshot-testing policy violation."""

    path: str
    line: int
    pattern: str


Detector = Callable[[ast.AST], int | None]


def _line(node: ast.AST) -> int:
    line = getattr(node, "lineno", 1)
    return line if isinstance(line, int) else 1


def _is_string_constant(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _is_snapshot_expression(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "snapshot"
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "snapshot"


def _compare_parts(compare: ast.Compare) -> tuple[ast.AST, ast.AST] | None:
    if len(compare.ops) != 1 or not isinstance(compare.ops[0], ast.Eq) or len(compare.comparators) != 1:
        return None
    return compare.left, compare.comparators[0]


def _contains_string_literal_equality(compare: ast.Compare) -> bool:
    parts = _compare_parts(compare)
    if parts is None:
        return False
    left, right = parts
    if _is_snapshot_expression(left) or _is_snapshot_expression(right):
        return False
    if _is_string_constant(left):
        return not _is_string_constant(right)
    if _is_string_constant(right):
        return not _is_string_constant(left)
    return False


def _touches_exception_message(node: ast.AST, except_bindings: frozenset[str]) -> bool:
    for child in ast.walk(node):
        if (
            isinstance(child, ast.Attribute)
            and child.attr == "message"
            and isinstance(child.value, ast.Name)
            and child.value.id in except_bindings
        ):
            return True
        if isinstance(child, ast.Subscript) and isinstance(child.value, ast.Attribute) and child.value.attr == "args":
            index = child.slice
            if (
                isinstance(index, ast.Constant)
                and index.value == 0
                and isinstance(child.value.value, ast.Name)
                and child.value.value.id in except_bindings
            ):
                return True
        if (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Name)
            and child.func.id == "str"
            and len(child.args) == 1
            and isinstance(child.args[0], ast.Name)
            and child.args[0].id in except_bindings
        ):
            return True
    return False


def detect_exception_message(node: ast.AST) -> int | None:
    # Kept for CLI use; visitor calls _touches_exception_message directly with binding context.
    if not isinstance(node, ast.Assert):
        return None
    if not isinstance(node.test, ast.Compare):
        return None
    if _touches_exception_message(node.test, frozenset()):
        return _line(node)
    return None


def detect_assert_str_eq(node: ast.AST) -> int | None:
    if not isinstance(node, ast.Assert):
        return None
    if not isinstance(node.test, ast.Compare):
        return None
    if _contains_string_literal_equality(node.test):
        return _line(node)
    return None


def detect_str_in(node: ast.AST) -> int | None:
    if not isinstance(node, ast.Compare):
        return None
    for index, op in enumerate(node.ops):
        if isinstance(op, ast.In):
            candidate = node.left if index == 0 else node.comparators[index - 1]
            if _is_string_constant(candidate):
                return _line(node)
    return None


def detect_string_method(node: ast.AST) -> int | None:
    if not isinstance(node, ast.Call):
        return None
    if not isinstance(node.func, ast.Attribute) or node.func.attr not in STRING_METHODS:
        return None
    if any(_is_string_constant(arg) for arg in node.args):
        return _line(node)
    return None


def detect_regex_match(node: ast.AST) -> int | None:
    if not isinstance(node, ast.Call):
        return None
    if not isinstance(node.func, ast.Attribute):
        return None
    if not isinstance(node.func.value, ast.Name) or node.func.value.id != "re":
        return None
    if node.func.attr not in REGEX_METHODS or not node.args:
        return None
    if _is_string_constant(node.args[0]):
        return _line(node)
    return None


PATTERN_DETECTORS: tuple[tuple[str, Detector], ...] = (
    ("exception_message", detect_exception_message),
    ("assert_str_eq", detect_assert_str_eq),
    ("str_in", detect_str_in),
    ("string_method", detect_string_method),
    ("regex_match", detect_regex_match),
)


class SnapshotTestingVisitor(ast.NodeVisitor):
    """AST visitor that records the first matching pattern per node."""

    def __init__(self, display_path: str) -> None:
        self._display_path = display_path
        self.findings: list[Finding] = []
        self._except_bindings: set[str] = set()

    def _record_first_match(self, node: ast.AST, detectors: tuple[tuple[str, Detector], ...]) -> None:
        for pattern, detector in detectors:
            line = detector(node)
            if line is not None:
                self.findings.append(Finding(path=self._display_path, line=line, pattern=pattern))
                break

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name:
            self._except_bindings.add(node.name)
        self.generic_visit(node)
        if node.name:
            self._except_bindings.discard(node.name)

    def visit_Assert(self, node: ast.Assert) -> None:
        if isinstance(node.test, ast.Compare):
            bindings = frozenset(self._except_bindings)
            if _touches_exception_message(node.test, bindings):
                self.findings.append(Finding(path=self._display_path, line=_line(node), pattern="exception_message"))
            elif _contains_string_literal_equality(node.test):
                self.findings.append(Finding(path=self._display_path, line=_line(node), pattern="assert_str_eq"))
        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare) -> None:
        self._record_first_match(node, (("str_in", detect_str_in),))
        super().generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        self._record_first_match(
            node,
            (
                ("string_method", detect_string_method),
                ("regex_match", detect_regex_match),
            ),
        )
        super().generic_visit(node)


def _display_path(path: Path, repo_root: Path) -> str:
    resolved_path = path.resolve()
    try:
        return resolved_path.relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return resolved_path.as_posix()


def _load_exemptions(repo_root: Path) -> set[str]:
    path = repo_root / EXEMPTIONS_PATH
    if not path.exists():
        return set()
    exemptions: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        entry = line.split("#", 1)[0].strip()
        if entry:
            exemptions.add(Path(entry).as_posix())
    return exemptions


def _is_exempt(path: Path, repo_root: Path, exemptions: set[str]) -> bool:
    display = _display_path(path, repo_root)
    return display in exemptions or path.resolve().as_posix() in exemptions


def _is_python_test_file(path: Path, repo_root: Path) -> bool:
    if path.suffix != ".py":
        return False
    try:
        relative = path.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return path.name.startswith("test_") or path.name.endswith("_test.py")
    return len(relative.parts) > 1 and relative.parts[0] == "tests"


def _iter_targets(raw_targets: Sequence[str], repo_root: Path) -> Iterable[Path]:
    if not raw_targets:
        yield from sorted(f for f in (repo_root / "tests").rglob("*.py") if _is_python_test_file(f, repo_root))
        return

    found: list[Path] = []
    for target_str in raw_targets:
        target = Path(target_str)
        path = target if target.is_absolute() else repo_root / target
        if path.is_dir():
            found.extend(sorted(f for f in path.rglob("*.py") if _is_python_test_file(f, repo_root)))
        elif path.is_file() and _is_python_test_file(path, repo_root):
            found.append(path)

    if not found:
        # Targets contained no test files (e.g. source dirs like "teleclaude" in --all mode).
        # Fall back to scanning tests/ so CI enforcement is not silently skipped.
        tests_dir = repo_root / "tests"
        if tests_dir.is_dir():
            yield from sorted(f for f in tests_dir.rglob("*.py") if _is_python_test_file(f, repo_root))
        return

    yield from found


def lint_file(path: Path, repo_root: Path, exemptions: set[str]) -> list[Finding]:
    """Return all snapshot-testing findings for one Python test file."""
    if _is_exempt(path, repo_root, exemptions):
        return []
    display = _display_path(path, repo_root)
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=display)
    except SyntaxError as exc:
        line = exc.lineno if exc.lineno is not None else 1
        return [Finding(path=display, line=line, pattern="syntax_error")]
    visitor = SnapshotTestingVisitor(display)
    visitor.visit(tree)
    return visitor.findings


def main(argv: Sequence[str] | None = None) -> int:
    """Run the snapshot-testing linter."""
    args = list(sys.argv[1:] if argv is None else argv)
    repo_root = Path.cwd()
    exemptions = _load_exemptions(repo_root)
    findings: list[Finding] = []
    seen: set[Path] = set()

    for path in _iter_targets(args, repo_root):
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        findings.extend(lint_file(resolved, repo_root, exemptions))

    for finding in findings:
        print(
            f"{finding.path}:{finding.line}: snapshot-testing[{finding.pattern}]: "
            f"string content assertions must use snapshots, named constants, or a non-empty guard; "
            f"see {AUTHORING_GUIDE}"
        )

    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
