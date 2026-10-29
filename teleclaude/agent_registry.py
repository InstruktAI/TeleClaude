"""Canonical registry of supported AI agents.

Leaf module with no internal TeleClaude dependencies (standard library only),
so it can be imported before ``config`` without recreating the import cycle
that once forced a second ``AgentName`` declaration. Every other module that
needs to know which agents exist, what they are called, how they launch, how
they are presented, or what they can do derives that knowledge from here.

``core.agents``, ``helpers.agent_types``, and ``constants`` remain the stable
public import surfaces for existing callers; they re-export or derive their
values from this module rather than declaring agent membership themselves.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from enum import StrEnum
from hashlib import sha256
from typing import Final, NotRequired, TypedDict

_TRAILING_CONTINUATION_SPACE: Final[str] = " "
_COMPACT_COMMAND: Final[str] = "/compact"
_ADD_DIR_FLAG: Final[str] = "--add-dir"
_FLAG_SEPARATOR: Final[str] = " "
_GEMINI_SANDBOX_FLAG: Final[str] = "--sandbox"
_CLAUDE_HELP_DESK_PROFILE_FLAGS: Final[str] = "--setting-sources '' --strict-mcp-config --tools Bash,Read,Glob,Grep"
_CLAUDE_RESTRICTED_DESK_PROFILE_FLAGS: Final[str] = f"{_CLAUDE_HELP_DESK_PROFILE_FLAGS} --disable-slash-commands"
_CLAUDE_NATIVE_SESSION_ID_ENV: Final[str] = "CLAUDE_CODE_SESSION_ID"
_CODEX_NATIVE_SESSION_ID_ENV: Final[str] = "CODEX_THREAD_ID"
_CLAUDE_DISCORD_AVATAR_URL: Final[str] = "https://avatars.githubusercontent.com/u/81847?v=4"
_CODEX_DISCORD_AVATAR_URL: Final[str] = "https://avatars.githubusercontent.com/u/267193182?v=4"


class AgentName(StrEnum):
    """The closed set of AI agents TeleClaude can launch and dispatch to."""

    CLAUDE = "claude"
    CODEX = "codex"
    GEMINI = "gemini"
    DEEPSEEK = "deepseek"

    @classmethod
    def from_str(cls, value: str) -> AgentName:
        """Normalize a raw string, including declared aliases, to a canonical member.

        Raises ``ValueError`` for anything outside the canonical set and its
        declared aliases.
        """
        normalized = value.strip().lower()
        for member in cls:
            if member.value == normalized or normalized in AGENT_REGISTRY[member].aliases:
                return member
        raise ValueError(f"Unknown agent '{value}'")

    @classmethod
    def choices(cls) -> tuple[str, ...]:
        """Return all canonical agent names as a tuple of string values, in declared order."""
        return tuple(member.value for member in cls)

    @property
    def prompt_marker(self) -> str:
        """Return the TUI prompt marker used for readiness detection."""
        return AGENT_REGISTRY[self].prompt_marker

    @property
    def startup_signal(self) -> AgentStartupSignal:
        """Return the provider-declared authority for first-input admission."""
        return AGENT_REGISTRY[self].startup_signal

    @property
    def composer_control(self) -> ComposerControl:
        """Return the runtime's composer control and neutralization contract."""
        return AGENT_REGISTRY[self].composer_control

    @property
    def compaction_command(self) -> str | None:
        """Return the command typed into the composer to compact context, or ``None`` if undeclared."""
        return AGENT_REGISTRY[self].compaction_command

    @property
    def discord_presentation(self) -> DiscordAuthorPresentation:
        """Return the closed Discord webhook identity for this agent."""
        return AGENT_REGISTRY[self].discord

    @property
    def git_identity(self) -> str | None:
        """Return the git ``--author`` value for this agent's GitHub bot identity.

        These are the vendors' own global GitHub bot accounts — public,
        stable, identical for every installation — so they are registry
        constants, not configuration. ``config.agents[name].git_identity``
        (an internal-tier, non-operator-editable field) is always populated
        from this exact value via ``constants.GIT_AUTHOR_IDENTITIES``; there
        is no override path, so reading it directly here is equivalent and
        keeps this property statically visible on the enum instead of a
        runtime-only patch. Returns ``None`` only if a canonical member ever
        carried no registry entry, which construction of ``AGENT_REGISTRY``
        makes structurally impossible today.
        """
        return AGENT_REGISTRY[self].git_identity


class AgentStartupSignal(StrEnum):
    """Authority that can open an agent's first-input readiness gate."""

    NATIVE = "native"
    PANE = "pane"


class OneShotSupport(StrEnum):
    """Whether an agent supports schema-constrained structured one-shot calls."""

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"


class DeskConfinement(StrEnum):
    """Whether an agent has a verified launch profile that confines a help-desk session.

    ``VERIFIED`` means the agent declares a ``help_desk`` profile whose
    confinement (file reads, commands, startup context, native tool surfaces)
    was proven by a canary probe. ``NONE`` means it declares no such profile
    and is unavailable for desk sessions.
    """

    VERIFIED = "verified"
    NONE = "none"


class LaunchProfile(StrEnum):
    """The closed set of launch profiles an agent session can run under."""

    DEFAULT = "default"
    RESTRICTED = "restricted"
    HELP_DESK = "help_desk"


class CredentialCheckKind(StrEnum):
    """Closed set of mechanisms setup/preflight can dispatch a credential check by."""

    KEYCHAIN_SERVICE = "keychain_service"
    FILE_PRESENCE = "file_presence"
    KEYCHAIN_OR_FILE = "keychain_or_file"


@dataclass(frozen=True)
class DiscordAuthorPresentation:
    """Stable webhook presentation for a known agent author."""

    alias: str
    avatar_url: str


@dataclass(frozen=True)
class PaletteTiers:
    """Hex colors at each presentation tier for one theme mode."""

    subtle: str
    muted: str
    normal: str
    highlight: str


@dataclass(frozen=True)
class AgentPalette:
    """Dark- and light-mode color tiers for one agent."""

    dark: PaletteTiers
    light: PaletteTiers


class ModelChainEntryDict(TypedDict):
    """One fallback entry in a per-mode model chain."""

    model: str
    flags: NotRequired[str]
    patch: NotRequired[str]


class AgentProtocolDict(TypedDict):
    """Fixed launch contract for one supported agent runtime.

    The only user-configurable field derived from this at the config boundary
    is ``profiles`` (overlaid, never replaced wholesale) and ``model_chains``
    (operator-declared, defaulting to this contract's ``mode_chains``).
    """

    session_dir: str
    log_pattern: str
    session_root: str
    session_pattern: str
    profiles: dict[str, str]
    mode_chains: dict[str, list[ModelChainEntryDict]]
    exec_subcommand: str
    interactive_flag: str
    non_interactive_flag: str
    resume_template: str
    continue_template: str
    prompt_at_launch: bool
    model_via_launch_patch: bool
    restricted_sandbox_mode: str


@dataclass(frozen=True)
class AgentExecutable:
    """Platform-specific binary resolution for one agent's CLI.

    ``macos_launcher_app`` is always installed on macOS for TCC/Full-Disk-Access
    identity stability (`sdlc/procedure/macos-stable-code-signing`).
    ``macos_launch_binary`` is the binary inside that bundle actually invoked at
    launch time; when it is ``None``, the bundle is installed but launch still
    resolves ``unix_binary`` directly (the Gemini/Antigravity case today: the CLI
    reads its own Keychain-backed credentials and is invoked as ``agy`` on every
    platform).
    """

    unix_binary: str
    macos_launcher_app: str
    macos_launch_binary: str | None


@dataclass(frozen=True)
class LauncherBuildSpec:
    """Swift launcher-wrapper build parameters for one agent (``src/Launcher/build.sh``).

    ``fixed_candidates`` carries only host-independent fallback paths; a
    genuinely host-computed candidate (DeepSeek's ``npm prefix -g`` bin) stays
    a build-time computation in the shell script, prepended to this list.
    """

    display_name: str
    launcher_binary: str
    override_env_keys: tuple[str, ...]
    fixed_candidates: tuple[str, ...]
    override_strict: bool
    strict_exit_code: int
    version: str


@dataclass(frozen=True)
class CredentialCheck:
    """How managed-runner preflight verifies one agent's credentials are usable."""

    kind: CredentialCheckKind
    login_hint: str
    keychain_services: tuple[str, ...] = ()
    file_path: str = ""


@dataclass(frozen=True)
class AgentDefinition:
    """Everything the platform knows about one canonical agent."""

    key: AgentName
    aliases: tuple[str, ...]
    prompt_marker: str
    composer_control: ComposerControl
    startup_signal: AgentStartupSignal
    discord: DiscordAuthorPresentation
    git_identity: str
    protocol: AgentProtocolDict
    palette: AgentPalette
    executable: AgentExecutable
    launcher_build: LauncherBuildSpec
    credential_check: CredentialCheck
    one_shot: OneShotSupport
    desk_confinement: DeskConfinement
    launch_environment: tuple[tuple[str, str], ...] = ()
    # The command typed into the composer to compact the agent's context.
    # Completion is observed through the agent's ``PostCompact`` hook with a
    # manual trigger, normalized to ``agent_idle``. ``None`` means the agent
    # declares no compaction, so its conversation sessions are never idle-closed.
    compaction_command: str | None = None
    # Private base profile flags used only while the daemon submits the declared
    # compaction command. This is separate from operator-editable profiles.
    compaction_launch_flags: str | None = None
    # The environment variable through which the runtime exports its own native
    # session id to the tool processes it spawns. ``None`` means the runtime
    # exports none, so a tool process cannot name the session it runs in.
    native_session_id_env: str | None = None


@dataclass(frozen=True)
class ComposerControl:
    """Paste-sensitive characters and submission marks for one runtime."""

    control_characters: tuple[str, ...]
    neutralizing_mark: str
    trailing_continuation_mark: str | None


def agent_permutation(*order: AgentName) -> tuple[str, ...]:
    """Validate a full permutation of the canonical roster and return its string values.

    Fails at import time (call sites declare these as module-level constants)
    when the order omits or repeats a member, so a future fifth agent breaks
    every hand-declared role order immediately rather than silently degrading
    to a three-agent-shaped policy. Membership is all this constructor proves;
    it deliberately does not — and cannot — validate *which* permutation is
    correct for a given role, since a swap of two members is equally a full
    permutation. Role fitness stays a policy decision at the call site.
    """
    seen = tuple(order)
    if len(seen) != len(set(seen)):
        raise ValueError(f"Agent order must not repeat members: {seen}")
    if frozenset(seen) != frozenset(AgentName):
        missing = frozenset(AgentName) - frozenset(seen)
        extra = frozenset(seen) - frozenset(AgentName)
        raise ValueError(
            f"Agent order must be a full permutation of {tuple(AgentName)}: missing={sorted(missing)} extra={sorted(extra)}"
        )
    return tuple(member.value for member in seen)


def _mount_flags(restricted_mount_dirs: tuple[str, ...]) -> str:
    return _FLAG_SEPARATOR.join(f"{_ADD_DIR_FLAG}{_FLAG_SEPARATOR}{d}" for d in restricted_mount_dirs)


_DEEPSEEK_LAUNCH_ENVIRONMENT: tuple[tuple[str, str], ...] = (("DSH_TUI_NO_LAUNCHPAD", "1"),)


def _build_definitions(restricted_mount_dirs: tuple[str, ...]) -> dict[AgentName, AgentDefinition]:
    """Assemble the immutable per-agent records from the platform's fixed facts."""
    claude_mount = _mount_flags(restricted_mount_dirs)
    gemini_mount = _mount_flags(restricted_mount_dirs)
    codex_mount = _mount_flags(restricted_mount_dirs)

    return {
        AgentName.CLAUDE: AgentDefinition(
            key=AgentName.CLAUDE,
            aliases=(),
            prompt_marker="\u276f",
            composer_control=ComposerControl(("!", "/"), "\u00a0", _TRAILING_CONTINUATION_SPACE),
            startup_signal=AgentStartupSignal.NATIVE,
            discord=DiscordAuthorPresentation(
                alias="Claude",
                avatar_url=_CLAUDE_DISCORD_AVATAR_URL,
            ),
            git_identity="claude[bot] <209825114+claude[bot]@users.noreply.github.com>",
            protocol={
                "session_dir": "~/.claude/sessions",
                "log_pattern": "*.jsonl",
                "session_root": "~/.claude/projects",
                "session_pattern": "*/*.jsonl",
                "profiles": {
                    "default": ('--dangerously-skip-permissions --settings \'{"forceLoginMethod": "claudeai"}\''),
                    "restricted": (
                        "--strict-mcp-config"
                        f' --settings \'{{"forceLoginMethod": "claudeai", "enabledMcpjsonServers": []}}\''
                        f" {claude_mount}"
                    ),
                    # Static half of the desk confinement: no user, project or
                    # local settings source, no MCP and no extra tools. The
                    # launch settings (permission mode, read fence, allow list,
                    # instruction selection, bundled-skill exclusion, hooks) and
                    # the session's own upload root are rendered per launch.
                    LaunchProfile.HELP_DESK: _CLAUDE_RESTRICTED_DESK_PROFILE_FLAGS,
                },
                "mode_chains": {
                    "fast": [{"model": "sonnet", "flags": "--model 'claude-haiku-5-5[1m]' --effort medium"}],
                    "med": [{"model": "sonnet", "flags": "--model 'claude-sonnet-5-5[1m]' --effort high"}],
                    "slow": [
                        # disabled as too expensive and reserved for manual invocation:
                        # {"model": "fable", "flags": "--model 'claude-fable-5-1[1m]' --effort high"},
                        {"model": "opus", "flags": "--model 'claude-opus-5-5[1m]' --effort high"},
                    ],
                    "default": [],
                },
                "exec_subcommand": "",
                "interactive_flag": "",
                "non_interactive_flag": "-p",
                "resume_template": "{base_cmd} --resume {session_id}",
                "continue_template": "{base_cmd} --continue",
                "prompt_at_launch": False,
                "model_via_launch_patch": False,
                "restricted_sandbox_mode": "",
            },
            palette=AgentPalette(
                dark=PaletteTiers(subtle="#875f00", muted="#af875f", normal="#d7af87", highlight="#ffffff"),
                light=PaletteTiers(subtle="#d7af87", muted="#af875f", normal="#875f00", highlight="#000000"),
            ),
            executable=AgentExecutable(
                unix_binary="claude",
                macos_launcher_app="ClaudeLauncher.app",
                macos_launch_binary="claude-launcher",
            ),
            launcher_build=LauncherBuildSpec(
                display_name="ClaudeLauncher",
                launcher_binary="claude-launcher",
                override_env_keys=("CLAUDE_PATH",),
                fixed_candidates=(),
                override_strict=True,
                strict_exit_code=1,
                version="1.0",
            ),
            credential_check=CredentialCheck(
                kind=CredentialCheckKind.KEYCHAIN_SERVICE,
                login_hint="run 'claude login' from a GUI terminal session",
                keychain_services=("Claude Code-credentials",),
            ),
            one_shot=OneShotSupport.SUPPORTED,
            desk_confinement=DeskConfinement.VERIFIED,
            compaction_command=_COMPACT_COMMAND,
            compaction_launch_flags=_CLAUDE_HELP_DESK_PROFILE_FLAGS,
            native_session_id_env=_CLAUDE_NATIVE_SESSION_ID_ENV,
        ),
        AgentName.CODEX: AgentDefinition(
            key=AgentName.CODEX,
            aliases=(),
            prompt_marker="\n\u203a ",
            composer_control=ComposerControl(("!", "/"), "\u200b", None),
            startup_signal=AgentStartupSignal.PANE,
            discord=DiscordAuthorPresentation(
                alias="Codex",
                avatar_url=_CODEX_DISCORD_AVATAR_URL,
            ),
            git_identity=(
                "chatgpt-codex-connector[bot] <199175422+chatgpt-codex-connector[bot]@users.noreply.github.com>"
            ),
            protocol={
                "session_dir": "~/.codex/sessions",
                "log_pattern": "*.jsonl",
                "session_root": "~/.codex/sessions",
                "session_pattern": "**/*.jsonl",
                "profiles": {
                    "default": "--dangerously-bypass-approvals-and-sandbox --search",
                    "restricted": f"--search {codex_mount}",
                },
                "mode_chains": {
                    "fast": [
                        {
                            "model": "luna",
                            "flags": (
                                "-m gpt-6-luna -c model_reasoning_effort='medium'"
                                " -c model_auto_compact_token_limit=900000 -c model_context_window=1000000"
                            ),
                        }
                    ],
                    "med": [
                        {
                            "model": "terra",
                            "flags": (
                                "-m gpt-6.1-terra -c model_reasoning_effort='high'"
                                " -c model_auto_compact_token_limit=900000 -c model_context_window=1000000"
                            ),
                        }
                    ],
                    "slow": [
                        # disabled as too expensive and reserved for manual invocation:
                        # {
                        #     "model": "astra",
                        #     "flags": (
                        #         "-m gpt-6-astra -c model_reasoning_effort='high'"
                        #         " -c model_auto_compact_token_limit=900000 -c model_context_window=1000000"
                        #     ),
                        # },
                        {
                            "model": "sol",
                            "flags": (
                                "-m gpt-6.1-sol -c model_reasoning_effort='high'"
                                " -c model_auto_compact_token_limit=900000 -c model_context_window=1000000"
                            ),
                        },
                    ],
                    "default": [],
                },
                "exec_subcommand": "exec",
                "interactive_flag": "",
                "non_interactive_flag": "",
                "resume_template": "{base_cmd} resume {session_id}",
                "continue_template": "{base_cmd} resume --last",
                "prompt_at_launch": False,
                "model_via_launch_patch": False,
                "restricted_sandbox_mode": "",
            },
            palette=AgentPalette(
                dark=PaletteTiers(subtle="#5f87af", muted="#87afd7", normal="#afd7ff", highlight="#ffffff"),
                light=PaletteTiers(subtle="#87afd7", muted="#5f87af", normal="#005f87", highlight="#000000"),
            ),
            executable=AgentExecutable(
                unix_binary="codex",
                macos_launcher_app="CodexLauncher.app",
                macos_launch_binary="codex-launcher",
            ),
            launcher_build=LauncherBuildSpec(
                display_name="CodexLauncher",
                launcher_binary="codex-launcher",
                override_env_keys=("CODEX_PATH",),
                fixed_candidates=(),
                override_strict=False,
                strict_exit_code=127,
                version="1.0",
            ),
            credential_check=CredentialCheck(
                kind=CredentialCheckKind.FILE_PRESENCE,
                login_hint="run 'codex auth login'",
                file_path="~/.codex/auth.json",
            ),
            one_shot=OneShotSupport.SUPPORTED,
            desk_confinement=DeskConfinement.NONE,
            compaction_command=_COMPACT_COMMAND,
            native_session_id_env=_CODEX_NATIVE_SESSION_ID_ENV,
        ),
        AgentName.GEMINI: AgentDefinition(
            key=AgentName.GEMINI,
            aliases=("agy",),
            prompt_marker=">",
            composer_control=ComposerControl(("!", "/"), "\u200b", _TRAILING_CONTINUATION_SPACE),
            startup_signal=AgentStartupSignal.PANE,
            discord=DiscordAuthorPresentation(
                alias="Gemini",
                avatar_url="https://avatars.githubusercontent.com/u/218312386?v=4",
            ),
            git_identity="gemini-cli[bot] <218312386+gemini-cli[bot]@users.noreply.github.com>",
            protocol={
                "session_dir": "~/.gemini/antigravity-cli/brain",
                "log_pattern": "*/.system_generated/logs/transcript.jsonl",
                "session_root": "~/.gemini/antigravity-cli/brain",
                "session_pattern": "*/.system_generated/logs/transcript.jsonl",
                "profiles": {
                    "default": "--dangerously-skip-permissions",
                    LaunchProfile.RESTRICTED: f"{_GEMINI_SANDBOX_FLAG}{_FLAG_SEPARATOR}{gemini_mount}",
                },
                "mode_chains": {
                    "fast": [{"model": "gemini", "flags": "--model 'Gemini 3.8 Flash (Low)'"}],
                    "med": [{"model": "gemini", "flags": "--model 'Gemini 3.8 Flash (Medium)'"}],
                    "slow": [{"model": "gemini", "flags": "--model 'Gemini 3.8 Flash (High)'"}],
                    "default": [],
                },
                "exec_subcommand": "",
                "interactive_flag": "",
                "non_interactive_flag": "-p",
                "resume_template": "{base_cmd} --conversation {session_id}",
                "continue_template": "{base_cmd} --continue",
                "prompt_at_launch": False,
                "model_via_launch_patch": False,
                "restricted_sandbox_mode": "",
            },
            palette=AgentPalette(
                dark=PaletteTiers(subtle="#8787af", muted="#af87ff", normal="#d7afff", highlight="#ffffff"),
                light=PaletteTiers(subtle="#d787ff", muted="#af5fff", normal="#870087", highlight="#000000"),
            ),
            executable=AgentExecutable(
                unix_binary="agy",
                macos_launcher_app="GeminiLauncher.app",
                macos_launch_binary=None,
            ),
            launcher_build=LauncherBuildSpec(
                display_name="GeminiLauncher",
                launcher_binary="gemini-launcher",
                override_env_keys=("GEMINI_PATH",),
                fixed_candidates=(),
                override_strict=False,
                strict_exit_code=127,
                version="1.0",
            ),
            credential_check=CredentialCheck(
                kind=CredentialCheckKind.KEYCHAIN_OR_FILE,
                login_hint="run 'agy auth login' from a GUI terminal session",
                keychain_services=("Antigravity CLI-credentials", "Antigravity-credentials"),
                file_path="~/.gemini/oauth_creds.json",
            ),
            one_shot=OneShotSupport.SUPPORTED,
            desk_confinement=DeskConfinement.NONE,
        ),
        AgentName.DEEPSEEK: AgentDefinition(
            key=AgentName.DEEPSEEK,
            aliases=(),
            # DeepSeek Harness TUI renders its input prompt as the U+276F glyph
            # (heavy right-pointing angle quotation mark, the same prompt char
            # as Claude) when idle; the daemon's tmux readiness detection
            # watches for it before typing the prompt.
            prompt_marker="\u276f",
            composer_control=ComposerControl(("!", "/"), "\u200b", None),
            startup_signal=AgentStartupSignal.PANE,
            discord=DiscordAuthorPresentation(
                alias="DeepSeek",
                avatar_url="https://github.com/deepseek-ai.png",
            ),
            # Placeholder until DeepSeek publishes a verified bot account (none
            # exists as of 2026-08 — no deepseek-ai[bot] GitHub user is
            # registered); decided by the human for the DSH integration.
            # Replace once a vendor bot exists.
            git_identity="deepseek <noreply@deepseek.co>",
            protocol={
                "session_dir": "~/.dsh/sessions",
                "log_pattern": "session.jsonl*",
                "session_root": "~/.dsh/sessions",
                "session_pattern": "**/session.jsonl*",
                "profiles": {
                    "default": "--profile dsh-tui",
                    # Restricted: same launch; the sandbox override is merged
                    # into the dynamically generated per-launch patch
                    # (workspace-write resolves its root from the session cwd,
                    # jailing the agent to its PWD).
                    "restricted": "--profile dsh-tui",
                },
                # The mode mapping is a parameter table: `model` is a display
                # label, `flags` stay CLI flags, and `patch` carries a JSON map
                # of loader-id -> config for the per-launch overlay (dsh has no
                # model CLI flag; the patch's model ids are the API's full
                # ids). The patch is generated per launch, written to the
                # session tmpdir, applied via `--patch`, and discarded with the
                # session — never a static file.
                "mode_chains": {
                    "fast": [
                        {
                            "model": "v4-flash",
                            "patch": (
                                '{"agent-default-model": {"provider": "deepseek-official",'
                                ' "model": "deepseek-v4-flash", "reasoningEffort": "low"}}'
                            ),
                        }
                    ],
                    "med": [
                        {
                            "model": "v4-pro",
                            "patch": (
                                '{"agent-default-model": {"provider": "deepseek-official",'
                                ' "model": "deepseek-v4-pro", "reasoningEffort": "high"}}'
                            ),
                        }
                    ],
                    "slow": [
                        {
                            "model": "v4-pro",
                            "patch": (
                                '{"agent-default-model": {"provider": "deepseek-official",'
                                ' "model": "deepseek-v4-pro", "reasoningEffort": "max"}}'
                            ),
                        }
                    ],
                    "default": [],
                },
                "exec_subcommand": "",
                "interactive_flag": "",
                "non_interactive_flag": "",
                "resume_template": "{base_cmd} --resume {session_id}",
                "continue_template": "",
                "prompt_at_launch": False,
                "model_via_launch_patch": True,
                # Merged into the per-launch patch when the restricted profile
                # is used (workspace-write resolves its root from the session
                # cwd, jailing the agent to its PWD).
                "restricted_sandbox_mode": "workspace-write",
            },
            palette=AgentPalette(
                dark=PaletteTiers(subtle="#3b4a8a", muted="#7582cf", normal="#9babfb", highlight="#ffffff"),
                light=PaletteTiers(subtle="#6d7fe0", muted="#4d6bfe", normal="#2f4ad0", highlight="#000000"),
            ),
            executable=AgentExecutable(
                unix_binary="dsh",
                macos_launcher_app="DeepSeekLauncher.app",
                macos_launch_binary="deepseek-launcher",
            ),
            launcher_build=LauncherBuildSpec(
                display_name="DeepSeekLauncher",
                launcher_binary="deepseek-launcher",
                override_env_keys=("DSH_PATH",),
                fixed_candidates=("/opt/homebrew/bin/dsh", "/usr/local/bin/dsh"),
                override_strict=False,
                strict_exit_code=127,
                version="1.0",
            ),
            credential_check=CredentialCheck(
                kind=CredentialCheckKind.FILE_PRESENCE,
                login_hint="run 'dsh auth login' (or the harness's configured login flow)",
                file_path="~/.dsh/.credentials.yaml",
            ),
            # dsh has no schema-constrained structured-output mode today; a
            # one-shot call must be refused explicitly rather than dispatched
            # into a spec table with no entry for it.
            one_shot=OneShotSupport.UNSUPPORTED,
            desk_confinement=DeskConfinement.NONE,
            launch_environment=_DEEPSEEK_LAUNCH_ENVIRONMENT,
        ),
    }


# Directories mounted into restricted (sandboxed) agent profiles. Declared
# here (rather than imported from `constants`) to keep this module free of
# internal TeleClaude dependencies; `constants.RESTRICTED_MOUNT_DIRS`
# re-exports this value for any other consumer.
_LOG_STATE_ROOT = f"{os.environ.get('XDG_STATE_HOME') or os.path.expanduser('~/.local/state')}/instrukt-ai"  # fmt: skip  # guard: direct-env-read - allowed: ambient host or terminal state
RESTRICTED_MOUNT_DIRS: tuple[str, ...] = ("~/.teleclaude/docs", _LOG_STATE_ROOT)

_PROFILES_KEY: Final = "profiles"
_VERIFIED_WITHOUT_DESK_PROFILE = "Agent '{agent}' declares a verified desk confinement but has no '{profile}' profile"
_UNVERIFIED_WITH_DESK_PROFILE = "Agent '{agent}' declares no desk confinement but has a '{profile}' profile"


def _validate_desk_confinement(definitions: dict[AgentName, AgentDefinition]) -> dict[AgentName, AgentDefinition]:
    """Fail at import when a desk confinement declaration and its profile disagree."""
    for name, definition in definitions.items():
        has_profile = LaunchProfile.HELP_DESK in definition.protocol[_PROFILES_KEY]
        verified = definition.desk_confinement is DeskConfinement.VERIFIED
        if verified != has_profile:
            template = _VERIFIED_WITHOUT_DESK_PROFILE if verified else _UNVERIFIED_WITH_DESK_PROFILE
            raise ValueError(template.format(agent=name.value, profile=LaunchProfile.HELP_DESK.value))
    return definitions


AGENT_REGISTRY: dict[AgentName, AgentDefinition] = _validate_desk_confinement(_build_definitions(RESTRICTED_MOUNT_DIRS))


def native_session_id_env_names() -> tuple[str, ...]:
    """Return the environment variables through which runtimes export their native session id."""
    return tuple(
        definition.native_session_id_env
        for definition in AGENT_REGISTRY.values()
        if definition.native_session_id_env is not None
    )


def registry_digest() -> str:
    """Return a stable short digest identifying the current agent roster.

    Hashes every field of every canonical agent's record — protocol,
    palette, credential check, launcher build, one-shot capability, and
    identity data, not just membership — so observation records can trust
    it as a correlation token proving which registry revision produced a
    given decision. ``default=str`` renders enum members by their
    ``StrEnum`` value (e.g. ``"native"``, not ``"AgentStartupSignal.NATIVE"``).
    """
    payload = json.dumps(
        {name.value: asdict(AGENT_REGISTRY[name]) for name in sorted(AGENT_REGISTRY, key=str)},
        sort_keys=True,
        default=str,
    )
    return sha256(payload.encode("utf-8")).hexdigest()[:12]
