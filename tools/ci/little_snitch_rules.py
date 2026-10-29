"""Build the published Little Snitch rule file from the committed source (sdlc/procedure/network-access-rules).

Homebrew installs every formula version under its own Cellar path, and Little Snitch matches a process by its
exact path. The source names each formula and the binary's path inside the formula's folder; this build expands
it into one rule per version and Homebrew prefix. It adds the formula's current version from the Homebrew API and
keeps every version the published file already carries, so a computer still on an older version keeps its rule.
Versions a computer runs that are older than the current one and not yet published are added by name
(``--add <formula>=<version>``). Rules that name a code identity are copied as they are.
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Final

_HOMEBREW_PREFIXES: Final = ("/opt/homebrew", "/usr/local")
_FORMULA_FIELD: Final = "formula"
_KEG_PATH_FIELD: Final = "keg-path"
_PROCESS_FIELD: Final = "process"
_NOTES_FIELD: Final = "notes"
_HTTP_NOT_FOUND: Final = 404
_TIMEOUT_S: Final = 30

Rule = dict[str, object]  # guard: loose-dict - An lsrules rule is Little Snitch's own JSON object, passed through.
Document = dict[str, object]  # guard: loose-dict - lsrules files and Homebrew API answers are third-party JSON.


@dataclass(frozen=True)
class FormulaEntry:
    """A source entry that names a Homebrew formula: expanded into one rule per version and prefix."""

    formula: str
    keg_path: str
    rule: Rule  # The rest of the entry: Little Snitch fields, copied into every expanded rule.

    @classmethod
    def read(cls, entry: Rule) -> FormulaEntry:
        formula, keg_path = entry[_FORMULA_FIELD], entry.get(_KEG_PATH_FIELD)
        if not isinstance(formula, str) or not isinstance(keg_path, str) or not formula or not keg_path:
            raise SystemExit(f"a formula entry needs a formula and a keg-path: {entry!r}")
        rule = {key: value for key, value in entry.items() if key not in (_FORMULA_FIELD, _KEG_PATH_FIELD)}
        return cls(formula, keg_path, rule)

    def process_path(self, prefix: str, version: str) -> str:
        return f"{prefix}/Cellar/{self.formula}/{version}/{self.keg_path}"

    def expand(self, versions: set[str]) -> list[Rule]:
        rules: list[Rule] = []
        for version in sorted(versions):
            for prefix in _HOMEBREW_PREFIXES:
                rule = dict(self.rule)
                rule[_PROCESS_FIELD] = self.process_path(prefix, version)
                rule[_NOTES_FIELD] = f"{self.formula} {version}: {self.rule.get(_NOTES_FIELD, '')}".rstrip()
                rules.append(rule)
        return rules


def _fetch_json(url: str) -> Document | None:
    """The JSON document at ``url``, or ``None`` when it does not exist yet."""
    try:
        with urllib.request.urlopen(url, timeout=_TIMEOUT_S) as response:
            document: Document = json.load(response)
            return document
    except urllib.error.HTTPError as error:
        if error.code == _HTTP_NOT_FOUND:
            return None
        raise


def _current_version(formula: str) -> str:
    """The formula's current Cellar folder name: its stable version, with ``_<revision>`` when revised."""
    document = _fetch_json(f"https://formulae.brew.sh/api/formula/{formula}.json")
    if document is None:
        raise SystemExit(f"Homebrew has no formula named {formula}")
    versions = document["versions"]
    assert isinstance(versions, dict)
    version = str(versions["stable"])
    revision = int(str(document.get("revision") or 0))
    return f"{version}_{revision}" if revision > 0 else version


def _published_versions(published: Document | None, entry: FormulaEntry) -> set[str]:
    """The versions of the entry's formula the published file already carries a rule for."""
    if published is None:
        return set()
    versions: set[str] = set()
    rules = published.get("rules")
    for rule in rules if isinstance(rules, list) else []:
        process = str(rule.get(_PROCESS_FIELD, "")) if isinstance(rule, dict) else ""
        for prefix in _HOMEBREW_PREFIXES:
            head, tail = f"{prefix}/Cellar/{entry.formula}/", f"/{entry.keg_path}"
            if process.startswith(head) and process.endswith(tail):
                versions.add(process[len(head) : -len(tail)])
    return versions


def build(source: Document, published: Document | None, added: dict[str, set[str]] | None = None) -> Document:
    """The rule file to publish: every source rule, expanded per version and Homebrew prefix where it names a formula.

    A version added for a formula the source does not name is refused, so a request never vanishes silently.
    """
    source_rules = source["rules"]
    assert isinstance(source_rules, list)
    entries = [FormulaEntry.read(entry) if _FORMULA_FIELD in entry else entry for entry in source_rules]
    named = {entry.formula for entry in entries if isinstance(entry, FormulaEntry)}
    unknown = sorted(set(added or {}) - named)
    if unknown:
        raise SystemExit(f"--add names formulas the source does not: {', '.join(unknown)}")
    rules: list[Rule] = []
    for entry in entries:
        if not isinstance(entry, FormulaEntry):
            rules.append(dict(entry))
            continue
        versions = (
            _published_versions(published, entry)
            | {_current_version(entry.formula)}
            | (added or {}).get(entry.formula, set())
        )
        rules.extend(entry.expand(versions))
    return {key: value for key, value in source.items() if key != "rules"} | {"rules": rules}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="the committed rules source")
    parser.add_argument("--published-url", required=True, help="where the rule file is published now")
    parser.add_argument("--output", type=Path, required=True, help="the rule file to publish")
    parser.add_argument("--add", nargs="*", default=[], metavar="FORMULA=VERSION", help="versions to add")
    arguments = parser.parse_args()
    added: dict[str, set[str]] = {}
    for pair in arguments.add:
        formula, _, version = pair.partition("=")
        if not formula or not version:
            parser.error(f"--add takes FORMULA=VERSION, got {pair!r}")
        added.setdefault(formula, set()).add(version)
    source = json.loads(arguments.source.read_text())
    rule_file = build(source, _fetch_json(arguments.published_url), added)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(rule_file, indent=2) + "\n")


if __name__ == "__main__":
    main()
