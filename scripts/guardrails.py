#!/usr/bin/env python3

from __future__ import annotations

import json
from pathlib import Path


def _fail(message: str) -> None:
    raise SystemExit(f"guardrails: {message}")


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]

    pyproject_path = repo_root / "pyproject.toml"
    if not pyproject_path.exists():
        _fail("missing pyproject.toml")

    pyright_path = repo_root / "pyrightconfig.json"
    if not pyright_path.exists():
        _fail("missing pyrightconfig.json")

    pyright = json.loads(pyright_path.read_text(encoding="utf-8"))
    if pyright.get("typeCheckingMode") != "strict":
        _fail("pyright typeCheckingMode must be strict")

    # Keep this guardrail tight: don't allow ruff to be removed silently.
    pyproject = pyproject_path.read_text(encoding="utf-8")
    if "[tool.ruff]" not in pyproject:
        _fail("pyproject.toml must define [tool.ruff]")


if __name__ == "__main__":
    main()
