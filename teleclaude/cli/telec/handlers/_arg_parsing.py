"""Declaration-driven CLI argument parsing shared by every telec handler.

``parse_command_args`` recognizes a token by checking it against the
``Flag`` objects a ``CommandDef`` declares — never against a hand-copied
literal — so option recognition cannot drift from the surface declaration.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from teleclaude.cli.telec.surface_types import CommandDef, Flag, FlagArity


class CliUsageError(Exception):
    """A usage-level parsing failure: unknown option, missing value, or a
    switch given a value. Carries only its message; the entry point renders
    it alongside the resolved command's usage.
    """


def _is_option_like(token: str) -> bool:
    """True for a token that looks like an option boundary (`--`, or a
    dash-leading token longer than a lone `-`)."""
    return token == "--" or (token.startswith("-") and token != "-" and len(token) > 1)


@dataclass(frozen=True)
class ParsedArgs:
    """The result of parsing one command node's argv against its declared flags.

    Values are looked up by ``Flag`` object, keyed internally by
    ``flag.long``: a handler that imports the wrong constant, or a constant
    not declared on the parsed node, fails immediately with a programming
    error rather than silently reading nothing.
    """

    positionals: tuple[str, ...]
    _declared: frozenset[str] = field(repr=False)
    _values: Mapping[str, tuple[str, ...]] = field(repr=False)

    def _require_declared(self, flag: Flag) -> None:
        if flag.long not in self._declared:
            raise AssertionError(f"{flag.long!r} is not declared on the parsed command node")

    def has(self, flag: Flag) -> bool:
        """Return whether ``flag`` was present (any arity, including SWITCH)."""
        self._require_declared(flag)
        return flag.long in self._values

    def value(self, flag: Flag) -> str | None:
        """Return the flag's value: the last occurrence for VALUE/REPEATED/GREEDY."""
        self._require_declared(flag)
        values = self._values.get(flag.long)
        return values[-1] if values else None

    def values(self, flag: Flag) -> tuple[str, ...]:
        """Return every accumulated value, in occurrence order (REPEATED/GREEDY)."""
        self._require_declared(flag)
        return self._values.get(flag.long, ())


def parse_command_args(node: CommandDef, args: Sequence[str]) -> ParsedArgs:
    """Parse ``args`` against ``node``'s declared flags.

    Tokenizer rules, left to right:
    1. ``--`` — every remaining token becomes a positional.
    2. A token equal to a declared ``long`` or ``short`` — consumed per arity.
       VALUE, REPEATED, and GREEDY all raise ``CliUsageError`` for a missing
       value when the option is the last token or is immediately followed by
       another option-like token (rejected rather than silently consumed as
       the value); a value that must itself look like an option is passed via
       the ``--<long>=<value>`` form instead.
    3. ``--<long>=<value>`` for a declared ``long`` — the value form.
    4. Any other dash-leading token longer than a lone ``-`` — a positional
       when ``node.literal_dash_tokens``, else raises ``CliUsageError``.
    5. Everything else (including a lone ``-``) — a positional.
    """
    declared: dict[str, Flag] = {}
    lookup: dict[str, Flag] = {}
    for flag in node.flags:
        declared[flag.long] = flag
        lookup[flag.long] = flag
        if flag.short:
            lookup[flag.short] = flag

    positionals: list[str] = []
    values: dict[str, list[str]] = {}
    tokens = list(args)
    count = len(tokens)
    index = 0
    past_separator = False

    while index < count:
        token = tokens[index]

        if not past_separator and token == "--":
            past_separator = True
            index += 1
            continue

        if past_separator:
            positionals.append(token)
            index += 1
            continue

        if token.startswith("--") and "=" in token:
            long_part, _, value_part = token.partition("=")
            flag = lookup.get(long_part)
            if flag is not None:
                if flag.arity is FlagArity.SWITCH:
                    raise CliUsageError(f"Option {flag.long} does not take a value")
                values.setdefault(flag.long, []).append(value_part)
                index += 1
                continue

        flag = lookup.get(token)
        if flag is not None:
            if flag.arity is FlagArity.SWITCH:
                values.setdefault(flag.long, [])
                index += 1
                continue
            if flag.arity is FlagArity.VALUE:
                if index + 1 >= count or _is_option_like(tokens[index + 1]):
                    raise CliUsageError(f"Missing value for {flag.long}")
                values[flag.long] = [tokens[index + 1]]
                index += 2
                continue
            if flag.arity is FlagArity.REPEATED:
                if index + 1 >= count or _is_option_like(tokens[index + 1]):
                    raise CliUsageError(f"Missing value for {flag.long}")
                values.setdefault(flag.long, []).append(tokens[index + 1])
                index += 2
                continue
            # GREEDY: consume every following token up to the next option-like
            # token, at least one.
            cursor = index + 1
            collected: list[str] = []
            while cursor < count and not _is_option_like(tokens[cursor]):
                collected.append(tokens[cursor])
                cursor += 1
            if not collected:
                raise CliUsageError(f"Missing value for {flag.long}")
            values.setdefault(flag.long, []).extend(collected)
            index = cursor
            continue

        if not token.startswith("-") or token == "-":
            positionals.append(token)
            index += 1
            continue
        if node.literal_dash_tokens:
            positionals.append(token)
            index += 1
            continue
        raise CliUsageError(f"Unknown option: {token}")

    return ParsedArgs(
        positionals=tuple(positionals),
        _declared=frozenset(declared),
        _values={key: tuple(value) for key, value in values.items()},
    )
