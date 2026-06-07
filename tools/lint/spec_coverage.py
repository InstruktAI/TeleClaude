"""Spec-anchored test coverage report.

Coverage is measured against the Gherkin scenarios in the feature specs, not
against source files. Every scenario is a coverage unit; a test binds a scenario
with ``@pytest.mark.spec("<spec_id>", "<scenario_id>")``. This tool builds the
scenario inventory from the specs, collects the bindings from the tests, and
reconciles the two — reporting unbound scenarios (the backlog), duplicate
bindings (redundancy), and orphan bindings (a test citing a scenario that does
not exist).

It also surfaces the prerequisite reality: a scenario can only be bound if it
has a stable id. Specs whose scenarios are anonymous Gherkin blocks must be
given ids first.

Usage:
    uv run python tools/lint/spec_coverage.py [--unbound] [--check]
"""

from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

_SPEC_ROOT = Path("docs/project/spec/feature")
_TEST_ROOT = Path("tests")

# A scenario id header, e.g. "#### UC-EB1: ..." -> "UC-EB1", or a named header
# "#### Creating a session — happy path" -> the slugged name.
_ID_HEADER = re.compile(r"^####\s+(UC-[A-Z]+\d+[A-Z]*)\b", re.MULTILINE)
_FRONTMATTER_ID = re.compile(r"^id:\s*['\"]?([^'\"\n]+)['\"]?\s*$", re.MULTILINE)


@dataclass
class Scenario:
    spec_id: str
    scenario_id: str | None  # None == anonymous (no stable id, not bindable yet)
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


def _scenario_blocks(text: str) -> int:
    """Count Gherkin scenario blocks — fenced blocks containing a ``When`` line."""
    count = 0
    in_fence = False
    has_when = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            if in_fence and has_when:
                count += 1
            in_fence = not in_fence
            has_when = False
        elif in_fence and re.match(r"\s*When ", line):
            has_when = True
    return count


def collect_scenarios() -> list[Scenario]:
    scenarios: list[Scenario] = []
    for spec_file in sorted(_SPEC_ROOT.rglob("*.md")):
        text = spec_file.read_text(encoding="utf-8")
        id_match = _FRONTMATTER_ID.search(text)
        spec_id = id_match.group(1) if id_match else spec_file.as_posix()
        rel = spec_file.as_posix()

        uc_ids = _ID_HEADER.findall(text)
        block_count = _scenario_blocks(text)

        if uc_ids:
            for sid in uc_ids:
                scenarios.append(Scenario(spec_id, sid, rel))
            # Any blocks beyond the labelled ones are anonymous.
            for _ in range(max(0, block_count - len(uc_ids))):
                scenarios.append(Scenario(spec_id, None, rel))
        else:
            # No stable ids — every block is currently anonymous/unbindable.
            for _ in range(block_count):
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
                bindings.append(Binding(spec_id, scenario_id, nodeid))
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

    bindable = report.bindable
    bindable_keys = {(s.spec_id, s.scenario_id) for s in bindable}
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
    print(f"  feature specs           : {len({s.spec_file for s in report.scenarios})}")
    print(f"  total scenarios         : {len(report.scenarios)}")
    print(f"  bindable (stable id)    : {len(bindable)}")
    print(f"  anonymous (need an id)  : {len(report.anonymous)}")
    print("-" * 60)
    print(f"  bound                   : {len(bound)}")
    print(f"  unbound (backlog)       : {len(unbound)}")
    print(f"  duplicate bindings      : {len(duplicates)}")
    print(f"  orphan bindings         : {len(orphans)}")
    print("=" * 60)

    for (spec_id, sid), n in sorted(duplicates.items()):
        print(f"DUPLICATE: {spec_id} :: {sid} bound by {n} tests")
    for b in orphans:
        print(f"ORPHAN: {b.test_nodeid} cites {b.spec_id} :: {b.scenario_id} (no such scenario)")
    if show_unbound:
        for spec_id, sid in sorted(unbound):
            print(f"UNBOUND: {spec_id} :: {sid}")

    if check and (duplicates or orphans):
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
