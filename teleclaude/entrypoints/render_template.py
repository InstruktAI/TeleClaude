"""Render an installation template to a destination file."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from teleclaude.core.reconciliation.template_installation import (
    UnresolvedPlaceholderError,
    render_template,
)

_DESCRIPTION = "Render a TeleClaude installation template."
_TEMPLATE_ARGUMENT = "template"
_OUTPUT_ARGUMENT = "output"
_VALUES_ARGUMENT = "values"
_VALUE_METAVAR = "NAME=VALUE"
_ASSIGNMENT_SEPARATOR = "="
_MALFORMED_VALUE_MESSAGE = "values must use NAME=VALUE with an identifier name"
_ENCODING_NAME = "utf-8"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=_DESCRIPTION)
    parser.add_argument(_TEMPLATE_ARGUMENT, type=Path)
    parser.add_argument(_OUTPUT_ARGUMENT, type=Path)
    parser.add_argument(_VALUES_ARGUMENT, nargs="*", metavar=_VALUE_METAVAR)
    return parser


def main() -> int:
    """Render the requested template, leaving output absent on resolution errors."""
    parser = _build_parser()
    arguments = parser.parse_args()
    values: dict[str, str] = {}
    for argument in arguments.values:
        name, separator, value = argument.partition(_ASSIGNMENT_SEPARATOR)
        if not separator or not name.isidentifier():
            parser.error(_MALFORMED_VALUE_MESSAGE)
        values[name] = value

    template: Path = arguments.template
    output: Path = arguments.output
    try:
        rendered = render_template(
            template.read_text(encoding=_ENCODING_NAME),
            template=template,
            values=values,
            # guard: direct-env-read - allowed: configuration loading or interpolation
            environ=os.environ,
        )
    except UnresolvedPlaceholderError as error:
        print(error, file=sys.stderr)
        return 1
    output.write_text(rendered, encoding=_ENCODING_NAME)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
