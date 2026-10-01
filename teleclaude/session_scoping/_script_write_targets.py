"""Static write destination extraction for supported interpreter scripts."""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from enum import StrEnum

from teleclaude.utils.transcript._codex_custom_exec import _read_js_quoted_string


@dataclass
class _JavaScriptLexicalContext:
    """Token context needed to distinguish regex literals from division."""

    control_parens: list[tuple[bool, bool, bool]] = dataclass_field(default_factory=list)
    block_braces: list[tuple[bool, bool]] = dataclass_field(default_factory=list)
    regex_allowed: bool = True
    statement_start: bool = True
    pending_block: bool = False
    pending_block_expression: bool = False
    pending_function: bool = False
    pending_function_expression: bool = False
    last_word: str | None = None


class _JSContextWord(StrEnum):
    RETURN = "return"
    THROW = "throw"
    CASE = "case"
    DELETE = "delete"
    VOID = "void"
    TYPEOF = "typeof"
    INSTANCEOF = "instanceof"
    IN = "in"
    OF = "of"
    DEFAULT = "default"
    YIELD = "yield"
    AWAIT = "await"
    ELSE = "else"
    DO = "do"
    TRY = "try"
    FINALLY = "finally"
    FUNCTION = "function"
    CLASS = "class"
    IF = "if"
    WHILE = "while"
    FOR = "for"
    WITH = "with"
    SWITCH = "switch"
    CATCH = "catch"


class _ScriptName(StrEnum):
    OPEN = "open"
    WRITE_TEXT = "write_text"
    WRITE_BYTES = "write_bytes"
    WRITE_FILE = "writeFile"
    WRITE_FILE_SYNC = "writeFileSync"
    APPEND_FILE = "appendFile"
    APPEND_FILE_SYNC = "appendFileSync"
    CONST = "const"
    LET = "let"
    VAR = "var"


class _OpenMode(StrEnum):
    WRITE = "w"
    APPEND = "a"
    EXCLUSIVE = "x"
    READ_WRITE = "r+"
    WRITE_READ = "w+"
    APPEND_READ = "a+"
    EXCLUSIVE_READ = "x+"


class _JSSyntax(StrEnum):
    EMPTY = ""
    SPACE = " "
    OPTION_END = "--"
    DASH = "-"
    GIT = "git"
    PYTHON = "python"
    SED = "sed"
    PERL = "perl"
    OPENING_PAREN = "("
    CLOSING_PAREN = ")"
    OPENING_BRACKET = "["
    CLOSING_BRACKET = "]"
    OPENING_BRACE = "{"
    CLOSING_BRACE = "}"
    COMMA = ","
    DOT = "."
    EQUALS = "="
    SEMICOLON = ";"
    SLASH = "/"
    PLUS = "+"
    MINUS = "-"
    ASTERISK = "*"
    PERCENT = "%"
    AMPERSAND = "&"
    PIPE = "|"
    CARET = "^"
    TILDE = "~"
    BANG = "!"
    COLON = ":"
    QUESTION = "?"
    LESS_THAN = "<"
    GREATER_THAN = ">"
    ARROW = "=>"
    INCREMENT = "++"
    DECREMENT = "--"
    BACKSLASH = "\\"
    SINGLE_QUOTE = "'"
    DOUBLE_QUOTE = '"'
    BACKTICK = "`"
    JS_LINE_COMMENT = "//"
    JS_BLOCK_START = "/*"
    JS_BLOCK_END = "*/"
    NEWLINE = "\n"
    CARRIAGE_RETURN = "\r"
    UNDERSCORE = "_"
    DOLLAR = "$"


_JS_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")
_JS_WRITE_CALL_NAMES = frozenset(
    {_ScriptName.WRITE_FILE, _ScriptName.WRITE_FILE_SYNC, _ScriptName.APPEND_FILE, _ScriptName.APPEND_FILE_SYNC}
)
_JS_PATH_METHOD_NAMES = frozenset({_ScriptName.WRITE_TEXT, _ScriptName.WRITE_BYTES})
_PYTHON_OPEN_WRITE_MODES = frozenset(_OpenMode)
_JS_OPEN_MODE_PATTERN = re.compile(r"['\"][wax+]")
_JS_IDENTIFIER = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
_JS_NUMBER = re.compile(r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
_JS_REGEX_PREFIX_WORDS = frozenset(
    {
        _JSContextWord.RETURN,
        _JSContextWord.THROW,
        _JSContextWord.CASE,
        _JSContextWord.DELETE,
        _JSContextWord.VOID,
        _JSContextWord.TYPEOF,
        _JSContextWord.INSTANCEOF,
        _JSContextWord.IN,
        _JSContextWord.OF,
        _JSContextWord.DEFAULT,
        _JSContextWord.YIELD,
        _JSContextWord.AWAIT,
        _JSContextWord.ELSE,
        _JSContextWord.DO,
    }
)
_JS_CONTROL_PAREN_WORDS = frozenset(
    {
        _JSContextWord.IF,
        _JSContextWord.WHILE,
        _JSContextWord.FOR,
        _JSContextWord.WITH,
        _JSContextWord.SWITCH,
        _JSContextWord.CATCH,
    }
)
_JS_BLOCK_PREFIX_WORDS = frozenset(
    {
        _JSContextWord.ELSE,
        _JSContextWord.DO,
        _JSContextWord.TRY,
        _JSContextWord.FINALLY,
        _JSContextWord.CLASS,
    }
)
_JS_REGEX_PREFIX_PUNCTUATION = frozenset(
    {
        _JSSyntax.OPENING_PAREN,
        _JSSyntax.OPENING_BRACKET,
        _JSSyntax.OPENING_BRACE,
        _JSSyntax.COMMA,
        _JSSyntax.COLON,
        _JSSyntax.SEMICOLON,
        _JSSyntax.EQUALS,
        _JSSyntax.QUESTION,
        _JSSyntax.BANG,
        _JSSyntax.PLUS,
        _JSSyntax.MINUS,
        _JSSyntax.ASTERISK,
        _JSSyntax.PERCENT,
        _JSSyntax.AMPERSAND,
        _JSSyntax.PIPE,
        _JSSyntax.CARET,
        _JSSyntax.TILDE,
        _JSSyntax.LESS_THAN,
        _JSSyntax.GREATER_THAN,
    }
)


def python_write_targets(source: str) -> set[str]:
    """Read recognized Python write destinations without executing the script."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    bindings: dict[str, list[tuple[tuple[int, int], ast.expr]]] = {}
    calls: list[tuple[tuple[int, int], ast.Call]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and node in _direct_module_children(tree):
            value = node.value
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and value is not None:
                    bindings.setdefault(target.id, []).append(((node.lineno, node.col_offset), value))
        elif isinstance(node, ast.Call):
            calls.append(((node.lineno, node.col_offset), node))
    result: set[str] = set()
    for call_position, call in calls:
        method = _python_call_name(call.func)
        destination: ast.expr | None = None
        if method == _ScriptName.OPEN and call.args:
            mode = call.args[1] if len(call.args) > 1 else None
            if not isinstance(mode, ast.Constant) or mode.value not in _PYTHON_OPEN_WRITE_MODES:
                continue
            destination = call.args[0]
        elif method in {
            _ScriptName.WRITE_TEXT,
            _ScriptName.WRITE_BYTES,
            _ScriptName.WRITE_FILE,
            _ScriptName.APPEND_FILE,
        }:
            destination = (
                call.func.value if isinstance(call.func, ast.Attribute) else (call.args[0] if call.args else None)
            )
        if destination is None:
            continue
        if isinstance(destination, ast.Name):
            candidates = [item for item in bindings.get(destination.id, []) if item[0] < call_position]
            if len(bindings.get(destination.id, [])) != 1 or len(candidates) != 1:
                continue
            destination = candidates[0][1]
        result.update(_ast_string_literals(destination))
    return result


def _python_call_name(function: ast.expr) -> str | None:
    if isinstance(function, ast.Name):
        return function.id
    return function.attr if isinstance(function, ast.Attribute) else None


def _direct_module_children(tree: ast.Module) -> set[ast.stmt]:
    """Return top-level statements so conditional and loop bindings stay unreadable."""
    return set(tree.body)


def _ast_string_literals(expression: ast.expr) -> set[str]:
    return {
        node.value for node in ast.walk(expression) if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def javascript_write_targets(source: str) -> set[str]:
    """Extract static JS write destinations while ignoring strings and comments."""
    regex_literals = _javascript_regex_literal_spans(source)
    if regex_literals is None:
        return set()
    bindings = _javascript_bindings(source, regex_literals)
    result: set[str] = set()
    for start, name, opening in _javascript_calls(source, regex_literals):
        closing = _matching_js_paren(source, opening)
        if closing is None:
            continue
        arguments = _split_js_arguments(source[opening + 1 : closing])
        if name in _JS_WRITE_CALL_NAMES and arguments:
            destination = arguments[0]
        elif name == _ScriptName.OPEN and len(arguments) > 1 and _JS_OPEN_MODE_PATTERN.search(arguments[1]):
            destination = arguments[0]
        elif name in _JS_PATH_METHOD_NAMES:
            receiver = _js_call_receiver(source, start)
            destination = receiver or ""
        else:
            continue
        destination = destination.strip()
        if _JS_IDENTIFIER_PATTERN.fullmatch(destination):
            assignments = [entry for entry in bindings.get(destination, []) if entry[0] < start]
            if len(bindings.get(destination, [])) != 1 or len(assignments) != 1:
                continue
            destination = assignments[0][1]
        result.update(_js_string_literals(destination))
    return result


def _javascript_regex_literal_spans(source: str) -> dict[int, int] | None:
    """Find regex literals in expression-start contexts without evaluating code."""
    spans: dict[int, int] = {}
    context = _JavaScriptLexicalContext()
    index = 0
    while index < len(source):
        skipped = _skip_js_noncode(source, index)
        if skipped != index:
            index = skipped
            continue
        character = source[index]
        if character.isspace():
            index += 1
            continue
        if character in {_JSSyntax.SINGLE_QUOTE, _JSSyntax.DOUBLE_QUOTE}:
            parsed = _read_js_quoted_string(source, index)
            if parsed is None:
                return None
            index = parsed[1]
            context.regex_allowed = False
            context.statement_start = False
            context.last_word = None
            continue
        if character == _JSSyntax.BACKTICK:
            index = _skip_js_template(source, index)
            context.regex_allowed = False
            context.statement_start = False
            context.last_word = None
            continue
        word_end = _consume_js_word(source, index, context)
        if word_end is not None:
            index = word_end
            continue
        if character == _JSSyntax.SLASH:
            if context.regex_allowed:
                regex_end = _skip_js_regex_literal(source, index)
                if regex_end is None:
                    return None
                spans[index] = regex_end
                index = regex_end
                context.regex_allowed = False
                context.statement_start = False
                context.last_word = None
                continue
            index += 2 if source.startswith(_JSSyntax.SLASH + _JSSyntax.EQUALS, index) else 1
            context.regex_allowed = True
            context.statement_start = False
            context.last_word = None
            continue
        index = _consume_js_punctuation(source, index, context)
    return spans


def _consume_js_word(source: str, index: int, context: _JavaScriptLexicalContext) -> int | None:
    """Consume an identifier or numeric token and update lexical context."""
    identifier = _JS_IDENTIFIER.match(source, index)
    if identifier is not None:
        word = identifier.group(0)
        context.last_word = word
        if word == _JSContextWord.FUNCTION:
            context.pending_function = True
            context.pending_function_expression = not context.statement_start
        if word in _JS_BLOCK_PREFIX_WORDS:
            context.pending_block = True
            context.pending_block_expression = word == _JSContextWord.CLASS and not context.statement_start
            context.regex_allowed = True
            context.statement_start = True
        else:
            context.regex_allowed = word in _JS_REGEX_PREFIX_WORDS
            context.statement_start = False
        return identifier.end()
    number = _JS_NUMBER.match(source, index)
    if number is None:
        return None
    context.regex_allowed = False
    context.statement_start = False
    context.last_word = None
    return number.end()


def _consume_js_punctuation(source: str, index: int, context: _JavaScriptLexicalContext) -> int:
    """Consume one structural token and update regex/block context."""
    character = source[index]
    if source.startswith(_JSSyntax.ARROW, index):
        context.regex_allowed = True
        context.statement_start = True
        context.pending_block = True
        context.pending_block_expression = True
        context.last_word = None
        return index + len(_JSSyntax.ARROW)
    if character == _JSSyntax.OPENING_PAREN:
        control = context.last_word in _JS_CONTROL_PAREN_WORDS
        context.control_parens.append((control, context.pending_function, context.pending_function_expression))
        context.pending_function = False
        context.pending_function_expression = False
        context.regex_allowed = True
        context.statement_start = False
        context.last_word = None
        return index + 1
    if character == _JSSyntax.CLOSING_PAREN:
        control, function_body, function_expression = (
            context.control_parens.pop() if context.control_parens else (False, False, False)
        )
        context.pending_block = context.pending_block or control or function_body
        context.pending_block_expression = function_expression
        context.regex_allowed = control
        context.statement_start = control or function_body
        context.last_word = None
        return index + 1
    if character == _JSSyntax.OPENING_BRACE:
        block = context.statement_start or context.pending_block
        expression_body = context.pending_block_expression if context.pending_block else False
        context.block_braces.append((block, expression_body))
        context.pending_block = False
        context.pending_block_expression = False
        context.regex_allowed = True
        context.statement_start = block
        context.last_word = None
        return index + 1
    if character == _JSSyntax.CLOSING_BRACE:
        block, expression_body = context.block_braces.pop() if context.block_braces else (False, False)
        context.regex_allowed = block and not expression_body
        context.statement_start = block and not expression_body
        context.last_word = None
        return index + 1
    if character == _JSSyntax.OPENING_BRACKET:
        context.regex_allowed = True
        context.statement_start = False
        context.last_word = None
        return index + 1
    if character == _JSSyntax.CLOSING_BRACKET:
        context.regex_allowed = False
        context.statement_start = False
        context.last_word = None
        return index + 1
    if source.startswith(_JSSyntax.INCREMENT, index) or source.startswith(_JSSyntax.DECREMENT, index):
        context.regex_allowed = False
        context.statement_start = False
        context.last_word = None
        return index + len(_JSSyntax.INCREMENT)
    context.regex_allowed = character in _JS_REGEX_PREFIX_PUNCTUATION
    context.statement_start = character == _JSSyntax.SEMICOLON
    context.last_word = None
    return index + 1


def _skip_js_regex_literal(source: str, start: int) -> int | None:
    """Read one slash-delimited regex token, including escaped and class slashes."""
    index = start + 1
    escaped = False
    in_character_class = False
    while index < len(source):
        character = source[index]
        if character in {_JSSyntax.NEWLINE, _JSSyntax.CARRIAGE_RETURN}:
            return None
        if escaped:
            escaped = False
        elif character == _JSSyntax.BACKSLASH:
            escaped = True
        elif character == _JSSyntax.OPENING_BRACKET:
            in_character_class = True
        elif character == _JSSyntax.CLOSING_BRACKET:
            in_character_class = False
        elif character == _JSSyntax.SLASH and not in_character_class:
            index += 1
            while index < len(source) and source[index].isalpha():
                index += 1
            return index
        index += 1
    return None


def _javascript_bindings(source: str, regex_literals: dict[int, int]) -> dict[str, list[tuple[int, str]]]:
    """Read simple variable assignments outside JS strings and comments."""
    bindings: dict[str, list[tuple[int, str]]] = {}
    declarations = (_ScriptName.CONST, _ScriptName.LET, _ScriptName.VAR)
    index = 0
    while index < len(source):
        if index in regex_literals:
            index = regex_literals[index]
            continue
        skipped = _skip_js_noncode(source, index)
        if skipped != index:
            index = skipped
            continue
        if source[index] in {_JSSyntax.SINGLE_QUOTE, _JSSyntax.DOUBLE_QUOTE, _JSSyntax.BACKTICK}:
            parsed = _read_js_quoted_string(source, index) if source[index] != _JSSyntax.BACKTICK else None
            index = parsed[1] if parsed is not None else _skip_js_template(source, index)
            continue
        declaration = next(
            (
                item
                for item in declarations
                if source.startswith(item, index)
                and _identifier_boundary(source, index - 1)
                and _identifier_boundary(source, index + len(item))
            ),
            None,
        )
        if declaration is None:
            index += 1
            continue
        name_start = index + len(declaration)
        while name_start < len(source) and source[name_start].isspace():
            name_start += 1
        name_match = _JS_IDENTIFIER.match(source[name_start:])
        if name_match is None:
            index = name_start
            continue
        name = name_match.group(0)
        value_start = name_start + len(name)
        while value_start < len(source) and source[value_start].isspace():
            value_start += 1
        if value_start >= len(source) or source[value_start] != _JSSyntax.EQUALS:
            index = value_start
            continue
        value_start += 1
        while value_start < len(source) and source[value_start].isspace():
            value_start += 1
        value_end = _js_expression_end(source, value_start)
        if value_end is None:
            return bindings
        bindings.setdefault(name, []).append((index, source[value_start:value_end].strip()))
        index = max(value_end, value_start + 1)
    return bindings


def _javascript_calls(source: str, regex_literals: dict[int, int]) -> Iterable[tuple[int, str, int]]:
    """Yield supported call names and opening parentheses outside strings/comments."""
    names = _JS_WRITE_CALL_NAMES | _JS_PATH_METHOD_NAMES | {_ScriptName.OPEN}
    index = 0
    while index < len(source):
        if index in regex_literals:
            index = regex_literals[index]
            continue
        skipped = _skip_js_noncode(source, index)
        if skipped != index:
            index = skipped
            continue
        if source[index] in {_JSSyntax.SINGLE_QUOTE, _JSSyntax.DOUBLE_QUOTE, _JSSyntax.BACKTICK}:
            parsed = _read_js_quoted_string(source, index) if source[index] != _JSSyntax.BACKTICK else None
            index = parsed[1] if parsed is not None else _skip_js_template(source, index)
            continue
        for name in names:
            end = index + len(name)
            if (
                source.startswith(name, index)
                and _identifier_boundary(source, index - 1)
                and _identifier_boundary(source, end)
            ):
                opening = end
                while opening < len(source) and source[opening].isspace():
                    opening += 1
                if opening < len(source) and source[opening] == _JSSyntax.OPENING_PAREN:
                    yield index, name, opening
                index = end
                break
        else:
            index += 1


def _matching_js_paren(source: str, opening: int) -> int | None:
    depth = 1
    index = opening + 1
    while index < len(source):
        skipped = _skip_js_noncode(source, index)
        if skipped != index:
            index = skipped
            continue
        character = source[index]
        if character in {_JSSyntax.SINGLE_QUOTE, _JSSyntax.DOUBLE_QUOTE}:
            parsed = _read_js_quoted_string(source, index)
            if parsed is None:
                return None
            index = parsed[1]
            continue
        if character == _JSSyntax.BACKTICK:
            index = _skip_js_template(source, index)
            continue
        if character == _JSSyntax.OPENING_PAREN:
            depth += 1
        elif character == _JSSyntax.CLOSING_PAREN:
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def _split_js_arguments(source: str) -> list[str]:
    pieces: list[str] = []
    start = 0
    depth = 0
    index = 0
    while index < len(source):
        skipped = _skip_js_noncode(source, index)
        if skipped != index:
            index = skipped
            continue
        character = source[index]
        if character in {_JSSyntax.SINGLE_QUOTE, _JSSyntax.DOUBLE_QUOTE}:
            parsed = _read_js_quoted_string(source, index)
            if parsed is None:
                return []
            index = parsed[1]
            continue
        if character == _JSSyntax.BACKTICK:
            index = _skip_js_template(source, index)
            continue
        if character in {_JSSyntax.OPENING_PAREN, _JSSyntax.OPENING_BRACKET, _JSSyntax.OPENING_BRACE}:
            depth += 1
        elif character in {_JSSyntax.CLOSING_PAREN, _JSSyntax.CLOSING_BRACKET, _JSSyntax.CLOSING_BRACE}:
            depth -= 1
        elif character == _JSSyntax.COMMA and depth == 0:
            pieces.append(source[start:index].strip())
            start = index + 1
        index += 1
    pieces.append(source[start:].strip())
    return pieces


def _js_expression_end(source: str, start: int) -> int | None:
    index = start
    depth = 0
    while index < len(source):
        skipped = _skip_js_noncode(source, index)
        if skipped != index:
            index = skipped
            continue
        character = source[index]
        if character in {_JSSyntax.SINGLE_QUOTE, _JSSyntax.DOUBLE_QUOTE}:
            parsed = _read_js_quoted_string(source, index)
            if parsed is None:
                return None
            index = parsed[1]
            continue
        if character in {_JSSyntax.OPENING_PAREN, _JSSyntax.OPENING_BRACKET, _JSSyntax.OPENING_BRACE}:
            depth += 1
        elif character in {_JSSyntax.CLOSING_PAREN, _JSSyntax.CLOSING_BRACKET, _JSSyntax.CLOSING_BRACE}:
            if depth == 0:
                break
            depth -= 1
        elif depth == 0 and character in {_JSSyntax.SEMICOLON, _JSSyntax.NEWLINE}:
            break
        index += 1
    return index


def _js_call_receiver(source: str, call_start: int) -> str | None:
    prefix = source[:call_start].rstrip()
    if not prefix.endswith(_JSSyntax.DOT):
        return None
    receiver_end = len(prefix) - 1
    receiver_start = receiver_end
    while receiver_start > 0 and (
        prefix[receiver_start - 1].isalnum()
        or prefix[receiver_start - 1] in {_JSSyntax.UNDERSCORE, _JSSyntax.DOLLAR, _JSSyntax.DOT}
    ):
        receiver_start -= 1
    return prefix[receiver_start:receiver_end]


def _js_string_literals(expression: str) -> set[str]:
    result: set[str] = set()
    index = 0
    while index < len(expression):
        skipped = _skip_js_noncode(expression, index)
        if skipped != index:
            index = skipped
            continue
        if expression[index] in {_JSSyntax.SINGLE_QUOTE, _JSSyntax.DOUBLE_QUOTE}:
            parsed = _read_js_quoted_string(expression, index)
            if parsed is None:
                break
            result.add(parsed[0])
            index = parsed[1]
            continue
        if expression[index] == _JSSyntax.BACKTICK:
            index = _skip_js_template(expression, index)
            continue
        index += 1
    return result


def _skip_js_noncode(source: str, index: int) -> int:
    if source.startswith(_JSSyntax.JS_LINE_COMMENT, index):
        line_end = source.find(_JSSyntax.NEWLINE, index + len(_JSSyntax.JS_LINE_COMMENT))
        return len(source) if line_end < 0 else line_end + 1
    if source.startswith(_JSSyntax.JS_BLOCK_START, index):
        comment_end = source.find(_JSSyntax.JS_BLOCK_END, index + len(_JSSyntax.JS_BLOCK_START))
        return len(source) if comment_end < 0 else comment_end + 2
    return index


def _skip_js_template(source: str, start: int) -> int:
    index = start + 1
    escaped = False
    while index < len(source):
        character = source[index]
        if escaped:
            escaped = False
        elif character == _JSSyntax.BACKSLASH:
            escaped = True
        elif character == _JSSyntax.BACKTICK:
            return index + 1
        index += 1
    return len(source)


def _identifier_boundary(source: str, index: int) -> bool:
    return (
        index < 0
        or index >= len(source)
        or not (source[index].isalnum() or source[index] in {_JSSyntax.UNDERSCORE, _JSSyntax.DOLLAR})
    )
