"""Import every module in the teleclaude package in one interpreter."""

from __future__ import annotations

import importlib
import pkgutil
import sys

import teleclaude

_PACKAGE_NAME = "teleclaude"
_MODULE_PREFIX_SEPARATOR = "."
_MODULE_FAILURE_FORMAT = "{name}: {error_type}: {error_message}"
_MODULE_COUNT_FORMAT = "Imported {count} teleclaude modules."


def main() -> int:
    """Import all discovered modules and report any failures."""
    module_names = sorted(
        module_info.name
        for module_info in pkgutil.walk_packages(teleclaude.__path__, f"{_PACKAGE_NAME}{_MODULE_PREFIX_SEPARATOR}")
    )
    failures: list[str] = []
    imported_count = 0
    for module_name in module_names:
        try:
            importlib.import_module(module_name)
        except Exception as import_error:
            failures.append(
                _MODULE_FAILURE_FORMAT.format(
                    name=module_name,
                    error_type=type(import_error).__name__,
                    error_message=import_error,
                )
            )
        else:
            imported_count += 1

    print(_MODULE_COUNT_FORMAT.format(count=imported_count))
    for failure in failures:
        print(failure, file=sys.stderr)
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
