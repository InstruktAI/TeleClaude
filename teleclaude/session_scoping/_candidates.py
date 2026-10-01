"""Advisory candidates for dirty paths named by successful shell activity."""

from __future__ import annotations

import posixpath
import re
from enum import StrEnum
from pathlib import Path

from teleclaude.shell_path_parser import ShellCommand, lex_shell_commands
from teleclaude.utils.transcript import ToolCallRecord, TurnTimeline

from ._script_write_targets import javascript_write_targets, python_write_targets

_COMMAND_FIELDS = ("command", "cmd", "CommandLine")
_CODE_MODE_TOOL_NAMES = frozenset({"exec"})
_CODE_MODE_INPUT_FIELD = "input"
_TOOL_NAME_QUALIFIER_SEPARATOR = "."
_PATH_CHARACTER_CLASS = r"[A-Za-z0-9_./\\-]"
_PATH_BOUNDARY_TEMPLATE = r"(?<!{boundary}){path}(?!{boundary})"
_IN_PLACE_EDITOR_PATTERN = re.compile(r"(?<![\w.-])(?:sed(?:\s+\S+)*\s+-i(?:\s|\.|$)|perl\s+-pi(?:\s|\.|$))")
_FILE_VERB_PATTERN = re.compile(r"(?<![\w.-])(?:tee|touch|mkdir|mv|cp|rm|install|ln|rsync|patch)(?:\s|$)")
_GIT_MUTATION_PATTERN = re.compile(r"(?<![\w.-])git\s+(?:-C\s+\S+\s+)?(?:add|mv|rm|restore|checkout|apply)(?:\s|$)")
_INTERPRETER_PATTERN = re.compile(r"(?<![\w.-])(?:python(?:\d+(?:\.\d+)*)?|node)(?=\s|$)")
_SCRIPT_MODE_PATTERN = re.compile(r"(?:\s(?:-c|-e|--eval)(?:\s|$)|<<-?\s*['\"]?[A-Za-z_][A-Za-z0-9_]*['\"]?)")
_SCRIPT_WRITE_PATTERN = re.compile(
    r"(?:open\s*\([^)]*,\s*['\"][wax+]|write_text\s*\(|write_bytes\s*\(|"
    r"writeFile(?:Sync)?\s*\(|appendFile(?:Sync)?\s*\()"
)


class _FileCommand(StrEnum):
    TEE = "tee"
    TOUCH = "touch"
    MKDIR = "mkdir"
    RM = "rm"
    MV = "mv"
    CP = "cp"
    INSTALL = "install"
    LN = "ln"
    RSYNC = "rsync"
    PATCH = "patch"


class _GitMutation(StrEnum):
    ADD = "add"
    MV = "mv"
    RM = "rm"
    RESTORE = "restore"
    CHECKOUT = "checkout"
    APPLY = "apply"


class _ScriptOption(StrEnum):
    PYTHON_COMMAND = "-c"
    NODE_EVAL = "-e"
    NODE_EVAL_LONG = "--eval"
    GIT_DIRECTORY = "-C"


class _FileOption(StrEnum):
    GIT_DIRECTORY = "-C"
    SUFFIX = "-S"
    SUFFIX_LONG = "--suffix"
    MODE = "-m"
    MODE_LONG = "--mode"
    OWNER = "-o"
    OWNER_LONG = "--owner"
    GROUP = "-g"
    GROUP_LONG = "--group"
    STRIP_PROGRAM = "--strip-program"
    TARGET_DIRECTORY = "-t"
    TARGET_DIRECTORY_LONG = "--target-directory"
    INSTALL_DIRECTORY = "-d"
    INSTALL_DIRECTORY_LONG = "--directory"


class _RsyncOption(StrEnum):
    RSH = "-e"
    RSH_LONG = "--rsh"
    RSYNC_PATH = "--rsync-path"
    FILES_FROM = "--files-from"
    INCLUDE_FROM = "--include-from"
    EXCLUDE_FROM = "--exclude-from"
    FILTER = "-f"
    FILTER_LONG = "--filter"
    INCLUDE = "--include"
    EXCLUDE = "--exclude"
    TEMP_DIR = "-T"
    TEMP_DIR_LONG = "--temp-dir"
    PARTIAL_DIR = "--partial-dir"
    BACKUP_DIR = "--backup-dir"
    LINK_DEST = "--link-dest"
    COPY_DEST = "--copy-dest"
    COMPARE_DEST = "--compare-dest"
    LOG_FILE = "--log-file"
    LOG_FILE_FORMAT = "--log-file-format"
    WRITE_BATCH = "--write-batch"
    ONLY_WRITE_BATCH = "--only-write-batch"
    READ_BATCH = "--read-batch"
    PASSWORD_FILE = "--password-file"
    EARLY_INPUT = "--early-input"
    OUT_FORMAT = "--out-format"
    REMOTE_OPTION = "-M"
    REMOTE_OPTION_LONG = "--remote-option"
    ICONV = "--iconv"
    CHMOD = "--chmod"
    BLOCK_SIZE = "-B"
    BLOCK_SIZE_LONG = "--block-size"
    MODIFY_WINDOW = "-@"
    MODIFY_WINDOW_LONG = "--modify-window"
    MAX_DELETE = "--max-delete"
    MAX_SIZE = "--max-size"
    MIN_SIZE = "--min-size"
    MAX_ALLOC = "--max-alloc"
    TIMEOUT = "--timeout"
    CONNECTION_TIMEOUT = "--contimeout"
    BANDWIDTH_LIMIT = "--bwlimit"
    ADDRESS = "--address"
    PORT = "--port"
    SOCKET_OPTIONS = "--sockopts"
    CHECKSUM_CHOICE = "--checksum-choice"
    COMPRESS_CHOICE = "--compress-choice"
    COMPRESS_LEVEL = "--compress-level"
    COMPRESS_THREADS = "--compress-threads"
    SKIP_COMPRESS = "--skip-compress"
    STOP_AFTER = "--stop-after"
    STOP_AT = "--stop-at"
    COPY_AS = "--copy-as"
    CHOWN = "--chown"
    USER_MAP = "--usermap"
    GROUP_MAP = "--groupmap"
    CONFINE_ROOT = "--confine-root"
    CONNECT_PROGRAM = "--connect-program"


class _RsyncFlag(StrEnum):
    REMOVE_SOURCE_FILES = "--remove-source-files"


class _SyntaxToken(StrEnum):
    SPACE = " "
    OPTION_END = "--"
    DASH = "-"
    GIT = "git"
    PYTHON = "python"
    SED = "sed"
    PERL = "perl"
    EQUALS = "="
    SLASH = "/"


_ENV_ASSIGNMENT_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$")
_FILE_COMMANDS_ALL_OPERANDS = frozenset(
    {_FileCommand.TEE, _FileCommand.TOUCH, _FileCommand.MKDIR, _FileCommand.RM, _FileCommand.MV}
)
_FILE_COMMANDS_LAST_OPERAND = frozenset({_FileCommand.CP, _FileCommand.INSTALL, _FileCommand.LN, _FileCommand.RSYNC})
_MUTATING_GIT_COMMANDS = frozenset(_GitMutation)
_FILE_OPTION_VALUE_OPTIONS = frozenset(
    {
        _FileOption.GIT_DIRECTORY,
        _FileOption.SUFFIX,
        _FileOption.MODE,
        _FileOption.OWNER,
        _FileOption.GROUP,
    }
)
_TARGET_DIRECTORY_OPTIONS = frozenset({_FileOption.TARGET_DIRECTORY, _FileOption.TARGET_DIRECTORY_LONG})
_INSTALL_DIRECTORY_OPTIONS = frozenset({_FileOption.INSTALL_DIRECTORY, _FileOption.INSTALL_DIRECTORY_LONG})
_FILE_COMMAND_ARGUMENT_OPTIONS: dict[_FileCommand, frozenset[str]] = {
    _FileCommand.CP: frozenset({_FileOption.SUFFIX, _FileOption.SUFFIX_LONG}),
    _FileCommand.INSTALL: frozenset(
        {
            _FileOption.SUFFIX,
            _FileOption.SUFFIX_LONG,
            _FileOption.MODE,
            _FileOption.MODE_LONG,
            _FileOption.OWNER,
            _FileOption.OWNER_LONG,
            _FileOption.GROUP,
            _FileOption.GROUP_LONG,
            _FileOption.STRIP_PROGRAM,
        }
    ),
    _FileCommand.LN: frozenset(),
    _FileCommand.RSYNC: frozenset(_RsyncOption),
}
_RSYNC_OUTPUT_OPTIONS = frozenset(
    {
        _RsyncOption.LOG_FILE,
        _RsyncOption.WRITE_BATCH,
        _RsyncOption.ONLY_WRITE_BATCH,
        _RsyncOption.TEMP_DIR,
        _RsyncOption.TEMP_DIR_LONG,
        _RsyncOption.PARTIAL_DIR,
        _RsyncOption.BACKUP_DIR,
    }
)


def undeclared_shell_write_candidates(
    timeline: TurnTimeline,
    *,
    dirty_paths: frozenset[str],
    declared_paths: frozenset[str],
    certain_tools: frozenset[str],
    checkout_root: Path,
) -> tuple[str, ...]:
    """Return dirty undeclared paths established as targets of successful writes."""
    unresolved = dirty_paths - declared_paths
    candidates: set[str] = set()
    for record in timeline.tool_calls:
        if record.had_error or not record.result_observed:
            continue
        if _canonical_tool_name(record.tool_name) in certain_tools:
            continue
        shell_targets: set[str] = set()
        for command_text in _command_texts(record):
            parsed = lex_shell_commands(command_text)
            if parsed is None:
                # An unreadable shell command cannot establish a write destination.
                continue
            for command in parsed:
                shell_targets.update(_shell_write_targets(command))
        if _canonical_tool_name(record.tool_name) in _CODE_MODE_TOOL_NAMES:
            raw_input = record.input_data.get(_CODE_MODE_INPUT_FIELD)
            if isinstance(raw_input, str):
                shell_targets.update(javascript_write_targets(raw_input))
        for path in unresolved:
            if any(_text_names_path(target, path, checkout_root) for target in shell_targets):
                candidates.add(path)
    return tuple(sorted(candidates))


def _canonical_tool_name(tool_name: str) -> str:
    """Normalize the timeline's provider-qualified tool name."""
    normalized = tool_name.strip().lower()
    return (
        normalized.rsplit(_TOOL_NAME_QUALIFIER_SEPARATOR, 1)[-1]
        if _TOOL_NAME_QUALIFIER_SEPARATOR in normalized
        else normalized
    )


def _command_texts(record: ToolCallRecord) -> tuple[str, ...]:
    """Read only the recorded command fields owned by the recognized runtimes."""
    commands: list[str] = []
    for field in _COMMAND_FIELDS:
        value = record.input_data.get(field)
        if isinstance(value, str) and value:
            commands.append(value)
    return tuple(commands)


def _shell_write_targets(command: ShellCommand) -> set[str]:
    """Collect targets from one command, keeping each operation's destination local."""
    targets = set(command.redirections)
    words = list(command.words)
    if not words:
        return targets
    executable_index = 0
    while executable_index < len(words) and _ENV_ASSIGNMENT_PATTERN.match(words[executable_index]):
        executable_index += 1
    if executable_index >= len(words):
        return targets
    executable = posixpath.basename(words[executable_index])
    argv = words[executable_index:]

    if _INTERPRETER_PATTERN.fullmatch(executable):
        script = _interpreter_script(argv, command.heredocs)
        if script is not None and (command.heredocs or _SCRIPT_MODE_PATTERN.search(_SyntaxToken.SPACE.join(argv))):
            if executable.startswith(_SyntaxToken.PYTHON):
                if _SCRIPT_WRITE_PATTERN.search(script):
                    targets.update(python_write_targets(script))
            elif _SCRIPT_WRITE_PATTERN.search(script):
                targets.update(javascript_write_targets(script))
        return targets

    is_file_verb = bool(_FILE_VERB_PATTERN.search(executable + _SyntaxToken.SPACE))
    if is_file_verb and executable in _FILE_COMMANDS_ALL_OPERANDS:
        targets.update(_operands(argv[1:]))
    elif is_file_verb and executable in _FILE_COMMANDS_LAST_OPERAND:
        targets.update(_file_command_write_targets(executable, argv[1:]))
    elif executable in {_SyntaxToken.SED, _SyntaxToken.PERL} and _IN_PLACE_EDITOR_PATTERN.search(
        _SyntaxToken.SPACE.join(argv)
    ):
        operand_words = _operands(argv[1:])
        if operand_words:
            targets.add(operand_words[-1])
    elif is_file_verb and executable == _FileCommand.PATCH:
        targets.update(_operands(argv[1:]))
    elif executable == _SyntaxToken.GIT and _GIT_MUTATION_PATTERN.search(_SyntaxToken.SPACE.join(argv)):
        git_index = _git_mutation_index(argv)
        if git_index is not None:
            targets.update(_operands(argv[git_index + 1 :]))
    return targets


def _interpreter_script(argv: list[str], heredocs: tuple[str, ...]) -> str | None:
    """Read an interpreter's explicit -c program or a consumed here-document."""
    if heredocs:
        return heredocs[0]
    for index, word in enumerate(argv[:-1]):
        if word in {_ScriptOption.PYTHON_COMMAND, _ScriptOption.NODE_EVAL, _ScriptOption.NODE_EVAL_LONG}:
            return argv[index + 1]
    return None


def _file_command_write_targets(executable: str, arguments: list[str]) -> set[str]:
    """Resolve command option values before separating sources from destinations."""
    file_command = next((command for command in _FILE_COMMANDS_LAST_OPERAND if command == executable), None)
    if file_command is None:
        return set()
    value_options = _FILE_COMMAND_ARGUMENT_OPTIONS[file_command]
    positional: list[str] = []
    output_targets: set[str] = set()
    target_directory: str | None = None
    create_directories = False
    remove_sources = False
    index = 0
    parse_options = True
    while index < len(arguments):
        argument = arguments[index]
        if parse_options and argument == _SyntaxToken.OPTION_END:
            parse_options = False
            index += 1
            continue
        if not parse_options:
            positional.append(argument)
            index += 1
            continue
        if file_command == _FileCommand.INSTALL and argument in _INSTALL_DIRECTORY_OPTIONS:
            create_directories = True
            index += 1
            continue
        target_option, target_value, target_consumed = (False, None, 1)
        if file_command != _FileCommand.RSYNC:
            target_option, target_value, target_consumed = _option_value(arguments, index, _TARGET_DIRECTORY_OPTIONS)
        if target_option:
            target_directory = target_value
            index += target_consumed
            continue
        value_option, option_value, value_consumed = _option_value(arguments, index, value_options)
        if value_option:
            if file_command == _FileCommand.RSYNC and option_value is not None and _is_rsync_output_option(argument):
                output_targets.add(option_value)
            index += value_consumed
            continue
        if file_command == _FileCommand.RSYNC and argument == _RsyncFlag.REMOVE_SOURCE_FILES:
            remove_sources = True
            index += 1
            continue
        if argument.startswith(_SyntaxToken.DASH):
            index += 1
            continue
        positional.append(argument)
        index += 1

    if target_directory:
        output_targets.update(_target_directory_outputs(target_directory, positional))
    elif create_directories:
        output_targets.update(positional)
    elif len(positional) >= 2:
        output_targets.add(positional[-1])
        if remove_sources:
            output_targets.update(positional[:-1])
    return output_targets


def _target_directory_outputs(target_directory: str, sources: list[str]) -> set[str]:
    """Form the output file paths created from each source in a target directory."""
    outputs: set[str] = set()
    for source in sources:
        source_name = posixpath.basename(source.rstrip(_SyntaxToken.SLASH))
        if source_name:
            outputs.add(posixpath.normpath(posixpath.join(target_directory, source_name)))
    return outputs


def _option_value(
    arguments: list[str],
    index: int,
    options: frozenset[str],
) -> tuple[bool, str | None, int]:
    """Return a recognized option value without treating it as a file operand."""
    argument = arguments[index]
    for option in options:
        if argument == option:
            if index + 1 < len(arguments):
                return True, arguments[index + 1], 2
            return True, None, 1
        if option.startswith(_SyntaxToken.OPTION_END) and argument.startswith(option + _SyntaxToken.EQUALS):
            return True, argument[len(option) + 1 :], 1
        if option.startswith(_SyntaxToken.DASH) and not option.startswith(_SyntaxToken.OPTION_END):
            if argument.startswith(option) and len(argument) > len(option):
                return True, argument[len(option) :], 1
    return False, None, 1


def _is_rsync_output_option(argument: str) -> bool:
    return argument in _RSYNC_OUTPUT_OPTIONS or any(
        argument.startswith(option + _SyntaxToken.EQUALS) for option in _RSYNC_OUTPUT_OPTIONS
    )


def _operands(words: list[str]) -> list[str]:
    """Return file operands, omitting option tokens and their common values."""
    operands: list[str] = []
    skip_value = False
    for word in words:
        if skip_value:
            skip_value = False
            continue
        if word in _FILE_OPTION_VALUE_OPTIONS:
            skip_value = True
            continue
        if word == _SyntaxToken.OPTION_END:
            continue
        if word.startswith(_SyntaxToken.DASH):
            continue
        operands.append(word)
    return operands


def _git_mutation_index(argv: list[str]) -> int | None:
    """Find a recognized git mutation subcommand after global options."""
    index = 1
    while index < len(argv):
        if argv[index] == _ScriptOption.GIT_DIRECTORY:
            index += 2
            continue
        if argv[index].startswith(_SyntaxToken.DASH):
            index += 1
            continue
        return index if argv[index] in _MUTATING_GIT_COMMANDS else None
    return None


def _text_names_path(text: str, path: str, checkout_root: Path) -> bool:
    """Match a known dirty path literally in an established destination expression."""
    absolute_path = (checkout_root / path).as_posix()
    for candidate in (path, absolute_path):
        matcher = re.compile(_PATH_BOUNDARY_TEMPLATE.format(boundary=_PATH_CHARACTER_CLASS, path=re.escape(candidate)))
        if matcher.search(text):
            return True
    return False
