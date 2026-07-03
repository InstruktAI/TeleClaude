"""Spec-anchored test coverage report.

Coverage is measured against the Gherkin scenarios in the specs, not against
source files. Every scenario is a coverage unit; a test binds a scenario with
``@pytest.mark.spec("<spec_id>", "<scenario_id>")``. This tool builds the
scenario inventory from the specs, collects the bindings from the tests, and
reconciles the two — reporting orphan bindings (a test citing a scenario that
does not exist), unbound scenarios (untested), duplicate bindings, and anonymous
scenarios (Gherkin with no stable id, not yet bindable).

Bookkeeping model (kept deliberately simple so the tool's job is easy):
  * one spec file == one spec id, derived from the path exactly as the doc index
    derives it (strip the ``docs/global/`` or ``docs/`` prefix and the ``.md``
    suffix) — never from frontmatter, which carries no authored id;
  * each scenario is a header section (``## … ######``) whose body contains a
    Gherkin ``When`` line; its id is the ``UC-…`` token in the header, or None
    (anonymous) when the header carries no such token;
  * a test binds ``(spec_id, scenario_id)``.

Usage:
    uv run python tools/lint/spec_coverage.py [--unbound] [--check]
"""

from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

_DOCS_ROOT = Path("docs")
_TEST_ROOT = Path("tests")

_HEADER = re.compile(r"^#{2,6}\s+(.+?)\s*$")
_UC_IN_HEADER = re.compile(r"\bUC-[A-Za-z0-9][A-Za-z0-9-]*\b")  # ids carry lowercase variants (UC-SFV1b)
_WHEN = re.compile(r"^\s*When\b", re.MULTILINE)


@dataclass
class Scenario:
    spec_id: str
    scenario_id: str | None  # None == anonymous (Gherkin present, no stable id)
    spec_file: str


@dataclass
class Binding:
    spec_id: str
    scenario_id: str
    test_nodeid: str


@dataclass
class Report:
    scenarios: list[Scenario] = field(default_factory=list)
    bindings: list[Binding] = field(default_factory=list)

    @property
    def bindable(self) -> list[Scenario]:
        return [s for s in self.scenarios if s.scenario_id is not None]

    @property
    def anonymous(self) -> list[Scenario]:
        return [s for s in self.scenarios if s.scenario_id is None]


def _normalize_spec_id(spec_id: str) -> str:
    """Canonical spec id — strip a ``docs/global/`` or ``docs/`` prefix and a ``.md`` suffix.

    Applied to both the inventory (derived from the file path) and the bindings — some
    tests cite the canonical id, others the raw file path; normalizing both sides makes a
    binding resolve regardless of which form it used.
    """
    for prefix in ("docs/global/", "docs/"):
        if spec_id.startswith(prefix):
            spec_id = spec_id[len(prefix) :]
            break
    return spec_id[:-3] if spec_id.endswith(".md") else spec_id


def _spec_id_for(path: Path) -> str:
    return _normalize_spec_id(path.as_posix())


def _sections(text: str) -> list[tuple[str, str]]:
    """Split markdown into (header_title, body) sections on ATX headers (## … ######)."""
    sections: list[tuple[str, str]] = []
    title: str | None = None
    body: list[str] = []
    for line in text.splitlines():
        match = _HEADER.match(line)
        if match:
            if title is not None:
                sections.append((title, "\n".join(body)))
            title = match.group(1)
            body = []
        elif title is not None:
            body.append(line)
    if title is not None:
        sections.append((title, "\n".join(body)))
    return sections


def collect_scenarios() -> list[Scenario]:
    scenarios: list[Scenario] = []
    for spec_file in sorted(_DOCS_ROOT.rglob("*.md")):
        if "/spec/" not in spec_file.as_posix():
            continue
        spec_id = _spec_id_for(spec_file)
        rel = spec_file.as_posix()
        for title, body in _sections(spec_file.read_text(encoding="utf-8")):
            uc = _UC_IN_HEADER.search(title)
            if uc:
                # A UC-headed section is a bindable scenario by definition — no Gherkin-
                # shape heuristic, so a scenario written as a table or Given/Then still counts.
                scenarios.append(Scenario(spec_id, uc.group(0), rel))
            elif _WHEN.search(body):
                # Gherkin (a When line) with no UC id in the header — anonymous, needs an id.
                scenarios.append(Scenario(spec_id, None, rel))
    return scenarios


def collect_bindings() -> list[Binding]:
    bindings: list[Binding] = []
    for test_file in sorted(_TEST_ROOT.rglob("test_*.py")):
        tree = ast.parse(test_file.read_text(encoding="utf-8"), filename=str(test_file))
        consts = _module_string_constants(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for dec in node.decorator_list:
                parsed = _parse_spec_marker(dec, consts)
                if parsed is None:
                    continue
                spec_id, scenario_id = parsed
                nodeid = f"{test_file.as_posix()}::{node.name}"
                bindings.append(Binding(_normalize_spec_id(spec_id), scenario_id, nodeid))
    return bindings


def _module_string_constants(tree: ast.Module) -> dict[str, str]:
    """Map module-level ``NAME = "string"`` assignments so markers can use constants."""
    consts: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    consts[target.id] = node.value.value
    return consts


def _resolve_str(arg: ast.expr, consts: dict[str, str]) -> str | None:
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value
    if isinstance(arg, ast.Name):
        return consts.get(arg.id)
    return None


def _parse_spec_marker(dec: ast.expr, consts: dict[str, str]) -> tuple[str, str] | None:
    """Match ``@pytest.mark.spec(<spec_id>, <scenario_id>)`` with literal or constant args."""
    if not isinstance(dec, ast.Call):
        return None
    func = dec.func
    if not (isinstance(func, ast.Attribute) and func.attr == "spec"):
        return None
    values = [v for v in (_resolve_str(a, consts) for a in dec.args) if v is not None]
    if len(values) >= 2:
        return values[0], values[1]
    return None


def build_report() -> Report:
    return Report(scenarios=collect_scenarios(), bindings=collect_bindings())


def main() -> None:
    check = "--check" in sys.argv
    show_unbound = "--unbound" in sys.argv
    report = build_report()

    bindable_keys = {(s.spec_id, s.scenario_id) for s in report.bindable}
    bound_keys = {(b.spec_id, b.scenario_id) for b in report.bindings}

    bound = bound_keys & bindable_keys
    unbound = bindable_keys - bound_keys
    orphans = [b for b in report.bindings if (b.spec_id, b.scenario_id) not in bindable_keys]

    seen: dict[tuple[str, str], int] = {}
    for b in report.bindings:
        seen[(b.spec_id, b.scenario_id)] = seen.get((b.spec_id, b.scenario_id), 0) + 1
    duplicates = {k: n for k, n in seen.items() if n > 1}

    print("=" * 60)
    print("SPEC-ANCHORED COVERAGE")
    print("=" * 60)
    print(f"  spec files              : {len({s.spec_file for s in report.scenarios})}")
    print(f"  total scenarios         : {len(report.scenarios)}")
    print(f"  bindable (stable UC id) : {len(report.bindable)}")
    print(f"  anonymous (need an id)  : {len(report.anonymous)}")
    print("-" * 60)
    print(f"  bound                   : {len(bound)}")
    print(f"  unbound (backlog)       : {len(unbound)}")
    print(f"  duplicate bindings      : {len(duplicates)}  (gated)")
    print(f"  orphan bindings         : {len(orphans)}  (gated)")
    print("=" * 60)

    for b in sorted(orphans, key=lambda b: (b.spec_id, b.scenario_id, b.test_nodeid)):
        print(f"ORPHAN: {b.test_nodeid} cites {b.spec_id} :: {b.scenario_id} (no such scenario)")
    if show_unbound:
        for spec_id, sid in sorted(unbound):
            print(f"UNBOUND: {spec_id} :: {sid}")
        for (spec_id, sid), n in sorted(duplicates.items()):
            print(f"DUPLICATE: {spec_id} :: {sid} bound by {n} tests")

    # Per the testing contract (software-development/policy/testing Rule 8), a duplicate
    # binding and an orphan binding both fail the check — coverage is a 1:1 bijection of
    # test to scenario. Unbound and anonymous are backlog, surfaced but not gated here.
    if check and (duplicates or orphans):
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
