"""Shared result model and command-line entry point for runtime acceptance."""

from __future__ import annotations

import argparse
import difflib
import fcntl
import hashlib
import http.client
import json
import math
import os
import platform
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from types import FrameType
from typing import Final, cast

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci import acceptance_work as payload_work
from tools.ci import workflow_claim as claim
from tools.ci import workflow_creation as creation
from tools.ci import workflow_events as events
from tools.ci import workflow_flow as full_flow
from tools.ci import workflow_foundation as foundation
from tools.ci import workflow_holds as holds
from tools.ci import workflow_integration as integration
from tools.ci import workflow_plans as plans
from tools.ci import workflow_prepared as prepared
from tools.ci import workflow_race as race
from tools.ci import workflow_ready as ready
from tools.ci import workflow_removal as removal
from tools.ci import workflow_review as review
from tools.ci import workflow_waiting as waiting
from tools.ci.enclosure_contract import Action, JsonObject, StaticPackage, parse_object, positive_integer
from tools.ci.enclosure_exchange import run_helper
from tools.ci.enclosure_guest import GuestContext, Purpose, Role, request_guest_poweroff
from tools.ci.enclosure_guest import Record as GuestShutdownRecord
from tools.ci.enclosure_inner import (
    PROVISIONAL_REPORT_SCHEMA,
    PROVISIONAL_STAGE,
    InnerCleanupEvidence,
    PayloadProvisional,
    PhysicalCleanupPending,
)
from tools.ci.enclosure_journal import Outcome as EnclosureOutcome
from tools.ci.enclosure_report import (
    validate_early_inputs,
    validate_event_inputs,
    validate_flow_session_closure,
    validate_flow_start_inputs,
    validate_provisional_bindings,
    validate_provisional_cleanup,
)
from tools.ci.enclosure_setup import run_guest_setup
from tools.ci.terminal import PersistentTerminal, TerminalFailure

_UTF8 = "utf-8"
_ENCLOSURE_ROLE_OPTION = "--enclosure-role"
_ENCLOSURE_MANIFEST_OPTION = "--enclosure-manifest"
_ENCLOSURE_ACTION_OPTION = "--enclosure-action"
_OBSERVATION_KEY_OPTION = "--observation-key"
_ENCLOSURE_MANIFEST_REQUIRED = "An enclosure role requires its protected manifest."
_ENCLOSURE_ACTION_ROLE = "An enclosure action belongs only to the privileged role."
_ENCLOSURE_ACTION_REQUIRED = "The privileged role requires its closed enclosure action."
_PROFILE_ARGUMENTS_REQUIRED = "Profile execution requires profile, source-revision and source-tree."
_ENCLOSED_FULL_REQUIRED = "Supervisor and payload roles require the full profile."
_ENCLOSURE_UNAVAILABLE = "The selected enclosure role is not yet implemented: {role}"
_ENCLOSURE_ENTRY_FAILED = "Enclosure entry failed: {error_class}: {detail}"
_ENCLOSURE_REQUIRED = "Full-profile product work requires the admitted guest payload binding."
_REPORT_SCHEMA_VERSION = 3
_DEFAULT_ROOT = "."
_REPORT_TEMP_SUFFIX = ".tmp"
_LINE_BREAK = "\n"
_ENVIRONMENT_CACHE_DIRECTORY = "teleclaude-runtime-acceptance"
_ENVIRONMENT_LOCK_SUFFIX = ".lock"
_ENVIRONMENT_MANIFESTS = ("pyproject.toml", "uv.lock", ".python-version")
_ENVIRONMENT_REQUIRED_MANIFESTS = ("pyproject.toml", "uv.lock")
_ENVIRONMENT_GROUPS = "runtime-only"
_UV_EXECUTABLE = "uv"
_UV_SYNC_COMMAND = "sync"
_UV_PROJECT_OPTION = "--project"
_UV_LOCKED_OPTION = "--locked"
_UV_NO_INSTALL_PROJECT_OPTION = "--no-install-project"
_UV_NO_DEFAULT_GROUPS_OPTION = "--no-default-groups"
_ENVIRONMENT_VARIABLE = "UV_PROJECT_ENVIRONMENT"
_UV_NO_SYNC_VARIABLE = "UV_NO_SYNC"
_UV_CACHE_VARIABLE = "UV_CACHE_DIR"
_COLD_HOME_VARIABLE = "HOME"
_TELECLAUDE_HOME_VARIABLE = "TELECLAUDE_HOME"
_PYTHON_PATH_VARIABLE = "PYTHONPATH"
_NO_BYTECODE_VARIABLE = "PYTHONDONTWRITEBYTECODE"
_NO_USER_SITE_VARIABLE = "PYTHONNOUSERSITE"
_XDG_STATE_VARIABLE = "XDG_STATE_HOME"
_XDG_CACHE_VARIABLE = "XDG_CACHE_HOME"
_XDG_CONFIG_VARIABLE = "XDG_CONFIG_HOME"
_XDG_DATA_VARIABLE = "XDG_DATA_HOME"
_TMP_VARIABLE = "TMPDIR"
_GIT_CONFIG_GLOBAL_VARIABLE = "GIT_CONFIG_GLOBAL"
_GIT_CONFIG_SYSTEM_VARIABLE = "GIT_CONFIG_SYSTEM"
_GIT_CONFIG_SYSTEM_DISABLED_VARIABLE = "GIT_CONFIG_NOSYSTEM"
_LOCALE_VARIABLE = "LANG"
_PATH_VARIABLE = "PATH"
_NO_COLOR_VARIABLE = "NO_COLOR"
_CONFIG_FILENAME = "config.yml"
_PROCEDURE_DELIVERY_FIXTURE = Path("tools/ci/fixtures/procedure_event_delivery.json")
_PROCEDURE_FIXTURE_DIRECTORY = Path("docs/global/general/procedure/runtime-acceptance-event-delivery")
_PROCEDURE_DEPENDENCY_FIXTURE_DIRECTORY = Path("docs/global/general/procedure/runtime-acceptance-event-handling")
_PROCEDURE_FIXTURE_HOME_PLACEHOLDER = "<HOME>"
_PROCEDURE_FIXTURE_INSTALL_MODULE = "teleclaude.entrypoints.install_publication"
_PROCEDURE_FIXTURE_MISSING_DEPENDENCY_ERROR = (
    "Entry procedure required read does not resolve to a readable published document:"
)
_PROCEDURE_FIXTURE_COMMIT_MESSAGE = "test: publish disposable runtime acceptance procedure fixtures"
_PROCEDURE_FIXTURE_GIT_AUTHOR = "Runtime Acceptance Fixture"
_PROCEDURE_FIXTURE_GIT_EMAIL = "runtime-acceptance@example.invalid"
_PROCEDURE_FIXTURE_CLONE_TIMEOUT_SECONDS = 60
_PROCEDURE_FIXTURE_PUBLICATION_TIMEOUT_SECONDS = 120
_PROCEDURE_FIXTURE_VALIDATION_TIMEOUT_SECONDS = 180
_PROCEDURE_FIXTURE_ENVIRONMENT = Path(".venv")
_PROCEDURE_FIXTURE_ENVIRONMENT_MISSING = "The checked source dependency environment is unavailable for its fixture."
_PROCEDURE_FIXTURE_TERMINAL_LINE_ENDING = "\r\n"
_PROCEDURE_FIXTURE_COMPANY_FIELD = "owner_company"
_PROCEDURE_FIXTURE_COMPANY_NAME_FIELD = "name"
_PROCEDURE_FIXTURE_COMPANY_SLUG_FIELD = "slug"
_PROCEDURE_FIXTURE_COMPANY_INVALID = "The procedure fixture has no synthetic owner company declaration."
_GIT_EXECUTABLE = "git"
_DOCS_GET_COMMAND = ("docs", "get")
_DOCS_CLOSURE_OPTION = "--closure"
_CLI_SNIPPET_BLOCK_SEPARATOR = "\n---\nid: "
_CLI_SNIPPET_ID_PREFIX = "id: "
_PROCEDURE_CLOSURE_SEQUENTIAL = "sequential"
_PROCEDURE_CLOSURE_BATCHED = "batched"
_PROCEDURE_CLOSURE_SNAPSHOT_DIFF_LIMIT = 2048
_PROCEDURE_CLOSURE_SNAPSHOT_DIFF_CONTEXT = 3
_PROCEDURE_CLOSURE_SNAPSHOT_DIFF_EXPECTED = "fixture-snapshot"
_PROCEDURE_CLOSURE_SNAPSHOT_DIFF_ACTUAL = "public-response"
_PROCEDURE_CLOSURE_SNAPSHOT_DIFF_TRUNCATION = "[snapshot diff truncated]"
_PROCEDURE_CLOSURE_SNAPSHOT_MISMATCH = "The normalized public response snapshot differs for {snippet_id}."
_PROCEDURE_REQUIRED_READS_HEADER = "## Required reads"
_PROCEDURE_MARKDOWN_H2_PREFIX = "## "
_OWNER_ESTABLISHMENT_MODULE = "teleclaude.entrypoints.macos_setup"
_CLI_EXECUTABLE = Path("bin") / "telec"
_CLI_HELP_ARGUMENTS = ("--help",)
_CLI_CODE_HELP_ARGUMENTS = ("code", "--help")
_CLI_VERSION_ARGUMENTS = ("version",)
_MODULE_HELP_ARGUMENTS = ("-P", "-m", _OWNER_ESTABLISHMENT_MODULE, "--help")
_UV_SYNC_TIMEOUT_SECONDS = 900
_COMMAND_TIMEOUT_SECONDS = 30
_PROCESS_TERMINATION_GRACE_SECONDS = 1
_SYNTHETIC_COMPUTER_NAME = "runtime-acceptance"
_SYNTHETIC_COMPUTER_USER = "runtime-acceptance"
_SYNTHETIC_COMPUTER_HOST = "runtime-acceptance.invalid"
_SYNTHETIC_AGENT = "claude"
_SYNTHETIC_RELEASE_CHANNEL = "alpha"
_UV_PROJECT_SUBCOMMAND = "run"
_UV_NO_SYNC_OPTION = "--no-sync"
_PYTHON_EXECUTABLE = "python"
_ARGUMENT_SEPARATOR = "--"
_EMPTY_BYTES = b""
_UTF8_REPLACEMENT = "replace"
_COMMAND_TIMEOUT_DETAIL = "The command exceeded its deadline."
_COMMAND_OUTPUT_LIMIT_DETAIL = "The command exceeded its output limit."
_ENVIRONMENT_INVALID = "The dependency-only environment generation is incomplete: {path}"
_ENVIRONMENT_SYNC_FAILED = "Could not prepare the locked dependency-only environment: {detail}"
_ENVIRONMENT_INPUT_MISSING = "The dependency environment input is missing: {path}"
_SCENARIO_COMMAND_FAILED = "A required public entry point did not return a non-empty successful result."
_PROCESS_LAUNCH_FAILED = "The required process could not be started."
_SCENARIO_COLD = "UC-RA1"
_SCENARIO_RUNTIME_READY = "UC-RA2"
_SCENARIO_OWNER_IDENTITY = "UC-RA3"
_SCENARIO_CONFIG_PATCH = "UC-RA4"
_SCENARIO_PROJECT_REGISTRATION = "UC-RA5"
_SCENARIO_JOB_SURFACE = "UC-RA6"
_SCENARIO_RESTART_PERSISTENCE = "UC-RA7"
_SCENARIO_NON_ADMIN_REFUSAL = "UC-RA8"
_SCENARIO_CLEANUP = "UC-RA9"
_SCENARIO_CANDIDATE_IDENTITY = "UC-RA10"
_SCENARIO_INVALID_CONFIG = "UC-RA11"
_SCENARIO_PROCEDURE_CLOSURE = "UC-RA12"
_SCENARIO_DELIVERY_VALIDATION = "UC-RA13"
_SCENARIO_ARCHIVED_HISTORY = "UC-RA14"
_SCENARIO_CURATION_REFUSAL = "UC-RA15"
_SCENARIO_RELEASE_SELECTED = "UC-RC1"
_SCENARIO_RELEASE_PULL_REFUSED = "UC-RC2"
_SCENARIO_RELEASE_ADOPTION = "UC-CSU-8"
_SCENARIO_RELEASE_NEXT = "UC-RC3"
_SCENARIO_RELEASE_REPLAY = "UC-CSU-9"
_SCENARIO_RELEASE_UNSUPPORTED = "UC-CSU-11"
_SCENARIO_RELEASE_RECORDING = "UC-CSU-12"
_SCENARIO_RELEASE_CONFLICT = "UC-RC5"
_SCENARIO_RELEASE_DEVELOPMENT_CLONE = "UC-RC6"
_SCENARIO_RELEASE_DECLARATION = "UC-CFG-MIG-17"
_SCENARIO_RELEASE_PUBLICATION = "UC-SPO34"
_SCENARIO_RELEASE_BLUEPRINT = "UC-BPF1"
_SCENARIO_WORKFLOW_FOUNDATION = "UC-WF-F0"
_SCENARIO_WORKFLOW_CREATION = "UC-WF-R1"
_SCENARIO_WORKFLOW_RETIRED_ACTS = "UC-WF-R4"
_SCENARIO_WORKFLOW_RETIRED_ACTS_B12 = "UC-WF-B12"
_R4_SNAPSHOT_COMMANDS: Final = (
    (
        (creation.TODO, creation.STAMP, creation.SLUG_FEATURE, creation.BUILD_STARTED_FLAG),
        creation.RETIRED_SNAPSHOT_R4_CLEARANCE,
    ),
    (
        (creation.TODO, creation.STAMP, creation.SLUG_FEATURE, creation.PRD_APPROVED_FLAG),
        creation.RETIRED_SNAPSHOT_R4_PRD,
    ),
    (
        (
            creation.TODO,
            creation.STAMP,
            creation.SLUG_FEATURE,
            creation.KICKBACK_FLAG,
            creation.REASON_OPTION,
            creation.KICKBACK_REASON,
        ),
        creation.RETIRED_SNAPSHOT_R4_KICKBACK,
    ),
)
_SCENARIO_WORKFLOW_PLANS = "UC-WF-R2"
_SCENARIO_WORKFLOW_HOLDS = "UC-WF-R3"
_SCENARIO_WORKFLOW_REMOVAL = "UC-WF-R5"
_SCENARIO_WORKFLOW_CLAIM = "UC-WF-B1"
_SCENARIO_WORKFLOW_RACE = "UC-WF-B2"
_SCENARIO_WORKFLOW_WAITING = "UC-WF-B3"
_SCENARIO_WORKFLOW_PREPARED = "UC-WF-B4"
_SCENARIO_WORKFLOW_REVIEW = "UC-WF-B5"
_SCENARIO_WORKFLOW_READY = "UC-WF-B7"
_SCENARIO_WORKFLOW_INTEGRATION = "UC-WF-B6"
_COLD_PROFILE_SCENARIOS = (_SCENARIO_COLD,)
_FULL_PROFILE_SCENARIOS = (
    _SCENARIO_COLD,
    _SCENARIO_RUNTIME_READY,
    _SCENARIO_OWNER_IDENTITY,
    _SCENARIO_CONFIG_PATCH,
    _SCENARIO_PROJECT_REGISTRATION,
    _SCENARIO_JOB_SURFACE,
    _SCENARIO_RESTART_PERSISTENCE,
    _SCENARIO_NON_ADMIN_REFUSAL,
    _SCENARIO_CLEANUP,
    _SCENARIO_CANDIDATE_IDENTITY,
    _SCENARIO_INVALID_CONFIG,
    _SCENARIO_PROCEDURE_CLOSURE,
    _SCENARIO_DELIVERY_VALIDATION,
    _SCENARIO_ARCHIVED_HISTORY,
    _SCENARIO_CURATION_REFUSAL,
    _SCENARIO_RELEASE_SELECTED,
    _SCENARIO_RELEASE_PULL_REFUSED,
    _SCENARIO_RELEASE_ADOPTION,
    _SCENARIO_RELEASE_NEXT,
    _SCENARIO_RELEASE_REPLAY,
    _SCENARIO_RELEASE_UNSUPPORTED,
    _SCENARIO_RELEASE_RECORDING,
    _SCENARIO_RELEASE_CONFLICT,
    _SCENARIO_RELEASE_DEVELOPMENT_CLONE,
    _SCENARIO_RELEASE_DECLARATION,
    _SCENARIO_RELEASE_BLUEPRINT,
    _SCENARIO_RELEASE_PUBLICATION,
    _SCENARIO_WORKFLOW_FOUNDATION,
    _SCENARIO_WORKFLOW_CREATION,
    _SCENARIO_WORKFLOW_RETIRED_ACTS,
    _SCENARIO_WORKFLOW_RETIRED_ACTS_B12,
    _SCENARIO_WORKFLOW_PLANS,
    _SCENARIO_WORKFLOW_HOLDS,
    _SCENARIO_WORKFLOW_REMOVAL,
    _SCENARIO_WORKFLOW_CLAIM,
    _SCENARIO_WORKFLOW_RACE,
    _SCENARIO_WORKFLOW_WAITING,
    _SCENARIO_WORKFLOW_PREPARED,
    _SCENARIO_WORKFLOW_REVIEW,
    _SCENARIO_WORKFLOW_READY,
    _SCENARIO_WORKFLOW_INTEGRATION,
)
_SCENARIO_PREREQUISITES = {
    _SCENARIO_WORKFLOW_FOUNDATION: (
        _SCENARIO_RUNTIME_READY,
        _SCENARIO_CONFIG_PATCH,
        _SCENARIO_PROJECT_REGISTRATION,
    ),
    _SCENARIO_WORKFLOW_CREATION: (
        _SCENARIO_RUNTIME_READY,
        _SCENARIO_CONFIG_PATCH,
        _SCENARIO_PROJECT_REGISTRATION,
    ),
    _SCENARIO_WORKFLOW_RETIRED_ACTS: (
        _SCENARIO_RUNTIME_READY,
        _SCENARIO_CONFIG_PATCH,
        _SCENARIO_PROJECT_REGISTRATION,
        _SCENARIO_WORKFLOW_CREATION,
    ),
    _SCENARIO_WORKFLOW_RETIRED_ACTS_B12: (_SCENARIO_WORKFLOW_RETIRED_ACTS,),
    _SCENARIO_WORKFLOW_PLANS: (
        _SCENARIO_RUNTIME_READY,
        _SCENARIO_CONFIG_PATCH,
        _SCENARIO_PROJECT_REGISTRATION,
    ),
    _SCENARIO_WORKFLOW_HOLDS: (
        _SCENARIO_RUNTIME_READY,
        _SCENARIO_CONFIG_PATCH,
        _SCENARIO_PROJECT_REGISTRATION,
    ),
    _SCENARIO_WORKFLOW_REMOVAL: (
        _SCENARIO_RUNTIME_READY,
        _SCENARIO_CONFIG_PATCH,
        _SCENARIO_PROJECT_REGISTRATION,
    ),
    _SCENARIO_WORKFLOW_CLAIM: (
        _SCENARIO_RUNTIME_READY,
        _SCENARIO_CONFIG_PATCH,
        _SCENARIO_PROJECT_REGISTRATION,
        _SCENARIO_WORKFLOW_FOUNDATION,
    ),
    _SCENARIO_WORKFLOW_RACE: (
        _SCENARIO_RUNTIME_READY,
        _SCENARIO_CONFIG_PATCH,
        _SCENARIO_PROJECT_REGISTRATION,
        _SCENARIO_WORKFLOW_FOUNDATION,
    ),
    _SCENARIO_WORKFLOW_WAITING: (
        _SCENARIO_RUNTIME_READY,
        _SCENARIO_CONFIG_PATCH,
        _SCENARIO_PROJECT_REGISTRATION,
        _SCENARIO_WORKFLOW_FOUNDATION,
    ),
    _SCENARIO_WORKFLOW_PREPARED: (
        _SCENARIO_RUNTIME_READY,
        _SCENARIO_CONFIG_PATCH,
        _SCENARIO_PROJECT_REGISTRATION,
        _SCENARIO_WORKFLOW_FOUNDATION,
        _SCENARIO_WORKFLOW_WAITING,
    ),
    _SCENARIO_WORKFLOW_REVIEW: (
        _SCENARIO_RUNTIME_READY,
        _SCENARIO_CONFIG_PATCH,
        _SCENARIO_PROJECT_REGISTRATION,
        _SCENARIO_WORKFLOW_FOUNDATION,
        _SCENARIO_WORKFLOW_WAITING,
        _SCENARIO_WORKFLOW_PREPARED,
    ),
    _SCENARIO_WORKFLOW_READY: (_SCENARIO_WORKFLOW_REVIEW,),
    _SCENARIO_WORKFLOW_INTEGRATION: (_SCENARIO_WORKFLOW_READY,),
}
_PROFILE_COLD = "cold"
_PROFILE_FULL = "full"
_UNKNOWN_REVISION = "unknown"
_EMPTY = ""
_DIAGNOSTIC_LIMIT = 4096
_COMMAND_EVIDENCE_COMMANDS_FIELD = "commands"
_COMMAND_EVIDENCE_ARGV_FIELD = "argv"
_COMMAND_EVIDENCE_EXIT_STATUS_FIELD = "exit_status"
_COMMAND_EVIDENCE_STDOUT_FIELD = "stdout"
_COMMAND_EVIDENCE_DIAGNOSTICS_FIELD = "diagnostics"
_EVIDENCE_SEPARATOR = "\n"
_EVIDENCE_STDOUT_TRUNCATION = "stdout truncated at diagnostic limit"
_EVIDENCE_STDERR_TRUNCATION = "stderr truncated at diagnostic limit"
_EVIDENCE_DIAGNOSTICS_TRUNCATION = "diagnostics truncated at diagnostic limit"
_INSTALLER_LOG_PATH = Path("install.log")
_INSTALLER_LOG_LABEL = "Installer log (end): "
_INSTALLER_LOG_UNAVAILABLE = "Installer log unavailable ({error_class})."
_INSTALLER_LOG_TRUNCATION_MARKER = "[earlier installer log content omitted]\n"
_DIAGNOSTIC_SEPARATOR = "\n"
_BINARY_READ_MODE = "rb"
_PROFILE_OPTION = "--profile"
_REPORT_OPTION = "--report"
_SELECT_OPTION = "--select"
_SELECT_HELP = "Comma-separated scenario ids to run (with their prerequisites); the report is never a full pass."
_SELECTION_SEPARATOR = ","
_SELECTION_UNKNOWN = "Unknown scenario id in the selection: {scenario_id}"
_PARTIAL_PASSED = "PARTIAL: the selected scenarios passed; the full profile did not run and is not claimed."
_EXIT_PARTIAL = 2
_ROOT_OPTION = "--root"
_SOURCE_REVISION_OPTION = "--source-revision"
_SOURCE_TREE_OPTION = "--source-tree"
_CLI_DESCRIPTION = "Run the bounded real-process CLI acceptance profile."
_REPORT_WRITE_ERROR = "Could not write runtime acceptance report: {error}"
_REPORT_WRITE_INCOMPLETE = "The serialized report write was incomplete."
_REPORT_READBACK_MISMATCH = "The persisted report bytes differ from the complete serialized report."
_B13_REPORT_SEAL_FAILURE = "B13 report delivery seal failed."
_B13_REPORT_WRITE_FAILURE = "B13 report write failed: {error}"
_B13_REPORT_READBACK_FAILURE = "B13 report read-back failed: {error}"
_B13_FAILURE_SEPARATOR = "; "
_SCENARIO_NOT_RUN = "No scenario action was registered."
_FIXTURE_INSTALLER_WHERE = "the installer environment"
_FIXTURE_LOGIN_WHERE = "the owner login shell"
_LOGIN_PROFILE_NOTE = "owner-login-profile"
_MACHINE_WORKFLOW_SECTION = "workflow"
_MACHINE_WORKFLOW_RUNNER_FIELD = "runner"
_WORKFLOW_RUNNER_MANUAL = "manual"
_FULL_WORKFLOW_RUNNER_NOT_MANUAL = "The public machine configuration does not report workflow.runner=manual."
_FULL_FOUNDATION_PREREQUISITES = "Journey F0 needs the installed fixture and the registered disposable project."
_FULL_FIXTURE_CLEANUP_ERROR = "The installed native fixture could not be removed."
_SCENARIO_NOT_SELECTED = "Not selected for this run; the scenario was not executed."
_INTERRUPTED = "The profile was interrupted."
_SYNTHETIC_HOME_DIRECTORY = "home"
_SYNTHETIC_STATE_DIRECTORY = "state"
_SYNTHETIC_CACHE_DIRECTORY = "cache"
_SYNTHETIC_CONFIG_DIRECTORY = "config"
_SYNTHETIC_DATA_DIRECTORY = "data"
_SYNTHETIC_TEMP_DIRECTORY = "tmp"
_ENVIRONMENT_MANIFEST_FILENAME = "environment.json"
_OUTPUT_LIMIT = 65536
_PROCESS_SUCCESS = 0
_PROCESS_FAILURE = 1
_PROCESS_LAUNCH_EXIT_CODE = 127
_REPORT_NAME_TEMPLATE = "runtime-acceptance-{identifier}.json"
_REPORT_RETIRED_ACT_DELIVERY_PATH = "retired_act_delivery_path"
_B13_REPORT_EVIDENCE_FIELD = "workflow_waiting_retired_kickback_evidence"
_B13_REPORT_DELIVERY_PATH_FIELD = "workflow_waiting_retired_kickback_delivery_path"
_B13_REPORT_MARKER_DIRECTORY_FIELD = "workflow_waiting_retired_kickback_marker_directory"
_VENV_CONFIG_FILENAME = "pyvenv.cfg"
_PYTHON_DIRECTORY = "bin"
_PATH_SEPARATOR = os.pathsep
_SCENARIO_PUBLIC_RESULT = "The public command did not return a non-empty successful result."
_SOURCE_TREE_PLACEHOLDER = "<source-tree>"
_DEPENDENCY_ENVIRONMENT_PLACEHOLDER = "<dependency-environment>"
_SYNTHETIC_RUNTIME_PLACEHOLDER = "<synthetic-runtime>"
_RUNTIME_HOME_PLACEHOLDER = "<runtime-home>"
_DISPOSABLE_PROJECT_PLACEHOLDER = "<disposable-project>"
_ADMIN_ROLE = "admin"
_WHOAMI_EMAIL_FIELD = "Email"
_WHOAMI_ROLE_FIELD = "Role"
_WHOAMI_LABEL_SEPARATOR = ": "
_JOB_LIST_SCOPE_LOCAL = "local"
_JOB_STATUS_LAST_RUN_FIELD = "last_run"
_JOB_STATUS_STATE_FIELD = "status"
_JOB_STATUS_NEXT_DUE_FIELD = "next_due"
_JOB_STATUS_NEVER = "never"
_JOB_LINE_SEPARATOR = ": "
_JOB_FIELD_SEPARATOR = "; "
_JOB_VALUE_SEPARATOR = "="
_JOB_STATUS_FIELDS = frozenset({_JOB_STATUS_LAST_RUN_FIELD, _JOB_STATUS_STATE_FIELD, _JOB_STATUS_NEXT_DUE_FIELD})
_ROLE_SECTION = "roles"
_ROLE_PLATFORM_FIELD = "platform"
_PROJECTS_RESPONSE_FIELD = "projects"
_PROJECT_PATH_FIELD = "path"
_PROJECT_NAME_FIELD = "name"
_COMPUTER_IS_LOCAL_FIELD = "is_local"
_COMPUTER_NAME_FIELD = "name"
_COMPUTER_STATUS_FIELD = "status"
_READY_LOCAL_COMPUTER_SNAPSHOT = Path("snapshots") / "ready-local-computer.json"
_MEMBER_PATCH_REFUSAL_SNAPSHOT = Path("snapshots") / "member-computer-patch-refusal.txt"
_CURATION_REFUSALS_SNAPSHOT = Path("snapshots") / "curation-refusals.txt"
_EMPTY_MEMORY_LIST_SNAPSHOT = Path("snapshots") / "empty-memory-list.txt"
_PTY_LINE_ENDING = "\r\n"
_ARCHIVED_CONVERSATION_SNAPSHOT = Path("snapshots") / "archived-conversation.txt"
_INVALID_PATCH_REFUSAL_SNAPSHOT = Path("snapshots") / "invalid-computer-patch-refusal.txt"
_REFUSAL_REQUEST_PREFIX = " (request "
_REFUSAL_REQUEST_END = ")"
_REFUSAL_REQUEST_PLACEHOLDER = "<request-id>"
_ADMIN_TERMINAL_PURPOSE = "administrator"
_MEMBER_TERMINAL_PURPOSE = "non-administrator"
_PROJECT_CONFIG_REVISION_FIELD = "revision"
_PROJECT_CONFIG_JOBS_FIELD = "jobs"
_UNKNOWN_KEY_PATCH_VALUE = True
_EXPECTED_COMMAND_ERROR = "A required public command failed or exceeded its bound."
_EXPECTED_REFUSAL_ERROR = "A public refusal command unexpectedly succeeded."
_EXPECTED_REFUSAL_OUTPUT_ERROR = "A public refusal returned no explanation."
_EXPECTED_STATE_PRESERVATION_ERROR = "A refused operation changed the stored configuration."
_EXPECTED_VALID_PATCH_ERROR = "A valid public configuration patch did not persist its typed value."
_EXPECTED_REVISION_CHANGE_ERROR = "A committed configuration patch did not advance its revision."
_EXPECTED_PERSON_IDENTITY_ERROR = "The owner person record lacks platform administrator standing."
_EXPECTED_OWNER_WHOAMI_ERROR = "The fresh CLI process did not report the seeded administrator identity."
_EXPECTED_MEMBER_WHOAMI_ERROR = "The member terminal did not report the seeded non-administrator identity."
_EXPECTED_JOB_DISCOVERY_ERROR = "The inert declared job did not appear exactly once in its public list."
_EXPECTED_JOB_NEVER_RUN_ERROR = "The inert declared job did not report a never-run status."
_EXPECTED_COMMAND_REFUSAL_ERROR = "The member patch did not return the expected command-clearance refusal: {output}"
_EXPECTED_INVALID_KEY_ERROR = "The schema refusal did not match its safe public-output snapshot: {output}"
_INVALID_REFUSAL_SNAPSHOT_MISSING = (
    "The invalid-patch public-output snapshot has not been captured from a disposable runtime."
)
_EXPECTED_PROJECT_LIST_ERROR = "The daemon project listing omitted the disposable project."
_EXPECTED_COMPUTER_LIST_ERROR = "The daemon did not return a ready local computer."
_EXPECTED_READINESS_ERROR = "The supported lifecycle did not report a ready daemon in time."
_FULL_INSTALL_ERROR = "The supported installer failed in the disposable runtime."
_FULL_SERVICE_STOP_ERROR = "The supported lifecycle could not stop the disposable runtime."
_FULL_PROJECT_RESTORE_ERROR = "The supported config surface could not restore the project job declarations."
_FULL_UNPROVEN_RETAINED = (
    "Closure of the journey's actors is UNPROVEN, so the disposable home and fixture controls are retained: {reasons}"
)
_FULL_RETENTION_KEY_COLLISION = "A retention key was reused for a different reason."
_FULL_RETENTION_KEY_MISSING = "A retention key no longer owns its exact recorded reason."
_FULL_STOP_UNPROVEN = "the supported stop did not record that the services are down (outcome: {outcome})"
_STOP_OUTCOME_NAME = "stop-outcome"
_STOP_OUTCOME_VARIABLE = "STOP_OUTCOME_FILE"
_STOPPED_OUTCOME = "stopped"
_FULL_TEMP_CLEANUP_ERROR = "The disposable runtime temporary resources could not be removed."
_FULL_TERMINAL_SETUP_ERROR = "The owned PTY could not enter the checked source directory."
_CLEANUP_FAILURE_SEPARATOR = ", "
_SYNTHETIC_PATH_ENVIRONMENT_VARIABLES = (
    _COLD_HOME_VARIABLE,
    _TELECLAUDE_HOME_VARIABLE,
    _XDG_STATE_VARIABLE,
    _XDG_CACHE_VARIABLE,
    _XDG_CONFIG_VARIABLE,
    _XDG_DATA_VARIABLE,
    _TMP_VARIABLE,
)
_DEFAULT_LANGUAGE = "C.UTF-8"
_UV_NO_SYNC_VALUE = "1"
_PROCESS_FAILURE_DETAIL = "The command failed with exit status {exit_status}."
_PROCESS_TIMEOUT_DETAIL = "The command exceeded its deadline."
_PROCESS_OUTPUT_LIMIT_DETAIL = "The command exceeded the output limit."
_BASH_EXECUTABLE = "/bin/bash"
_BASH_NO_PROFILE_OPTION = "--noprofile"
_BASH_NO_RC_OPTION = "--norc"
_BASH_INTERACTIVE_OPTION = "-i"
_PROMPT_VARIABLE = "PS1"
_CONTINUATION_PROMPT_VARIABLE = "PS2"
_FULL_COMMAND_TIMEOUT_SECONDS = 60
_INSTALL_COMMAND_TIMEOUT_SECONDS = 3600
_START_COMMAND_TIMEOUT_SECONDS = 300
_RESTART_COMMAND_TIMEOUT_SECONDS = 300
_STOP_COMMAND_TIMEOUT_SECONDS = 120
_READINESS_WINDOW_SECONDS = 90
_READINESS_POLL_INTERVAL_SECONDS = 1
_HEALTH_OBSERVATION_TIMEOUT_SECONDS = 5
_HEALTH_SOCKET_PATH = "/tmp/teleclaude-api.sock"
_HEALTH_HTTP_REQUEST = b"GET /health HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
_HEALTH_RESPONSE_LIMIT_BYTES = 16384
_HEALTH_PREPARATION_FIELD = "preparation"
_HEALTH_PID_FIELD = "pid"
_HEALTH_TOKEN_FIELD = "token"
_HEALTH_INSTANCE_INVALID = "The public health response lacks a valid daemon instance."
_HEALTH_INSTANCE_UNCHANGED = "The configuration change did not produce a ready replacement daemon in time."
_OWNER_SEED_NAME = "runtime-acceptance-owner"
_OWNER_SEED_EMAIL = "runtime-acceptance-owner@probe.invalid"
_OWNER_SEED_SLUG = "runtime-acceptance-owner"
_MEMBER_NAME = "runtime-acceptance-member"
_MEMBER_EMAIL = "runtime-acceptance-member@probe.invalid"
_MEMBER_SLUG = "runtime-acceptance-member"
_MEMBER_ROLE = "member"
_PROJECT_NAME_PREFIX = "runtime-acceptance-project-"
_PROJECT_NAME_SUFFIX_LENGTH = 8
_EMAIL_OPTION = "--email"
_SLUG_OPTION = "--slug"
_ROLE_OPTION = "--role"
_PROJECT_PATH_OPTION = "--path"
_REVISION_OPTION = "--revision"
_YAML_OPTION = "--yaml"
_FORMAT_OPTION = "--format"
_JSON_FORMAT = "json"
_SHELL_CHANGE_DIRECTORY = "cd"
_TIMEZONE_UTC = "UTC"
_TIMEZONE_EUROPE_AMSTERDAM = "Europe/Amsterdam"
_FALSE_EXECUTABLE = "/usr/bin/false"
_SLEEP_EXECUTABLE = "/bin/sleep"
_TIMEOUT_PROBE_DURATION = "2"
_TIMEOUT_PROBE_SECONDS = 0.1
_FULL_HOME_REQUIRED = "The full profile requires the disposable VM's normal home directory."
_FULL_PROJECT_MISSING = "The disposable project was not created before the dependent journey."
_FULL_PROJECT_JOBS_NOT_EMPTY = "The fresh disposable project unexpectedly has pre-existing jobs."
_FULL_CONFIG_RESTORE_ERROR = "The public config surface could not restore disabled external adapters."
_FULL_TERMINAL_CLEANUP_ERROR = "An owned terminal session did not close cleanly."
_FULL_FAILURE_PROBE_FAILED = "A required failing or timed-out child process was not reported as failed."
_FULL_CANDIDATE_IDENTITY_INVALID = "The full profile lacks an exact source and tree identity."
_FULL_REPORT_INVALID = "The full runtime acceptance report is incomplete or does not match its candidate."
_JOB_INERT_NAME = "runtime-acceptance-inert"
_JOB_INERT_SCRIPT = "jobs/runtime_acceptance_inert.py"
_JOB_INERT_SCHEDULE = "365d"
_JOB_NAME_FIELD = "name"
_JOB_CATEGORY_FIELD = "category"
_JOB_ENABLED_FIELD = "enabled"
_JOB_SCHEDULE_FIELD = "when"
_JOB_INTERVAL_FIELD = "every"
_JOB_SCRIPT_FIELD = "script"
_JOB_SYSTEM_CATEGORY = "system"
_PROJECT_DIRECTORY_NAME = "disposable-project"
_JOBS_FIXTURE_DIRECTORY = "jobs"
_JOBS_FIXTURE_FILENAME = "runtime_acceptance_inert.py"
_PROJECT_CONFIG_SECTION = "project"
_MACHINE_REVISION_FIELD = "revision"
_REQUEST_ID_FIELD = "request_id"
_MACHINE_TIMEZONE_FIELD = "timezone"
_MACHINE_NAME_FIELD = "name"
_MACHINE_ADAPTER_SECTIONS = ("telegram", "discord", "whatsapp", "email", "tts", "stt")
_MACHINE_ADAPTER_ENABLED_FIELD = "enabled"
_INVALID_MACHINE_KEY = "runtime_acceptance_undeclared_key"
_NOTHING_TO_RESTORE = "No disposable configuration needs restoration."
_FULL_SETUP_FAILURE = "A required disposable runtime setup command failed."
_FULL_CLEANUP_FAILURE = "The disposable runtime did not settle its owned resources: {failures}"
_SERVICE_STATUS_COMMAND = ("make", "status")
_SERVICE_START_COMMAND = ("make", "start")
_SERVICE_STOP_COMMAND = ("make", "stop")
_SERVICE_RESTART_COMMAND = ("make", "restart")
_INSTALLER_COMMAND = ("bin/install.sh", "--yes")
_COMPUTERS_LIST_COMMAND = ("bin/telec", "computers", "list")
_PROJECTS_LIST_COMMAND = ("bin/telec", "projects", "list")
_CONFIG_COMPUTER_GET_COMMAND = ("bin/telec", "config", "computer", "get", "--format", "json")
_CONFIG_COMPUTER_PATCH_PREFIX = ("bin/telec", "config", "computer", "patch")
_CONFIG_PERSON_INIT_PREFIX = ("bin/telec", "config", "person", "init")
_CONFIG_PERSON_GET_PREFIX = ("bin/telec", "config", "person", "get")
_CONFIG_COMPANY_INIT_PREFIX = ("bin/telec", "config", "company", "init")
_CONFIG_PROJECT_CREATE_PREFIX = ("bin/telec", "config", "project", "create")
_CONFIG_PROJECT_GET_PREFIX = ("bin/telec", "config", "project", "get")
_CONFIG_PROJECT_PATCH_PREFIX = ("bin/telec", "config", "project", "patch")
_AUTH_LOGIN_PREFIX = ("bin/telec", "auth", "login")
_AUTH_WHOAMI_COMMAND = ("bin/telec", "auth", "whoami")
_AUTH_LOGOUT_COMMAND = ("bin/telec", "auth", "logout")
_HISTORY_SEARCH_PREFIX = ("bin/telec", "history", "search")
_HISTORY_SHOW_PREFIX = ("bin/telec", "history", "show")
_JSON_OPTION = "--json"
_MEMORIES_COMMAND_PREFIX = ("bin/telec", "memories")
_MEMORIES_LIST_COMMAND = (*_MEMORIES_COMMAND_PREFIX, "list")
_MESSAGE_COUNT_FIELD = "message_count"
_TELECLAUDE_ID_FIELD = "tc_id"
_CONVERSATION_TEXT_FIELD = "conversation_text"
_ARCHIVE_NATIVE_ID = "7f3c2a10-5b1d-4c8e-9a11-0d2e4f6a8b90"
_ARCHIVE_SEARCH_TERM = "runtimeacceptancearchive"
_ARCHIVE_PROJECT_DIRECTORY = "-runtime-acceptance-archive"
_ARCHIVE_TRANSCRIPT_ROOT = (".claude", "projects")
_ARCHIVE_ADOPTION_WINDOW_SECONDS = 120
_ARCHIVE_POLL_INTERVAL_SECONDS = 2
_MINIMUM_ARCHIVED_MESSAGES = 1
_ARCHIVE_USER_TURN = "Please remember the {term} marker in this conversation."
_ARCHIVE_ASSISTANT_TURN = "The {term} marker is noted."
_ARCHIVE_TRANSCRIPT_TIMESTAMPS = ("2026-01-01T10:00:00.000Z", "2026-01-01T10:00:05.000Z")
_CURATION_REFUSED_EXTRACTION = "00000000-0000-4000-8000-000000000000"
_CURATION_REFUSED_IDENTITY = f"person:{_OWNER_SEED_SLUG}"
_CURATION_REFUSED_TEXT = "runtime acceptance attempted memory"
_CURATION_REFUSED_COMMANDS = (
    ("scope", "--identity", _CURATION_REFUSED_IDENTITY),
    (
        "add",
        "--identity",
        _CURATION_REFUSED_IDENTITY,
        "--extraction",
        _CURATION_REFUSED_EXTRACTION,
        "--type",
        "preference",
        _CURATION_REFUSED_TEXT,
    ),
    (
        "update",
        "1",
        "--identity",
        _CURATION_REFUSED_IDENTITY,
        "--extraction",
        _CURATION_REFUSED_EXTRACTION,
        _CURATION_REFUSED_TEXT,
    ),
    ("retire", "1", "--identity", _CURATION_REFUSED_IDENTITY, "--extraction", _CURATION_REFUSED_EXTRACTION),
    (
        "prospect",
        "--desk",
        "hd-company-runtime-acceptance",
        "--extraction",
        _CURATION_REFUSED_EXTRACTION,
        "--type",
        "request",
        _CURATION_REFUSED_TEXT,
    ),
    ("extraction", "read", _CURATION_REFUSED_EXTRACTION),
    ("extraction", "complete", _CURATION_REFUSED_EXTRACTION),
    ("extraction", "fail", _CURATION_REFUSED_EXTRACTION, "--reason", "runtime acceptance attempt"),
)
_ARCHIVE_ADOPTION_ERROR = "The archived transcript did not become exactly one conversation with a TeleClaude identity."
_ARCHIVE_RETRIEVAL_ERROR = "History retrieval did not return the archived conversation."
_CURATION_NOT_REFUSED_ERROR = "A memory-curation operation was not refused for a caller that is not a procedure agent."
_CURATION_MEMORY_LISTING_ERROR = "The authorized memory listing does not match the captured empty fixture result."
_JOBS_LIST_COMMAND = ("bin/telec", "jobs", "list")
_JOBS_STATUS_COMMAND = ("bin/telec", "jobs", "status")
_ENV_OWNER_NAME_VARIABLE = "TELECLAUDE_OWNER_NAME"
_ENV_OWNER_EMAIL_VARIABLE = "TELECLAUDE_OWNER_EMAIL"
_CI_VARIABLE = "CI"
_USER_VARIABLE = "USER"
_LOGNAME_VARIABLE = "LOGNAME"
_SHELL_VARIABLE = "SHELL"
_XDG_RUNTIME_VARIABLE = "XDG_RUNTIME_DIR"
_DBUS_SESSION_VARIABLE = "DBUS_SESSION_BUS_ADDRESS"
_INERT_JOB_SCRIPT_TEXT = """from jobs.base import Job, JobResult


class RuntimeAcceptanceInertJob(Job):
    def run(self, context=None):
        return JobResult(success=True, message=\"inert fixture\")


JOB = RuntimeAcceptanceInertJob()
"""
_JSON_SEPARATOR_VALUES = (",", ":")
_JSON_OBJECT_START = "{"
_JSON_ARRAY_START = "["
_FULL_NO_OUTPUT_ERROR = "A required public command returned no result."
_FULL_PATCH_FAILED = "The public configuration transaction did not complete as required."
_FULL_STATE_CHANGED = "A refused operation changed the persisted machine configuration."
_FULL_API_RESPONSE_INVALID = "The public API returned no expected structured result."
_FULL_PROJECT_NOT_LISTED = "The public project listing omitted the disposable project."
_FULL_JOB_RESPONSE_MISSING = "The public job listing or status returned no result."
_FULL_OWNER_NOT_ADMIN = "The synthetic owner did not resolve to platform administrator standing."
_FULL_BAD_REVISION = "A public configuration read did not return its opaque revision."
_FULL_CONFIG_SHAPE_INVALID = "A public configuration read returned an invalid structure."
_FULL_COLD_PROFILE_REQUIRED = "A full profile is run in addition to the cold entry profile."
_FULL_RUNTIME_STATE = "full_runtime"
_JSON_SEPARATORS = (",", ":")
_MANIFEST_KEY_FIELD = "key"
_MANIFEST_GROUPS_FIELD = "groups"
_CONFIG_COMPUTER_FIELD = "computer"
_CONFIG_AGENTS_FIELD = "agents"
_CONFIG_DEFAULT_FIELD = "default"
_CONFIG_DEPLOYMENT_FIELD = "deployment"
_CONFIG_CHANNEL_FIELD = "channel"
_COMPUTER_USER_FIELD = "user"
_COMPUTER_ROLE_FIELD = "role"
_COMPUTER_TIMEZONE_FIELD = "timezone"
_COMPUTER_WORKING_DIRECTORY_FIELD = "default_working_dir"
_COMPUTER_MASTER_FIELD = "is_master"
_COMPUTER_HOST_FIELD = "host"
_RUNNER_IDENTITY_FIELDS = frozenset({_COMPUTER_NAME_FIELD, _COMPUTER_USER_FIELD, _COMPUTER_HOST_FIELD})
_REDACTED_RUNNER_IDENTITY = "<runner-identity>"
_COMPUTER_INGRESS_FIELD = "is_ingress_node"
_AGENT_ENABLED_FIELD = "enabled"
_COMPUTER_ROLE_DEFAULT = "general"
_TRUE_TEXT = "1"
_FALSE_TEXT = "0"
_UV_SYNC_ARGUMENTS = (
    _UV_EXECUTABLE,
    _UV_SYNC_COMMAND,
    _UV_PROJECT_OPTION,
)
_PYTHON_ENVIRONMENT_EXECUTABLE = Path("bin") / _PYTHON_EXECUTABLE


class Profile(StrEnum):
    """Supported acceptance profile selection."""

    COLD = _PROFILE_COLD
    FULL = _PROFILE_FULL


class ScenarioStatus(StrEnum):
    """Terminal outcome for one required scenario."""

    PASSED = "passed"
    FAILED = "failed"
    NOT_RUN = "not_run"
    P4_PENDING_OUTER = "P4_PENDING_OUTER"


type JSONValue = str | int | float | bool | None | list[JSONValue] | dict[str, JSONValue]
type JSONObject = dict[str, JSONValue]


@dataclass(frozen=True)
class ScenarioResult:
    """Outcome and bounded evidence for one required scenario."""

    scenario_id: str
    status: ScenarioStatus
    duration_seconds: float
    commands: tuple[CommandEvidence, ...] = ()
    diagnostics: str = _EMPTY


@dataclass(frozen=True)
class CommandEvidence:
    """Bounded process evidence for one public command invoked by a scenario."""

    argv: tuple[str, ...]
    exit_status: int | None
    duration_seconds: float
    stdout: str = _EMPTY
    stderr: str = _EMPTY
    diagnostics: str = _EMPTY


@dataclass(frozen=True)
class DaemonInstance:
    """Public process identity observed before and after a configuration restart."""

    pid: int
    token: str


@dataclass(frozen=True)
class WhoAmIFields:
    """Identity fields rendered by the public terminal whoami command."""

    email: str
    role: str


@dataclass(frozen=True)
class JobListRow:
    """One scoped row rendered by the public jobs list command."""

    scope: str
    name: str


@dataclass(frozen=True)
class JobStatusRow:
    """Run-state fields rendered by the public jobs status command."""

    name: str
    last_run: str
    status: str
    next_due: str


@dataclass(frozen=True)
class CleanupResult:
    """Cleanup outcome retained independently from the scenario outcome."""

    status: ScenarioStatus
    detail: str = _EMPTY
    commands: tuple[CommandEvidence, ...] = ()


@dataclass(frozen=True)
class AcceptanceReport:
    """Structured evidence identifying the source, profile, journeys and cleanup."""

    schema_version: int
    source_revision: str
    source_tree: str
    profile: Profile
    scenario_inventory: tuple[str, ...]
    scenarios: tuple[ScenarioResult, ...]
    cleanup: CleanupResult
    duration_seconds: float
    selection: tuple[str, ...] = ()
    workflow_event_evidence: JSONObject = field(default_factory=dict)
    retired_act_evidence: creation.RetiredActEvidence = field(default_factory=creation.empty_retired_act_evidence)
    workflow_waiting_retired_kickback_evidence: waiting.WaitingKickbackEvidence = field(
        default_factory=waiting.empty_b13_evidence
    )
    retired_act_delivery_path: Path | None = field(default=None, repr=False)
    workflow_waiting_retired_kickback_delivery_path: Path | None = field(default=None, repr=False)
    workflow_waiting_retired_kickback_marker_directory: Path | None = field(default=None, repr=False)
    payload_provisional: PayloadProvisional | None = field(default=None, repr=False)

    @property
    def passed(self) -> bool:
        """A pass of the whole inventory; selected or provisional runs never supply one."""
        return (
            self.payload_provisional is None
            and not self.selection
            and self.cleanup.status is ScenarioStatus.PASSED
            and len(self.scenarios) == len(self.scenario_inventory)
            and all(result.status is ScenarioStatus.PASSED for result in self.scenarios)
        )

    @property
    def selection_passed(self) -> bool:
        """A selected result requires cleanup, including outside physical closure for a newly provisional run."""
        executed = [result for result in self.scenarios if result.status is not ScenarioStatus.NOT_RUN]
        return (
            self.payload_provisional is None
            and bool(self.selection)
            and self.cleanup.status is ScenarioStatus.PASSED
            and bool(executed)
            and all(result.status is ScenarioStatus.PASSED for result in executed)
            and {result.scenario_id for result in executed} == set(self.selection)
        )


ScenarioAction = Callable[[], ScenarioResult | None]
CleanupAction = Callable[[list[CommandEvidence]], None]


def _bound_command_evidence(evidence: Sequence[CommandEvidence]) -> tuple[CommandEvidence, ...]:
    """Copy command evidence with each diagnostic stream bounded for the report."""
    return tuple(
        CommandEvidence(
            argv=command.argv,
            exit_status=command.exit_status,
            duration_seconds=command.duration_seconds,
            stdout=command.stdout[:_DIAGNOSTIC_LIMIT],
            stderr=command.stderr[:_DIAGNOSTIC_LIMIT],
            diagnostics=command.diagnostics[:_DIAGNOSTIC_LIMIT],
        )
        for command in evidence
    )


def execute_profile(
    profile: Profile,
    *,
    source_revision: str,
    source_tree: str,
    scenario_inventory: Sequence[str],
    scenario_actions: Mapping[str, ScenarioAction],
    cleanup_action: CleanupAction,
    selection: frozenset[str] = frozenset(),
    payload_provisional: PayloadProvisional | None = None,
) -> AcceptanceReport:
    """Run required scenarios in order and retain failures, omissions and cleanup.

    A non-empty ``selection`` runs only those scenarios; the others are reported as not run because they were not
    selected, and the report is never a pass of the whole inventory.
    """
    started = time.monotonic()
    outcomes: list[ScenarioResult] = []
    cleanup = CleanupResult(status=ScenarioStatus.NOT_RUN)
    for scenario_id in scenario_inventory:
        if selection and scenario_id not in selection:
            outcomes.append(
                ScenarioResult(
                    scenario_id=scenario_id,
                    status=ScenarioStatus.NOT_RUN,
                    duration_seconds=0,
                    diagnostics=_SCENARIO_NOT_SELECTED,
                )
            )
            continue
        action = scenario_actions.get(scenario_id)
        if action is None:
            outcomes.append(
                ScenarioResult(
                    scenario_id=scenario_id,
                    status=ScenarioStatus.NOT_RUN,
                    duration_seconds=0,
                    diagnostics=_SCENARIO_NOT_RUN,
                )
            )
            continue
        scenario_started = time.monotonic()
        try:
            payload_work.check()
            result = action()
            if (result is None or result.status is ScenarioStatus.PASSED) and payload_work.expired():
                result = ScenarioResult(
                    scenario_id=scenario_id,
                    status=ScenarioStatus.FAILED,
                    duration_seconds=time.monotonic() - scenario_started,
                    commands=result.commands if result is not None else (),
                    diagnostics=f"{result.diagnostics}\n{payload_work.EXPIRED}"
                    if result is not None and result.diagnostics
                    else payload_work.EXPIRED,
                )
            outcomes.append(
                ScenarioResult(
                    scenario_id=scenario_id,
                    status=result.status if result is not None else ScenarioStatus.PASSED,
                    duration_seconds=time.monotonic() - scenario_started,
                    commands=_bound_command_evidence(result.commands) if result is not None else (),
                    diagnostics=result.diagnostics[:_DIAGNOSTIC_LIMIT] if result is not None else _EMPTY,
                )
            )
        except KeyboardInterrupt:
            outcomes.append(
                ScenarioResult(
                    scenario_id=scenario_id,
                    status=ScenarioStatus.FAILED,
                    duration_seconds=time.monotonic() - scenario_started,
                    diagnostics=_INTERRUPTED,
                )
            )
        except Exception as exc:
            outcomes.append(
                ScenarioResult(
                    scenario_id=scenario_id,
                    status=ScenarioStatus.FAILED,
                    duration_seconds=time.monotonic() - scenario_started,
                    diagnostics=f"{type(exc).__name__}: {exc}"[:_DIAGNOSTIC_LIMIT],
                )
            )
        if outcomes[-1].status is not ScenarioStatus.PASSED:
            for not_run_id in scenario_inventory[len(outcomes) :]:
                outcomes.append(
                    ScenarioResult(
                        scenario_id=not_run_id,
                        status=ScenarioStatus.NOT_RUN,
                        duration_seconds=0,
                        diagnostics=_SCENARIO_NOT_SELECTED
                        if selection and not_run_id not in selection
                        else _SCENARIO_NOT_RUN,
                    )
                )
            break
    cleanup_evidence: list[CommandEvidence] = []
    try:
        payload_work.check()
        cleanup_action(cleanup_evidence)
        payload_work.check()
        cleanup = CleanupResult(status=ScenarioStatus.PASSED)
    except PhysicalCleanupPending as exc:
        expired = payload_work.expired()
        pending = payload_provisional is not None and not expired
        cleanup = CleanupResult(
            status=ScenarioStatus.P4_PENDING_OUTER if pending else ScenarioStatus.FAILED,
            detail=_EMPTY if pending else payload_work.EXPIRED if expired else str(exc),
            commands=_bound_command_evidence(cleanup_evidence),
        )
    except Exception as exc:
        cleanup = CleanupResult(
            status=ScenarioStatus.FAILED,
            detail=f"{type(exc).__name__}: {exc}"[:_DIAGNOSTIC_LIMIT],
            commands=_bound_command_evidence(cleanup_evidence),
        )
    except KeyboardInterrupt:
        cleanup = CleanupResult(
            status=ScenarioStatus.FAILED,
            detail=_INTERRUPTED,
            commands=_bound_command_evidence(cleanup_evidence),
        )
    return AcceptanceReport(
        schema_version=PROVISIONAL_REPORT_SCHEMA if payload_provisional is not None else _REPORT_SCHEMA_VERSION,
        source_revision=source_revision,
        source_tree=source_tree,
        profile=profile,
        scenario_inventory=tuple(scenario_inventory),
        scenarios=tuple(outcomes),
        cleanup=cleanup,
        duration_seconds=time.monotonic() - started,
        selection=tuple(sorted(selection)),
        payload_provisional=payload_provisional,
    )


@dataclass(frozen=True)
class ProcessExecution:
    """Bounded output and lifecycle result from one child process group."""

    exit_status: int
    stdout: str
    stderr: str
    duration_seconds: float
    diagnostics: str = _EMPTY


@dataclass
class FullRuntimeResources:
    """Resources and reversible setup state owned by one disposable full profile."""

    source_root: Path
    temporary_root: Path
    environment: dict[str, str]
    source_revision: str
    source_tree: str
    report_path: Path | None = None
    payload_provisional: PayloadProvisional | None = None
    daemon_stop_outcome: str | None = None
    inner_cleanup: InnerCleanupEvidence | None = None
    public_cleanup_finished_ns: int | None = None
    daemon_stop_started_ns: int | None = None
    daemon_stop_finished_ns: int | None = None
    daemon_stop_execution: ProcessExecution | None = None
    daemon_stop_error: str | None = None
    admin_terminal: PersistentTerminal | None = None
    member_terminal: PersistentTerminal | None = None
    install_attempted: bool = False
    start_attempted: bool = False
    project_path: Path | None = None
    project_slug: str | None = None
    project_name: str | None = None
    original_adapter_flags: dict[str, bool] | None = None
    adapter_flags_changed: bool = False
    original_timezone: str | None = None
    expected_timezone: str | None = None
    unrelated_computer_role: str | None = None
    release_world: object | None = None
    fixture_setup: foundation.FixtureSetup | None = None
    workflow_flow: full_flow.WorkflowFlow | None = None
    workflow_chain: tuple[str, ...] = ()
    early_workflow: JSONObject = field(default_factory=dict)
    retained: list[str] = field(default_factory=list)
    retired_act_selected: bool = False
    retired_act_evidence: creation.RetiredActEvidence = field(default_factory=creation.empty_retired_act_evidence)
    retired_act_deadline: float | None = None
    b13_selected: bool = False
    b13_evidence: waiting.WaitingKickbackEvidence = field(default_factory=waiting.empty_b13_evidence)
    b13_marker_path: Path | None = None
    b13_carrier_path: Path | None = None
    retained_keys: dict[str, str] = field(default_factory=dict)
    owner_identity_facts: JSONObject = field(default_factory=dict)

    def early_accounting(self, case: str) -> creation.EvidenceObject | None:
        """Retain existing B3/B4 observations only for the admitted new-run report."""
        if self.payload_provisional is None:
            return None
        record: creation.EvidenceObject = {
            "schema_version": 1,
            "case": case,
            "project_path": str(self.project_path),
            "started_ns": time.monotonic_ns(),
            "finished_ns": None,
            "baseline": [],
            "settlement": {},
            "cleanup_problems": None,
            "journey_error": None,
            "cleanup_error": None,
            "seal_error": None,
            "attempt_ledgers": [],
            "drivers": [],
        }
        self.early_workflow[case] = record
        return record

    def open_admin_terminal(self) -> PersistentTerminal:
        """Create the one administrator PTY retained for fresh CLI processes."""
        if self.admin_terminal is None:
            self.admin_terminal = _open_terminal(self.environment)
            if self.admin_terminal.run([_SHELL_CHANGE_DIRECTORY, str(self.source_root)]).returncode != _PROCESS_SUCCESS:
                self.admin_terminal.close()
                self.admin_terminal = None
                raise RuntimeError(_FULL_TERMINAL_SETUP_ERROR)
        return self.admin_terminal

    def open_member_terminal(self) -> PersistentTerminal:
        """Create a second PTY for the registered non-administrator caller."""
        if self.member_terminal is None:
            self.member_terminal = _open_terminal(self.environment)
            if (
                self.member_terminal.run([_SHELL_CHANGE_DIRECTORY, str(self.source_root)]).returncode
                != _PROCESS_SUCCESS
            ):
                self.member_terminal.close()
                self.member_terminal = None
                raise RuntimeError(_FULL_TERMINAL_SETUP_ERROR)
        return self.member_terminal

    def sanitize(self, text: str) -> str:
        """Remove source, home and disposable paths from retained command evidence."""
        text = text.replace(str(self.source_root), _SOURCE_TREE_PLACEHOLDER)
        text = text.replace(str(self.temporary_root), _SYNTHETIC_RUNTIME_PLACEHOLDER)
        home = self.environment.get(_COLD_HOME_VARIABLE)
        if home:
            text = text.replace(home, _RUNTIME_HOME_PLACEHOLDER)
        if self.project_path is not None:
            text = text.replace(str(self.project_path), _DISPOSABLE_PROJECT_PLACEHOLDER)
        return text

    def retain_key(self, key: str, reason: str) -> None:
        """Register an independently owned retention reason without conflating other journeys' holds."""
        existing = self.retained_keys.get(key)
        if existing is not None:
            if existing != reason:
                raise ValueError(_FULL_RETENTION_KEY_COLLISION)
            return
        self.retained_keys[key] = reason
        self.retained.append(reason)

    def release_key(self, key: str) -> None:
        """Clear only the exact reason owned by this retention key."""
        reason = self.retained_keys.pop(key, None)
        if reason is None:
            return
        try:
            self.retained.remove(reason)
        except ValueError as error:
            self.retained_keys[key] = reason
            raise ValueError(_FULL_RETENTION_KEY_MISSING) from error


def _run_bounded_process(
    argv: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    timeout_seconds: float,
    output_limit_bytes: int = _OUTPUT_LIMIT,
) -> ProcessExecution:
    """Run one command in an owned process group and retain bounded evidence."""
    started = time.monotonic()
    command_end = payload_work.command_end(timeout_seconds)
    # A child process is required to exercise the checked public executable and uv as real boundaries.
    try:
        process = subprocess.Popen(
            list(argv),
            cwd=cwd,
            env=dict(environment),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            close_fds=True,
            start_new_session=True,
        )
    except OSError:
        return ProcessExecution(
            exit_status=_PROCESS_LAUNCH_EXIT_CODE,
            stdout=_EMPTY,
            stderr=_EMPTY,
            duration_seconds=time.monotonic() - started,
            diagnostics=_PROCESS_LAUNCH_FAILED,
        )
    try:
        try:
            # Startup may return late; retain its handle and spend no fresh allowance afterwards.
            stdout_bytes, stderr_bytes = process.communicate(timeout=payload_work.remaining(command_end))
            diagnostics = _EMPTY
        except subprocess.TimeoutExpired:
            _stop_process_group(process)
            stdout_bytes, stderr_bytes = process.communicate()
            diagnostics = _PROCESS_TIMEOUT_DETAIL
        except BaseException:
            _stop_process_group(process)
            process.communicate()
            raise
    finally:
        if process.poll() is None:
            _stop_process_group(process)
    output_exceeded = len(stdout_bytes) > output_limit_bytes or len(stderr_bytes) > output_limit_bytes
    if output_exceeded:
        diagnostics = _PROCESS_OUTPUT_LIMIT_DETAIL
    if payload_work.expired():
        diagnostics = f"{diagnostics}; {payload_work.EXPIRED}" if diagnostics else payload_work.EXPIRED
    return ProcessExecution(
        exit_status=process.returncode if process.returncode is not None else _PROCESS_FAILURE,
        stdout=stdout_bytes[:output_limit_bytes].decode(_UTF8, errors=_UTF8_REPLACEMENT),
        stderr=stderr_bytes[:output_limit_bytes].decode(_UTF8, errors=_UTF8_REPLACEMENT),
        duration_seconds=time.monotonic() - started,
        diagnostics=diagnostics,
    )


def _stop_process_group(process: subprocess.Popen[bytes]) -> None:
    """Terminate every process in the command group, escalating after a short grace."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=_PROCESS_TERMINATION_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    try:
        process.wait()
    except ChildProcessError:
        return


def _environment_cache_key(source_root: Path) -> str:
    """Hash dependency inputs and interpreter identity for an immutable environment."""
    digest = hashlib.sha256()
    for relative_path in _ENVIRONMENT_MANIFESTS:
        manifest_path = source_root / relative_path
        digest.update(relative_path.encode(_UTF8))
        if manifest_path.is_file():
            digest.update(manifest_path.read_bytes())
        elif relative_path in _ENVIRONMENT_REQUIRED_MANIFESTS:
            raise FileNotFoundError(_ENVIRONMENT_INPUT_MISSING.format(path=relative_path))
    identity = (
        _ENVIRONMENT_GROUPS,
        str(Path(sys.executable).resolve()),
        sys.version,
        sys.implementation.cache_tag or _UNKNOWN_REVISION,
        platform.platform(),
    )
    digest.update(json.dumps(identity, separators=_JSON_SEPARATORS).encode(_UTF8))
    return digest.hexdigest()


def _environment_cache_root() -> Path:
    """Return the caller-owned, machine-local cache root for immutable environments."""
    cache_name = f"{_ENVIRONMENT_CACHE_DIRECTORY}-{os.getuid()}"
    return Path(tempfile.gettempdir()) / cache_name


def ensure_dependency_environment(source_root: Path) -> Path:
    """Prepare or reuse a locked environment that contains dependencies but no app install."""
    resolved_root = source_root.expanduser().resolve()
    cache_root = _environment_cache_root()
    cache_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    cache_root.chmod(0o700)
    generation = _environment_cache_key(resolved_root)
    environment_path = cache_root / generation
    lock_path = cache_root / f"{generation}{_ENVIRONMENT_LOCK_SUFFIX}"
    with lock_path.open("a+b") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        if environment_path.exists():
            _validate_dependency_environment(environment_path, generation)
            return environment_path
        environment = _dependency_sync_environment(cache_root, environment_path)
        sync_result = _run_bounded_process(
            (
                *_UV_SYNC_ARGUMENTS,
                str(resolved_root),
                _UV_LOCKED_OPTION,
                _UV_NO_INSTALL_PROJECT_OPTION,
                _UV_NO_DEFAULT_GROUPS_OPTION,
            ),
            cwd=resolved_root,
            environment=environment,
            timeout_seconds=_UV_SYNC_TIMEOUT_SECONDS,
        )
        if sync_result.exit_status != 0 or sync_result.diagnostics:
            if environment_path.exists() and not environment_path.is_symlink():
                shutil.rmtree(environment_path)
            detail = _PROCESS_FAILURE_DETAIL.format(exit_status=sync_result.exit_status)
            raise RuntimeError(_ENVIRONMENT_SYNC_FAILED.format(detail=detail))
        manifest_path = environment_path / _ENVIRONMENT_MANIFEST_FILENAME
        manifest_path.write_text(json.dumps({"key": generation, "groups": _ENVIRONMENT_GROUPS}), encoding=_UTF8)
        _validate_dependency_environment(environment_path, generation)
        return environment_path


def _dependency_sync_environment(cache_root: Path, environment_path: Path) -> dict[str, str]:
    """Build an allowlisted environment for uv without inheriting credentials or project config."""
    runtime_home = cache_root / _SYNTHETIC_HOME_DIRECTORY
    runtime_cache = cache_root / _SYNTHETIC_CACHE_DIRECTORY
    runtime_temp = cache_root / _SYNTHETIC_TEMP_DIRECTORY
    runtime_home.mkdir(mode=0o700, parents=True, exist_ok=True)
    runtime_cache.mkdir(mode=0o700, parents=True, exist_ok=True)
    runtime_temp.mkdir(mode=0o700, parents=True, exist_ok=True)
    child_environment = {
        _PATH_VARIABLE: os.environ.get(_PATH_VARIABLE, _EMPTY),
        _COLD_HOME_VARIABLE: str(runtime_home),
        _UV_CACHE_VARIABLE: str(runtime_cache),
        _ENVIRONMENT_VARIABLE: str(environment_path),
        _LOCALE_VARIABLE: os.environ.get(_LOCALE_VARIABLE, _DEFAULT_LANGUAGE),
        _TMP_VARIABLE: str(runtime_temp),
    }
    return child_environment


def _validate_dependency_environment(environment_path: Path, generation: str) -> None:
    """Refuse an incomplete or mismatched cached environment without mutating it."""
    manifest_path = environment_path / _ENVIRONMENT_MANIFEST_FILENAME
    python_path = environment_path / _PYTHON_ENVIRONMENT_EXECUTABLE
    config_path = environment_path / _VENV_CONFIG_FILENAME
    if (
        environment_path.is_symlink()
        or not environment_path.is_dir()
        or not manifest_path.is_file()
        or not python_path.is_file()
        or not config_path.is_file()
    ):
        raise RuntimeError(_ENVIRONMENT_INVALID.format(path=environment_path.name))
    try:
        manifest: object = json.loads(manifest_path.read_text(encoding=_UTF8))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(_ENVIRONMENT_INVALID.format(path=environment_path.name)) from exc
    if manifest != {_MANIFEST_KEY_FIELD: generation, _MANIFEST_GROUPS_FIELD: _ENVIRONMENT_GROUPS}:
        raise RuntimeError(_ENVIRONMENT_INVALID.format(path=environment_path.name))


def _make_cold_environment(
    source_root: Path,
    dependency_environment: Path,
    temporary_root: Path,
    *,
    channel: str = _SYNTHETIC_RELEASE_CHANNEL,
    working_directory: Path | None = None,
) -> dict[str, str]:
    """Create disposable paths and a synthetic runtime config for cold CLI startup."""
    home = temporary_root / _SYNTHETIC_HOME_DIRECTORY
    state = temporary_root / _SYNTHETIC_STATE_DIRECTORY
    cache = temporary_root / _SYNTHETIC_CACHE_DIRECTORY
    config = temporary_root / _SYNTHETIC_CONFIG_DIRECTORY
    data = temporary_root / _SYNTHETIC_DATA_DIRECTORY
    temporary = temporary_root / _SYNTHETIC_TEMP_DIRECTORY
    for path in (home, state, cache, config, data, temporary):
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    machine_config = {
        _CONFIG_COMPUTER_FIELD: {
            _COMPUTER_NAME_FIELD: _SYNTHETIC_COMPUTER_NAME,
            _COMPUTER_USER_FIELD: _SYNTHETIC_COMPUTER_USER,
            _COMPUTER_ROLE_FIELD: _COMPUTER_ROLE_DEFAULT,
            _COMPUTER_TIMEZONE_FIELD: _TIMEZONE_UTC,
            _COMPUTER_WORKING_DIRECTORY_FIELD: str(source_root if working_directory is None else working_directory),
            _COMPUTER_MASTER_FIELD: False,
            _COMPUTER_HOST_FIELD: _SYNTHETIC_COMPUTER_HOST,
            _COMPUTER_INGRESS_FIELD: False,
        },
        _CONFIG_AGENTS_FIELD: {
            _CONFIG_DEFAULT_FIELD: _SYNTHETIC_AGENT,
            _SYNTHETIC_AGENT: {_AGENT_ENABLED_FIELD: True},
        },
        _CONFIG_DEPLOYMENT_FIELD: {_CONFIG_CHANNEL_FIELD: channel},
    }
    (home / _CONFIG_FILENAME).write_text(json.dumps(machine_config), encoding=_UTF8)
    child_environment = {
        _PATH_VARIABLE: os.environ.get(_PATH_VARIABLE, _EMPTY),
        _LOCALE_VARIABLE: os.environ.get(_LOCALE_VARIABLE, _DEFAULT_LANGUAGE),
        _COLD_HOME_VARIABLE: str(home),
        _TELECLAUDE_HOME_VARIABLE: str(home),
        _ENVIRONMENT_VARIABLE: str(dependency_environment),
        _UV_NO_SYNC_VARIABLE: _UV_NO_SYNC_VALUE,
        _NO_BYTECODE_VARIABLE: _TRUE_TEXT,
        _NO_USER_SITE_VARIABLE: _TRUE_TEXT,
        _XDG_STATE_VARIABLE: str(state),
        _XDG_CACHE_VARIABLE: str(cache),
        _XDG_CONFIG_VARIABLE: str(config),
        _XDG_DATA_VARIABLE: str(data),
        _TMP_VARIABLE: str(temporary),
        _GIT_CONFIG_GLOBAL_VARIABLE: os.devnull,
        _GIT_CONFIG_SYSTEM_VARIABLE: os.devnull,
        _GIT_CONFIG_SYSTEM_DISABLED_VARIABLE: _TRUE_TEXT,
        _NO_COLOR_VARIABLE: _TRUE_TEXT,
    }
    return child_environment


def _sanitize_report_text(
    text: str,
    source_root: Path,
    dependency_environment: Path,
    child_environment: Mapping[str, str],
) -> str:
    """Remove machine-local source, environment and disposable paths from retained output."""
    replacements = [
        (str(source_root), _SOURCE_TREE_PLACEHOLDER),
        (str(dependency_environment), _DEPENDENCY_ENVIRONMENT_PLACEHOLDER),
    ]
    replacements.extend(
        (child_environment[name], _SYNTHETIC_RUNTIME_PLACEHOLDER)
        for name in _SYNTHETIC_PATH_ENVIRONMENT_VARIABLES
        if name in child_environment
    )
    for value, replacement in sorted(replacements, key=lambda item: len(item[0]), reverse=True):
        text = text.replace(value, replacement)
    return text


def _full_runtime_environment() -> dict[str, str]:
    """Build an allowlisted child environment that keeps the disposable VM home intact."""
    host_environment = os.environ  # fmt: skip  # guard: direct-env-read - allowed: child-process environment construction
    home = host_environment.get(_COLD_HOME_VARIABLE)
    if not home:
        raise RuntimeError(_FULL_HOME_REQUIRED)
    child_environment = {
        _PATH_VARIABLE: host_environment.get(_PATH_VARIABLE, _EMPTY),
        _COLD_HOME_VARIABLE: home,
        _LOCALE_VARIABLE: host_environment.get(_LOCALE_VARIABLE, _DEFAULT_LANGUAGE),
        _TMP_VARIABLE: tempfile.gettempdir(),
        _NO_BYTECODE_VARIABLE: _TRUE_TEXT,
        _NO_USER_SITE_VARIABLE: _TRUE_TEXT,
        _UV_NO_SYNC_VARIABLE: _UV_NO_SYNC_VALUE,
        _GIT_CONFIG_GLOBAL_VARIABLE: os.devnull,
        _GIT_CONFIG_SYSTEM_VARIABLE: os.devnull,
        _GIT_CONFIG_SYSTEM_DISABLED_VARIABLE: _TRUE_TEXT,
        _ENV_OWNER_NAME_VARIABLE: _OWNER_SEED_NAME,
        _ENV_OWNER_EMAIL_VARIABLE: _OWNER_SEED_EMAIL,
    }
    for name in (_USER_VARIABLE, _LOGNAME_VARIABLE, _SHELL_VARIABLE, _XDG_RUNTIME_VARIABLE, _DBUS_SESSION_VARIABLE):
        value = host_environment.get(name)
        if value:
            child_environment[name] = value
    if (ci_value := host_environment.get(_CI_VARIABLE)) is not None:
        child_environment[_CI_VARIABLE] = ci_value
    return child_environment


def _open_terminal(environment: Mapping[str, str]) -> PersistentTerminal:
    """Open one persistent PTY shell for authenticated, fresh CLI child processes."""
    terminal_environment = dict(environment)
    terminal_environment[_PROMPT_VARIABLE] = _EMPTY
    terminal_environment[_CONTINUATION_PROMPT_VARIABLE] = _EMPTY
    terminal = PersistentTerminal(
        [_BASH_EXECUTABLE, _BASH_NO_PROFILE_OPTION, _BASH_NO_RC_OPTION, _BASH_INTERACTIVE_OPTION],
        environment=terminal_environment,
        timeout_seconds=_FULL_COMMAND_TIMEOUT_SECONDS,
        output_limit_bytes=_OUTPUT_LIMIT,
        disable_echo=True,
    )
    terminal.__enter__()
    return terminal


def _record_terminal_command(
    resources: FullRuntimeResources,
    terminal: PersistentTerminal,
    argv: Sequence[str],
    evidence: list[CommandEvidence],
    timeout_seconds: float | None = None,
) -> tuple[int | None, str]:
    """Run one fresh CLI command on an owned PTY and retain bounded sanitized evidence."""
    started = time.monotonic()
    if resources.retired_act_deadline is not None:
        remaining = resources.retired_act_deadline - started
        if remaining <= 0:
            raise creation.binding_failure(creation.B12_ERROR_PREFIX + creation.B12_DETAIL_DEADLINE)
        timeout_seconds = min(timeout_seconds or _FULL_COMMAND_TIMEOUT_SECONDS, remaining)
    argv_tuple = tuple(argv)
    if argv_tuple and argv_tuple[0] == str(_CLI_EXECUTABLE):
        argv_tuple = (str(resources.source_root / _CLI_EXECUTABLE), *argv_tuple[1:])
    try:
        result = terminal.run(argv_tuple, timeout_seconds=timeout_seconds)
    except TerminalFailure as exc:
        evidence.append(
            CommandEvidence(
                argv=tuple(resources.sanitize(value) for value in argv_tuple),
                exit_status=None,
                duration_seconds=time.monotonic() - started,
                stdout=resources.sanitize(exc.output)[:_DIAGNOSTIC_LIMIT],
                diagnostics=exc.diagnostic,
            )
        )
        return None, exc.output
    sanitized_output = resources.sanitize(_terminal_diagnostic_output(result.output))
    evidence.append(
        CommandEvidence(
            argv=tuple(resources.sanitize(value) for value in argv_tuple),
            exit_status=result.returncode,
            duration_seconds=time.monotonic() - started,
            stdout=sanitized_output[:_DIAGNOSTIC_LIMIT],
        )
    )
    return result.returncode, result.output


def _record_external_command(
    resources: FullRuntimeResources,
    argv: Sequence[str],
    *,
    cwd: Path,
    timeout_seconds: float,
    evidence: list[CommandEvidence],
) -> ProcessExecution:
    """Run a lifecycle command in an owned process group and retain bounded evidence."""
    result = _run_bounded_process(
        argv,
        cwd=cwd,
        environment=resources.environment,
        timeout_seconds=timeout_seconds,
    )
    evidence.append(
        CommandEvidence(
            argv=tuple(resources.sanitize(value) for value in argv),
            exit_status=result.exit_status,
            duration_seconds=result.duration_seconds,
            stdout=resources.sanitize(result.stdout)[:_DIAGNOSTIC_LIMIT]
            if result.exit_status != _PROCESS_SUCCESS or result.diagnostics
            else _EMPTY,
            stderr=resources.sanitize(result.stderr)[:_DIAGNOSTIC_LIMIT]
            if result.exit_status != _PROCESS_SUCCESS or result.diagnostics
            else _EMPTY,
            diagnostics=result.diagnostics,
        )
    )
    return result


def _capture_scenario(
    scenario_id: str,
    resources: FullRuntimeResources,
    action: Callable[[list[CommandEvidence]], None],
) -> ScenarioResult:
    """Collect command evidence for one full-profile journey without leaking runtime paths."""
    started = time.monotonic()
    evidence: list[CommandEvidence] = []
    try:
        action(evidence)
        status = ScenarioStatus.PASSED
        diagnostics = _EMPTY
    except Exception as exc:
        status = ScenarioStatus.FAILED
        diagnostics = resources.sanitize(f"{type(exc).__name__}: {exc}")[:_DIAGNOSTIC_LIMIT]
    return ScenarioResult(
        scenario_id=scenario_id,
        status=status,
        duration_seconds=time.monotonic() - started,
        commands=tuple(
            command
            if (
                status is ScenarioStatus.FAILED
                and (
                    index == len(evidence) - 1
                    or command.exit_status != _PROCESS_SUCCESS
                    or command.diagnostics
                    or (scenario_id == _SCENARIO_CURATION_REFUSAL and index == 0)
                )
            )
            or scenario_id == _SCENARIO_WORKFLOW_RETIRED_ACTS
            else replace(command, stdout=_EMPTY)
            for index, command in enumerate(evidence)
        ),
        diagnostics=diagnostics,
    )


FullScenarioAction = Callable[[FullRuntimeResources, list[CommandEvidence]], None]


def _bind_full_scenario(
    scenario_id: str,
    resources: FullRuntimeResources,
    action: FullScenarioAction,
) -> ScenarioAction:
    """Adapt one full-profile action to the report runner's result contract."""

    def run() -> ScenarioResult:
        def invoke(evidence: list[CommandEvidence]) -> None:
            action(resources, evidence)

        return _capture_scenario(scenario_id, resources, invoke)

    return run


def _structured_value(output: str) -> object | None:
    """Decode one JSON value from a CLI terminal capture, skipping shell echo and prompt text."""
    decoder = json.JSONDecoder()
    for index, character in enumerate(output):
        if character not in (_JSON_OBJECT_START, _JSON_ARRAY_START):
            continue
        try:
            value, _ = decoder.raw_decode(output[index:])
            return cast(object, value)
        except json.JSONDecodeError:
            continue
    return None


def _mapping_value(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    if any(not isinstance(key, str) for key in value):
        return None
    return value


def _terminal_diagnostic_output(output: str) -> str:
    """Keep public result structure without the disposable runner's identity values."""
    payload = _structured_value(output)
    if payload is None:
        return output
    return json.dumps(_redact_runner_identity(payload), ensure_ascii=True)


def _redact_runner_identity(value: object) -> object:
    """Redact identity leaves in public computer and configuration result objects."""
    mapping = _mapping_value(value)
    if mapping is not None:
        return {
            key: _REDACTED_RUNNER_IDENTITY
            if key in _RUNNER_IDENTITY_FIELDS and isinstance(item, str)
            else _redact_runner_identity(item)
            for key, item in mapping.items()
        }
    if isinstance(value, list):
        return [_redact_runner_identity(item) for item in value]
    return value


def _computer_view(output: str) -> tuple[Mapping[str, object], str]:
    """Read the typed public computer view and opaque revision from CLI JSON."""
    payload = _mapping_value(_structured_value(output))
    if payload is None:
        raise ValueError(_FULL_CONFIG_SHAPE_INVALID)
    computer = _mapping_value(payload.get(_CONFIG_COMPUTER_FIELD))
    revision = payload.get(_MACHINE_REVISION_FIELD)
    if computer is None or not isinstance(revision, str) or not revision:
        raise ValueError(_FULL_BAD_REVISION)
    return computer, revision


def _computer_identity(machine: Mapping[str, object]) -> Mapping[str, object]:
    """Read identity fields inside the computer-kind machine document."""
    computer = _mapping_value(machine.get(_CONFIG_COMPUTER_FIELD))
    if computer is None:
        raise ValueError(_FULL_CONFIG_SHAPE_INVALID)
    return computer


def _machine_state_view(output: str) -> tuple[JSONObject, str]:
    """Read the full declared machine view without its per-request metadata."""
    payload = _mapping_value(_structured_value(output))
    if payload is None:
        raise ValueError(_FULL_CONFIG_SHAPE_INVALID)
    revision = payload.get(_MACHINE_REVISION_FIELD)
    if not isinstance(revision, str) or not revision:
        raise ValueError(_FULL_BAD_REVISION)
    state = cast(
        JSONObject,
        {key: value for key, value in payload.items() if key not in (_MACHINE_REVISION_FIELD, _REQUEST_ID_FIELD)},
    )
    return state, revision


def _project_view(output: str) -> tuple[Mapping[str, object], str]:
    """Read the typed public project view and opaque revision from CLI JSON."""
    payload = _mapping_value(_structured_value(output))
    if payload is None:
        raise ValueError(_FULL_CONFIG_SHAPE_INVALID)
    project = _mapping_value(payload.get(_PROJECT_CONFIG_SECTION))
    revision = payload.get(_PROJECT_CONFIG_REVISION_FIELD)
    if project is None or not isinstance(revision, str) or not revision:
        raise ValueError(_FULL_BAD_REVISION)
    return project, revision


def _project_list_contains(output: str, project_name: str, project_path: Path) -> bool:
    """Match the declared project identity and path in the structured public listing."""
    payload = _structured_value(output)
    if isinstance(payload, Mapping):
        payload = payload.get(_PROJECTS_RESPONSE_FIELD)
    if not isinstance(payload, list):
        return False
    expected_path = str(project_path.resolve())
    for item in payload:
        row = _mapping_value(item)
        if row is None:
            continue
        if row.get(_PROJECT_NAME_FIELD) == project_name and row.get(_PROJECT_PATH_FIELD) == expected_path:
            return True
    return False


def _computer_list_has_ready_local(output: str) -> bool:
    """Verify the public daemon response reports its local computer online."""
    expected = _mapping_value(
        json.loads((Path(__file__).parent / _READY_LOCAL_COMPUTER_SNAPSHOT).read_text(encoding=_UTF8))
    )
    payload = _structured_value(output)
    if not isinstance(payload, list):
        return False
    for item in payload:
        row = _mapping_value(item)
        if row is not None and row.get(_COMPUTER_IS_LOCAL_FIELD) is True:
            actual = {
                _COMPUTER_IS_LOCAL_FIELD: row.get(_COMPUTER_IS_LOCAL_FIELD),
                _COMPUTER_STATUS_FIELD: row.get(_COMPUTER_STATUS_FIELD),
            }
            return actual == expected
    return False


def _owner_record_is_administrator(output: str) -> bool:
    """Verify the owner seed resolves to the declared platform administrator standing."""
    payload = _mapping_value(_structured_value(output))
    if payload is None:
        return False
    roles = payload.get(_ROLE_SECTION)
    return isinstance(roles, list) and any(
        (role := _mapping_value(item)) is not None and role.get(_ROLE_PLATFORM_FIELD) == _ADMIN_ROLE for item in roles
    )


def _parse_whoami_fields(output: str) -> WhoAmIFields | None:
    """Parse the public whoami key/value lines without grading unrelated output text."""
    fields: dict[str, str] = {}
    expected_fields = {_WHOAMI_EMAIL_FIELD, _WHOAMI_ROLE_FIELD}
    for line in output.splitlines():
        field, separator, value = line.partition(_WHOAMI_LABEL_SEPARATOR)
        if separator and field in expected_fields:
            if field in fields:
                return None
            fields[field] = value.strip()
    email = fields.get(_WHOAMI_EMAIL_FIELD)
    role = fields.get(_WHOAMI_ROLE_FIELD)
    if not email or not role:
        return None
    return WhoAmIFields(email=email, role=role)


def _parse_job_list_rows(output: str) -> tuple[JobListRow, ...] | None:
    """Parse the scope/name rows rendered by the public jobs list command."""
    rows: list[JobListRow] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        fields = line.split(maxsplit=1)
        if len(fields) != 2 or not fields[0] or not fields[1].strip():
            return None
        rows.append(JobListRow(scope=fields[0], name=fields[1].strip()))
    return tuple(rows)


def _parse_job_status_rows(output: str) -> tuple[JobStatusRow, ...] | None:
    """Parse the name and keyed run-state fields rendered by public jobs status."""
    rows: list[JobStatusRow] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        name, separator, rendered_fields = line.partition(_JOB_LINE_SEPARATOR)
        if not separator or not name.strip():
            return None
        fields: dict[str, str] = {}
        for rendered_field in rendered_fields.split(_JOB_FIELD_SEPARATOR):
            field, value_separator, value = rendered_field.partition(_JOB_VALUE_SEPARATOR)
            if not value_separator or not field or field in fields:
                return None
            fields[field] = value
        if frozenset(fields) != _JOB_STATUS_FIELDS:
            return None
        rows.append(
            JobStatusRow(
                name=name.strip(),
                last_run=fields[_JOB_STATUS_LAST_RUN_FIELD],
                status=fields[_JOB_STATUS_STATE_FIELD],
                next_due=fields[_JOB_STATUS_NEXT_DUE_FIELD],
            )
        )
    return tuple(rows)


def _member_patch_refusal_matches(output: str) -> bool:
    """Compare the real member/operation denial with its public-output snapshot."""
    expected = (Path(__file__).parent / _MEMBER_PATCH_REFUSAL_SNAPSHOT).read_text(encoding=_UTF8)
    observed = _LINE_BREAK.join(output.splitlines()).strip() + _LINE_BREAK
    return observed == expected


def _invalid_patch_refusal_matches(resources: FullRuntimeResources, output: str) -> bool:
    """Compare complete safe refusal prose, normalizing only runtime paths and request identity."""
    snapshot_path = Path(__file__).parent / _INVALID_PATCH_REFUSAL_SNAPSHOT
    if not snapshot_path.is_file():
        raise ValueError(_INVALID_REFUSAL_SNAPSHOT_MISSING)
    expected = snapshot_path.read_text(encoding=_UTF8)
    observed = _LINE_BREAK.join(resources.sanitize(output).splitlines()).strip()
    description, marker, request = observed.rpartition(_REFUSAL_REQUEST_PREFIX)
    if marker and request.endswith(_REFUSAL_REQUEST_END):
        identifier = request.removesuffix(_REFUSAL_REQUEST_END)
        try:
            canonical_identifier = str(uuid.UUID(identifier))
        except ValueError:
            canonical_identifier = _EMPTY
        if canonical_identifier and identifier == canonical_identifier:
            observed = description + marker + _REFUSAL_REQUEST_PLACEHOLDER + _REFUSAL_REQUEST_END
    return observed + _LINE_BREAK == expected


def _require_process_success(result: ProcessExecution) -> None:
    if result.exit_status != _PROCESS_SUCCESS or result.diagnostics:
        raise RuntimeError(_EXPECTED_COMMAND_ERROR)


def _require_terminal_success(exit_status: int | None, output: str, evidence: Sequence[CommandEvidence]) -> None:
    if exit_status != _PROCESS_SUCCESS or not output.strip() or evidence[-1].diagnostics:
        raise RuntimeError(_FULL_NO_OUTPUT_ERROR)


def _require_terminal_exit(exit_status: int | None, evidence: Sequence[CommandEvidence]) -> None:
    if exit_status != _PROCESS_SUCCESS or evidence[-1].diagnostics:
        raise RuntimeError(_EXPECTED_COMMAND_ERROR)


def _read_computer_config(
    resources: FullRuntimeResources,
    terminal: PersistentTerminal,
    evidence: list[CommandEvidence],
) -> tuple[Mapping[str, object], str, str]:
    exit_status, output = _record_terminal_command(
        resources,
        terminal,
        _CONFIG_COMPUTER_GET_COMMAND,
        evidence,
    )
    _require_terminal_success(exit_status, output, evidence)
    computer, revision = _computer_view(output)
    return computer, revision, output


def _read_project_config(
    resources: FullRuntimeResources,
    terminal: PersistentTerminal,
    project_slug: str,
    evidence: list[CommandEvidence],
) -> tuple[Mapping[str, object], str, str]:
    argv = (*_CONFIG_PROJECT_GET_PREFIX, project_slug, _FORMAT_OPTION, _JSON_FORMAT)
    exit_status, output = _record_terminal_command(resources, terminal, argv, evidence)
    _require_terminal_success(exit_status, output, evidence)
    project, revision = _project_view(output)
    return project, revision, output


def _patch_configuration(
    resources: FullRuntimeResources,
    terminal: PersistentTerminal,
    argv_prefix: Sequence[str],
    revision: str,
    patch: Mapping[str, JSONValue],
    evidence: list[CommandEvidence],
) -> None:
    argv = (*argv_prefix, _REVISION_OPTION, revision, _YAML_OPTION, json.dumps(patch))
    exit_status, output = _record_terminal_command(resources, terminal, argv, evidence)
    _require_terminal_success(exit_status, output, evidence)


def _disable_external_adapters(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    terminal = resources.open_admin_terminal()
    computer, revision, _ = _read_computer_config(resources, terminal, evidence)
    changes: JSONObject = {}
    original_flags: dict[str, bool] = {}
    for section_name in _MACHINE_ADAPTER_SECTIONS:
        section = _mapping_value(computer.get(section_name))
        if section is None:
            continue
        enabled = section.get(_MACHINE_ADAPTER_ENABLED_FIELD)
        if enabled is True:
            original_flags[section_name] = True
        changes[section_name] = {_MACHINE_ADAPTER_ENABLED_FIELD: False}
    if not changes:
        return
    resources.original_adapter_flags = original_flags
    resources.adapter_flags_changed = True
    _patch_configuration(
        resources,
        terminal,
        _CONFIG_COMPUTER_PATCH_PREFIX,
        revision,
        changes,
        evidence,
    )


def _restore_full_profile_changes(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    terminal = resources.admin_terminal
    if terminal is None:
        return
    if resources.adapter_flags_changed or resources.original_timezone is not None:
        try:
            computer, revision, _ = _read_computer_config(resources, terminal, evidence)
            restore: JSONObject = {}
            if (
                resources.original_timezone is not None
                and _computer_identity(computer).get(_MACHINE_TIMEZONE_FIELD) != resources.original_timezone
            ):
                restore[_CONFIG_COMPUTER_FIELD] = {_MACHINE_TIMEZONE_FIELD: resources.original_timezone}
            for section_name, enabled in (resources.original_adapter_flags or {}).items():
                section = _mapping_value(computer.get(section_name))
                if section is None:
                    raise ValueError(_FULL_CONFIG_SHAPE_INVALID)
                if section.get(_MACHINE_ADAPTER_ENABLED_FIELD) is not enabled:
                    restore[section_name] = {_MACHINE_ADAPTER_ENABLED_FIELD: enabled}
            if restore:
                _patch_configuration(
                    resources,
                    terminal,
                    _CONFIG_COMPUTER_PATCH_PREFIX,
                    revision,
                    restore,
                    evidence,
                )
            resources.adapter_flags_changed = False
            resources.original_timezone = None
        except Exception as exc:
            raise RuntimeError(_FULL_CONFIG_RESTORE_ERROR) from exc


def _record_retained_workflow_markers(resources: FullRuntimeResources) -> bool:
    retained_markers = sorted(resources.temporary_root.rglob("RETAINED.json"))
    unresolved_marker = False
    for marker in retained_markers:
        try:
            marker_bytes = marker.read_bytes()
            record = json.loads(marker_bytes)
            if _is_b12_delivery_marker(resources, marker, record, marker_bytes):
                continue
            if _is_b13_delivery_marker(resources, marker, record, marker_bytes):
                continue
            reason = record.get(creation.B12Field.REASON) if isinstance(record, Mapping) else None
            resources.retained.append(
                f"retained marker {marker}: {reason if isinstance(reason, str) else 'unreadable status'}"
            )
            unresolved_marker = True
        except (OSError, ValueError) as error:
            resources.retained.append(f"retained marker {marker} cannot be read: {type(error).__name__}")
            unresolved_marker = True
    return unresolved_marker


def _is_b13_delivery_marker(resources: FullRuntimeResources, marker: Path, record: object, marker_bytes: bytes) -> bool:
    """Allow only a complete B13 evidence seal to pass the marker scan before report delivery."""
    expected = resources.b13_marker_path
    carrier = resources.b13_carrier_path
    evidence = resources.b13_evidence
    if expected is None or carrier is None or marker != expected or not isinstance(record, Mapping):
        return False
    if not waiting.verify_b13_delivery(evidence, marker, carrier, resources.sanitize):
        return False
    return (
        record.get("schema_version") == waiting.B13_SCHEMA_VERSION
        and record.get(waiting.B13_STATUS_FIELD) == waiting.B13_STATUS_COMPLETE
        and record.get(waiting.B13_REASON_FIELD) == waiting.B13_RETENTION_REASON
        and record.get(waiting.B13_SOURCE_REVISION_FIELD) == resources.source_revision
        and record.get(waiting.B13_SOURCE_TREE_FIELD) == resources.source_tree
        and record.get(waiting.B13_ISSUE_REVISION_FIELD) == waiting.B13_ISSUE_REVISION
        and record.get(waiting.B13_ASSERTION_SHA_FIELD) == waiting.B13_ASSERTION_SHA
        and record.get(waiting.B13_ITEM_FIELD) == evidence.item
        and record.get(waiting.B13_ARGV_FIELD) == evidence.argv
        and record.get(waiting.B13_ACTORS_FIELD) == evidence.prerequisites.get(waiting.B13_ACTORS_FIELD)
        and record.get(waiting.B13_CANDIDATE_FIELD) == evidence.prerequisites.get(waiting.B13_CANDIDATE_FIELD)
        and record.get(waiting.B13_CONTROL_PATHS_FIELD) == evidence.prerequisites.get(waiting.B13_CONTROL_PATHS_FIELD)
        and record.get(waiting.B13_ATTEMPTS_PATH_FIELD) == evidence.carrier.get(waiting.B13_ATTEMPTS_PATH_FIELD)
        and record.get(waiting.B13_ATTEMPTS_SHA_FIELD) == evidence.attempt_ledger.get("original_sha256")
        and record.get(waiting.B13_ATTEMPTS_BYTES_FIELD) == evidence.attempt_ledger.get("original_byte_count")
        and record.get(waiting.B13_CARRIER_SHA_FIELD) == evidence.carrier.get(waiting.B13_CARRIER_SHA_FIELD)
        and record.get(waiting.B13_CARRIER_BYTES_FIELD) == evidence.carrier.get(waiting.B13_CARRIER_BYTES_FIELD)
        and hashlib.sha256(marker_bytes).hexdigest() == evidence.carrier.get(waiting.B13_MARKER_SHA_FIELD)
        and len(marker_bytes) == evidence.carrier.get(waiting.B13_MARKER_BYTES_FIELD)
    )


def _is_b12_delivery_marker(resources: FullRuntimeResources, marker: Path, record: object, marker_bytes: bytes) -> bool:
    """Recognize only the completed B12 marker retained until report.json is safely written."""
    expected = resources.temporary_root / creation.B12_MATRIX_DIRECTORY / creation.B12_MARKER_FILE
    if marker != expected or resources.retired_act_evidence.status != creation.B12_STATUS_COMPLETE:
        return False
    if not isinstance(record, Mapping):
        return False
    return (
        record.get(creation.B12Field.SCHEMA_VERSION) == creation.B12_JSON_SCHEMA
        and record.get(creation.B12Field.REASON) == creation.B12_REASON
        and record.get(creation.B12Field.SOURCE_REVISION) == resources.source_revision
        and record.get(creation.B12Field.SOURCE_TREE) == resources.source_tree
        and record.get(creation.B12Field.ISSUE_REVISION) == creation.B12_ISSUE_REVISION
        and record.get(creation.B12Field.ASSERTION_SHA256) == creation.B12_ARTIFACT_SHA
        and record.get(creation.B12Field.ORDERED_CASES) == [case_id for case_id, _, _ in creation.B12_CASES]
        and record.get(creation.B12Field.ORDERED_CASE_PLAN)
        == [
            {
                creation.B12Field.CASE_ID: case_id,
                creation.B12Field.ARGV: list(argv),
                creation.B12Field.RETIRED_TYPE: retired_type,
            }
            for case_id, argv, retired_type in creation.B12_CASES
        ]
        and record.get(creation.B12Field.ATTEMPTS_PATH) == str((marker.parent / creation.B12_ATTEMPTS_FILE).resolve())
        and isinstance(record.get(creation.B12Field.S0), Mapping)
        and isinstance(record.get(creation.B12Field.B0), list)
        and isinstance(record.get(creation.B12Field.T0), list)
        and hashlib.sha256(marker_bytes).hexdigest()
        == resources.retired_act_evidence.carrier.get(creation.B12Field.MARKER_SHA256)
        and len(marker_bytes) == resources.retired_act_evidence.carrier.get(creation.B12Field.MARKER_BYTE_COUNT)
        and all(
            case.get(creation.B12Field.CLASSIFICATION) == creation.B12_CLASS_VERIFIED
            for case in resources.retired_act_evidence.cases
        )
    )


def _remove_temporary_root_except_delivery_carriers(resources: FullRuntimeResources) -> None:
    """Remove ordinary disposable profile contents while preserving complete report-delivery carriers."""
    retained_carriers = {resources.temporary_root / creation.B12_MATRIX_DIRECTORY}
    if resources.b13_marker_path is not None:
        retained_carriers.add(resources.b13_marker_path.parent)
    for child in resources.temporary_root.iterdir():
        if child in retained_carriers:
            continue
        if child.is_symlink() or not child.is_dir():
            child.unlink()
        else:
            shutil.rmtree(child)


def _remove_temporary_profile_root(resources: FullRuntimeResources) -> None:
    """Preserve complete B12/B13 report-delivery carriers until write_report succeeds."""
    delivery_marker = resources.temporary_root / creation.B12_MATRIX_DIRECTORY / creation.B12_MARKER_FILE
    b12_delivery = resources.retired_act_evidence.status == creation.B12_STATUS_COMPLETE and delivery_marker.is_file()
    b13_delivery = (
        resources.b13_marker_path is not None
        and resources.b13_marker_path.is_file()
        and _is_b13_delivery_marker(
            resources,
            resources.b13_marker_path,
            json.loads(resources.b13_marker_path.read_bytes()),
            resources.b13_marker_path.read_bytes(),
        )
    )
    if b12_delivery or b13_delivery:
        _remove_temporary_root_except_delivery_carriers(resources)
    else:
        shutil.rmtree(resources.temporary_root)


def _freeze_retired_act_evidence(resources: FullRuntimeResources) -> None:
    """Copy local B12 carrier integrity into its in-memory report before cleanup can remove files."""
    snapshot = resources.retired_act_evidence
    if snapshot.status == creation.B12_STATUS_NOT_SELECTED:
        return
    path = resources.temporary_root / creation.B12_MATRIX_DIRECTORY / creation.B12_ATTEMPTS_FILE
    marker_path = path.parent / creation.B12_MARKER_FILE
    if not path.exists():
        if marker_path.exists() or snapshot.carrier.get(creation.B12Field.FRAMING) != creation.B12_FRAMING_NOT_CREATED:
            snapshot.status = creation.B12_STATUS_UNPROVEN
            snapshot.evidence_failure = creation.B12_DETAIL_MISSING_CARRIER
            snapshot.carrier[creation.B12Field.READ_ERROR] = snapshot.evidence_failure
        return
    try:
        raw = path.read_bytes()
        embedded = creation.embedded_b12_evidence_bytes(snapshot)
        snapshot.carrier.update(
            {
                creation.B12Field.ATTEMPTS_PATH: resources.sanitize(str(path.resolve())),
                creation.B12Field.ORIGINAL_SHA256: hashlib.sha256(raw).hexdigest(),
                creation.B12Field.ORIGINAL_BYTE_COUNT: len(raw),
                creation.B12Field.FRAMING: (
                    creation.B12_FRAMING_COMPLETE
                    if not raw or raw.endswith(_LINE_BREAK.encode(_UTF8))
                    else creation.B12_FRAMING_PARTIAL
                ),
                creation.B12Field.RAW_TEXT: resources.sanitize(raw.decode(_UTF8, errors=_UTF8_REPLACEMENT))[
                    :_DIAGNOSTIC_LIMIT
                ],
                creation.B12Field.RAW_TEXT_TRUNCATED: len(raw) > _DIAGNOSTIC_LIMIT,
                creation.B12Field.EMBEDDED_SHA256: hashlib.sha256(embedded).hexdigest(),
                creation.B12Field.EMBEDDED_BYTE_COUNT: len(embedded),
                creation.B12Field.EMBEDDED_SCOPE: creation.B12_EMBEDDED_SCOPE,
            }
        )
        try:
            records = creation.validate_b12_attempts(raw, complete=snapshot.status == creation.B12_STATUS_COMPLETE)
            snapshot.carrier[creation.B12Field.LINE_COUNT] = len(records)
        except Exception as error:
            snapshot.status = creation.B12_STATUS_UNPROVEN
            snapshot.evidence_failure = creation.B12_EXCEPTION_DETAIL.format(
                error_class=type(error).__name__, detail=error
            )
            snapshot.carrier[creation.B12Field.READ_ERROR] = snapshot.evidence_failure
    except Exception as error:
        snapshot.status = creation.B12_STATUS_UNPROVEN
        snapshot.evidence_failure = creation.B12_EXCEPTION_DETAIL.format(error_class=type(error).__name__, detail=error)
        snapshot.carrier[creation.B12Field.READ_ERROR] = snapshot.evidence_failure
    if path.exists():
        try:
            marker_raw = marker_path.read_bytes()
            snapshot.carrier[creation.B12Field.MARKER_PATH] = resources.sanitize(str(marker_path.resolve()))
            if hashlib.sha256(marker_raw).hexdigest() != snapshot.carrier.get(creation.B12Field.MARKER_SHA256) or len(
                marker_raw
            ) != snapshot.carrier.get(creation.B12Field.MARKER_BYTE_COUNT):
                raise ValueError(creation.B12_CARRIER_ERROR_MARKER)
        except Exception as error:
            snapshot.status = creation.B12_STATUS_UNPROVEN
            snapshot.evidence_failure = creation.B12_EXCEPTION_DETAIL.format(
                error_class=type(error).__name__, detail=error
            )
            snapshot.carrier[creation.B12Field.READ_ERROR] = snapshot.evidence_failure
    completed_path = path.parent / creation.B12_COMPLETED_FILE
    if snapshot.status == creation.B12_STATUS_COMPLETE and not completed_path.is_file():
        snapshot.status = creation.B12_STATUS_UNPROVEN
        snapshot.evidence_failure = creation.B12_DETAIL_COMPLETED_SNAPSHOT
        snapshot.carrier[creation.B12Field.COMPLETED_READ_ERROR] = snapshot.evidence_failure
    elif completed_path.is_file():
        try:
            expected_completed_hash = snapshot.carrier.get(creation.B12Field.COMPLETED_SHA256)
            expected_completed_bytes = snapshot.carrier.get(creation.B12Field.COMPLETED_BYTE_COUNT)
            completed_raw = completed_path.read_bytes()
            completed = json.loads(completed_raw)
            snapshot.carrier.update(
                {
                    creation.B12Field.COMPLETED_PATH: resources.sanitize(str(completed_path.resolve())),
                    creation.B12Field.COMPLETED_SHA256: hashlib.sha256(completed_raw).hexdigest(),
                    creation.B12Field.COMPLETED_BYTE_COUNT: len(completed_raw),
                    creation.B12Field.COMPLETED_RAW_TEXT: resources.sanitize(
                        completed_raw.decode(_UTF8, errors=_UTF8_REPLACEMENT)
                    )[:_DIAGNOSTIC_LIMIT],
                    creation.B12Field.COMPLETED_RAW_TEXT_TRUNCATED: len(completed_raw) > _DIAGNOSTIC_LIMIT,
                    creation.B12Field.COMPLETED_READ_ERROR: _EMPTY,
                }
            )
            if snapshot.status == creation.B12_STATUS_COMPLETE and (
                not isinstance(completed, dict)
                or completed.get(creation.B12Field.STATUS) != creation.B12_STATUS_COMPLETE
                or completed.get(creation.B12Field.ORDERED_RESULTS) != snapshot.cases
                or completed.get(creation.B12Field.ATTEMPTS_SHA256)
                != snapshot.carrier.get(creation.B12Field.ORIGINAL_SHA256)
                or completed.get(creation.B12Field.ATTEMPTS_BYTE_COUNT)
                != snapshot.carrier.get(creation.B12Field.ORIGINAL_BYTE_COUNT)
                or completed.get(creation.B12Field.ATTEMPTS_LINE_COUNT)
                != snapshot.carrier.get(creation.B12Field.LINE_COUNT)
                or hashlib.sha256(completed_raw).hexdigest() != expected_completed_hash
                or len(completed_raw) != expected_completed_bytes
            ):
                raise ValueError(creation.B12_DETAIL_COMPLETED_SNAPSHOT)
        except Exception as error:
            snapshot.status = creation.B12_STATUS_UNPROVEN
            snapshot.evidence_failure = creation.B12_EXCEPTION_DETAIL.format(
                error_class=type(error).__name__, detail=error
            )
            snapshot.carrier[creation.B12Field.COMPLETED_READ_ERROR] = snapshot.evidence_failure


def _freeze_b13_profile_evidence(resources: FullRuntimeResources) -> None:
    """Validate B13's existing external report seal before any full-profile removal branch."""
    marker = resources.b13_marker_path
    carrier = resources.b13_carrier_path
    if marker is None or carrier is None or resources.b13_evidence.carrier.get("owned") is not True:
        return
    try:
        valid = (
            waiting.verify_b13_delivery(resources.b13_evidence, marker, carrier, resources.sanitize)
            if resources.b13_evidence.status == waiting.B13_STATUS_COMPLETE
            else waiting.verify_b13_seal(resources.b13_evidence, marker, carrier)
        )
        if not valid:
            raise ValueError(waiting.B13_ERROR_SEAL)
    except Exception as error:
        resources.b13_evidence.status = waiting.B13_STATUS_UNPROVEN
        resources.b13_evidence.evidence_failure = resources.sanitize(f"{type(error).__name__}: {error}")
        waiting.capture_b13_attempt_ledger(resources.b13_evidence, marker, resources.sanitize)
        resources.retain_key(waiting.B13_RETENTION_KEY, waiting.B13_RETENTION_REASON)


def _remove_legacy_profile_resources(resources: FullRuntimeResources, failures: list[str]) -> None:
    """Keep the existing fixture/temp removal mechanics together; newly provisional runs retain both."""
    if resources.fixture_setup is not None and foundation.remove_fixture(resources.fixture_setup):
        failures.append(_FULL_FIXTURE_CLEANUP_ERROR)
    try:
        _remove_temporary_profile_root(resources)
    except OSError:
        failures.append(_FULL_TEMP_CLEANUP_ERROR)


def _finish_public_cleanup(
    resources: FullRuntimeResources,
    cleanup_evidence: list[CommandEvidence],
    failures: list[str],
    *,
    has_retained_marker: bool,
) -> None:
    """Finish all public restoration/logout and original terminal disposal before the supported stop call."""
    try:
        if not has_retained_marker and not resources.retained:
            _restore_full_profile_changes(resources, cleanup_evidence)
    except Exception:
        failures.append(_FULL_CONFIG_RESTORE_ERROR)
    for terminal in (resources.member_terminal, resources.admin_terminal):
        if terminal is None:
            continue
        try:
            logout_status, logout_output = _record_terminal_command(
                resources,
                terminal,
                _AUTH_LOGOUT_COMMAND,
                cleanup_evidence,
            )
            _require_terminal_success(logout_status, logout_output, cleanup_evidence)
        except Exception:
            failures.append(_FULL_TERMINAL_CLEANUP_ERROR)
    if isinstance(resources.release_world, ReleaseWorld):
        try:
            _close_release_world(resources.release_world, cleanup_evidence)
        except Exception:
            failures.append(_FULL_TERMINAL_CLEANUP_ERROR)
    for terminal in (resources.member_terminal, resources.admin_terminal):
        if terminal is None:
            continue
        try:
            terminal.close()
        except Exception:
            failures.append(_FULL_TERMINAL_CLEANUP_ERROR)
    resources.public_cleanup_finished_ns = time.monotonic_ns()


def _stop_profile_runtime(
    resources: FullRuntimeResources, cleanup_evidence: list[CommandEvidence], failures: list[str]
) -> None:
    """Attempt the supported P3 once after public work; later file/marker errors never erase its actual result."""
    if not resources.install_attempted:
        return
    stop_outcome = resources.temporary_root / _STOP_OUTCOME_NAME
    resources.daemon_stop_started_ns = time.monotonic_ns()
    try:
        result = _record_external_command(
            resources,
            (*_SERVICE_STOP_COMMAND, f"{_STOP_OUTCOME_VARIABLE}={stop_outcome}"),
            cwd=resources.source_root,
            timeout_seconds=_STOP_COMMAND_TIMEOUT_SECONDS,
            evidence=cleanup_evidence,
        )
        resources.daemon_stop_execution = result
        if result.exit_status != _PROCESS_SUCCESS or result.diagnostics:
            failures.append(_FULL_SERVICE_STOP_ERROR)
    except Exception as error:
        resources.daemon_stop_error = resources.sanitize(f"{type(error).__name__}: {error}")
        failures.append(_FULL_SERVICE_STOP_ERROR)
    try:
        recorded = stop_outcome.read_text(encoding=_UTF8).strip() if stop_outcome.is_file() else _EMPTY
        resources.daemon_stop_outcome = recorded
        if resources.workflow_flow is not None:
            resources.workflow_flow.record_profile_stop(recorded)
        if recorded != _STOPPED_OUTCOME:
            resources.retained.append(_FULL_STOP_UNPROVEN.format(outcome=recorded or "none"))
    except Exception as error:
        detail = resources.sanitize(f"{type(error).__name__}: {error}")
        resources.daemon_stop_error = _CLEANUP_FAILURE_SEPARATOR.join(
            item for item in (resources.daemon_stop_error, detail) if item
        )
        failures.append(_FULL_SERVICE_STOP_ERROR)
    finally:
        resources.daemon_stop_finished_ns = time.monotonic_ns()


def _close_full_profile_resources(
    resources: FullRuntimeResources,
    cleanup_evidence: list[CommandEvidence],
) -> None:
    """Perform public cleanup before P3, preserving new-run resources and every independent failure for outside closure."""
    b12_status_before_freeze = resources.retired_act_evidence.status
    _freeze_retired_act_evidence(resources)
    if (
        b12_status_before_freeze == creation.B12_STATUS_COMPLETE
        and resources.retired_act_evidence.status != creation.B12_STATUS_COMPLETE
    ):
        resources.retained.append(creation.B12_DETAIL_POSTFREEZE)
    _freeze_b13_profile_evidence(resources)
    failures: list[str] = []
    has_retained_marker = _record_retained_workflow_markers(resources)
    _finish_public_cleanup(resources, cleanup_evidence, failures, has_retained_marker=has_retained_marker)
    _stop_profile_runtime(resources, cleanup_evidence, failures)
    if resources.payload_provisional is not None:
        work_end = positive_integer(parse_object(resources.payload_provisional.binding_bytes), "payload_end_ns")
        stop = resources.daemon_stop_execution
        resources.inner_cleanup = InnerCleanupEvidence(
            resources.public_cleanup_finished_ns or 0,
            resources.daemon_stop_started_ns,
            resources.daemon_stop_finished_ns,
            resources.daemon_stop_outcome,
            stop.exit_status if stop is not None else None,
            stop.diagnostics if stop is not None else _EMPTY,
            resources.daemon_stop_error,
            work_end,
            tuple(failures),
            tuple(resources.retained),
        )
    if resources.retained:
        failures.append(_FULL_UNPROVEN_RETAINED.format(reasons=_CLEANUP_FAILURE_SEPARATOR.join(resources.retained)))
    elif resources.payload_provisional is None:
        _remove_legacy_profile_resources(resources, failures)
    if failures:
        raise RuntimeError(_FULL_CLEANUP_FAILURE.format(failures=_CLEANUP_FAILURE_SEPARATOR.join(failures)))
    if resources.payload_provisional is not None:
        if resources.inner_cleanup is not None and resources.inner_cleanup.pending_physical:
            raise PhysicalCleanupPending(ScenarioStatus.P4_PENDING_OUTER.value)
        raise RuntimeError(_FULL_STOP_UNPROVEN.format(outcome=resources.daemon_stop_outcome or "none"))


def _run_readiness_check(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    deadline = time.monotonic() + _READINESS_WINDOW_SECONDS
    while time.monotonic() < deadline:
        result = _record_external_command(
            resources,
            _SERVICE_STATUS_COMMAND,
            cwd=resources.source_root,
            timeout_seconds=_FULL_COMMAND_TIMEOUT_SECONDS,
            evidence=evidence,
        )
        if result.exit_status == _PROCESS_SUCCESS and not result.diagnostics:
            return
        payload_work.sleep(_READINESS_POLL_INTERVAL_SECONDS)
    raise RuntimeError(_EXPECTED_READINESS_ERROR)


def _read_health_body(socket_path: str, timeout_seconds: float) -> bytes | None:
    """Read bounded HTTP bytes with one deadline across connect, headers and body."""
    command_end = payload_work.command_end(timeout_seconds)
    expired = threading.Event()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(payload_work.remaining(command_end))

            def expire() -> None:
                expired.set()
                try:
                    connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    # Deadline expiry can race an unconnected or already-closed socket.
                    pass

            timer = threading.Timer(payload_work.remaining(command_end), expire)
            timer.start()
            try:
                connection.connect(socket_path)
                if expired.is_set():
                    return None
                connection.sendall(_HEALTH_HTTP_REQUEST)
                with http.client.HTTPResponse(connection) as response:
                    response.begin()
                    if response.status != http.HTTPStatus.OK:
                        return None
                    body = response.read(_HEALTH_RESPONSE_LIMIT_BYTES + 1)
            finally:
                timer.cancel()
                timer.join()
    except (ConnectionError, FileNotFoundError, TimeoutError):
        return None
    except http.client.HTTPException:
        if expired.is_set():
            return None
        raise
    return None if expired.is_set() else body


def _read_daemon_instance(socket_path: str, timeout_seconds: float) -> DaemonInstance | None:
    """Observe the public local health identity; a closed socket is a transition state."""
    body = _read_health_body(socket_path, timeout_seconds)
    if body is None:
        return None
    if len(body) > _HEALTH_RESPONSE_LIMIT_BYTES:
        raise ValueError(_HEALTH_INSTANCE_INVALID)
    health = _mapping_value(json.loads(body))
    preparation = _mapping_value(health.get(_HEALTH_PREPARATION_FIELD)) if health is not None else None
    if preparation is None:
        raise ValueError(_HEALTH_INSTANCE_INVALID)
    pid, token = preparation.get(_HEALTH_PID_FIELD), preparation.get(_HEALTH_TOKEN_FIELD)
    if type(pid) is not int or pid <= 0 or not isinstance(token, str) or not token:
        raise ValueError(_HEALTH_INSTANCE_INVALID)
    return DaemonInstance(pid, token)


def _await_config_restart(
    resources: FullRuntimeResources, evidence: list[CommandEvidence], previous: DaemonInstance
) -> None:
    """Wait for a different process instance before applying the ordinary readiness gate."""
    deadline = time.monotonic() + _READINESS_WINDOW_SECONDS
    while (remaining := deadline - time.monotonic()) > 0:
        instance = _read_daemon_instance(_HEALTH_SOCKET_PATH, min(_HEALTH_OBSERVATION_TIMEOUT_SECONDS, remaining))
        if instance is not None and instance != previous:
            _run_readiness_check(resources, evidence)
            return
        remaining = deadline - time.monotonic()
        if remaining > 0:
            payload_work.sleep(min(_READINESS_POLL_INTERVAL_SECONDS, remaining))
    raise RuntimeError(_HEALTH_INSTANCE_UNCHANGED)


class _FoundationRunner:
    """The profile\'s side of journey F0: the owner terminal, bounded child processes and retained evidence."""

    def __init__(self, resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
        self._resources = resources
        self._evidence = evidence

    @property
    def environment(self) -> Mapping[str, str]:
        """The profile\'s allowlisted child environment."""
        return self._resources.environment

    def cli(self, argv: Sequence[str], timeout_seconds: float, *, retain: bool = True) -> foundation.Outcome:
        """Run one fresh public CLI process on the authenticated owner terminal."""
        terminal = self._resources.open_admin_terminal()
        command_evidence: list[CommandEvidence] = []
        status, output = _record_terminal_command(self._resources, terminal, argv, command_evidence, timeout_seconds)
        if retain:
            self._evidence.extend(command_evidence)
        recorded = command_evidence[-1] if command_evidence else None
        return foundation.Outcome(
            status,
            output,
            stderr=recorded.stderr if recorded is not None else _EMPTY,
            diagnostics=recorded.diagnostics if recorded is not None else _EMPTY,
            duration_seconds=recorded.duration_seconds if recorded is not None else 0.0,
        )

    def process(
        self, argv: Sequence[str], cwd: Path, environment: Mapping[str, str], timeout_seconds: float
    ) -> foundation.Outcome:
        """Run one bounded child process and retain its sanitized evidence."""
        result = _run_bounded_process(argv, cwd=cwd, environment=environment, timeout_seconds=timeout_seconds)
        self._evidence.append(
            CommandEvidence(
                argv=tuple(self._resources.sanitize(value) for value in argv),
                exit_status=result.exit_status,
                duration_seconds=result.duration_seconds,
                stdout=self._resources.sanitize(result.stdout)[:_DIAGNOSTIC_LIMIT],
                stderr=self._resources.sanitize(result.stderr)[:_DIAGNOSTIC_LIMIT],
                diagnostics=result.diagnostics,
            )
        )
        return foundation.Outcome(
            result.exit_status,
            f"{result.stdout}{result.stderr}",
            diagnostics=result.diagnostics,
            duration_seconds=result.duration_seconds,
        )

    def note(self, argv: Sequence[str], outcome: foundation.Outcome, diagnostics: str) -> None:
        """Retain bounded evidence of a command the fixture ran inside its pane."""
        stdout = self._resources.sanitize(outcome.output)
        stderr = self._resources.sanitize(outcome.stderr)
        detail = self._resources.sanitize(diagnostics)
        command_diagnostics = self._resources.sanitize(outcome.diagnostics)
        truncations: list[str] = []
        if len(stdout) > _DIAGNOSTIC_LIMIT:
            truncations.append(_EVIDENCE_STDOUT_TRUNCATION)
        if len(stderr) > _DIAGNOSTIC_LIMIT:
            truncations.append(_EVIDENCE_STDERR_TRUNCATION)
        if len(detail) > _DIAGNOSTIC_LIMIT or len(command_diagnostics) > _DIAGNOSTIC_LIMIT:
            truncations.append(_EVIDENCE_DIAGNOSTICS_TRUNCATION)
        diagnostic_parts = tuple(value for value in (detail, command_diagnostics, *truncations) if value)
        retained_diagnostics = _EVIDENCE_SEPARATOR.join(diagnostic_parts)
        if len(retained_diagnostics) > _DIAGNOSTIC_LIMIT:
            marker_size = len(_EVIDENCE_SEPARATOR) + len(_EVIDENCE_DIAGNOSTICS_TRUNCATION)
            retained_diagnostics = (
                retained_diagnostics[: _DIAGNOSTIC_LIMIT - marker_size]
                + _EVIDENCE_SEPARATOR
                + _EVIDENCE_DIAGNOSTICS_TRUNCATION
            )
        self._evidence.append(
            CommandEvidence(
                argv=tuple(self._resources.sanitize(value) for value in argv),
                exit_status=outcome.exit_status,
                duration_seconds=outcome.duration_seconds,
                stdout=stdout[:_DIAGNOSTIC_LIMIT],
                stderr=stderr[:_DIAGNOSTIC_LIMIT],
                diagnostics=retained_diagnostics[:_DIAGNOSTIC_LIMIT],
            )
        )


def _install_native_fixture(
    resources: FullRuntimeResources, installer_environment: dict[str, str], evidence: list[CommandEvidence]
) -> None:
    """Install the inert agent executable before the supported installation, and prove the installer will find it."""
    home = installer_environment.get(_COLD_HOME_VARIABLE)
    if not home:
        raise RuntimeError(_FULL_HOME_REQUIRED)
    setup = foundation.fixture_paths(Path(home), resources.temporary_root)
    foundation.install_fixture(resources.source_root, setup)
    resources.fixture_setup = setup
    installer_environment[_PATH_VARIABLE] = _PATH_SEPARATOR.join(
        (str(setup.executable.parent), installer_environment.get(_PATH_VARIABLE, _EMPTY))
    )
    foundation.require_owned_resolution(
        _FoundationRunner(resources, evidence),
        setup,
        installer_environment,
        resources.source_root,
        _FIXTURE_INSTALLER_WHERE,
        login=False,
    )


def _require_manual_runner(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    """Read the machine configuration through the public path and require the manual workflow runner."""
    terminal = resources.open_admin_terminal()
    computer, _, _ = _read_computer_config(resources, terminal, evidence)
    workflow = _mapping_value(computer.get(_MACHINE_WORKFLOW_SECTION))
    if workflow is None or workflow.get(_MACHINE_WORKFLOW_RUNNER_FIELD) != _WORKFLOW_RUNNER_MANUAL:
        raise ValueError(_FULL_WORKFLOW_RUNNER_NOT_MANUAL)


def _full_workflow_foundation(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    """Journey F0: native fixture binding, public self identity, startup admission and close."""
    setup = resources.fixture_setup
    if setup is None or resources.project_path is None:
        raise ValueError(_FULL_FOUNDATION_PREREQUISITES)
    runner = _FoundationRunner(resources, evidence)
    _require_manual_runner(resources, evidence)
    home = resources.environment.get(_COLD_HOME_VARIABLE)
    if not home:
        raise RuntimeError(_FULL_HOME_REQUIRED)
    uv_executable = shutil.which(_UV_EXECUTABLE, path=resources.environment.get(_PATH_VARIABLE))
    login_directories = [setup.executable.parent]
    if uv_executable is not None:
        login_directories.append(Path(uv_executable).parent)
    written = foundation.put_tools_on_login_path(Path(home), login_directories)
    if written:
        runner.note((_LOGIN_PROFILE_NOTE,), foundation.Outcome(_PROCESS_SUCCESS, written), _EMPTY)
    foundation.require_owned_resolution(
        runner,
        setup,
        foundation.owner_login_environment(resources.environment),
        resources.source_root,
        _FIXTURE_LOGIN_WHERE,
        login=True,
    )
    foundation.run_foundation(runner, setup, resources.project_path, _OWNER_SEED_EMAIL)


def _full_workflow_creation(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    """Journey R1: plain creation, the acknowledgement gate and the manual runner's absence of sessions."""
    if resources.project_path is None:
        raise ValueError(_FULL_FOUNDATION_PREREQUISITES)
    creation.run_creation(_FoundationRunner(resources, evidence), resources.project_path, resources.source_root)


def _full_workflow_retired_acts(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    """Journey R4, optionally extended by B12's approved retired-act vocabulary matrix."""
    if resources.project_path is None:
        if resources.retired_act_selected:
            resources.retired_act_evidence.selected_amendment = creation.B12_AMENDMENT
            resources.retired_act_evidence.status = creation.B12_STATUS_UNPROVEN
            resources.retired_act_evidence.primary_failure = _FULL_FOUNDATION_PREREQUISITES
        raise ValueError(_FULL_FOUNDATION_PREREQUISITES)
    runner = _FoundationRunner(resources, evidence)
    if resources.retired_act_selected:
        started_at = time.monotonic()
        resources.retired_act_deadline = started_at + creation.B12_SCENARIO_SECONDS
        resources.retired_act_evidence.selected_amendment = creation.B12_AMENDMENT
        resources.retired_act_evidence.status = creation.B12_STATUS_PARTIAL
        try:
            _full_owner_identity(resources, evidence)
            resources.retired_act_evidence.prerequisites[creation.B12Field.OWNER_IDENTITY] = dict(
                resources.owner_identity_facts
            )
            creation.run_retired_act_matrix(
                runner,
                resources.project_path,
                resources.source_root,
                resources.temporary_root,
                resources.retired_act_evidence,
                resources.retained.append,
                lambda reason: resources.retained.remove(reason) if reason in resources.retained else None,
                resources.sanitize,
                started_at=started_at,
            )
        except KeyboardInterrupt as error:
            if not resources.retired_act_evidence.primary_failure:
                resources.retired_act_evidence.status = creation.B12_STATUS_UNPROVEN
                resources.retired_act_evidence.primary_failure = resources.sanitize(
                    creation.B12_INTERRUPT_DETAIL.format(detail=error)
                )
            resources.retired_act_evidence.duration_seconds = max(
                resources.retired_act_evidence.duration_seconds, time.monotonic() - started_at
            )
            raise
        except Exception as error:
            if not resources.retired_act_evidence.primary_failure:
                resources.retired_act_evidence.status = creation.B12_STATUS_UNPROVEN
                resources.retired_act_evidence.primary_failure = resources.sanitize(
                    creation.B12_EXCEPTION_DETAIL.format(error_class=type(error).__name__, detail=error)
                )
            resources.retired_act_evidence.duration_seconds = max(
                resources.retired_act_evidence.duration_seconds, time.monotonic() - started_at
            )
            raise
        finally:
            resources.retired_act_deadline = None
    else:
        creation.run_retired_acts(runner, resources.project_path, resources.source_root)


def _full_workflow_b12(resources: FullRuntimeResources, _evidence: list[CommandEvidence]) -> None:
    """Require R4's amendment run to have a complete, sealed upload-carried matrix snapshot."""
    del _evidence
    snapshot = resources.retired_act_evidence
    if not resources.retired_act_selected or snapshot.status != creation.B12_STATUS_COMPLETE:
        raise ValueError(creation.B12_DETAIL_MODE)
    if len(snapshot.cases) != len(creation.B12_CASES) or any(
        case.get("classification") != creation.B12_CLASS_VERIFIED for case in snapshot.cases
    ):
        raise ValueError(creation.B12_DETAIL_SIXTEEN)


def _full_workflow_plans(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    """Journey R2: plan creation and the task lane outside the v2 machine."""
    if resources.project_path is None:
        raise ValueError(_FULL_FOUNDATION_PREREQUISITES)
    plans.run_plans(_FoundationRunner(resources, evidence), resources.project_path, resources.source_root)


def _full_workflow_holds(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    """Journey R3: the public hold and release, with no phase override."""
    if resources.project_path is None:
        raise ValueError(_FULL_FOUNDATION_PREREQUISITES)
    holds.run_holds(_FoundationRunner(resources, evidence), resources.project_path, resources.source_root)


def _full_workflow_removal(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    """Journey R5: soft removal and restoration of a plain preparation item."""
    if resources.project_path is None:
        raise ValueError(_FULL_FOUNDATION_PREREQUISITES)
    removal.run_removal(_FoundationRunner(resources, evidence), resources.project_path, resources.source_root)


def _full_workflow_claim(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    """Journey B1: an explicit prepare starts the real driver, which claims with its reservation."""
    setup = resources.fixture_setup
    if setup is None or resources.project_path is None:
        raise ValueError(_FULL_FOUNDATION_PREREQUISITES)
    claim.run_claim(
        _FoundationRunner(resources, evidence),
        setup,
        resources.project_path,
        resources.source_root,
        _OWNER_SEED_EMAIL,
        lambda: _register_procedure_fixture_company(resources, evidence),
        resources.retained.append,
    )


def _full_workflow_race(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    """Journey B2: a start in progress refuses a distinct requester, and a race leaves one driver."""
    setup = resources.fixture_setup
    if setup is None or resources.project_path is None:
        raise ValueError(_FULL_FOUNDATION_PREREQUISITES)
    race.run_race(
        _FoundationRunner(resources, evidence),
        setup,
        resources.project_path,
        resources.source_root,
        _OWNER_SEED_EMAIL,
        lambda: _register_procedure_fixture_company(resources, evidence),
        resources.retained.append,
    )


def _full_workflow_waiting(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    """Journey B3: a driver waits on the owner, a dispatched session cannot decide, the owner's own session can."""
    setup = resources.fixture_setup
    if (
        setup is None
        or resources.project_path is None
        or resources.project_slug is None
        or resources.project_name is None
    ):
        raise ValueError(_FULL_FOUNDATION_PREREQUISITES)
    resources.b13_marker_path = setup.control.parent / waiting.B13_DIRECTORY / waiting.B13_MARKER_FILE
    if resources.report_path is not None:
        resources.b13_carrier_path = resources.report_path.with_name(
            resources.report_path.name + waiting.B13_CARRIER_SUFFIX
        )
    waiting.run_waiting(
        _FoundationRunner(resources, evidence),
        setup,
        resources.project_path,
        resources.source_root,
        _OWNER_SEED_EMAIL,
        _OWNER_SEED_SLUG,
        resources.project_slug,
        resources.project_name,
        lambda: _register_procedure_fixture_company(resources, evidence),
        resources.retained.append,
        resources.retain_key,
        resources.release_key,
        resources.report_path,
        resources.source_revision,
        resources.source_tree,
        resources.b13_evidence,
        resources.sanitize,
        accounting=resources.early_accounting("B3"),
    )


def _full_workflow_prepared(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    """Journey B4: prepared names the judged body, a moved body refuses prepared and work, the work driver claims."""
    setup = resources.fixture_setup
    if setup is None or resources.project_path is None:
        raise ValueError(_FULL_FOUNDATION_PREREQUISITES)
    if resources.project_slug is None:
        raise ValueError(_FULL_FOUNDATION_PREREQUISITES)
    event_binding = events.load_binding(setup.control.parent)
    resources.retained.append(f"B10 event evidence retained at {event_binding.carrier_root}")
    prepared.run_prepared(
        _FoundationRunner(resources, evidence),
        setup,
        resources.project_path,
        resources.source_root,
        _OWNER_SEED_EMAIL,
        _OWNER_SEED_SLUG,
        resources.report_path or resources.temporary_root / "runtime-acceptance-report.json",
        resources.project_slug,
        event_binding,
        lambda: _register_procedure_fixture_company(resources, evidence),
        resources.retained.append,
        accounting=resources.early_accounting("B4"),
    )


def _full_workflow_review(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    """Journey B5: continue the B4 work item through review acts, stamp refusals and re-stamp."""
    setup = resources.fixture_setup
    if setup is None or resources.project_path is None or resources.project_slug is None:
        raise ValueError(_FULL_FOUNDATION_PREREQUISITES)
    event_binding = events.load_binding(setup.control.parent)
    events.verify_case(event_binding, "B4")
    event_previous_seal = events.seal_for(event_binding, "B4")
    resources.retained.append(f"B10 event evidence retained at {event_binding.carrier_root}")
    if resources.workflow_flow is None:
        resources.workflow_flow = full_flow.WorkflowFlow(
            host=_FoundationRunner(resources, evidence),
            setup=setup,
            source_root=resources.source_root,
            project=resources.project_path,
            owner_email=_OWNER_SEED_EMAIL,
            project_slug=resources.project_slug,
            chain=resources.workflow_chain,
            register_company=lambda: _register_procedure_fixture_company(resources, evidence),
            retain=resources.retained.append,
            event_window=event_binding,
            event_previous_seal=event_previous_seal,
            event_case_seal=event_previous_seal,
            payload_provisional=resources.payload_provisional,
        )
    flow = resources.workflow_flow
    try:
        flow.attach(_FoundationRunner(resources, evidence))
        if flow.ledger is None:
            flow.setup_flow()
        review.run_b5(flow)
    except BaseException as error:
        flow.finalize(str(error))
        raise


def _full_workflow_ready(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    """Journey B7: return a held ready item to work, observe exact message keyed requests and re-stamp."""
    if resources.workflow_flow is None:
        raise ValueError(_FULL_FOUNDATION_PREREQUISITES)
    resources.workflow_flow.attach(_FoundationRunner(resources, evidence))
    ready.run_b7(resources.workflow_flow)


def _full_workflow_integration(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    """Journey B6: admit only the registry claimant and observe real integration and delivery."""
    if resources.workflow_flow is None:
        raise ValueError(_FULL_FOUNDATION_PREREQUISITES)
    resources.workflow_flow.attach(_FoundationRunner(resources, evidence))
    integration.run_b6(resources.workflow_flow)


def _full_install_and_ready(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    resources.install_attempted = True
    installer_environment = dict(resources.environment)
    installer_environment[_ENV_OWNER_NAME_VARIABLE] = _OWNER_SEED_NAME
    installer_environment[_ENV_OWNER_EMAIL_VARIABLE] = _OWNER_SEED_EMAIL
    installer_environment.pop(_CI_VARIABLE, None)
    _install_native_fixture(resources, installer_environment, evidence)
    install_result = _run_bounded_process(
        (str(resources.source_root / _INSTALLER_COMMAND[0]), *_INSTALLER_COMMAND[1:]),
        cwd=resources.source_root,
        environment=installer_environment,
        timeout_seconds=_INSTALL_COMMAND_TIMEOUT_SECONDS,
    )
    diagnostics = _EMPTY
    if install_result.exit_status != _PROCESS_SUCCESS or install_result.diagnostics:
        max_process_diagnostic_chars = (
            _DIAGNOSTIC_LIMIT - len(_INSTALLER_LOG_LABEL) - len(_INSTALLER_LOG_TRUNCATION_MARKER) - 1
        )
        process_diagnostics = resources.sanitize(install_result.diagnostics)[:max_process_diagnostic_chars]
        diagnostic_prefix = f"{process_diagnostics}{_DIAGNOSTIC_SEPARATOR}" if process_diagnostics else _EMPTY
        installer_log_diagnostic: str
        try:
            log_budget = max(
                1,
                _DIAGNOSTIC_LIMIT
                - len(diagnostic_prefix)
                - len(_INSTALLER_LOG_LABEL)
                - len(_INSTALLER_LOG_TRUNCATION_MARKER),
            )
            with (resources.source_root / _INSTALLER_LOG_PATH).open(_BINARY_READ_MODE) as installer_log:
                installer_log.seek(0, os.SEEK_END)
                log_size = installer_log.tell()
                log_start = max(0, log_size - log_budget)
                installer_log.seek(log_start)
                log_excerpt = installer_log.read(log_budget).decode(_UTF8, errors=_UTF8_REPLACEMENT)
            truncation_marker = _INSTALLER_LOG_TRUNCATION_MARKER if log_start else _EMPTY
            available_log_chars = max(
                1,
                _DIAGNOSTIC_LIMIT - len(diagnostic_prefix) - len(_INSTALLER_LOG_LABEL) - len(truncation_marker),
            )
            sanitized_log_excerpt = resources.sanitize(log_excerpt)
            installer_log_diagnostic = (
                f"{_INSTALLER_LOG_LABEL}{truncation_marker}{sanitized_log_excerpt[-available_log_chars:]}"
            )
        except OSError as error:
            installer_log_diagnostic = _INSTALLER_LOG_UNAVAILABLE.format(error_class=type(error).__name__)[
                : _DIAGNOSTIC_LIMIT - len(diagnostic_prefix)
            ]
        diagnostics = f"{diagnostic_prefix}{installer_log_diagnostic}"[:_DIAGNOSTIC_LIMIT]
    evidence.append(
        CommandEvidence(
            argv=tuple(resources.sanitize(value) for value in _INSTALLER_COMMAND),
            exit_status=install_result.exit_status,
            duration_seconds=install_result.duration_seconds,
            stdout=resources.sanitize(install_result.stdout)[:_DIAGNOSTIC_LIMIT]
            if install_result.exit_status != _PROCESS_SUCCESS or install_result.diagnostics
            else _EMPTY,
            stderr=resources.sanitize(install_result.stderr)[:_DIAGNOSTIC_LIMIT]
            if install_result.exit_status != _PROCESS_SUCCESS or install_result.diagnostics
            else _EMPTY,
            diagnostics=diagnostics,
        )
    )
    if install_result.exit_status != _PROCESS_SUCCESS or install_result.diagnostics:
        raise RuntimeError(_FULL_INSTALL_ERROR)
    terminal = resources.open_admin_terminal()
    login_status, login_output = _record_terminal_command(
        resources,
        terminal,
        (*_AUTH_LOGIN_PREFIX, _OWNER_SEED_EMAIL),
        evidence,
    )
    _require_terminal_success(login_status, login_output, evidence)
    _disable_external_adapters(resources, evidence)
    resources.start_attempted = True
    start_result = _record_external_command(
        resources,
        _SERVICE_START_COMMAND,
        cwd=resources.source_root,
        timeout_seconds=_START_COMMAND_TIMEOUT_SECONDS,
        evidence=evidence,
    )
    _require_process_success(start_result)
    _run_readiness_check(resources, evidence)
    computer_status, computer_output = _record_terminal_command(
        resources,
        terminal,
        _COMPUTERS_LIST_COMMAND,
        evidence,
    )
    _require_terminal_success(computer_status, computer_output, evidence)
    if not _computer_list_has_ready_local(computer_output):
        raise ValueError(_EXPECTED_COMPUTER_LIST_ERROR)


def _full_owner_identity(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    terminal = resources.open_admin_terminal()
    whoami_status, whoami_output = _record_terminal_command(
        resources,
        terminal,
        _AUTH_WHOAMI_COMMAND,
        evidence,
    )
    _require_terminal_success(whoami_status, whoami_output, evidence)
    whoami = _parse_whoami_fields(whoami_output)
    if whoami is None or whoami.email != _OWNER_SEED_EMAIL or whoami.role != _ADMIN_ROLE:
        raise ValueError(_EXPECTED_OWNER_WHOAMI_ERROR)
    person_status, person_output = _record_terminal_command(
        resources,
        terminal,
        (*_CONFIG_PERSON_GET_PREFIX, _OWNER_SEED_SLUG, _FORMAT_OPTION, _JSON_FORMAT),
        evidence,
    )
    _require_terminal_success(person_status, person_output, evidence)
    if not _owner_record_is_administrator(person_output):
        raise ValueError(_EXPECTED_PERSON_IDENTITY_ERROR)
    resources.owner_identity_facts = {
        creation.B12Field.EMAIL: whoami.email,
        creation.B12Field.ROLE: whoami.role,
        creation.B12Field.PERSON_IS_ADMINISTRATOR: True,
    }


def _full_configuration_change(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    terminal = resources.open_admin_terminal()
    computer, revision, _ = _read_computer_config(resources, terminal, evidence)
    computer = _computer_identity(computer)
    original_timezone = computer.get(_MACHINE_TIMEZONE_FIELD)
    if not isinstance(original_timezone, str):
        raise ValueError(_FULL_CONFIG_SHAPE_INVALID)
    unrelated_role = computer.get(_COMPUTER_ROLE_FIELD)
    if not isinstance(unrelated_role, str):
        raise ValueError(_FULL_CONFIG_SHAPE_INVALID)
    timezone = _TIMEZONE_EUROPE_AMSTERDAM if original_timezone == _TIMEZONE_UTC else _TIMEZONE_UTC
    resources.original_timezone = original_timezone
    resources.expected_timezone = timezone
    resources.unrelated_computer_role = unrelated_role
    previous_instance = _read_daemon_instance(_HEALTH_SOCKET_PATH, _HEALTH_OBSERVATION_TIMEOUT_SECONDS)
    if previous_instance is None:
        raise RuntimeError(_EXPECTED_READINESS_ERROR)
    adapter_patch: JSONObject = {
        section_name: {_MACHINE_ADAPTER_ENABLED_FIELD: False} for section_name in _MACHINE_ADAPTER_SECTIONS
    }
    patch: JSONObject = {
        _CONFIG_COMPUTER_FIELD: {_MACHINE_TIMEZONE_FIELD: timezone},
        _MACHINE_WORKFLOW_SECTION: {_MACHINE_WORKFLOW_RUNNER_FIELD: _WORKFLOW_RUNNER_MANUAL},
        **adapter_patch,
    }
    _patch_configuration(resources, terminal, _CONFIG_COMPUTER_PATCH_PREFIX, revision, patch, evidence)
    verified_terminal = resources.open_admin_terminal()
    verified_machine, new_revision, _ = _read_computer_config(resources, verified_terminal, evidence)
    verified = _computer_identity(verified_machine)
    if verified.get(_MACHINE_TIMEZONE_FIELD) != timezone:
        raise ValueError(_EXPECTED_VALID_PATCH_ERROR)
    if verified.get(_COMPUTER_ROLE_FIELD) != unrelated_role:
        raise ValueError(_FULL_STATE_CHANGED)
    if new_revision == revision:
        raise ValueError(_EXPECTED_REVISION_CHANGE_ERROR)
    verified_workflow = _mapping_value(verified_machine.get(_MACHINE_WORKFLOW_SECTION))
    if verified_workflow is None or verified_workflow.get(_MACHINE_WORKFLOW_RUNNER_FIELD) != _WORKFLOW_RUNNER_MANUAL:
        raise ValueError(_FULL_WORKFLOW_RUNNER_NOT_MANUAL)
    _await_config_restart(resources, evidence, previous_instance)


def _full_project_registration(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    terminal = resources.open_admin_terminal()
    project_name = f"{_PROJECT_NAME_PREFIX}{uuid.uuid4().hex[:_PROJECT_NAME_SUFFIX_LENGTH]}"
    project_path = resources.temporary_root / _PROJECT_DIRECTORY_NAME
    resources.project_name = project_name
    resources.project_slug = project_name
    resources.project_path = project_path
    argv = (*_CONFIG_PROJECT_CREATE_PREFIX, project_name, _PROJECT_PATH_OPTION, str(project_path))
    exit_status, output = _record_terminal_command(resources, terminal, argv, evidence)
    _require_terminal_success(exit_status, output, evidence)
    listing_status, listing_output = _record_terminal_command(
        resources,
        terminal,
        _PROJECTS_LIST_COMMAND,
        evidence,
    )
    _require_terminal_success(listing_status, listing_output, evidence)
    if not _project_list_contains(listing_output, project_name, project_path):
        raise ValueError(_EXPECTED_PROJECT_LIST_ERROR)


def _full_jobs_surface(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    if resources.project_path is None or resources.project_slug is None:
        raise ValueError(_FULL_PROJECT_MISSING)
    fixture_directory = resources.project_path / _JOBS_FIXTURE_DIRECTORY
    fixture_directory.mkdir(parents=True, exist_ok=True)
    fixture_path = resources.project_path / _JOB_INERT_SCRIPT
    fixture_path.write_text(_INERT_JOB_SCRIPT_TEXT, encoding=_UTF8)
    terminal = resources.open_admin_terminal()
    project, revision, _ = _read_project_config(resources, terminal, resources.project_slug, evidence)
    original_jobs = project.get(_PROJECT_CONFIG_JOBS_FIELD, [])
    if not isinstance(original_jobs, list):
        raise ValueError(_FULL_CONFIG_SHAPE_INVALID)
    jobs: list[JSONValue] = [
        cast(
            JSONObject,
            {
                _JOB_NAME_FIELD: _JOB_INERT_NAME,
                _JOB_CATEGORY_FIELD: _JOB_SYSTEM_CATEGORY,
                _JOB_ENABLED_FIELD: True,
                _JOB_SCHEDULE_FIELD: {_JOB_INTERVAL_FIELD: _JOB_INERT_SCHEDULE},
                _JOB_SCRIPT_FIELD: _JOB_INERT_SCRIPT,
            },
        )
    ]
    if original_jobs:
        raise ValueError(_FULL_PROJECT_JOBS_NOT_EMPTY)
    _patch_configuration(
        resources,
        terminal,
        _CONFIG_PROJECT_PATCH_PREFIX + (resources.project_slug,),
        revision,
        {_PROJECT_CONFIG_JOBS_FIELD: jobs},
        evidence,
    )
    terminal_status, _ = _record_terminal_command(
        resources,
        terminal,
        (_SHELL_CHANGE_DIRECTORY, str(resources.project_path)),
        evidence,
    )
    _require_terminal_exit(terminal_status, evidence)
    list_status, list_output = _record_terminal_command(resources, terminal, _JOBS_LIST_COMMAND, evidence)
    _require_terminal_success(list_status, list_output, evidence)
    list_rows = _parse_job_list_rows(list_output)
    matching_list_rows = (
        [row for row in list_rows if row.name == _JOB_INERT_NAME and row.scope == _JOB_LIST_SCOPE_LOCAL]
        if list_rows is not None
        else []
    )
    if len(matching_list_rows) != 1:
        raise ValueError(_EXPECTED_JOB_DISCOVERY_ERROR)
    status_status, status_output = _record_terminal_command(resources, terminal, _JOBS_STATUS_COMMAND, evidence)
    _require_terminal_success(status_status, status_output, evidence)
    status_rows = _parse_job_status_rows(status_output)
    matching_status_rows = (
        [row for row in status_rows if row.name == _JOB_INERT_NAME] if status_rows is not None else []
    )
    if (
        len(matching_status_rows) != 1
        or matching_status_rows[0].last_run != _JOB_STATUS_NEVER
        or matching_status_rows[0].status != _JOB_STATUS_NEVER
    ):
        raise ValueError(_EXPECTED_JOB_NEVER_RUN_ERROR)
    terminal_status, _ = _record_terminal_command(
        resources,
        terminal,
        (_SHELL_CHANGE_DIRECTORY, str(resources.source_root)),
        evidence,
    )
    _require_terminal_exit(terminal_status, evidence)


def _full_restart_persistence(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    resources.start_attempted = True
    restart_result = _record_external_command(
        resources,
        _SERVICE_RESTART_COMMAND,
        cwd=resources.source_root,
        timeout_seconds=_RESTART_COMMAND_TIMEOUT_SECONDS,
        evidence=evidence,
    )
    _require_process_success(restart_result)
    _run_readiness_check(resources, evidence)
    terminal = resources.open_admin_terminal()
    computer, _, _ = _read_computer_config(resources, terminal, evidence)
    computer = _computer_identity(computer)
    if computer.get(_MACHINE_TIMEZONE_FIELD) != resources.expected_timezone:
        raise ValueError(_FULL_STATE_CHANGED)
    if computer.get(_COMPUTER_ROLE_FIELD) != resources.unrelated_computer_role:
        raise ValueError(_FULL_STATE_CHANGED)
    if resources.project_path is None or resources.project_name is None:
        raise ValueError(_FULL_PROJECT_MISSING)
    status, output = _record_terminal_command(resources, terminal, _PROJECTS_LIST_COMMAND, evidence)
    _require_terminal_success(status, output, evidence)
    if not _project_list_contains(output, resources.project_name, resources.project_path):
        raise ValueError(_FULL_STATE_CHANGED)


def _full_non_admin_refusal(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    admin_terminal = resources.open_admin_terminal()
    person_init = (
        *_CONFIG_PERSON_INIT_PREFIX,
        _MEMBER_NAME,
        _EMAIL_OPTION,
        _MEMBER_EMAIL,
        _SLUG_OPTION,
        _MEMBER_SLUG,
        _ROLE_OPTION,
        _MEMBER_ROLE,
    )
    init_status, init_output = _record_terminal_command(resources, admin_terminal, person_init, evidence)
    _require_terminal_success(init_status, init_output, evidence)
    member_terminal = resources.open_member_terminal()
    member_login_status, member_login_output = _record_terminal_command(
        resources,
        member_terminal,
        (*_AUTH_LOGIN_PREFIX, _MEMBER_EMAIL),
        evidence,
    )
    _require_terminal_success(member_login_status, member_login_output, evidence)
    member_identity_status, member_identity_output = _record_terminal_command(
        resources,
        member_terminal,
        _AUTH_WHOAMI_COMMAND,
        evidence,
    )
    _require_terminal_success(member_identity_status, member_identity_output, evidence)
    member_identity = _parse_whoami_fields(member_identity_output)
    if member_identity is None or member_identity.email != _MEMBER_EMAIL or member_identity.role != _MEMBER_ROLE:
        raise ValueError(_EXPECTED_MEMBER_WHOAMI_ERROR)
    computer, revision, before_output = _read_computer_config(resources, admin_terminal, evidence)
    before_state, _ = _machine_state_view(before_output)
    current_timezone = _computer_identity(computer).get(_MACHINE_TIMEZONE_FIELD)
    if not isinstance(current_timezone, str):
        raise ValueError(_FULL_CONFIG_SHAPE_INVALID)
    attempted_timezone = _TIMEZONE_EUROPE_AMSTERDAM if current_timezone == _TIMEZONE_UTC else _TIMEZONE_UTC
    refusal_status, refusal_output = _record_terminal_command(
        resources,
        member_terminal,
        (
            *_CONFIG_COMPUTER_PATCH_PREFIX,
            _REVISION_OPTION,
            revision,
            _YAML_OPTION,
            json.dumps({_CONFIG_COMPUTER_FIELD: {_MACHINE_TIMEZONE_FIELD: attempted_timezone}}),
        ),
        evidence,
    )
    if refusal_status in (_PROCESS_SUCCESS, None) or not refusal_output.strip():
        raise ValueError(_EXPECTED_REFUSAL_ERROR)
    expected_refusal = _member_patch_refusal_matches(refusal_output)
    _, after_revision, after_output = _read_computer_config(resources, admin_terminal, evidence)
    after_state, _ = _machine_state_view(after_output)
    if after_revision != revision or after_state != before_state:
        raise ValueError(_EXPECTED_STATE_PRESERVATION_ERROR)
    if not expected_refusal:
        raise ValueError(_EXPECTED_COMMAND_REFUSAL_ERROR.format(output=resources.sanitize(refusal_output)))


def _full_unknown_key_refusal(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    terminal = resources.open_admin_terminal()
    before_state, revision = _machine_state_view(_read_computer_config(resources, terminal, evidence)[2])
    invalid_patch = {_INVALID_MACHINE_KEY: _UNKNOWN_KEY_PATCH_VALUE}
    refusal_status, refusal_output = _record_terminal_command(
        resources,
        terminal,
        (
            *_CONFIG_COMPUTER_PATCH_PREFIX,
            _REVISION_OPTION,
            revision,
            _YAML_OPTION,
            json.dumps(invalid_patch),
        ),
        evidence,
    )
    _, after_revision, after_output = _read_computer_config(resources, terminal, evidence)
    after_state, _ = _machine_state_view(after_output)
    if after_revision != revision or after_state != before_state:
        raise ValueError(_EXPECTED_STATE_PRESERVATION_ERROR)
    if refusal_status in (_PROCESS_SUCCESS, None) or not refusal_output.strip():
        raise ValueError(_EXPECTED_REFUSAL_ERROR)
    if not _invalid_patch_refusal_matches(resources, refusal_output):
        raise ValueError(_EXPECTED_INVALID_KEY_ERROR.format(output=resources.sanitize(refusal_output)))


def _full_failure_cleanup_probe(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    failure = _run_bounded_process(
        (_FALSE_EXECUTABLE,),
        cwd=resources.source_root,
        environment=resources.environment,
        timeout_seconds=_FULL_COMMAND_TIMEOUT_SECONDS,
    )
    evidence.append(
        CommandEvidence(
            argv=(_FALSE_EXECUTABLE,),
            exit_status=failure.exit_status,
            duration_seconds=failure.duration_seconds,
            diagnostics=failure.diagnostics,
        )
    )
    if failure.exit_status == _PROCESS_SUCCESS:
        raise ValueError(_FULL_FAILURE_PROBE_FAILED)
    timeout = _run_bounded_process(
        (_SLEEP_EXECUTABLE, _TIMEOUT_PROBE_DURATION),
        cwd=resources.source_root,
        environment=resources.environment,
        timeout_seconds=_TIMEOUT_PROBE_SECONDS,
    )
    evidence.append(
        CommandEvidence(
            argv=(_SLEEP_EXECUTABLE, _TIMEOUT_PROBE_DURATION),
            exit_status=timeout.exit_status,
            duration_seconds=timeout.duration_seconds,
            diagnostics=timeout.diagnostics,
        )
    )
    if timeout.diagnostics != _PROCESS_TIMEOUT_DETAIL:
        raise ValueError(_FULL_FAILURE_PROBE_FAILED)


def _full_candidate_identity(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    del evidence
    if not resources.source_root.is_dir() or not resources.source_revision or not resources.source_tree:
        raise ValueError(_FULL_CANDIDATE_IDENTITY_INVALID)


def _procedure_fixture(resources: FullRuntimeResources) -> Mapping[str, object]:
    """Load the scenario-owned source and normalized response contract."""
    fixture_path = resources.source_root / _PROCEDURE_DELIVERY_FIXTURE
    payload = json.loads(fixture_path.read_text(encoding=_UTF8))
    fixture = _mapping_value(payload)
    if fixture is None or _mapping_value(fixture.get("sources")) is None:
        raise ValueError("The procedure event acceptance fixture is malformed.")
    return fixture


def _procedure_fixture_command(
    resources: FullRuntimeResources,
    argv: Sequence[str],
    *,
    cwd: Path,
    evidence: list[CommandEvidence],
    timeout_seconds: float = _FULL_COMMAND_TIMEOUT_SECONDS,
) -> ProcessExecution:
    """Run a bounded command against an isolated source fixture."""
    if argv and argv[0] == str(resources.source_root / _CLI_EXECUTABLE) and tuple(argv[1:3]) == _DOCS_GET_COMMAND:
        return _procedure_fixture_authenticated_read(resources, argv, cwd=cwd, evidence=evidence)
    return _record_external_command(resources, argv, cwd=cwd, timeout_seconds=timeout_seconds, evidence=evidence)


def _procedure_fixture_authenticated_read(
    resources: FullRuntimeResources,
    argv: Sequence[str],
    *,
    cwd: Path,
    evidence: list[CommandEvidence],
) -> ProcessExecution:
    """Keep the public owner's existing login on its real PTY while reading fixture docs."""
    terminal = resources.open_admin_terminal()
    started = time.monotonic()
    try:
        status, output = _record_terminal_command(resources, terminal, (_SHELL_CHANGE_DIRECTORY, str(cwd)), evidence)
        _require_terminal_exit(status, evidence)
        if status != _PROCESS_SUCCESS:
            raise RuntimeError(_FULL_TERMINAL_SETUP_ERROR)
        status, output = _record_terminal_command(resources, terminal, argv, evidence)
        return ProcessExecution(
            exit_status=status if status is not None else _PROCESS_FAILURE,
            stdout=output.replace(_PROCEDURE_FIXTURE_TERMINAL_LINE_ENDING, _LINE_BREAK),
            stderr=_EMPTY,
            duration_seconds=time.monotonic() - started,
            diagnostics=_PROCESS_TIMEOUT_DETAIL if status is None else _EMPTY,
        )
    finally:
        status, output = _record_terminal_command(
            resources, terminal, (_SHELL_CHANGE_DIRECTORY, str(resources.source_root)), evidence
        )
        _require_terminal_exit(status, evidence)
        if status != _PROCESS_SUCCESS:
            raise RuntimeError(_FULL_TERMINAL_SETUP_ERROR)


def _procedure_fixture_success(
    resources: FullRuntimeResources,
    evidence: list[CommandEvidence],
    argv: Sequence[str],
    *,
    cwd: Path,
    timeout_seconds: float = _FULL_COMMAND_TIMEOUT_SECONDS,
) -> ProcessExecution:
    result = _procedure_fixture_command(resources, argv, cwd=cwd, evidence=evidence, timeout_seconds=timeout_seconds)
    if result.exit_status != _PROCESS_SUCCESS or result.diagnostics:
        detail = resources.sanitize(result.stderr or result.stdout or result.diagnostics)
        raise RuntimeError(f"A procedure fixture command failed: {detail[:_DIAGNOSTIC_LIMIT]}")
    return result


def _create_procedure_fixture_checkout(
    resources: FullRuntimeResources,
    fixture_name: str,
    evidence: list[CommandEvidence],
) -> Path:
    """Make a disposable source checkout whose committed docs use the regular publisher."""
    _register_procedure_fixture_company(resources, evidence)
    return _clone_procedure_fixture_checkout(resources, fixture_name, evidence)


def _register_procedure_fixture_company(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    """Register the synthetic owner company the source checkout\'s project declaration names, through the public command."""
    company = _mapping_value(_procedure_fixture(resources).get(_PROCEDURE_FIXTURE_COMPANY_FIELD))
    if company is None:
        raise ValueError(_PROCEDURE_FIXTURE_COMPANY_INVALID)
    company_name = company.get(_PROCEDURE_FIXTURE_COMPANY_NAME_FIELD)
    company_slug = company.get(_PROCEDURE_FIXTURE_COMPANY_SLUG_FIELD)
    if not isinstance(company_name, str) or not company_name or not isinstance(company_slug, str) or not company_slug:
        raise ValueError(_PROCEDURE_FIXTURE_COMPANY_INVALID)
    status, output = _record_terminal_command(
        resources,
        resources.open_admin_terminal(),
        (*_CONFIG_COMPANY_INIT_PREFIX, company_name, _SLUG_OPTION, company_slug),
        evidence,
    )
    _require_terminal_success(status, output, evidence)


def _clone_procedure_fixture_checkout(
    resources: FullRuntimeResources,
    fixture_name: str,
    evidence: list[CommandEvidence],
) -> Path:
    """Clone the source checkout into a disposable one with its dependency environment and a git author."""
    checkout = resources.temporary_root / fixture_name
    clone_argv = (
        _GIT_EXECUTABLE,
        "clone",
        "--quiet",
        "--shared",
        str(resources.source_root),
        str(checkout),
    )
    _procedure_fixture_success(
        resources,
        evidence,
        clone_argv,
        cwd=resources.temporary_root,
        timeout_seconds=_PROCEDURE_FIXTURE_CLONE_TIMEOUT_SECONDS,
    )
    dependency_environment = resources.source_root / _PROCEDURE_FIXTURE_ENVIRONMENT
    if not (dependency_environment / _PYTHON_ENVIRONMENT_EXECUTABLE).is_file():
        raise RuntimeError(_PROCEDURE_FIXTURE_ENVIRONMENT_MISSING)
    (checkout / _PROCEDURE_FIXTURE_ENVIRONMENT).symlink_to(dependency_environment, target_is_directory=True)
    _procedure_fixture_success(
        resources,
        evidence,
        (_GIT_EXECUTABLE, "config", "user.name", _PROCEDURE_FIXTURE_GIT_AUTHOR),
        cwd=checkout,
    )
    _procedure_fixture_success(
        resources,
        evidence,
        (_GIT_EXECUTABLE, "config", "user.email", _PROCEDURE_FIXTURE_GIT_EMAIL),
        cwd=checkout,
    )
    return checkout


def _write_procedure_fixture_sources(
    checkout: Path,
    fixture: Mapping[str, object],
    *,
    include_interruptible: bool,
    include_invalid: bool = False,
) -> None:
    """Materialize only scenario-owned procedure sources into the disposable checkout."""
    sources = _mapping_value(fixture.get("sources"))
    if sources is None:
        raise ValueError("The procedure event acceptance fixture has no sources.")
    for relative_path, content in sources.items():
        if not isinstance(content, str):
            raise ValueError("The procedure event acceptance fixture contains an invalid source.")
        if not include_interruptible and relative_path == str(
            _PROCEDURE_DEPENDENCY_FIXTURE_DIRECTORY / "interruptible.md"
        ):
            continue
        if not include_invalid and "/invalid-" in relative_path:
            continue
        destination = checkout / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(_expand_procedure_fixture_home(content), encoding=_UTF8)


def _expand_procedure_fixture_home(content: str) -> str:
    """Resolve portable fixture home markers before publishing synthetic sources."""
    return content.replace(_PROCEDURE_FIXTURE_HOME_PLACEHOLDER, str(Path.home()))


def _commit_procedure_fixture(checkout: Path, resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    """Commit disposable authored documentation so installed-commit publication can consume it."""
    _procedure_fixture_success(
        resources,
        evidence,
        (
            _GIT_EXECUTABLE,
            "add",
            str(_PROCEDURE_FIXTURE_DIRECTORY),
            str(_PROCEDURE_DEPENDENCY_FIXTURE_DIRECTORY),
        ),
        cwd=checkout,
    )
    _procedure_fixture_success(
        resources,
        evidence,
        (_GIT_EXECUTABLE, "commit", "--quiet", "-m", _PROCEDURE_FIXTURE_COMMIT_MESSAGE),
        cwd=checkout,
    )


def _publish_procedure_fixture(
    checkout: Path,
    resources: FullRuntimeResources,
    evidence: list[CommandEvidence],
) -> ProcessExecution:
    """Run the public install publication entry point for one committed fixture revision."""
    return _procedure_fixture_command(
        resources,
        (
            _UV_EXECUTABLE,
            _UV_PROJECT_SUBCOMMAND,
            _UV_PROJECT_OPTION,
            str(resources.source_root),
            _UV_NO_SYNC_OPTION,
            _PYTHON_EXECUTABLE,
            "-m",
            _PROCEDURE_FIXTURE_INSTALL_MODULE,
        ),
        cwd=checkout,
        evidence=evidence,
        timeout_seconds=_PROCEDURE_FIXTURE_PUBLICATION_TIMEOUT_SECONDS,
    )


def _closure_response_blocks(output: str) -> list[str]:
    """Split only snippet openings, retaining each metadata/body divider."""
    return [_CLI_SNIPPET_ID_PREFIX + block for block in output.split(_CLI_SNIPPET_BLOCK_SEPARATOR)[1:]]


def _closure_block_ids(output: str) -> list[str]:
    """Read the ordered IDs from the public CLI's normalized Markdown response blocks."""
    blocks = _closure_response_blocks(output)
    identifiers: list[str] = []
    for block in blocks:
        for line in block.splitlines():
            if line.startswith(_CLI_SNIPPET_ID_PREFIX):
                identifiers.append(line.removeprefix(_CLI_SNIPPET_ID_PREFIX))
                break
    return identifiers


def _procedure_closure_snapshot_diff(expected: str, actual: str, resources: FullRuntimeResources) -> str:
    """Return a bounded, sanitized unified diff for a mismatched public closure body."""
    diff = "".join(
        difflib.unified_diff(
            resources.sanitize(expected).splitlines(keepends=True),
            resources.sanitize(actual).splitlines(keepends=True),
            fromfile=_PROCEDURE_CLOSURE_SNAPSHOT_DIFF_EXPECTED,
            tofile=_PROCEDURE_CLOSURE_SNAPSHOT_DIFF_ACTUAL,
            n=_PROCEDURE_CLOSURE_SNAPSHOT_DIFF_CONTEXT,
        )
    )
    if len(diff) <= _PROCEDURE_CLOSURE_SNAPSHOT_DIFF_LIMIT:
        return diff
    return diff[:_PROCEDURE_CLOSURE_SNAPSHOT_DIFF_LIMIT] + _LINE_BREAK + _PROCEDURE_CLOSURE_SNAPSHOT_DIFF_TRUNCATION


def _normalize_procedure_closure_snapshot_body(body: str) -> str:
    """Drop only the Required reads directive and trailing blank lines from an expected source body."""
    normalized_lines: list[str] = []
    in_required_reads = False
    for line in body.splitlines(keepends=True):
        stripped_line = line.strip()
        if stripped_line == _PROCEDURE_REQUIRED_READS_HEADER:
            in_required_reads = True
            continue
        if in_required_reads and stripped_line.startswith(_PROCEDURE_MARKDOWN_H2_PREFIX):
            in_required_reads = False
        if not in_required_reads:
            normalized_lines.append(line)
    return "".join(normalized_lines).rstrip(_LINE_BREAK)


def _check_procedure_closure_snapshot(
    resources: FullRuntimeResources,
    output: str,
    snapshot: Mapping[str, object],
    fixture: Mapping[str, object],
) -> None:
    expected_ids = snapshot.get("included_ids")
    if not isinstance(expected_ids, list) or not all(isinstance(item, str) for item in expected_ids):
        raise ValueError("A procedure closure response snapshot is malformed.")
    blocks = _closure_response_blocks(output)
    actual_ids = _closure_block_ids(output)
    if actual_ids != expected_ids:
        raise ValueError(f"The public procedure closure did not match its ordered response snapshot: {actual_ids!r}")
    sources = _mapping_value(fixture.get("sources"))
    if sources is None:
        raise ValueError("The procedure closure fixture has no authored body snapshots.")
    expected_blocks: dict[str, str] = {}
    for relative_path, content in sources.items():
        if (
            not isinstance(content, str)
            or not relative_path.startswith("docs/global/")
            or not relative_path.endswith(".md")
        ):
            continue
        content = _expand_procedure_fixture_home(content)
        frontmatter = content.split("---\n", 2)
        if len(frontmatter) != 3:
            raise ValueError(f"The authored response snapshot has malformed frontmatter: {relative_path}")
        description = next(
            (
                line.removeprefix("description: ")
                for line in frontmatter[1].splitlines()
                if line.startswith("description: ")
            ),
            None,
        )
        if not description:
            raise ValueError(f"The authored response snapshot has no description: {relative_path}")
        snippet_id = relative_path.removeprefix("docs/global/").removesuffix(".md")
        frontmatter[2] = frontmatter[2].lstrip(_LINE_BREAK)
        expected_blocks[snippet_id] = (
            f"id: {snippet_id}\ntype: procedure\ndomain: general\nscope: global\n"
            f"description: {description}\n---\n{frontmatter[2]}"
        )
        expected_blocks[snippet_id] = _normalize_procedure_closure_snapshot_body(expected_blocks[snippet_id])
    for snippet_id, block in zip(actual_ids, blocks, strict=True):
        expected = expected_blocks.get(snippet_id, _EMPTY)
        if block.rstrip(_LINE_BREAK) != expected:
            detail = _PROCEDURE_CLOSURE_SNAPSHOT_MISMATCH.format(snippet_id=snippet_id)
            diff = _procedure_closure_snapshot_diff(expected, block, resources)
            raise ValueError(detail + _LINE_BREAK + diff)


def _restore_procedure_fixture_publication(
    resources: FullRuntimeResources,
    evidence: list[CommandEvidence],
) -> None:
    """Restore this checkout's committed publication after disposable fixture assertions."""
    result = _publish_procedure_fixture(resources.source_root, resources, evidence)
    if result.exit_status != _PROCESS_SUCCESS or result.diagnostics:
        detail = resources.sanitize(result.stderr or result.stdout or result.diagnostics)
        raise RuntimeError(f"Could not restore the installed documentation generation: {detail[:_DIAGNOSTIC_LIMIT]}")


def _full_procedure_closure(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    fixture = _procedure_fixture(resources)
    closures = _mapping_value(fixture.get("closures"))
    if closures is None:
        raise ValueError("The procedure event acceptance fixture has no closure snapshots.")
    checkout = _create_procedure_fixture_checkout(resources, "procedure-closure-fixture", evidence)
    try:
        _write_procedure_fixture_sources(checkout, fixture, include_interruptible=True)
        _commit_procedure_fixture(checkout, resources, evidence)
        lint = _procedure_fixture_success(
            resources,
            evidence,
            (str(resources.source_root / _CLI_EXECUTABLE), "code", "lint", "--all"),
            cwd=checkout,
            timeout_seconds=_PROCEDURE_FIXTURE_VALIDATION_TIMEOUT_SECONDS,
        )
        if not lint.stdout.strip() and not lint.stderr.strip():
            raise ValueError("The public documentation validation command returned no evidence.")
        publication = _publish_procedure_fixture(checkout, resources, evidence)
        if publication.exit_status != _PROCESS_SUCCESS or publication.diagnostics:
            raise RuntimeError(
                "The valid procedure fixture did not pass normal documentation publication: "
                + resources.sanitize(publication.stderr or publication.stdout or publication.diagnostics)
            )
        for snapshot_name in (_PROCEDURE_CLOSURE_SEQUENTIAL, _PROCEDURE_CLOSURE_BATCHED):
            snapshot = _mapping_value(closures.get(snapshot_name))
            if snapshot is None or not isinstance(snapshot.get("id"), str):
                raise ValueError(f"The {snapshot_name} closure response snapshot is malformed.")
            result = _procedure_fixture_success(
                resources,
                evidence,
                (
                    str(resources.source_root / _CLI_EXECUTABLE),
                    *_DOCS_GET_COMMAND,
                    cast(str, snapshot["id"]),
                    _DOCS_CLOSURE_OPTION,
                ),
                cwd=checkout,
            )
            _check_procedure_closure_snapshot(resources, result.stdout, snapshot, fixture)

        missing_id = fixture.get("missing_dependency")
        if not isinstance(missing_id, str):
            raise ValueError("The procedure event acceptance fixture has no missing dependency identity.")
        (checkout / _PROCEDURE_DEPENDENCY_FIXTURE_DIRECTORY / "interruptible.md").unlink()
        _commit_procedure_fixture(checkout, resources, evidence)
        publication = _publish_procedure_fixture(checkout, resources, evidence)
        if publication.exit_status != _PROCESS_SUCCESS or publication.diagnostics:
            raise RuntimeError("The intentionally incomplete dependency fixture could not be published.")
        batched_snapshot = _mapping_value(closures.get(_PROCEDURE_CLOSURE_BATCHED))
        if batched_snapshot is None or not isinstance(batched_snapshot.get("id"), str):
            raise ValueError("The batched closure response snapshot is malformed.")
        result = _procedure_fixture_command(
            resources,
            (
                str(resources.source_root / _CLI_EXECUTABLE),
                *_DOCS_GET_COMMAND,
                cast(str, batched_snapshot["id"]),
                _DOCS_CLOSURE_OPTION,
            ),
            cwd=checkout,
            evidence=evidence,
        )
        if (
            result.exit_status == _PROCESS_SUCCESS
            or _PROCEDURE_FIXTURE_MISSING_DEPENDENCY_ERROR not in (result.stdout + result.stderr)
            or missing_id not in (result.stdout + result.stderr)
        ):
            raise ValueError("The public closure accepted or misidentified a missing mandatory instruction.")
    finally:
        _restore_procedure_fixture_publication(resources, evidence)


def _full_delivery_declaration_validation(
    resources: FullRuntimeResources,
    evidence: list[CommandEvidence],
) -> None:
    fixture = _procedure_fixture(resources)
    invalid = _mapping_value(fixture.get("invalid"))
    if invalid is None:
        raise ValueError("The invalid procedure declaration fixture is malformed.")
    invalid_ids = invalid.get("ids")
    if not isinstance(invalid_ids, list) or not all(isinstance(item, str) for item in invalid_ids):
        raise ValueError("The invalid procedure declaration identities are malformed.")
    fields = invalid.get("fields")
    if not isinstance(fields, list) or not all(isinstance(field, str) for field in fields):
        raise ValueError("The invalid procedure declaration fields are malformed.")
    checkout = _create_procedure_fixture_checkout(resources, "procedure-invalid-fixture", evidence)
    try:
        _write_procedure_fixture_sources(checkout, fixture, include_interruptible=True, include_invalid=True)
        _commit_procedure_fixture(checkout, resources, evidence)
        validation = _procedure_fixture_command(
            resources,
            (str(resources.source_root / _CLI_EXECUTABLE), "code", "lint", "--all"),
            cwd=checkout,
            evidence=evidence,
            timeout_seconds=_PROCEDURE_FIXTURE_VALIDATION_TIMEOUT_SECONDS,
        )
        validation_text = validation.stdout + validation.stderr
        if validation.exit_status == _PROCESS_SUCCESS or any(field not in validation_text for field in fields):
            raise ValueError("Public documentation validation did not reject every invalid delivery field.")
        publication = _publish_procedure_fixture(checkout, resources, evidence)
        if publication.exit_status == _PROCESS_SUCCESS:
            raise ValueError("Normal publication accepted an invalid procedure delivery declaration.")
        for invalid_id in invalid_ids:
            retrieval = _procedure_fixture_command(
                resources,
                (
                    str(resources.source_root / _CLI_EXECUTABLE),
                    *_DOCS_GET_COMMAND,
                    invalid_id,
                    _DOCS_CLOSURE_OPTION,
                ),
                cwd=checkout,
                evidence=evidence,
            )
            if retrieval.exit_status == _PROCESS_SUCCESS:
                raise ValueError("An invalid procedure declaration became active after publication was refused.")
    finally:
        _restore_procedure_fixture_publication(resources, evidence)


def _restart_runtime(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    """Restart the disposable runtime through its public service command and wait for readiness."""
    resources.start_attempted = True
    restart_result = _record_external_command(
        resources,
        _SERVICE_RESTART_COMMAND,
        cwd=resources.source_root,
        timeout_seconds=_RESTART_COMMAND_TIMEOUT_SECONDS,
        evidence=evidence,
    )
    _require_process_success(restart_result)
    _run_readiness_check(resources, evidence)


def _archive_transcript_path(resources: FullRuntimeResources) -> Path:
    home = Path(resources.environment[_COLD_HOME_VARIABLE])
    return home.joinpath(*_ARCHIVE_TRANSCRIPT_ROOT, _ARCHIVE_PROJECT_DIRECTORY, f"{_ARCHIVE_NATIVE_ID}.jsonl")


def _write_archive_transcript(resources: FullRuntimeResources) -> Path:
    """Place a synthetic native transcript no session record claims under the runtime's agent root."""
    path = _archive_transcript_path(resources)
    path.parent.mkdir(parents=True, exist_ok=True)
    working_directory = str(resources.project_path or resources.source_root)
    user_timestamp, assistant_timestamp = _ARCHIVE_TRANSCRIPT_TIMESTAMPS
    entries: list[JSONObject] = [
        {
            "type": "user",
            "timestamp": user_timestamp,
            "cwd": working_directory,
            "sessionId": _ARCHIVE_NATIVE_ID,
            "message": {"role": "user", "content": _ARCHIVE_USER_TURN.format(term=_ARCHIVE_SEARCH_TERM)},
        },
        {
            "type": "assistant",
            "timestamp": assistant_timestamp,
            "cwd": working_directory,
            "sessionId": _ARCHIVE_NATIVE_ID,
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": _ARCHIVE_ASSISTANT_TURN.format(term=_ARCHIVE_SEARCH_TERM)}],
            },
        },
    ]
    lines = [json.dumps(entry) for entry in entries]
    path.write_text(_LINE_BREAK.join(lines) + _LINE_BREAK, encoding=_UTF8)
    return path


def _archived_conversation_rows(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> list[object]:
    """The search rows that name the archived conversation, read through a fresh public CLI process."""
    terminal = resources.open_admin_terminal()
    status, output = _record_terminal_command(
        resources, terminal, (*_HISTORY_SEARCH_PREFIX, _ARCHIVE_SEARCH_TERM, _JSON_OPTION), evidence
    )
    if status != _PROCESS_SUCCESS:
        return []
    payload = _structured_value(output)
    return list(payload) if isinstance(payload, list) else []


def _await_archived_conversation(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> str:
    """Wait for the runtime to archive the transcript; the TeleClaude identity of its one conversation."""
    deadline = time.monotonic() + _ARCHIVE_ADOPTION_WINDOW_SECONDS
    while time.monotonic() < deadline:
        rows = _archived_conversation_rows(resources, evidence)
        if len(rows) == 1:
            row = _mapping_value(rows[0])
            identity = row.get("tc_id") if row is not None else None
            if isinstance(identity, str) and identity:
                return identity
        payload_work.sleep(_ARCHIVE_POLL_INTERVAL_SECONDS)
    raise ValueError(_ARCHIVE_ADOPTION_ERROR)


def _archived_conversation_matches(conversation_text: str) -> bool:
    """Compare the retrieved conversation body with the snapshot of what the archived transcript renders to."""
    expected = (Path(__file__).parent / _ARCHIVED_CONVERSATION_SNAPSHOT).read_text(encoding=_UTF8)
    return conversation_text.strip() + _LINE_BREAK == expected


def _require_archived_history(
    resources: FullRuntimeResources, evidence: list[CommandEvidence], requested_id: str, conversation_id: str
) -> None:
    """History retrieval by one identity returns the archived conversation under the TeleClaude identity."""
    terminal = resources.open_admin_terminal()
    status, output = _record_terminal_command(
        resources, terminal, (*_HISTORY_SHOW_PREFIX, requested_id, _JSON_OPTION), evidence
    )
    detail = _mapping_value(_structured_value(output))
    message_count = detail.get(_MESSAGE_COUNT_FIELD) if detail is not None else None
    if (
        status != _PROCESS_SUCCESS
        or detail is None
        or detail.get(_TELECLAUDE_ID_FIELD) != conversation_id
        or not isinstance(message_count, int)
        or message_count < _MINIMUM_ARCHIVED_MESSAGES
        or not _archived_conversation_matches(str(detail.get(_CONVERSATION_TEXT_FIELD, _EMPTY)))
    ):
        raise ValueError(_ARCHIVE_RETRIEVAL_ERROR)


def _full_archived_history(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    transcript = _write_archive_transcript(resources)
    _restart_runtime(resources, evidence)
    conversation_id = _await_archived_conversation(resources, evidence)
    _require_archived_history(resources, evidence, conversation_id, conversation_id)
    _require_archived_history(resources, evidence, _ARCHIVE_NATIVE_ID, conversation_id)
    transcript.unlink()
    _restart_runtime(resources, evidence)
    _require_archived_history(resources, evidence, conversation_id, conversation_id)


def _full_curation_refusal(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    terminal = resources.open_admin_terminal()
    before_status, before_listing = _record_terminal_command(resources, terminal, _MEMORIES_LIST_COMMAND, evidence)
    _require_terminal_success(before_status, before_listing, evidence)
    _require_empty_memory_listing(before_listing)
    expected_refusals = (Path(__file__).parent / _CURATION_REFUSALS_SNAPSHOT).read_text(encoding=_UTF8).splitlines()
    for operation, expected in zip(_CURATION_REFUSED_COMMANDS, expected_refusals, strict=True):
        status, output = _record_terminal_command(
            resources, terminal, (*_MEMORIES_COMMAND_PREFIX, *operation), evidence
        )
        if status in (_PROCESS_SUCCESS, None) or _LINE_BREAK.join(output.splitlines()).strip() != expected:
            raise ValueError(_CURATION_NOT_REFUSED_ERROR)
    after_status, after_listing = _record_terminal_command(resources, terminal, _MEMORIES_LIST_COMMAND, evidence)
    _require_terminal_success(after_status, after_listing, evidence)
    _require_empty_memory_listing(after_listing)


def _require_empty_memory_listing(output: str) -> None:
    """Bind the fixture's empty public result without treating PTY layout as memory state."""
    expected = (Path(__file__).parent / _EMPTY_MEMORY_LIST_SNAPSHOT).read_text(encoding=_UTF8)
    observed = output.replace(_PTY_LINE_ENDING, _LINE_BREAK)
    # The terminal wrapper emits one separator newline before its status marker.
    if not observed.endswith(_LINE_BREAK) or observed.removesuffix(_LINE_BREAK) != expected:
        raise ValueError(_CURATION_MEMORY_LISTING_ERROR)


def _cold_entrypoint_scenario(
    source_root: Path,
    child_environment: Mapping[str, str],
    dependency_environment: Path,
) -> ScenarioResult:
    """Exercise the reviewed cold public entry points from one prospective source tree."""
    command_rows = (
        ((str(_CLI_EXECUTABLE), *_CLI_HELP_ARGUMENTS), child_environment),
        ((str(_CLI_EXECUTABLE), *_CLI_CODE_HELP_ARGUMENTS), child_environment),
        ((str(_CLI_EXECUTABLE), *_CLI_VERSION_ARGUMENTS), child_environment),
    )
    evidence: list[CommandEvidence] = []
    scenario_started = time.monotonic()
    for argv, command_environment in command_rows:
        result = _run_bounded_process(
            argv,
            cwd=source_root,
            environment=command_environment,
            timeout_seconds=_COMMAND_TIMEOUT_SECONDS,
        )
        evidence.append(
            CommandEvidence(
                argv=argv,
                exit_status=result.exit_status,
                duration_seconds=result.duration_seconds,
                stdout=_sanitize_report_text(result.stdout, source_root, dependency_environment, child_environment),
                stderr=_sanitize_report_text(result.stderr, source_root, dependency_environment, child_environment),
                diagnostics=result.diagnostics,
            )
        )
        if result.exit_status != _PROCESS_SUCCESS or not result.stdout.strip() or result.diagnostics:
            return ScenarioResult(
                scenario_id=_SCENARIO_COLD,
                status=ScenarioStatus.FAILED,
                duration_seconds=time.monotonic() - scenario_started,
                commands=tuple(evidence),
                diagnostics=_SCENARIO_PUBLIC_RESULT,
            )
    module_environment = dict(child_environment)
    module_environment[_PYTHON_PATH_VARIABLE] = str(source_root)
    module_environment[_PATH_VARIABLE] = (
        f"{dependency_environment / _PYTHON_ENVIRONMENT_EXECUTABLE.parent}"
        f"{_PATH_SEPARATOR}{module_environment[_PATH_VARIABLE]}"
    )
    module_argv = (
        _PYTHON_EXECUTABLE,
        *_MODULE_HELP_ARGUMENTS,
    )
    module_result = _run_bounded_process(
        module_argv,
        cwd=source_root,
        environment=module_environment,
        timeout_seconds=_COMMAND_TIMEOUT_SECONDS,
    )
    evidence.append(
        CommandEvidence(
            argv=module_argv,
            exit_status=module_result.exit_status,
            duration_seconds=module_result.duration_seconds,
            stdout=_sanitize_report_text(
                module_result.stdout,
                source_root,
                dependency_environment,
                module_environment,
            ),
            stderr=_sanitize_report_text(
                module_result.stderr,
                source_root,
                dependency_environment,
                module_environment,
            ),
            diagnostics=module_result.diagnostics,
        )
    )
    passed = (
        module_result.exit_status == _PROCESS_SUCCESS
        and bool(module_result.stdout.strip())
        and not module_result.diagnostics
    )
    return ScenarioResult(
        scenario_id=_SCENARIO_COLD,
        status=ScenarioStatus.PASSED if passed else ScenarioStatus.FAILED,
        duration_seconds=time.monotonic() - scenario_started,
        commands=tuple(evidence),
        diagnostics=_EMPTY if passed else _SCENARIO_PUBLIC_RESULT,
    )


_RELEASE_FIXTURE = Path("tools/ci/fixtures/release_checkout.json")
_RELEASE_ROOT_DIRECTORY = "release"
_RELEASE_ORIGIN_DIRECTORY = "origin"
_RELEASE_INSTALL_DIRECTORY = "install"
_RELEASE_AWAY_DIRECTORY = "origin-away"
_RELEASE_PROBE_DIRECTORY = "probe"
_RELEASE_DEVELOPMENT_DIRECTORY = "development"
_RELEASE_SECOND_INSTALL = "second"
_RELEASE_PRIMARY_INSTALL = "primary"
_RELEASE_TIMEOUT_SECONDS = 180
_RELEASE_FILE_LIST_LIMIT_BYTES = 16 * 1024 * 1024
_RELEASE_BRANCH = "main"
_RELEASE_CHANNEL = "beta"
_RELEASE_BRANCH_REF = "refs/heads/main"
_RELEASE_ATTACHED_BRANCH = "attached-release"
_RELEASE_NOTE_FILE = "RELEASE.txt"
_RELEASE_DEVELOPMENT_FILE = "dev.txt"
_RELEASE_PYPROJECT = "pyproject.toml"
_RELEASE_DECLARATION = "teleclaude.yml"
_RELEASE_PROJECTS_REGISTRY = "projects.yaml"
_RELEASE_AGENT_HOME_DIRECTORY = ".claude"
_RELEASE_PENDING_RECORD = Path("state") / "self_update_pending.json"
_RELEASE_CONFIG_FILE = "config.yml"
_RELEASE_VENV = ".venv"
_RELEASE_EVENT_FILE = "release-event.json"
_RELEASE_EVENT_TYPE = "github.release"
_RELEASE_EVENT_SOURCE = "runtime-acceptance"
_RELEASE_EVENT_TIME = "2026-01-01T00:00:00Z"
_RELEASE_EVENT_HOME = "none"
_RELEASE_EVENT_ACTION = "published"
_RELEASE_VERSION_PATTERN = r'version\s*=\s*"[^"]+"'
_RELEASE_VERSION_TEMPLATE = 'version="{version}"'
_RELEASE_SCHEMA_PATTERN = r"^schema_version: (\d+)$"
_RELEASE_DECLARATION_MAINTENANCE_INDENT = "    "
_RELEASE_BLOCK_INDENT = "      "
_RELEASE_POSTURE_ACTION = "release-posture"
_RELEASE_UPDATE_ACTION = "self-update"
_RELEASE_MARKER_ACTION = "release-marker"
_RELEASE_MODULE_SELF_UPDATE = "teleclaude.deployment.self_update"
_RELEASE_MODULE_POSTURE = "teleclaude.deployment.release_checkout"
_RELEASE_MODULE_DRAIN = "teleclaude.core.integration.post_commit_maintenance"
_RELEASE_MODULE_MIGRATIONS = "teleclaude.config.migrations"
_RELEASE_MODULE_PUBLISH = "teleclaude.core.integration.publish_action"
_RELEASE_MODULE_INSTALL_PUBLICATION = "teleclaude.entrypoints.install_publication"
_RELEASE_HOME_OPTION = "--home"
_RELEASE_HOME_ROOT = "."
_RELEASE_PUBLICATION_STATE = Path(".teleclaude") / "publication" / "homes.yaml"
_RELEASE_PUBLICATION_ROOT_PREFIX = ".: "
_RELEASE_PUBLICATION_ERROR = "Publication did not deploy the installed release commit."
_RELEASE_OUTPUT_MISSING_ERROR = "A deployed output of the installed release is missing: {output}"
_RELEASE_OUTPUT_SOURCE_ERROR = "A deployed output does not come from the installed release commit: {output}"
_RELEASE_PROBE_DOCUMENT = Path("docs/local/concept/release-probe.md")
_RELEASE_PROBE_BASELINES = (Path("docs/local/baseline.md"), Path("docs/local/baseline-progressive.md"))
_RELEASE_PROBE_SKILL = Path("agents/local/skills/release-probe/SKILL.md")
_RELEASE_PROBE_SKILLS_MASTER = Path("agents/global/skills/AGENTS.master.md")
_RELEASE_MASTER_NAME = "AGENTS.master.md"
_RELEASE_PROBE_LABEL = "Release probe {version}"
_RELEASE_PROBE_DEVELOPMENT_LABEL = "Release probe development {identity}"
_RELEASE_PROBE_DOCUMENT_TEXT = (
    "---\ndescription: {label}\n---\n\n# Release Probe — Concept\n\n## What\n\n{label}\n\n## Why\n\n"
    "It lets the release journeys tell which commit was published.\n"
)
_RELEASE_PROBE_SKILL_TEXT = (
    "---\nname: release-probe\ndescription: Report the installed release identity.\n---\n\n"
    "# Release Probe Skill\n\n{label}\n\n## Steps\n\n1. Report the label above.\n"
)
_RELEASE_PROBE_MASTER_TEXT = "# Release probe master\n\n{label}\n"
_RELEASE_PROBE_SKILLS_TEXT = "# Release probe skills\n"
_RELEASE_DEPLOYED_SKILL = Path(".claude") / "skills" / "release-probe" / "SKILL.md"
_RELEASE_DEPLOYED_MASTER = Path("AGENTS.md")
_RELEASE_DEPLOYED_INDEX = Path("docs") / "local" / "index.yaml"
_RELEASE_PUBLISHED_DOMAIN = "general"
_RELEASE_FRONTMATTER_FENCE = "---"
_RELEASE_FIELD_SEPARATOR = ": "
_RELEASE_ENTRY_START = "- "
_RELEASE_ENTRY_CONTINUATION = "  "
_RELEASE_DESCRIPTION_FIELD = "description"
_RELEASE_CATALOG_PATH_FIELD = "path"
_RELEASE_CATALOG_ID_FIELD = "id"
_RELEASE_PROBE_CATALOG_ID = "local/projects/release-fixture/concept/release-probe"
_RELEASE_BLUEPRINT_SNAPSHOT = Path("snapshots") / "release-blueprint-query.txt"
_RELEASE_RETRY_REFUSAL_SNAPSHOT = Path("snapshots") / "release-retry-refusal.txt"
_RELEASE_REFUSAL_ERROR = "The refused command did not return the public clearance refusal."
_RELEASE_BLUEPRINT_QUERY_ERROR = "The Blueprint query did not answer for the installed commit with its snapshot result."
_RELEASE_LOCAL_BIN = Path(".local") / "bin"
_RELEASE_PERSON_EMAIL = "release-owner@probe.invalid"
_RELEASE_GLOBAL_TEXT = (
    "kind: global\npeople:\n- name: Release Owner\n  email: {email}\n  slug: release-owner\n  role: admin\n"
    "schema_version: {schema_version}\n"
)
_RELEASE_TELEC_MODULE = "teleclaude.cli.telec"
_RELEASE_CONVERGENCE_MODULE = "teleclaude.entrypoints.docs_layout_convergence"
_RELEASE_NEUTRAL_STEPS = (("install", "install_command"), ("plumbing-convergence", "marker_command"))
_RELEASE_LEGACY_ID = "id: projects/"
_RELEASE_CURRENT_ID = "id: local/projects/"
_RELEASE_WRITE_PROTECTED_MODE = 0o500
_RELEASE_PROTECTED_DIRECTORY = "skills"
_RELEASE_WRITABLE_MODE = 0o700
_RELEASE_BLUEPRINT_MANIFEST = Path(".teleclaude") / "blueprint" / "manifest.json"
_RELEASE_BLUEPRINT_BASELINE_FIELD = "baseline_sha"
_RELEASE_BLUEPRINT_AFFECTED_PATH = "tools/ci/release_marker.py"
_RELEASE_BLUEPRINT_ERROR = "Blueprint maintenance did not publish a generation for the installed release commit."
_RELEASE_TERMINAL_ERROR = "The release journey terminal could not be prepared or a command in it failed: {argv}"
_RELEASE_REPLAY_PRESERVE_ERROR = "A failed publication did not leave the previous deployment in place."
_RELEASE_CATALOG_ERROR = "Catalog refresh did not rebuild the stale catalog from the installed release commit."
_RELEASE_INVALID_DECLARATION_ERROR = "An invalid retained declaration was not refused or its stored bytes changed."
_RELEASE_INVALID_AGENTS = "agents:\n  enabled: false"
_RELEASE_VALID_AGENTS = "agents:\n  enabled: true"
_RELEASE_INVALID_HELP_DESK = "help_desk:\n  enabled: true\n"
_RELEASE_REPLAY_ACTION = "sync"
_RELEASE_BEFORE_OPTION = "--before-sha"
_RELEASE_MAINTENANCE_DIRECTORY = Path(".teleclaude") / "maintenance"
_RELEASE_REPLAY_RECORD = "sync.json"
_RELEASE_RECORD_STATE_FIELD = "state"
_RELEASE_RECORD_FAILED = "failed"
_RELEASE_RECORD_AFTER_FIELD = "after_sha"
_RELEASE_RECORD_BEFORE_FIELD = "before_sha"
_RELEASE_REPLAY_RECORD_ERROR = "The failed publication left no retained failed record."
_RELEASE_TRIGGER_OPTION = "--trigger"
_RELEASE_TRIGGER_MAINTENANCE = "maintenance"
_RELEASE_ROOT_OPTION = "--root"
_RELEASE_AFTER_OPTION = "--after-sha"
_RELEASE_HEAD_OPTION = "--head"
_RELEASE_SERIALIZED_OPTION = "--serialized"
_RELEASE_SHELL_PUBLISH = 'source "$1/bin/install.sh" >/dev/null 2>&1 && publish_binary telec "$1/bin/telec"'
_RELEASE_SHELL_SELECT = 'source "$1/bin/install.sh" >/dev/null 2>&1 && select_installed_release'
_RELEASE_COMMIT_MESSAGE = "release {version}"
_RELEASE_DEVELOPMENT_MESSAGE = "development work after the release"
_RELEASE_GIT_AUTHOR_NAME = "Runtime Acceptance Release Fixture"
_RELEASE_GIT_AUTHOR_EMAIL = "runtime-acceptance@example.invalid"
_RELEASE_TAG_TEMPLATE = "v{version}"
_RELEASE_VERSION_TEMPLATE_MINOR = "1.{minor}.0"
_RELEASE_PENDING_SCHEMA_FIELD = "schema_version"
_RELEASE_PENDING_TARGET_COMMIT_FIELD = "target_commit"
_RELEASE_PENDING_FROM_COMMIT_FIELD = "from_commit"
_RELEASE_PENDING_FROM_VERSION_FIELD = "from_version"
_RELEASE_PENDING_TARGET_FIELD = "target"
_RELEASE_PENDING_CURRENT_SCHEMA = 1
_RELEASE_PENDING_NEWER_SCHEMA = 2
_RELEASE_LOG_PATTERN = "*.log"
_RELEASE_IN_MEMORY_OUTCOME = "outcome=upcast_in_memory"
_RELEASE_PROJECT_SUBJECT = "subject_kind=project"
_RELEASE_MAINTENANCE_TRIGGER_TEXT = "trigger=maintenance"
_RELEASE_PERSISTED_OUTCOME = "outcome=written_untracked"
_RELEASE_COMPUTER_SUBJECT = "subject_kind=computer"
_RELEASE_EXPECTED_FAILURE = 1
_RELEASE_REFUSED_COMMAND_ERROR = "A command that must refuse succeeded: {argv}"
_RELEASE_COMMAND_ERROR = "A required release command failed: {argv}"
_RELEASE_NOT_DETACHED_ERROR = "The installed checkout is not in detached HEAD."
_RELEASE_TAG_ERROR = "The installed checkout does not select the expected release tag: {observed}"
_RELEASE_COMMIT_ERROR = "The installed checkout's commit is not the release tag's full commit."
_RELEASE_ATTACHED_ERROR = "The installed checkout is not on its branch."
_RELEASE_MOVED_ERROR = "The installed checkout moved when it had to stay."
_RELEASE_PULL_MOVED_ERROR = "An argument-less pull moved the installed checkout."
_RELEASE_PULL_DEMONSTRATION_ERROR = "A detached single-branch clone did not advance on an ordinary pull."
_RELEASE_MARKER_ERROR = "Maintenance did not run against the installed commit."
_RELEASE_PENDING_ERROR = "The pending convergence record is not the expected current-format record."
_RELEASE_PENDING_PRESENT_ERROR = "A completed convergence left its pending record behind."
_RELEASE_PENDING_ABSENT_ERROR = "A refused convergence did not retain its pending record."
_RELEASE_WORK_LOST_ERROR = "Local work did not survive a refused release transition."
_RELEASE_BRANCH_LOST_ERROR = "An existing branch did not survive the release transition."
_RELEASE_DEVELOPMENT_PRIVILEGE_ERROR = "A development checkout acquired installation effects."
_RELEASE_DECLARATION_CHANGED_ERROR = "The installed declaration's stored bytes changed."
_RELEASE_MIGRATION_COMMIT_ERROR = "A configuration migration committed to the installed release source."
_RELEASE_OTHER_HOME_ERROR = "The other home did not receive its ordinary persisted migration."
_RELEASE_RETAINED_RECORD_ERROR = "The installed declaration outcome did not state its retained, in-memory source."
_RELEASE_FIXTURE_INVALID = "The release checkout fixture is malformed."
_RELEASE_POSTURE_NOT_APPLICABLE_ERROR = "The posture operation changed a checkout that is not the installation."
_RELEASE_SOURCE_LIST_ERROR = "The candidate source file list could not be read."
_GIT_DIRECTORY = ".git"
_RELEASE_COPY_ERROR = "The candidate source could not be copied into the disposable history."
_RELEASE_BLOCK_MISSING_ERROR = "The candidate declaration lacks the maintenance action {action}."
_RELEASE_MARKER_ARGV = "marker_command"
_RELEASE_PRIOR_SOURCES = "prior_sources"
_RELEASE_PENDING_RECORD_FIXTURE = "pending_record"
_RELEASE_MARKER_FILE_FIELD = "marker_file"
_RELEASE_DIVERGENT_INSTALL = "divergent"
_RELEASE_SIDE_BRANCH_TEMPLATE = "release-side-{version}"
_RELEASE_SIDE_COMMIT_MESSAGE = "release {version} on a separate history"
_RELEASE_OLDER_VERSION = "1.0.7"
_RELEASE_NON_INCREASING_VERSION = "1.0.8"
_RELEASE_SIDEWAYS_PATCH_OFFSET = 9
_RELEASE_LOCAL_WORK_FILE = "local-unpublished.txt"
_RELEASE_LOCAL_WORK_MESSAGE = "local work that was never published"
_RELEASE_HEADS_FORMAT = "--format=%(refname) %(objectname)"
_RELEASE_HEADS_NAMESPACE = "refs/heads"
_RELEASE_BLOCKER_TEXT = "occupies the activation's record directory\n"
_RELEASE_UNSUPPORTED_MOVED_ERROR = "A refused release transition moved the installed source or its branches."
_RELEASE_UNSUPPORTED_RECORDED_ERROR = "A refused release transition recorded maintenance for its target."
_RELEASE_PENDING_IDENTITY_ERROR = "The retained pending convergence lost its original range or target identity."
_RELEASE_RECORDING_ADVANCE_ERROR = "A release whose recording failed did not leave the source at its target."
_RELEASE_RECORDING_EARLY_ERROR = "Maintenance ran although the activation was never recorded."
_RELEASE_PROJECT_SLUG = "release-fixture"
_RELEASE_SCHEMA_LINE = "schema_version: {version}"
_RELEASE_UNDECLARED_KEY = (("\nschema_version: ", "\nundeclared_release_key: true\nschema_version: "),)
_RELEASE_UNSUPPORTED_TYPE = (("docs:\n  enabled: true", "docs:\n  enabled: [1]"),)
_RELEASE_INVALID_ENUM = (("- activation: canonical_main", "- activation: sideways"),)
_RELEASE_INVALID_RELATIONSHIP = (
    (_RELEASE_VALID_AGENTS, _RELEASE_INVALID_AGENTS),
    ("\nschema_version: ", "\n" + _RELEASE_INVALID_HELP_DESK + "schema_version: "),
)
_RELEASE_INVALID_SHAPES = (
    _RELEASE_UNDECLARED_KEY,
    _RELEASE_UNSUPPORTED_TYPE,
    _RELEASE_INVALID_ENUM,
    _RELEASE_INVALID_RELATIONSHIP,
)


@dataclass(frozen=True)
class ReleaseInstall:
    """One disposable installation: its checkout, synthetic home and child environment."""

    base: Path
    checkout: Path
    home: Path
    environment: dict[str, str]


@dataclass
class ReleaseWorld:
    """Disposable release history plus the installations that follow it."""

    resources: FullRuntimeResources
    fixture: Mapping[str, object]
    dependency_environment: Path
    root: Path
    origin: Path
    git_environment: dict[str, str]
    candidate_declaration: str
    candidate_sources: dict[str, str]
    schema_version: int
    copied: bool = False
    minor: int = 0
    primary: ReleaseInstall | None = None
    second: ReleaseInstall | None = None
    terminal: PersistentTerminal | None = None


def _release_python(world: ReleaseWorld) -> str:
    return str(world.dependency_environment / _PYTHON_ENVIRONMENT_EXECUTABLE)


def _release_run(
    world: ReleaseWorld,
    evidence: list[CommandEvidence],
    argv: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    expect_success: bool = True,
) -> ProcessExecution:
    """Run one release command in an owned process group and keep bounded, sanitized evidence."""
    result = _run_bounded_process(argv, cwd=cwd, environment=environment, timeout_seconds=_RELEASE_TIMEOUT_SECONDS)
    succeeded = result.exit_status == _PROCESS_SUCCESS and not result.diagnostics
    evidence.append(
        CommandEvidence(
            argv=tuple(world.resources.sanitize(value) for value in argv),
            exit_status=result.exit_status,
            duration_seconds=result.duration_seconds,
            stdout=world.resources.sanitize(result.stdout)[:_DIAGNOSTIC_LIMIT]
            if succeeded != expect_success
            else _EMPTY,
            stderr=world.resources.sanitize(result.stderr)[:_DIAGNOSTIC_LIMIT]
            if succeeded != expect_success
            else _EMPTY,
            diagnostics=result.diagnostics,
        )
    )
    if result.diagnostics or succeeded != expect_success:
        message = _RELEASE_COMMAND_ERROR if expect_success else _RELEASE_REFUSED_COMMAND_ERROR
        raise RuntimeError(message.format(argv=" ".join(world.resources.sanitize(value) for value in argv)))
    return result


def _release_git(
    world: ReleaseWorld,
    evidence: list[CommandEvidence],
    cwd: Path,
    *arguments: str,
    environment: Mapping[str, str] | None = None,
    expect_success: bool = True,
) -> str:
    """Run Git for a release fixture and return its trimmed output."""
    result = _release_run(
        world,
        evidence,
        (_GIT_EXECUTABLE, *arguments),
        cwd=cwd,
        environment=world.git_environment if environment is None else environment,
        expect_success=expect_success,
    )
    return result.stdout.strip()


def _declaration_block(declaration: str, action: str) -> str:
    """The lines of one maintenance action in a declaration, as the candidate states them."""
    lines = declaration.splitlines()
    header = f"{_RELEASE_DECLARATION_MAINTENANCE_INDENT}{action}:"
    if header not in lines:
        raise ValueError(_RELEASE_BLOCK_MISSING_ERROR.format(action=action))
    start = lines.index(header)
    block = [header]
    for line in lines[start + 1 :]:
        if line.strip() and not line.startswith(_RELEASE_BLOCK_INDENT):
            break
        block.append(line)
    return _LINE_BREAK.join(block)


def _fixture_declaration(world: ReleaseWorld, *, posture: bool, schema_version: int, code: bool) -> str:
    """A minimal project declaration whose actions are the candidate's own, plus the probe action."""
    marker_command = json.dumps(world.fixture[_RELEASE_MARKER_ARGV])
    actions = [_declaration_block(world.candidate_declaration, _RELEASE_UPDATE_ACTION)]
    activation_actions = [_RELEASE_MARKER_ACTION]
    if posture:
        actions.insert(0, _declaration_block(world.candidate_declaration, _RELEASE_POSTURE_ACTION))
        activation_actions.insert(0, _RELEASE_POSTURE_ACTION)
    marker = _LINE_BREAK.join(
        (
            f"{_RELEASE_DECLARATION_MAINTENANCE_INDENT}{_RELEASE_MARKER_ACTION}:",
            f"{_RELEASE_BLOCK_INDENT}main_only: true",
            f"{_RELEASE_BLOCK_INDENT}precedence: 90",
            f"{_RELEASE_BLOCK_INDENT}command: {marker_command}",
        )
    )
    neutral = [
        _LINE_BREAK.join(
            (
                f"{_RELEASE_DECLARATION_MAINTENANCE_INDENT}{step}:",
                f"{_RELEASE_BLOCK_INDENT}main_only: true",
                f"{_RELEASE_BLOCK_INDENT}precedence: 10",
                f"{_RELEASE_BLOCK_INDENT}command: {json.dumps(world.fixture[field])}",
            )
        )
        for step, field in _RELEASE_NEUTRAL_STEPS
    ]
    return _LINE_BREAK.join(
        (
            "description: Disposable release journey project",
            "kind: project",
            "project_name: ReleaseFixture",
            "project_slug: release-fixture",
            "business:",
            "  publishes:",
            f"    - slug: {_RELEASE_PUBLISHED_DOMAIN}",
            "      trigger: Disposable release journey publication",
            "code:",
            f"  enabled: {str(code).lower()}",
            "docs:",
            "  enabled: true",
            "agents:",
            "  enabled: true",
            "checkpoint:",
            "  maintenance:",
            *actions,
            marker,
            *neutral,
            "  bindings:",
            "    - events: [github.push, github.release]",
            f"      actions: [{_RELEASE_UPDATE_ACTION}]",
            "    - activation: canonical_main",
            f"      actions: [{', '.join(activation_actions)}]",
            f"schema_version: {schema_version}",
            _EMPTY,
        )
    )


def _write_probe_sources(origin: Path, label: str) -> None:
    """Write the bounded documentation and agent-artifact sources whose label names the commit they belong to."""
    for relative in (
        _RELEASE_PROBE_DOCUMENT,
        _RELEASE_PROBE_SKILL,
        _RELEASE_PROBE_SKILLS_MASTER,
        *_RELEASE_PROBE_BASELINES,
    ):
        (origin / relative).parent.mkdir(parents=True, exist_ok=True)
    (origin / _RELEASE_PROBE_DOCUMENT).write_text(_RELEASE_PROBE_DOCUMENT_TEXT.format(label=label), encoding=_UTF8)
    (origin / _RELEASE_PROBE_SKILL).write_text(_RELEASE_PROBE_SKILL_TEXT.format(label=label), encoding=_UTF8)
    (origin / _RELEASE_PROBE_SKILLS_MASTER).write_text(_RELEASE_PROBE_SKILLS_TEXT, encoding=_UTF8)
    (origin / _RELEASE_MASTER_NAME).write_text(_RELEASE_PROBE_MASTER_TEXT.format(label=label), encoding=_UTF8)
    for baseline in _RELEASE_PROBE_BASELINES:
        (origin / baseline).write_text(_EMPTY, encoding=_UTF8)


def _replace_publication_sources(world: ReleaseWorld) -> None:
    """Swap the candidate's own documentation and agent sources for the bounded probe set.

    The candidate's code and declarations are the subject of the journeys; its full documentation
    layout needs a registered company and domains that a disposable history does not carry.
    """
    for directory in (world.origin / "docs", world.origin / "agents"):
        shutil.rmtree(directory, ignore_errors=True)
    for master in list(world.origin.rglob(_RELEASE_MASTER_NAME)):
        if _GIT_DIRECTORY not in master.relative_to(world.origin).parts:
            master.unlink()


def _copy_candidate_sources(world: ReleaseWorld, evidence: list[CommandEvidence]) -> None:
    """Copy the checked candidate's tracked files into the disposable history's working tree."""
    listing = _run_bounded_process(
        (_GIT_EXECUTABLE, "ls-files", "-z"),
        cwd=world.resources.source_root,
        environment=world.git_environment,
        timeout_seconds=_RELEASE_TIMEOUT_SECONDS,
        output_limit_bytes=_RELEASE_FILE_LIST_LIMIT_BYTES,
    )
    if listing.exit_status != _PROCESS_SUCCESS:
        raise RuntimeError(_RELEASE_SOURCE_LIST_ERROR)
    for name in filter(None, listing.stdout.split("\0")):
        source = world.resources.source_root / name
        destination = world.origin / name
        if not source.is_file() and not source.is_symlink():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            if source.is_symlink():
                destination.symlink_to(os.readlink(source))
            else:
                shutil.copy2(source, destination)
        except OSError as error:
            raise RuntimeError(_RELEASE_COPY_ERROR) from error
    _replace_publication_sources(world)
    world.copied = True


def _release_commit(
    world: ReleaseWorld,
    evidence: list[CommandEvidence],
    *,
    prior: bool,
    schema_version: int | None = None,
    note: str = _EMPTY,
    code: bool = False,
) -> str:
    """Commit and tag the next release on the disposable history; return its tag."""
    if not world.copied:
        _copy_candidate_sources(world, evidence)
    prior_sources = cast(Mapping[str, str], world.fixture[_RELEASE_PRIOR_SOURCES])
    for relative, text in prior_sources.items():
        (world.origin / relative).write_text(world.candidate_sources[relative] if not prior else text, encoding=_UTF8)
    world.minor += 1
    version = _RELEASE_VERSION_TEMPLATE_MINOR.format(minor=world.minor)
    (world.origin / _RELEASE_DECLARATION).write_text(
        _fixture_declaration(
            world,
            posture=not prior,
            schema_version=world.schema_version if schema_version is None else schema_version,
            code=code,
        ),
        encoding=_UTF8,
    )
    _write_probe_sources(world.origin, _RELEASE_PROBE_LABEL.format(version=version))
    pyproject = world.origin / _RELEASE_PYPROJECT
    pyproject.write_text(
        re.sub(
            _RELEASE_VERSION_PATTERN,
            _RELEASE_VERSION_TEMPLATE.format(version=version),
            pyproject.read_text(encoding=_UTF8),
            count=1,
        ),
        encoding=_UTF8,
    )
    (world.origin / _RELEASE_NOTE_FILE).write_text(note or f"{version}\n", encoding=_UTF8)
    tag = _RELEASE_TAG_TEMPLATE.format(version=version)
    _release_git(world, evidence, world.origin, "add", "-A")
    _release_git(
        world, evidence, world.origin, "commit", "--quiet", "-m", _RELEASE_COMMIT_MESSAGE.format(version=version)
    )
    _release_git(world, evidence, world.origin, "tag", tag)
    return tag


def _release_development_commit(world: ReleaseWorld, evidence: list[CommandEvidence]) -> None:
    """Advance the upstream development branch past the latest release."""
    identity = uuid.uuid4().hex
    (world.origin / _RELEASE_DEVELOPMENT_FILE).write_text(f"{identity}\n", encoding=_UTF8)
    _write_probe_sources(world.origin, _RELEASE_PROBE_DEVELOPMENT_LABEL.format(identity=identity))
    _release_git(world, evidence, world.origin, "add", "-A")
    _release_git(world, evidence, world.origin, "commit", "--quiet", "-m", _RELEASE_DEVELOPMENT_MESSAGE)


def _release_world(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> ReleaseWorld:
    """The scenario-shared disposable history, created on first use."""
    if resources.release_world is not None:
        return cast(ReleaseWorld, resources.release_world)
    fixture = _mapping_value(json.loads((resources.source_root / _RELEASE_FIXTURE).read_text(encoding=_UTF8)))
    if fixture is None or _mapping_value(fixture.get(_RELEASE_PRIOR_SOURCES)) is None:
        raise ValueError(_RELEASE_FIXTURE_INVALID)
    declaration = (resources.source_root / _RELEASE_DECLARATION).read_text(encoding=_UTF8)
    schema_match = re.search(_RELEASE_SCHEMA_PATTERN, declaration, flags=re.MULTILINE)
    if schema_match is None:
        raise ValueError(_RELEASE_FIXTURE_INVALID)
    root = resources.temporary_root / _RELEASE_ROOT_DIRECTORY
    origin = root / _RELEASE_ORIGIN_DIRECTORY
    origin.mkdir(parents=True)
    host_environment = os.environ  # fmt: skip  # guard: direct-env-read - allowed: child-process environment construction
    git_environment = {
        _PATH_VARIABLE: host_environment.get(_PATH_VARIABLE, _EMPTY),
        _GIT_CONFIG_GLOBAL_VARIABLE: os.devnull,
        _GIT_CONFIG_SYSTEM_VARIABLE: os.devnull,
        _GIT_CONFIG_SYSTEM_DISABLED_VARIABLE: _TRUE_TEXT,
        "GIT_AUTHOR_NAME": _RELEASE_GIT_AUTHOR_NAME,
        "GIT_AUTHOR_EMAIL": _RELEASE_GIT_AUTHOR_EMAIL,
        "GIT_COMMITTER_NAME": _RELEASE_GIT_AUTHOR_NAME,
        "GIT_COMMITTER_EMAIL": _RELEASE_GIT_AUTHOR_EMAIL,
        _COLD_HOME_VARIABLE: str(root),
    }
    prior_sources = cast(Mapping[str, str], fixture[_RELEASE_PRIOR_SOURCES])
    world = ReleaseWorld(
        resources=resources,
        fixture=fixture,
        dependency_environment=ensure_dependency_environment(resources.source_root),
        root=root,
        origin=origin,
        git_environment=git_environment,
        candidate_declaration=declaration,
        candidate_sources={
            relative: (resources.source_root / relative).read_text(encoding=_UTF8) for relative in prior_sources
        },
        schema_version=int(schema_match.group(1)),
    )
    resources.release_world = world
    _release_git(world, evidence, origin, "init", "--quiet", "-b", _RELEASE_BRANCH)
    return world


def _release_install(
    world: ReleaseWorld,
    evidence: list[CommandEvidence],
    name: str,
    *,
    single_branch: bool,
    revision: str,
) -> ReleaseInstall:
    """Clone the history as an installation, publish its executable through the installer and name its channel."""
    base = world.root / name
    base.mkdir(parents=True)
    checkout = base / _RELEASE_INSTALL_DIRECTORY
    environment = _make_cold_environment(
        world.resources.source_root,
        world.dependency_environment,
        base,
        channel=_RELEASE_CHANNEL,
        working_directory=checkout,
    )
    environment.update(world.git_environment)
    environment[_COLD_HOME_VARIABLE] = str(base / _SYNTHETIC_HOME_DIRECTORY)
    host_home = world.resources.environment.get(_COLD_HOME_VARIABLE)
    if host_home:
        environment[_PATH_VARIABLE] = _PATH_SEPARATOR.join(
            (str(Path(host_home) / _RELEASE_LOCAL_BIN), environment[_PATH_VARIABLE])
        )
    (base / _SYNTHETIC_HOME_DIRECTORY / _RELEASE_DECLARATION).write_text(
        _RELEASE_GLOBAL_TEXT.format(email=_RELEASE_PERSON_EMAIL, schema_version=world.schema_version), encoding=_UTF8
    )
    (base / _SYNTHETIC_HOME_DIRECTORY / _RELEASE_AGENT_HOME_DIRECTORY).mkdir(parents=True, exist_ok=True)
    clone = ["clone", "--quiet", *(["--single-branch", "--branch", _RELEASE_BRANCH] if single_branch else [])]
    _release_git(world, evidence, base, *clone, f"file://{world.origin}", str(checkout))
    _release_git(world, evidence, checkout, "checkout", "--quiet", revision)
    (checkout / _RELEASE_VENV).symlink_to(world.dependency_environment, target_is_directory=True)
    install = ReleaseInstall(
        base=base, checkout=checkout, home=base / _SYNTHETIC_HOME_DIRECTORY, environment=environment
    )
    _release_run(
        world,
        evidence,
        (_BASH_EXECUTABLE, "-c", _RELEASE_SHELL_PUBLISH, "install", str(checkout)),
        cwd=checkout,
        environment=environment,
    )
    return install


def _release_event(world: ReleaseWorld, install: ReleaseInstall, tag: str) -> Path:
    """Write one published-release announcement as the file the updater reads."""
    path = install.base / _RELEASE_EVENT_FILE
    path.write_text(
        json.dumps(
            {
                "id": uuid.uuid4().hex,
                "type": _RELEASE_EVENT_TYPE,
                "source": _RELEASE_EVENT_SOURCE,
                "time": _RELEASE_EVENT_TIME,
                "home": _RELEASE_EVENT_HOME,
                "data": {"action": _RELEASE_EVENT_ACTION, "release": {"tag_name": tag}},
            }
        ),
        encoding=_UTF8,
    )
    return path


def _release_module(
    world: ReleaseWorld,
    evidence: list[CommandEvidence],
    install: ReleaseInstall,
    module: str,
    *arguments: str,
    expect_success: bool = True,
) -> ProcessExecution:
    """Run one public module entry point from the installed checkout."""
    return _release_run(
        world,
        evidence,
        (_release_python(world), "-m", module, *arguments),
        cwd=install.checkout,
        environment=install.environment,
        expect_success=expect_success,
    )


def _release_update(
    world: ReleaseWorld,
    evidence: list[CommandEvidence],
    install: ReleaseInstall,
    tag: str,
    *,
    expect_success: bool = True,
    drain: bool = True,
) -> None:
    """Deliver one release announcement to the installation's updater, then settle the maintenance it recorded."""
    event_file = _release_event(world, install, tag)
    _release_module(
        world, evidence, install, _RELEASE_MODULE_SELF_UPDATE, str(event_file), expect_success=expect_success
    )
    if expect_success and drain:
        _release_drain(world, evidence, install)


def _release_drain(world: ReleaseWorld, evidence: list[CommandEvidence], install: ReleaseInstall) -> None:
    """Run the recorded maintenance through its public automation entry point."""
    _release_module(world, evidence, install, _RELEASE_MODULE_DRAIN)


def _head(world: ReleaseWorld, evidence: list[CommandEvidence], install: ReleaseInstall) -> str:
    return _release_git(world, evidence, install.checkout, "rev-parse", "HEAD")


def _require_selected(world: ReleaseWorld, evidence: list[CommandEvidence], install: ReleaseInstall, tag: str) -> None:
    """Require detached HEAD with the release tag and its full commit observable together."""
    _release_git(world, evidence, install.checkout, "symbolic-ref", "--quiet", "HEAD", expect_success=False)
    observed = _release_git(world, evidence, install.checkout, "describe", "--tags", "--exact-match")
    if observed != tag:
        raise ValueError(_RELEASE_TAG_ERROR.format(observed=observed))
    if _head(world, evidence, install) != _release_git(
        world, evidence, install.checkout, "rev-parse", f"{tag}^{{commit}}"
    ):
        raise ValueError(_RELEASE_COMMIT_ERROR)


def _release_marker(world: ReleaseWorld, install: ReleaseInstall) -> str:
    """The commit recorded maintenance last ran against, or nothing when it has not run."""
    marker = install.checkout / str(world.fixture[_RELEASE_MARKER_FILE_FIELD])
    return marker.read_text(encoding=_UTF8).strip() if marker.exists() else _EMPTY


def _require_marker(world: ReleaseWorld, evidence: list[CommandEvidence], install: ReleaseInstall) -> None:
    """Require that recorded maintenance ran against the commit the installation runs."""
    if _release_marker(world, install) != _head(world, evidence, install):
        raise ValueError(_RELEASE_MARKER_ERROR)


def _require_pull_refused(world: ReleaseWorld, evidence: list[CommandEvidence], install: ReleaseInstall) -> None:
    """An argument-less pull refuses and leaves the selected commit where it was."""
    before = _head(world, evidence, install)
    _release_run(
        world,
        evidence,
        (_GIT_EXECUTABLE, "pull"),
        cwd=install.checkout,
        environment=install.environment,
        expect_success=False,
    )
    if _head(world, evidence, install) != before:
        raise ValueError(_RELEASE_PULL_MOVED_ERROR)


def _release_selected_visibly(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    """UC-RC1: the prior updater's activation leaves the new release selected in detached HEAD."""
    world = _release_world(resources, evidence)
    prior_tag = _release_commit(world, evidence, prior=True)
    world.primary = install = _release_install(
        world, evidence, _RELEASE_PRIMARY_INSTALL, single_branch=True, revision=_RELEASE_BRANCH
    )
    adopted_tag = _release_commit(world, evidence, prior=False)
    probe = world.root / _RELEASE_PROBE_DIRECTORY
    _release_git(
        world,
        evidence,
        world.root,
        "clone",
        "--quiet",
        "--single-branch",
        "--branch",
        _RELEASE_BRANCH,
        f"file://{world.origin}",
        str(probe),
    )
    _release_git(world, evidence, probe, "checkout", "--quiet", "--detach", prior_tag)
    before = _release_git(world, evidence, probe, "rev-parse", "HEAD")
    _release_git(world, evidence, probe, "pull", "--quiet")
    if _release_git(world, evidence, probe, "rev-parse", "HEAD") == before:
        raise ValueError(_RELEASE_PULL_DEMONSTRATION_ERROR)
    _release_update(world, evidence, install, adopted_tag, drain=False)
    if _release_git(world, evidence, install.checkout, "symbolic-ref", "--quiet", "HEAD") != _RELEASE_BRANCH_REF:
        raise ValueError(_RELEASE_ATTACHED_ERROR)
    _release_drain(world, evidence, install)
    _require_selected(world, evidence, install, adopted_tag)
    _require_marker(world, evidence, install)


def _release_pull_refused(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    """UC-RC2: an ordinary pull cannot advance a single-branch or a normal release installation."""
    world = _release_world(resources, evidence)
    primary = world.primary
    if primary is None:
        raise ValueError(_RELEASE_FIXTURE_INVALID)
    _release_development_commit(world, evidence)
    _require_pull_refused(world, evidence, primary)
    latest = _release_git(world, evidence, world.origin, "describe", "--tags", "--abbrev=0", "--match", "v*", "HEAD~1")
    world.second = second = _release_install(
        world, evidence, _RELEASE_SECOND_INSTALL, single_branch=False, revision=latest
    )
    _release_run(
        world,
        evidence,
        (_BASH_EXECUTABLE, "-c", _RELEASE_SHELL_SELECT, "install", str(second.checkout)),
        cwd=second.checkout,
        environment=second.environment,
    )
    _require_selected(world, evidence, second, latest)
    _release_development_commit(world, evidence)
    _require_pull_refused(world, evidence, second)


def _write_pending_record(install: ReleaseInstall, record: Mapping[str, object]) -> Path:
    path = install.home / _RELEASE_PENDING_RECORD
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record), encoding=_UTF8)
    return path


def _release_adoption(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    """UC-CSU-8: a detached installation adopts the exact next release and migrates its owned pending record."""
    world = _release_world(resources, evidence)
    install = world.primary
    if install is None:
        raise ValueError(_RELEASE_FIXTURE_INVALID)
    tag = _release_commit(world, evidence, prior=False)
    _release_update(world, evidence, install, tag)
    _require_selected(world, evidence, install, tag)
    _require_marker(world, evidence, install)
    if _release_git(world, evidence, install.checkout, "rev-parse", _RELEASE_BRANCH) == _head(world, evidence, install):
        raise ValueError(_RELEASE_MOVED_ERROR)
    _release_pending_record_migration(world, evidence, install)


def _release_pending_record_migration(
    world: ReleaseWorld, evidence: list[CommandEvidence], install: ReleaseInstall
) -> None:
    """The stored unversioned record is brought forward before use, and a newer one is refused untouched."""
    legacy = cast(Mapping[str, str], world.fixture[_RELEASE_PENDING_RECORD_FIXTURE])
    left_from = _head(world, evidence, install)
    target = _release_commit(world, evidence, prior=False)
    record = {**legacy, _RELEASE_PENDING_FROM_COMMIT_FIELD: left_from, _RELEASE_PENDING_TARGET_FIELD: target}
    path = _write_pending_record(install, record)
    away = world.root / _RELEASE_AWAY_DIRECTORY
    world.origin.rename(away)
    try:
        _release_update(world, evidence, install, target, expect_success=False)
    finally:
        away.rename(world.origin)
    migrated = cast(Mapping[str, object], json.loads(path.read_text(encoding=_UTF8)))
    if (
        migrated.get(_RELEASE_PENDING_SCHEMA_FIELD) != _RELEASE_PENDING_CURRENT_SCHEMA
        or migrated.get(_RELEASE_PENDING_TARGET_COMMIT_FIELD) is not None
        or any(migrated.get(field) != value for field, value in record.items())
    ):
        raise ValueError(_RELEASE_PENDING_ERROR)
    _release_update(world, evidence, install, target)
    if path.exists():
        raise ValueError(_RELEASE_PENDING_PRESENT_ERROR)
    _require_selected(world, evidence, install, target)
    interrupted = {**record, _RELEASE_PENDING_FROM_COMMIT_FIELD: left_from}
    _write_pending_record(install, interrupted)
    reached = _head(world, evidence, install)
    _release_update(world, evidence, install, target)
    if _head(world, evidence, install) != reached or path.exists():
        raise ValueError(_RELEASE_MOVED_ERROR)
    path = _write_pending_record(install, {**record, _RELEASE_PENDING_SCHEMA_FIELD: _RELEASE_PENDING_NEWER_SCHEMA})
    before = path.read_text(encoding=_UTF8)
    _release_update(world, evidence, install, target, expect_success=False)
    if path.read_text(encoding=_UTF8) != before:
        raise ValueError(_RELEASE_PENDING_ERROR)
    path.unlink()


def _release_next_from_detached(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    """UC-RC3: the installation normalizes the commit it runs, then adopts the next release, staying detached."""
    world = _release_world(resources, evidence)
    install = world.primary
    if install is None:
        raise ValueError(_RELEASE_FIXTURE_INVALID)
    current = _release_git(world, evidence, install.checkout, "describe", "--tags", "--exact-match")
    _release_git(world, evidence, install.checkout, "checkout", "--quiet", "-b", _RELEASE_ATTACHED_BRANCH)
    _release_update(world, evidence, install, current)
    _require_selected(world, evidence, install, current)
    _release_git(world, evidence, install.checkout, "rev-parse", "--verify", _RELEASE_ATTACHED_BRANCH)
    tag = _release_commit(world, evidence, prior=False)
    _release_update(world, evidence, install, tag)
    _require_selected(world, evidence, install, tag)
    _require_marker(world, evidence, install)


def _release_replay(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    """UC-CSU-9: an older release announcement leaves the installed revision unchanged."""
    world = _release_world(resources, evidence)
    install = world.primary
    if install is None:
        raise ValueError(_RELEASE_FIXTURE_INVALID)
    before = _head(world, evidence, install)
    older = _release_git(world, evidence, install.checkout, "tag", "--list", "--sort=version:refname", "v*").split()[0]
    _release_update(world, evidence, install, older)
    if _head(world, evidence, install) != before:
        raise ValueError(_RELEASE_MOVED_ERROR)
    _require_selected(
        world, evidence, install, _release_git(world, evidence, install.checkout, "describe", "--tags", "--exact-match")
    )


def _release_heads(world: ReleaseWorld, evidence: list[CommandEvidence], install: ReleaseInstall) -> str:
    """Every local branch with the commit it names."""
    return _release_git(
        world, evidence, install.checkout, "for-each-ref", _RELEASE_HEADS_FORMAT, _RELEASE_HEADS_NAMESPACE
    )


def _stored_pending(install: ReleaseInstall) -> Mapping[str, object]:
    """The pending convergence record exactly as the updater stored it."""
    record = _mapping_value(json.loads((install.home / _RELEASE_PENDING_RECORD).read_text(encoding=_UTF8)))
    if record is None:
        raise ValueError(_RELEASE_PENDING_ERROR)
    return record


def _require_pending_identity(
    world: ReleaseWorld, evidence: list[CommandEvidence], install: ReleaseInstall, left_from: str, tag: str
) -> str:
    """Require the retained pending record to keep the original source and the immutable target; return the target."""
    target_commit = _release_git(world, evidence, install.checkout, "rev-parse", f"{tag}^{{commit}}")
    pending = _stored_pending(install)
    if (
        pending.get(_RELEASE_PENDING_SCHEMA_FIELD) != _RELEASE_PENDING_CURRENT_SCHEMA
        or pending.get(_RELEASE_PENDING_FROM_COMMIT_FIELD) != left_from
        or pending.get(_RELEASE_PENDING_TARGET_FIELD) != tag
        or pending.get(_RELEASE_PENDING_TARGET_COMMIT_FIELD) != target_commit
    ):
        raise ValueError(_RELEASE_PENDING_IDENTITY_ERROR)
    return target_commit


def _release_side_release(world: ReleaseWorld, evidence: list[CommandEvidence], base: str, version: str) -> str:
    """Commit and tag a release of the given version on a branch of its own that starts at ``base``."""
    tag = _RELEASE_TAG_TEMPLATE.format(version=version)
    _release_git(
        world,
        evidence,
        world.origin,
        "checkout",
        "--quiet",
        "-b",
        _RELEASE_SIDE_BRANCH_TEMPLATE.format(version=version),
        base,
    )
    pyproject = world.origin / _RELEASE_PYPROJECT
    pyproject.write_text(
        re.sub(
            _RELEASE_VERSION_PATTERN,
            _RELEASE_VERSION_TEMPLATE.format(version=version),
            pyproject.read_text(encoding=_UTF8),
            count=1,
        ),
        encoding=_UTF8,
    )
    (world.origin / _RELEASE_NOTE_FILE).write_text(f"{version}\n", encoding=_UTF8)
    _release_git(world, evidence, world.origin, "add", "-A")
    _release_git(
        world,
        evidence,
        world.origin,
        "commit",
        "--quiet",
        "-m",
        _RELEASE_SIDE_COMMIT_MESSAGE.format(version=version),
    )
    _release_git(world, evidence, world.origin, "tag", tag)
    _release_git(world, evidence, world.origin, "checkout", "--quiet", _RELEASE_BRANCH)
    return tag


def _require_transition_refused(
    world: ReleaseWorld, evidence: list[CommandEvidence], install: ReleaseInstall, tag: str
) -> None:
    """The updater refuses ``tag`` before moving anything and keeps its pending transition, which is then discarded."""
    left_from = _head(world, evidence, install)
    heads = _release_heads(world, evidence, install)
    _release_update(world, evidence, install, tag, expect_success=False)
    if _head(world, evidence, install) != left_from or _release_heads(world, evidence, install) != heads:
        raise ValueError(_RELEASE_UNSUPPORTED_MOVED_ERROR)
    target_commit = _require_pending_identity(world, evidence, install, left_from, tag)
    if (install.checkout / _RELEASE_MAINTENANCE_DIRECTORY / target_commit).exists():
        raise ValueError(_RELEASE_UNSUPPORTED_RECORDED_ERROR)
    (install.home / _RELEASE_PENDING_RECORD).unlink()


def _release_unsupported_transitions(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    """UC-CSU-11: a source the installation cannot move to without losing history is refused where it stands."""
    world = _release_world(resources, evidence)
    install = world.primary
    if install is None:
        raise ValueError(_RELEASE_FIXTURE_INVALID)
    installed = _release_version(world, evidence, install, "HEAD")
    oldest = _release_git(world, evidence, install.checkout, "tag", "--list", "--sort=version:refname", "v*").split()[0]
    major, minor, patch = (int(part) for part in installed.split("."))
    sideways = f"{major}.{minor}.{patch + _RELEASE_SIDEWAYS_PATCH_OFFSET}"
    for base, version in (
        (oldest, _RELEASE_OLDER_VERSION),
        (oldest, sideways),
        (_RELEASE_BRANCH, _RELEASE_NON_INCREASING_VERSION),
    ):
        _require_transition_refused(world, evidence, install, _release_side_release(world, evidence, base, version))
    divergent = _release_install(
        world, evidence, _RELEASE_DIVERGENT_INSTALL, single_branch=False, revision=_RELEASE_BRANCH
    )
    (divergent.checkout / _RELEASE_LOCAL_WORK_FILE).write_text(f"{uuid.uuid4().hex}\n", encoding=_UTF8)
    _release_git(world, evidence, divergent.checkout, "add", _RELEASE_LOCAL_WORK_FILE)
    _release_git(world, evidence, divergent.checkout, "commit", "--quiet", "-m", _RELEASE_LOCAL_WORK_MESSAGE)
    _require_transition_refused(world, evidence, divergent, _release_commit(world, evidence, prior=False))
    if _release_git(world, evidence, divergent.checkout, "symbolic-ref", "--quiet", "HEAD") != _RELEASE_BRANCH_REF:
        raise ValueError(_RELEASE_ATTACHED_ERROR)
    tag = _release_commit(world, evidence, prior=False)
    _release_update(world, evidence, install, tag)
    _require_selected(world, evidence, install, tag)
    _require_marker(world, evidence, install)


def _release_recording_refused(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    """UC-CSU-12: a transition whose maintenance cannot be recorded stays pending and completes once it can."""
    world = _release_world(resources, evidence)
    install = world.primary
    if install is None:
        raise ValueError(_RELEASE_FIXTURE_INVALID)
    left_from = _head(world, evidence, install)
    tag = _release_commit(world, evidence, prior=False)
    target_commit = _release_git(world, evidence, world.origin, "rev-parse", f"{tag}^{{commit}}")
    blocker = install.checkout / _RELEASE_MAINTENANCE_DIRECTORY / target_commit
    blocker.parent.mkdir(parents=True, exist_ok=True)
    blocker.write_text(_RELEASE_BLOCKER_TEXT, encoding=_UTF8)
    _release_update(world, evidence, install, tag, expect_success=False)
    if _head(world, evidence, install) != target_commit:
        raise ValueError(_RELEASE_RECORDING_ADVANCE_ERROR)
    _require_pending_identity(world, evidence, install, left_from, tag)
    if _release_marker(world, install) == target_commit:
        raise ValueError(_RELEASE_RECORDING_EARLY_ERROR)
    blocker.unlink()
    _release_update(world, evidence, install, tag)
    if (install.home / _RELEASE_PENDING_RECORD).exists():
        raise ValueError(_RELEASE_PENDING_PRESENT_ERROR)
    _require_selected(world, evidence, install, tag)
    _require_marker(world, evidence, install)


def _release_conflict(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    """UC-RC5: conflicting local work refuses the transition and survives it."""
    world = _release_world(resources, evidence)
    install = world.primary
    if install is None:
        raise ValueError(_RELEASE_FIXTURE_INVALID)
    reached = _head(world, evidence, install)
    note = install.checkout / _RELEASE_NOTE_FILE
    note.write_text("local work\n", encoding=_UTF8)
    tag = _release_commit(world, evidence, prior=False)
    _release_update(world, evidence, install, tag, expect_success=False)
    if _head(world, evidence, install) != reached or note.read_text(encoding=_UTF8) != "local work\n":
        raise ValueError(_RELEASE_WORK_LOST_ERROR)
    if not (install.home / _RELEASE_PENDING_RECORD).exists():
        raise ValueError(_RELEASE_PENDING_ABSENT_ERROR)
    _release_git(world, evidence, install.checkout, "rev-parse", "--verify", _RELEASE_ATTACHED_BRANCH)
    _release_git(world, evidence, install.checkout, "checkout", "--", _RELEASE_NOTE_FILE)
    _release_update(world, evidence, install, tag)
    _require_selected(world, evidence, install, tag)


def _release_development_clone(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    """UC-RC6: a detached development checkout gains no installation effects."""
    world = _release_world(resources, evidence)
    install = world.primary
    if install is None:
        raise ValueError(_RELEASE_FIXTURE_INVALID)
    checkout = world.root / _RELEASE_DEVELOPMENT_DIRECTORY
    _release_git(
        world,
        evidence,
        world.root,
        "clone",
        "--quiet",
        "--single-branch",
        "--branch",
        _RELEASE_BRANCH,
        f"file://{world.origin}",
        str(checkout),
    )
    tag = _release_git(world, evidence, checkout, "describe", "--tags", "--abbrev=0", "--match", "v*", "HEAD")
    _release_git(world, evidence, checkout, "checkout", "--quiet", "--detach", tag)
    mapping = _release_git(world, evidence, checkout, "config", "--get-all", "remote.origin.fetch")
    development = ReleaseInstall(
        base=install.base, checkout=checkout, home=install.home, environment=install.environment
    )
    _release_module(
        world,
        evidence,
        development,
        _RELEASE_MODULE_POSTURE,
        _RELEASE_ROOT_OPTION,
        str(checkout),
        _RELEASE_AFTER_OPTION,
        _release_git(world, evidence, checkout, "rev-parse", "HEAD"),
    )
    _release_module(world, evidence, development, _RELEASE_MODULE_DRAIN, expect_success=False)
    if (
        _release_git(world, evidence, checkout, "config", "--get-all", "remote.origin.fetch") != mapping
        or (checkout / ".teleclaude" / "maintenance").exists()
    ):
        raise ValueError(_RELEASE_DEVELOPMENT_PRIVILEGE_ERROR)
    _release_git(world, evidence, checkout, "symbolic-ref", "--quiet", "HEAD", expect_success=False)


def _release_retained_declaration(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    """UC-CFG-MIG-17: configuration migration retains the installed declaration and migrates the other home."""
    world = _release_world(resources, evidence)
    install = world.primary
    if install is None:
        raise ValueError(_RELEASE_FIXTURE_INVALID)
    tag = _release_commit(world, evidence, prior=False, schema_version=world.schema_version - 1)
    _release_update(world, evidence, install, tag)
    (install.home / _RELEASE_PROJECTS_REGISTRY).write_text(f"projects:\n  - {install.checkout}\n", encoding=_UTF8)
    declaration = install.checkout / _RELEASE_DECLARATION
    stored = declaration.read_bytes()
    reached = _head(world, evidence, install)
    commits = _release_git(world, evidence, install.checkout, "rev-list", "--count", "--all")
    machine_before = (install.home / _RELEASE_CONFIG_FILE).read_text(encoding=_UTF8)
    _release_module(
        world, evidence, install, _RELEASE_MODULE_MIGRATIONS, _RELEASE_TRIGGER_OPTION, _RELEASE_TRIGGER_MAINTENANCE
    )
    if declaration.read_bytes() != stored:
        raise ValueError(_RELEASE_DECLARATION_CHANGED_ERROR)
    if (
        _head(world, evidence, install) != reached
        or _release_git(world, evidence, install.checkout, "rev-list", "--count", "--all") != commits
    ):
        raise ValueError(_RELEASE_MIGRATION_COMMIT_ERROR)
    _require_selected(world, evidence, install, tag)
    if (install.home / _RELEASE_CONFIG_FILE).read_text(encoding=_UTF8) == machine_before:
        raise ValueError(_RELEASE_OTHER_HOME_ERROR)
    records = _LINE_BREAK.join(
        log.read_text(encoding=_UTF8, errors=_UTF8_REPLACEMENT) for log in install.base.rglob(_RELEASE_LOG_PATTERN)
    ).splitlines()
    if not any(
        _RELEASE_PROJECT_SUBJECT in line
        and _RELEASE_IN_MEMORY_OUTCOME in line
        and _RELEASE_MAINTENANCE_TRIGGER_TEXT in line
        for line in records
    ) or not any(
        _RELEASE_COMPUTER_SUBJECT in line
        and _RELEASE_PERSISTED_OUTCOME in line
        and _RELEASE_MAINTENANCE_TRIGGER_TEXT in line
        for line in records
    ):
        raise ValueError(_RELEASE_RETAINED_RECORD_ERROR)
    _release_telec(world, evidence, install, *_release_public_load(), expect_success=True)
    older_schema = _RELEASE_SCHEMA_LINE.format(version=world.schema_version - 1)
    current_schema = _RELEASE_SCHEMA_LINE.format(version=world.schema_version)
    for shape in _RELEASE_INVALID_SHAPES:
        invalid_older = stored.decode(_UTF8)
        for find, replacement in shape:
            invalid_older = invalid_older.replace(find, replacement, 1)
        for invalid in (invalid_older, invalid_older.replace(older_schema, current_schema, 1)):
            declaration.write_text(invalid, encoding=_UTF8)
            (install.home / _RELEASE_CONFIG_FILE).write_text(machine_before, encoding=_UTF8)
            _release_telec(world, evidence, install, *_release_public_load(), expect_success=False)
            _release_module(
                world,
                evidence,
                install,
                _RELEASE_MODULE_MIGRATIONS,
                _RELEASE_TRIGGER_OPTION,
                _RELEASE_TRIGGER_MAINTENANCE,
                expect_success=False,
            )
            if (
                declaration.read_text(encoding=_UTF8) != invalid
                or _head(world, evidence, install) != reached
                or _release_git(world, evidence, install.checkout, "rev-list", "--count", "--all") != commits
            ):
                raise ValueError(_RELEASE_INVALID_DECLARATION_ERROR)
            if (install.home / _RELEASE_CONFIG_FILE).read_text(encoding=_UTF8) == machine_before:
                raise ValueError(_RELEASE_OTHER_HOME_ERROR)
            _release_git(world, evidence, install.checkout, "checkout", "--", _RELEASE_DECLARATION)


def _release_public_load() -> tuple[str, ...]:
    """The public command that reads the registered project's configuration the way every consumer does."""
    return ("config", "project", "get", _RELEASE_PROJECT_SLUG)


def _release_terminal(
    world: ReleaseWorld, evidence: list[CommandEvidence], install: ReleaseInstall
) -> PersistentTerminal:
    """The authenticated terminal of the registered release owner, opened on first use."""
    if world.terminal is None:
        terminal = _open_terminal(install.environment)
        world.terminal = terminal
        if terminal.run([_SHELL_CHANGE_DIRECTORY, str(install.checkout)]).returncode != _PROCESS_SUCCESS:
            raise RuntimeError(_FULL_TERMINAL_SETUP_ERROR)
        _release_terminal_run(
            world,
            evidence,
            install,
            (_release_python(world), "-m", _RELEASE_TELEC_MODULE, "auth", "login", _RELEASE_PERSON_EMAIL),
        )
    return world.terminal


def _release_terminal_run(
    world: ReleaseWorld,
    evidence: list[CommandEvidence],
    install: ReleaseInstall,
    argv: Sequence[str],
    *,
    expect_success: bool = True,
    refusal_snapshot: Path | None = None,
) -> str:
    """Run one public command as the signed-in release owner and require its expected outcome.

    An expected refusal must also equal its public-output snapshot, so an unrelated failure is not one.
    """
    terminal = world.terminal if world.terminal is not None else _release_terminal(world, evidence, install)
    status, output = _record_terminal_command(world.resources, terminal, argv, evidence)
    if status is None or (status == _PROCESS_SUCCESS) != expect_success or (not expect_success and not output.strip()):
        raise RuntimeError(
            _RELEASE_TERMINAL_ERROR.format(argv=" ".join(world.resources.sanitize(value) for value in argv))
        )
    if refusal_snapshot is not None:
        expected = (Path(__file__).parent / refusal_snapshot).read_text(encoding=_UTF8)
        if _LINE_BREAK.join(output.splitlines()).strip() + _LINE_BREAK != expected:
            raise RuntimeError(_RELEASE_REFUSAL_ERROR)
    return output


def _release_telec(
    world: ReleaseWorld,
    evidence: list[CommandEvidence],
    install: ReleaseInstall,
    *arguments: str,
    expect_success: bool = True,
) -> str:
    """Run the public ``telec`` command line as the signed-in release owner."""
    return _release_terminal_run(
        world,
        evidence,
        install,
        (_release_python(world), "-m", _RELEASE_TELEC_MODULE, *arguments),
        expect_success=expect_success,
    )


def _make_removable(root: Path) -> None:
    """Restore owner access to every directory a journey left write-protected."""
    for directory, _, _ in os.walk(root):
        Path(directory).chmod(_RELEASE_WRITABLE_MODE)


def _close_release_world(world: ReleaseWorld, evidence: list[CommandEvidence]) -> None:
    """Sign the release owner out, close its terminal and make the disposable history removable."""
    terminal = world.terminal
    world.terminal = None
    try:
        if terminal is not None:
            try:
                exit_status, _ = _record_terminal_command(
                    world.resources,
                    terminal,
                    (_release_python(world), "-m", _RELEASE_TELEC_MODULE, "auth", "logout"),
                    evidence,
                )
                _require_terminal_exit(exit_status, evidence)
            finally:
                terminal.close()
    finally:
        if world.resources.payload_provisional is None:
            _make_removable(world.root)


def _release_version(world: ReleaseWorld, evidence: list[CommandEvidence], install: ReleaseInstall, ref: str) -> str:
    tag = _release_git(world, evidence, install.checkout, "describe", "--tags", "--exact-match", ref)
    return tag.removeprefix("v")


def _deployed_outputs(install: ReleaseInstall) -> tuple[Path, ...]:
    """The installed commit's deployed skill, compiled instructions and documentation catalog."""
    return (
        install.checkout / _RELEASE_DEPLOYED_SKILL,
        install.checkout / _RELEASE_DEPLOYED_MASTER,
        install.checkout / _RELEASE_DEPLOYED_INDEX,
    )


def _frontmatter_fields(text: str) -> dict[str, str]:
    """The ``key: value`` fields of a document's leading frontmatter block."""
    fields: dict[str, str] = {}
    lines = text.splitlines()
    if not lines or lines[0] != _RELEASE_FRONTMATTER_FENCE:
        return fields
    for line in lines[1:]:
        if line == _RELEASE_FRONTMATTER_FENCE:
            break
        key, separator, value = line.partition(_RELEASE_FIELD_SEPARATOR)
        if separator:
            fields[key] = value
    return fields


def _catalog_entries(path: Path) -> list[dict[str, str]]:
    """The snippet entries of a generated documentation catalog, as field mappings."""
    entries: list[dict[str, str]] = []
    for line in path.read_text(encoding=_UTF8).splitlines():
        if line.startswith(_RELEASE_ENTRY_START):
            entries.append({})
            line = line.removeprefix(_RELEASE_ENTRY_START)
        elif not line.startswith(_RELEASE_ENTRY_CONTINUATION) or not entries:
            continue
        key, separator, value = line.strip().partition(_RELEASE_FIELD_SEPARATOR)
        if separator:
            entries[-1][key] = value
    return entries


def _committed(
    world: ReleaseWorld, evidence: list[CommandEvidence], install: ReleaseInstall, ref: str, path: Path
) -> str:
    """One source file as committed at ``ref``."""
    return _release_git(world, evidence, install.checkout, "show", f"{ref}:{path}")


def _require_published(world: ReleaseWorld, evidence: list[CommandEvidence], install: ReleaseInstall) -> None:
    """The deployed outputs are the installed commit's sources, while local main names different ones.

    The deployed skill and compiled instructions equal their sources at the installed commit and
    differ from the sources at local main; the catalog entry carries the installed commit's document
    description, path and identity.
    """
    skill, master, catalog = _deployed_outputs(install)
    for output in (skill, master, catalog):
        if not output.is_file() or not output.read_text(encoding=_UTF8).strip():
            raise ValueError(_RELEASE_OUTPUT_MISSING_ERROR.format(output=output.name))
    for output, source in ((skill, _RELEASE_PROBE_SKILL), (master, Path(_RELEASE_MASTER_NAME))):
        installed = _committed(world, evidence, install, "HEAD", source)
        if output.read_text(encoding=_UTF8).strip() != installed or installed == _committed(
            world, evidence, install, _RELEASE_BRANCH, source
        ):
            raise ValueError(_RELEASE_OUTPUT_SOURCE_ERROR.format(output=output.name))
    document = _frontmatter_fields(_committed(world, evidence, install, "HEAD", _RELEASE_PROBE_DOCUMENT))
    probes = [
        entry
        for entry in _catalog_entries(catalog)
        if entry.get(_RELEASE_CATALOG_PATH_FIELD) == str(_RELEASE_PROBE_DOCUMENT)
    ]
    if (
        len(probes) != 1
        or probes[0].get(_RELEASE_DESCRIPTION_FIELD) != document.get(_RELEASE_DESCRIPTION_FIELD)
        or probes[0].get(_RELEASE_CATALOG_ID_FIELD) != _RELEASE_PROBE_CATALOG_ID
        or document
        == _frontmatter_fields(_committed(world, evidence, install, _RELEASE_BRANCH, _RELEASE_PROBE_DOCUMENT))
    ):
        raise ValueError(_RELEASE_OUTPUT_SOURCE_ERROR.format(output=catalog.name))


def _release_publication(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    """UC-SPO34: every publication entry point deploys the installed commit while local main names another."""
    world = _release_world(resources, evidence)
    install = world.primary
    if install is None:
        raise ValueError(_RELEASE_FIXTURE_INVALID)
    _release_terminal(world, evidence, install)
    _release_update(world, evidence, install, _release_commit(world, evidence, prior=False))
    _require_published(world, evidence, install)

    for output in _deployed_outputs(install):
        output.unlink()
    _release_telec(world, evidence, install, "sync")
    _require_published(world, evidence, install)

    _release_update(world, evidence, install, _release_commit(world, evidence, prior=False), drain=False)
    _release_module(world, evidence, install, _RELEASE_MODULE_INSTALL_PUBLICATION)
    _require_published(world, evidence, install)
    _release_drain(world, evidence, install)

    index = install.checkout / _RELEASE_DEPLOYED_INDEX
    installed = _RELEASE_PROBE_LABEL.format(version=_release_version(world, evidence, install, "HEAD"))
    main = _RELEASE_PROBE_LABEL.format(version=_release_version(world, evidence, install, _RELEASE_BRANCH))
    index.write_text(
        index.read_text(encoding=_UTF8).replace(_RELEASE_CURRENT_ID, _RELEASE_LEGACY_ID).replace(installed, main),
        encoding=_UTF8,
    )
    _release_terminal_run(
        world, evidence, install, (_release_python(world), "-m", _RELEASE_CONVERGENCE_MODULE, str(install.checkout))
    )
    _require_published(world, evidence, install)

    previous = (install.checkout / _RELEASE_DEPLOYED_SKILL).read_text(encoding=_UTF8)
    protected = install.home / _RELEASE_PROTECTED_DIRECTORY
    protected.chmod(_RELEASE_WRITE_PROTECTED_MODE)
    try:
        _release_update(world, evidence, install, _release_commit(world, evidence, prior=False), drain=False)
        _release_module(world, evidence, install, _RELEASE_MODULE_DRAIN, expect_success=False)
    finally:
        _make_removable(install.home)
    if (install.checkout / _RELEASE_DEPLOYED_SKILL).read_text(encoding=_UTF8) != previous:
        raise ValueError(_RELEASE_REPLAY_PRESERVE_ERROR)
    failed = _head(world, evidence, install)
    command = (_RELEASE_AFTER_OPTION, failed, "--action", _RELEASE_REPLAY_ACTION)
    _release_terminal_run(
        world,
        evidence,
        install,
        (_release_python(world), "-m", _RELEASE_TELEC_MODULE, "code", "maintenance", "retry", *command),
        expect_success=False,
        refusal_snapshot=_RELEASE_RETRY_REFUSAL_SNAPSHOT,
    )
    _release_replay_recorded_publication(world, evidence, install, failed)


def _failed_range(install: ReleaseInstall, after_sha: str) -> Mapping[str, object]:
    """The retained failed record of one commit activation's publication action."""
    record = install.checkout / _RELEASE_MAINTENANCE_DIRECTORY / after_sha / _RELEASE_REPLAY_RECORD
    payload = _mapping_value(json.loads(record.read_text(encoding=_UTF8)))
    if payload is None or payload.get(_RELEASE_RECORD_STATE_FIELD) != _RELEASE_RECORD_FAILED:
        raise ValueError(_RELEASE_REPLAY_RECORD_ERROR)
    return payload


def _release_replay_recorded_publication(
    world: ReleaseWorld, evidence: list[CommandEvidence], install: ReleaseInstall, failed: str
) -> None:
    """Run the recorded publication command for a failed range after a newer release was adopted.

    The command is the public module the declared ``sync`` action runs, given the immutable range of
    the real retained failed record. The range selects the touched homes; the deployed commit is the
    installed one, not the range's own.
    """
    record = _failed_range(install, failed)
    _release_update(world, evidence, install, _release_commit(world, evidence, prior=False), drain=False)
    arguments: tuple[str, ...] = (_RELEASE_AFTER_OPTION, str(record[_RELEASE_RECORD_AFTER_FIELD]))
    before = record.get(_RELEASE_RECORD_BEFORE_FIELD)
    if isinstance(before, str):
        arguments = (*arguments, _RELEASE_BEFORE_OPTION, before)
    _release_module(world, evidence, install, _RELEASE_MODULE_PUBLISH, *arguments)
    _require_published(world, evidence, install)
    if _release_version(world, evidence, install, failed) == _release_version(world, evidence, install, "HEAD"):
        raise ValueError(_RELEASE_PUBLICATION_ERROR)


def _release_blueprint(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    """UC-BPF1: Blueprint maintenance and queries answer for the installed commit, not for local main."""
    world = _release_world(resources, evidence)
    install = world.primary
    if install is None:
        raise ValueError(_RELEASE_FIXTURE_INVALID)
    _release_update(world, evidence, install, _release_commit(world, evidence, prior=False, code=True))
    installed = _head(world, evidence, install)
    manifest = cast(
        Mapping[str, object], json.loads((install.checkout / _RELEASE_BLUEPRINT_MANIFEST).read_text(encoding=_UTF8))
    )
    if manifest.get(_RELEASE_BLUEPRINT_BASELINE_FIELD) != installed or installed == _release_git(
        world, evidence, install.checkout, "rev-parse", _RELEASE_BRANCH
    ):
        raise ValueError(_RELEASE_BLUEPRINT_ERROR)
    answer = _release_telec(world, evidence, install, "code", "blueprint", "affected", _RELEASE_BLUEPRINT_AFFECTED_PATH)
    expected = (Path(__file__).parent / _RELEASE_BLUEPRINT_SNAPSHOT).read_text(encoding=_UTF8)
    if _LINE_BREAK.join(answer.splitlines()).strip() + _LINE_BREAK != expected:
        raise ValueError(_RELEASE_BLUEPRINT_QUERY_ERROR)


def run_profile(
    profile: Profile,
    *,
    source_root: Path,
    source_revision: str,
    source_tree: str,
    selection: frozenset[str] = frozenset(),
    report_path: Path | None = None,
    payload_admission: GuestContext | None = None,
) -> AcceptanceReport:
    """Run the selected profile with disposable state and report cleanup separately."""
    provisional = None
    if profile is Profile.FULL:
        if payload_admission is None:
            return _unadmitted_full_report(source_revision, source_tree, selection)
        payload_admission.verify_request(source_root, source_revision, source_tree, selection)
        provisional = PayloadProvisional.from_admitted(payload_admission)
    end_ns = payload_admission.payload_deadline().effective_end() if payload_admission is not None else None
    with payload_work.scope(end_ns):
        return _run_profile(
            profile,
            source_root=source_root,
            source_revision=source_revision,
            source_tree=source_tree,
            selection=selection,
            report_path=report_path,
            payload_provisional=provisional,
        )


def _run_profile(
    profile: Profile,
    *,
    source_root: Path,
    source_revision: str,
    source_tree: str,
    selection: frozenset[str],
    report_path: Path | None,
    payload_provisional: PayloadProvisional | None,
) -> AcceptanceReport:
    """Execute the existing profile body inside its caller's admitted work scope."""
    payload_work.check()
    resolved_root = source_root.expanduser().resolve()
    temporary_root = Path(tempfile.mkdtemp(prefix=_ENVIRONMENT_CACHE_DIRECTORY))
    resources: FullRuntimeResources | None = None
    try:

        def cold_action() -> ScenarioResult:
            dependency_environment = ensure_dependency_environment(resolved_root)
            child_environment = _make_cold_environment(resolved_root, dependency_environment, temporary_root)
            return _cold_entrypoint_scenario(resolved_root, child_environment, dependency_environment)

        actions: dict[str, ScenarioAction] = {_SCENARIO_COLD: cold_action}
        inventory: Sequence[str] = _COLD_PROFILE_SCENARIOS

        def cleanup_cold(evidence: list[CommandEvidence]) -> None:
            del evidence
            shutil.rmtree(temporary_root)

        cleanup_action: CleanupAction = cleanup_cold
        if profile is Profile.FULL:
            resources = FullRuntimeResources(
                source_root=resolved_root,
                temporary_root=temporary_root,
                environment=_full_runtime_environment(),
                source_revision=source_revision,
                source_tree=source_tree,
                report_path=report_path.resolve() if report_path is not None else None,
                payload_provisional=payload_provisional,
                retired_act_selected=not selection or _SCENARIO_WORKFLOW_RETIRED_ACTS_B12 in selection,
                b13_selected=not selection or _SCENARIO_WORKFLOW_WAITING in selection,
                retired_act_evidence=creation.empty_retired_act_evidence(
                    status=(
                        creation.B12_STATUS_NOT_RUN
                        if not selection or _SCENARIO_WORKFLOW_RETIRED_ACTS_B12 in selection
                        else creation.B12_STATUS_NOT_SELECTED
                    ),
                    source_revision=source_revision,
                    source_tree=source_tree,
                ),
                b13_evidence=waiting.empty_b13_evidence(
                    status=(
                        waiting.B13_STATUS_NOT_RUN
                        if not selection or _SCENARIO_WORKFLOW_WAITING in selection
                        else waiting.B13_STATUS_NOT_SELECTED
                    ),
                    source_revision=source_revision,
                    source_tree=source_tree,
                ),
            )
            resources.workflow_chain = full_flow.declared_chain(selection)
            actions.update(
                {
                    _SCENARIO_RUNTIME_READY: _bind_full_scenario(
                        _SCENARIO_RUNTIME_READY, resources, _full_install_and_ready
                    ),
                    _SCENARIO_OWNER_IDENTITY: _bind_full_scenario(
                        _SCENARIO_OWNER_IDENTITY, resources, _full_owner_identity
                    ),
                    _SCENARIO_CONFIG_PATCH: _bind_full_scenario(
                        _SCENARIO_CONFIG_PATCH, resources, _full_configuration_change
                    ),
                    _SCENARIO_PROJECT_REGISTRATION: _bind_full_scenario(
                        _SCENARIO_PROJECT_REGISTRATION, resources, _full_project_registration
                    ),
                    _SCENARIO_JOB_SURFACE: _bind_full_scenario(_SCENARIO_JOB_SURFACE, resources, _full_jobs_surface),
                    _SCENARIO_RESTART_PERSISTENCE: _bind_full_scenario(
                        _SCENARIO_RESTART_PERSISTENCE, resources, _full_restart_persistence
                    ),
                    _SCENARIO_NON_ADMIN_REFUSAL: _bind_full_scenario(
                        _SCENARIO_NON_ADMIN_REFUSAL, resources, _full_non_admin_refusal
                    ),
                    _SCENARIO_CLEANUP: _bind_full_scenario(_SCENARIO_CLEANUP, resources, _full_failure_cleanup_probe),
                    _SCENARIO_CANDIDATE_IDENTITY: _bind_full_scenario(
                        _SCENARIO_CANDIDATE_IDENTITY, resources, _full_candidate_identity
                    ),
                    _SCENARIO_INVALID_CONFIG: _bind_full_scenario(
                        _SCENARIO_INVALID_CONFIG, resources, _full_unknown_key_refusal
                    ),
                    _SCENARIO_PROCEDURE_CLOSURE: _bind_full_scenario(
                        _SCENARIO_PROCEDURE_CLOSURE, resources, _full_procedure_closure
                    ),
                    _SCENARIO_DELIVERY_VALIDATION: _bind_full_scenario(
                        _SCENARIO_DELIVERY_VALIDATION, resources, _full_delivery_declaration_validation
                    ),
                    _SCENARIO_ARCHIVED_HISTORY: _bind_full_scenario(
                        _SCENARIO_ARCHIVED_HISTORY, resources, _full_archived_history
                    ),
                    _SCENARIO_CURATION_REFUSAL: _bind_full_scenario(
                        _SCENARIO_CURATION_REFUSAL, resources, _full_curation_refusal
                    ),
                    _SCENARIO_RELEASE_SELECTED: _bind_full_scenario(
                        _SCENARIO_RELEASE_SELECTED, resources, _release_selected_visibly
                    ),
                    _SCENARIO_RELEASE_PULL_REFUSED: _bind_full_scenario(
                        _SCENARIO_RELEASE_PULL_REFUSED, resources, _release_pull_refused
                    ),
                    _SCENARIO_RELEASE_ADOPTION: _bind_full_scenario(
                        _SCENARIO_RELEASE_ADOPTION, resources, _release_adoption
                    ),
                    _SCENARIO_RELEASE_NEXT: _bind_full_scenario(
                        _SCENARIO_RELEASE_NEXT, resources, _release_next_from_detached
                    ),
                    _SCENARIO_RELEASE_REPLAY: _bind_full_scenario(_SCENARIO_RELEASE_REPLAY, resources, _release_replay),
                    _SCENARIO_RELEASE_UNSUPPORTED: _bind_full_scenario(
                        _SCENARIO_RELEASE_UNSUPPORTED, resources, _release_unsupported_transitions
                    ),
                    _SCENARIO_RELEASE_RECORDING: _bind_full_scenario(
                        _SCENARIO_RELEASE_RECORDING, resources, _release_recording_refused
                    ),
                    _SCENARIO_RELEASE_CONFLICT: _bind_full_scenario(
                        _SCENARIO_RELEASE_CONFLICT, resources, _release_conflict
                    ),
                    _SCENARIO_RELEASE_DEVELOPMENT_CLONE: _bind_full_scenario(
                        _SCENARIO_RELEASE_DEVELOPMENT_CLONE, resources, _release_development_clone
                    ),
                    _SCENARIO_RELEASE_DECLARATION: _bind_full_scenario(
                        _SCENARIO_RELEASE_DECLARATION, resources, _release_retained_declaration
                    ),
                    _SCENARIO_RELEASE_PUBLICATION: _bind_full_scenario(
                        _SCENARIO_RELEASE_PUBLICATION, resources, _release_publication
                    ),
                    _SCENARIO_RELEASE_BLUEPRINT: _bind_full_scenario(
                        _SCENARIO_RELEASE_BLUEPRINT, resources, _release_blueprint
                    ),
                    _SCENARIO_WORKFLOW_FOUNDATION: _bind_full_scenario(
                        _SCENARIO_WORKFLOW_FOUNDATION, resources, _full_workflow_foundation
                    ),
                    _SCENARIO_WORKFLOW_CREATION: _bind_full_scenario(
                        _SCENARIO_WORKFLOW_CREATION, resources, _full_workflow_creation
                    ),
                    _SCENARIO_WORKFLOW_RETIRED_ACTS: _bind_full_scenario(
                        _SCENARIO_WORKFLOW_RETIRED_ACTS, resources, _full_workflow_retired_acts
                    ),
                    _SCENARIO_WORKFLOW_RETIRED_ACTS_B12: _bind_full_scenario(
                        _SCENARIO_WORKFLOW_RETIRED_ACTS_B12, resources, _full_workflow_b12
                    ),
                    _SCENARIO_WORKFLOW_PLANS: _bind_full_scenario(
                        _SCENARIO_WORKFLOW_PLANS, resources, _full_workflow_plans
                    ),
                    _SCENARIO_WORKFLOW_HOLDS: _bind_full_scenario(
                        _SCENARIO_WORKFLOW_HOLDS, resources, _full_workflow_holds
                    ),
                    _SCENARIO_WORKFLOW_REMOVAL: _bind_full_scenario(
                        _SCENARIO_WORKFLOW_REMOVAL, resources, _full_workflow_removal
                    ),
                    _SCENARIO_WORKFLOW_CLAIM: _bind_full_scenario(
                        _SCENARIO_WORKFLOW_CLAIM, resources, _full_workflow_claim
                    ),
                    _SCENARIO_WORKFLOW_RACE: _bind_full_scenario(
                        _SCENARIO_WORKFLOW_RACE, resources, _full_workflow_race
                    ),
                    _SCENARIO_WORKFLOW_WAITING: _bind_full_scenario(
                        _SCENARIO_WORKFLOW_WAITING, resources, _full_workflow_waiting
                    ),
                    _SCENARIO_WORKFLOW_PREPARED: _bind_full_scenario(
                        _SCENARIO_WORKFLOW_PREPARED, resources, _full_workflow_prepared
                    ),
                    _SCENARIO_WORKFLOW_REVIEW: _bind_full_scenario(
                        _SCENARIO_WORKFLOW_REVIEW, resources, _full_workflow_review
                    ),
                    _SCENARIO_WORKFLOW_READY: _bind_full_scenario(
                        _SCENARIO_WORKFLOW_READY, resources, _full_workflow_ready
                    ),
                    _SCENARIO_WORKFLOW_INTEGRATION: _bind_full_scenario(
                        _SCENARIO_WORKFLOW_INTEGRATION, resources, _full_workflow_integration
                    ),
                }
            )
            inventory = _FULL_PROFILE_SCENARIOS

            def cleanup_full(evidence: list[CommandEvidence]) -> None:
                _close_full_profile_resources(resources, evidence)

            cleanup_action = cleanup_full
        report = execute_profile(
            profile,
            source_revision=source_revision,
            source_tree=source_tree,
            scenario_inventory=inventory,
            scenario_actions=actions,
            cleanup_action=cleanup_action,
            selection=selection,
            payload_provisional=payload_provisional,
        )
        if resources is not None:
            try:
                event_evidence = events.profile_report(
                    temporary_root,
                    selected_cases=tuple(
                        case for case in events.CASE_SEQUENCE if not selection or f"UC-WF-{case}" in selection
                    )
                    if payload_provisional is not None
                    else None,
                )
            except Exception as error:
                event_evidence = {
                    "status": "unproven",
                    "case_report_path": str(temporary_root / events.CASE_REPORT_FILE),
                    "error": str(error),
                }
            delivery_path: Path | None = None
            delivery_marker = temporary_root / creation.B12_MATRIX_DIRECTORY / creation.B12_MARKER_FILE
            if delivery_marker.is_file():
                try:
                    marker_bytes = delivery_marker.read_bytes()
                    marker_record = json.loads(marker_bytes)
                    if _is_b12_delivery_marker(resources, delivery_marker, marker_record, marker_bytes):
                        delivery_path = delivery_marker.parent.resolve()
                except (OSError, ValueError):
                    delivery_path = None
            b13_delivery_path: Path | None = None
            b13_marker_directory: Path | None = None
            if (
                resources.b13_marker_path is not None
                and resources.b13_carrier_path is not None
                and resources.b13_marker_path.is_file()
            ):
                try:
                    marker_bytes = resources.b13_marker_path.read_bytes()
                    marker_record = json.loads(marker_bytes)
                    if _is_b13_delivery_marker(resources, resources.b13_marker_path, marker_record, marker_bytes):
                        b13_delivery_path = resources.b13_carrier_path.resolve()
                        b13_marker_directory = resources.b13_marker_path.parent.resolve()
                except (OSError, ValueError):
                    b13_delivery_path = None
                    b13_marker_directory = None
            return replace(
                report,
                workflow_event_evidence=event_evidence,
                retired_act_evidence=resources.retired_act_evidence,
                workflow_waiting_retired_kickback_evidence=resources.b13_evidence,
                retired_act_delivery_path=delivery_path,
                workflow_waiting_retired_kickback_delivery_path=b13_delivery_path,
                workflow_waiting_retired_kickback_marker_directory=b13_marker_directory,
                payload_provisional=payload_provisional.observe(
                    {
                        "owned_profile_root": str(temporary_root),
                        "daemon_stop_outcome": resources.daemon_stop_outcome,
                        "inner_cleanup": resources.inner_cleanup.record()
                        if resources.inner_cleanup is not None
                        else None,
                        "recorded_retention_reasons": list(resources.retained),
                        "recorded_retention_keys": dict(resources.retained_keys),
                        "flow_finalizer": resources.workflow_flow.finalizer_summary
                        if resources.workflow_flow is not None
                        else None,
                        "flow_finalizer_errors": list(resources.workflow_flow.finalizer_errors)
                        if resources.workflow_flow is not None
                        else [],
                        "early_workflow": resources.early_workflow,
                    }
                )
                if payload_provisional is not None
                else None,
            )
        return report
    except BaseException:
        if payload_provisional is None and temporary_root.exists() and (resources is None or not resources.retained):
            shutil.rmtree(temporary_root)
        raise


def _retire_delivered_b12_carrier(path: Path) -> None:
    """Remove only B12's delivery marker/carrier after the upload report has been written."""
    try:
        shutil.rmtree(path)
        parent = path.parent
        descriptor = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        parent.rmdir()
    except OSError:
        return


def _write_report_payload(report_path: Path, temporary_path: Path, payload: Mapping[str, object]) -> None:
    """Replace the report only after a complete serialized payload is available."""
    try:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        data = (json.dumps(payload, indent=2, allow_nan=False) + _LINE_BREAK).encode(_UTF8)
        with temporary_path.open("wb") as handle:
            if handle.write(data) != len(data):
                raise OSError(_REPORT_WRITE_INCOMPLETE)
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(report_path)
        directory = os.open(report_path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        if report_path.read_bytes() != data:
            raise OSError(_REPORT_READBACK_MISMATCH)
    except (OSError, TypeError, ValueError) as exc:
        raise RuntimeError(_REPORT_WRITE_ERROR.format(error=exc)) from exc


def _append_b13_failure(existing: str, addition: str) -> str:
    """Preserve an earlier B13 failure while recording an independent later cause."""
    if not existing:
        return addition
    if addition in existing:
        return existing
    return existing + _B13_FAILURE_SEPARATOR + addition


def _b13_report_unproven(
    report: AcceptanceReport,
    *,
    evidence_failure: str = _EMPTY,
    export_failure: str = _EMPTY,
) -> AcceptanceReport:
    """Downgrade B13 without replacing cleanup facts or claiming unobserved retention."""
    evidence = report.workflow_waiting_retired_kickback_evidence
    evidence.status = waiting.B13_STATUS_UNPROVEN
    evidence.evidence_failure = _append_b13_failure(evidence.evidence_failure, evidence_failure)
    evidence.export_failure = _append_b13_failure(evidence.export_failure, export_failure)
    detail = export_failure or evidence_failure or _B13_REPORT_SEAL_FAILURE
    scenarios = tuple(
        replace(
            result,
            status=ScenarioStatus.FAILED,
            diagnostics=_append_b13_failure(result.diagnostics, detail),
        )
        if result.scenario_id == _SCENARIO_WORKFLOW_WAITING
        else result
        for result in report.scenarios
    )
    return replace(
        report,
        scenarios=scenarios,
    )


def _report_payload(report: AcceptanceReport) -> JsonObject:
    """Keep legacy bytes/schema shape while serializing only newly admitted reports as a typed provisional stage."""
    payload = asdict(report)
    for name in (
        _REPORT_RETIRED_ACT_DELIVERY_PATH,
        _B13_REPORT_DELIVERY_PATH_FIELD,
        _B13_REPORT_MARKER_DIRECTORY_FIELD,
        "payload_provisional",
    ):
        payload.pop(name, None)
    if report.payload_provisional is not None:
        payload["stage"] = PROVISIONAL_STAGE
        payload["payload_provisional"] = report.payload_provisional.record()
    return cast(JsonObject, payload)


def write_report(report: AcceptanceReport, report_path: Path) -> AcceptanceReport:
    """Persist a report atomically enough that readers never accept a partial JSON file."""
    b13 = report.workflow_waiting_retired_kickback_evidence
    b13_delivery_path = report.workflow_waiting_retired_kickback_delivery_path
    b13_marker_directory = report.workflow_waiting_retired_kickback_marker_directory
    if b13.status == waiting.B13_STATUS_COMPLETE and (
        not isinstance(b13_delivery_path, Path)
        or not isinstance(b13_marker_directory, Path)
        or not (b13_marker_directory / waiting.B13_MARKER_FILE).is_file()
        or not waiting.verify_b13_delivery(
            b13,
            b13_marker_directory / waiting.B13_MARKER_FILE,
            b13_delivery_path,
            lambda value: value,
        )
    ):
        report = _b13_report_unproven(
            report,
            evidence_failure=waiting.B13_ERROR_SEAL,
            export_failure=_B13_REPORT_SEAL_FAILURE,
        )
    temporary_path = report_path.with_suffix(f"{report_path.suffix}{_REPORT_TEMP_SUFFIX}")
    payload = _report_payload(report)
    delivery_path = report.retired_act_delivery_path
    try:
        _write_report_payload(report_path, temporary_path, payload)
    except RuntimeError as error:
        if report.workflow_waiting_retired_kickback_evidence.status != waiting.B13_STATUS_COMPLETE:
            raise
        safe_error = str(error).replace(str(report_path.parent), _SYNTHETIC_RUNTIME_PLACEHOLDER)
        report = _b13_report_unproven(report, export_failure=_B13_REPORT_WRITE_FAILURE.format(error=safe_error))
        failure_payload = _report_payload(report)
        _write_report_payload(report_path, temporary_path, failure_payload)
        return report
    try:
        report_bytes = report_path.read_bytes()
        report_value = json.loads(report_bytes)
        if not isinstance(report_value, Mapping):
            raise ValueError(waiting.B13_ERROR_SEAL)
        b13_value = report_value.get(_B13_REPORT_EVIDENCE_FIELD)
        if b13_value != asdict(report.workflow_waiting_retired_kickback_evidence):
            raise ValueError(waiting.B13_ERROR_SEAL)
    except (OSError, ValueError, TypeError) as error:
        if report.workflow_waiting_retired_kickback_evidence.status != waiting.B13_STATUS_COMPLETE:
            raise RuntimeError(waiting.B13_ERROR_SEAL) from error
        safe_error = str(error).replace(str(report_path.parent), _SYNTHETIC_RUNTIME_PLACEHOLDER)
        report = _b13_report_unproven(report, export_failure=_B13_REPORT_READBACK_FAILURE.format(error=safe_error))
        failure_payload = _report_payload(report)
        _write_report_payload(report_path, temporary_path, failure_payload)
        return report
    if report.workflow_waiting_retired_kickback_evidence.status == waiting.B13_STATUS_COMPLETE and (
        not isinstance(b13_delivery_path, Path)
        or not isinstance(b13_marker_directory, Path)
        or not (b13_marker_directory / waiting.B13_MARKER_FILE).is_file()
        or not waiting.verify_b13_delivery(
            report.workflow_waiting_retired_kickback_evidence,
            b13_marker_directory / waiting.B13_MARKER_FILE,
            b13_delivery_path,
            lambda value: value,
        )
    ):
        report = _b13_report_unproven(
            report,
            evidence_failure=waiting.B13_ERROR_SEAL,
            export_failure=_B13_REPORT_SEAL_FAILURE,
        )
        failure_payload = _report_payload(report)
        _write_report_payload(report_path, temporary_path, failure_payload)
        return report
    if (
        report.payload_provisional is None
        and report.workflow_waiting_retired_kickback_evidence.status == waiting.B13_STATUS_COMPLETE
    ):
        assert isinstance(b13_marker_directory, Path)
        assert isinstance(b13_delivery_path, Path)
        shutil.rmtree(b13_marker_directory)
        b13_delivery_path.unlink()
        descriptor = os.open(b13_delivery_path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    if report.payload_provisional is None and isinstance(delivery_path, Path):
        _retire_delivered_b12_carrier(delivery_path)
    return report


def _validate_b13_report(report: Mapping[str, object], source_revision: str, source_tree: str) -> None:
    """Validate B13's exact ten-call evidence and embedded external-carrier seal."""
    b13_value = report.get("workflow_waiting_retired_kickback_evidence")
    if not isinstance(b13_value, dict):
        raise ValueError
    b13 = b13_value
    b13_fields = {
        "schema_version",
        "status",
        "assertion_path",
        "assertion_sha256",
        "issue_revision",
        "source_revision",
        "source_tree",
        "item",
        "argv",
        "prerequisites",
        "before",
        "response",
        "readbacks",
        "attempt_ledger",
        "carrier",
        "duration_seconds",
        "primary_failure",
        "evidence_failure",
        waiting.B13_EXPORT_FAILURE_FIELD,
    }
    b13_carrier = b13.get("carrier")
    b13_response = b13.get("response")
    b13_before = b13.get("before")
    b13_reads = b13.get("readbacks")
    b13_ledger = b13.get("attempt_ledger")
    b13_payload = {key: value for key, value in b13.items() if key != "carrier"}
    b13_payload_bytes = (
        json.dumps(b13_payload, sort_keys=True, separators=waiting.B13_JSON_SEPARATORS) + waiting.B13_NEWLINE
    ).encode(_UTF8)
    prerequisites = b13.get("prerequisites")
    actor_data = prerequisites.get(waiting.B13_ACTORS_FIELD, {}) if isinstance(prerequisites, dict) else {}
    owner_slug = actor_data.get("owner_slug", "") if isinstance(actor_data, dict) else ""
    waiting_snapshot = b13_before.get("item") if isinstance(b13_before, dict) else None
    has_admitted, _ = creation.dig(waiting_snapshot, "standing.admitted")
    if (
        set(b13) != b13_fields
        or b13.get("schema_version") != waiting.B13_SCHEMA_VERSION
        or b13.get("status") != waiting.B13_STATUS_COMPLETE
        or b13.get("assertion_path") != waiting.B13_ASSERTION_PATH
        or b13.get("assertion_sha256") != waiting.B13_ASSERTION_SHA
        or b13.get("issue_revision") != waiting.B13_ISSUE_REVISION
        or b13.get("source_revision") != source_revision
        or b13.get("source_tree") != source_tree
        or b13.get("item") != "b3-item"
        or b13.get("argv") != list(waiting.B13_CALL_ARGV)
        or type(b13.get("duration_seconds")) not in (int, float)
        or not math.isfinite(b13["duration_seconds"])
        or b13["duration_seconds"] > waiting.B13_SCENARIO_SECONDS
        or b13.get("primary_failure") != _EMPTY
        or b13.get("evidence_failure") != _EMPTY
        or b13.get(waiting.B13_EXPORT_FAILURE_FIELD) != _EMPTY
        or not isinstance(prerequisites, dict)
        or actor_data.get("owner") is None
        or not isinstance(owner_slug, str)
        or not owner_slug
        or not isinstance(actor_data.get("first_driver"), str)
        or not isinstance(actor_data.get("child"), str)
        or prerequisites.get("first_claim_positive") is not True
        or prerequisites.get("waiting_act_positive") is not True
        or prerequisites.get("child_closed") is not True
        or prerequisites.get("first_driver_live") is not True
        or prerequisites.get("unresolved_start_attempts") != []
        or not isinstance(prerequisites.get(waiting.B13_CANDIDATE_FIELD), str)
        or not prerequisites.get(waiting.B13_CANDIDATE_FIELD)
        or not isinstance(prerequisites.get(waiting.B13_CONTROL_PATHS_FIELD), list)
        or not isinstance(b13_before, dict)
        or creation.dig(waiting_snapshot, "state.lifecycle_phase") != (True, waiting.PHASE_WAITING)
        or creation.dig(waiting_snapshot, "standing.phase") != (True, waiting.PHASE_WAITING)
        or creation.dig(waiting_snapshot, "standing.waiting_on") != (True, owner_slug)
        or creation.dig(waiting_snapshot, "state.active_runner")[1] not in (None, "")
        or has_admitted
        or not isinstance(b13_response, dict)
        or b13_response.get("argv") != list(waiting.B13_CALL_ARGV)
        or type(b13_response.get("exit_status")) is not int
        or b13_response.get("exit_status") == 0
        or b13_response.get("diagnostics") != _EMPTY
        or b13_response.get(waiting.B13_OPERATION_FIELD) is not None
        or b13_response.get(waiting.B13_OPERATION_STATUS_FIELD) != waiting.B13_OPERATION_NOT_APPLICABLE
        or b13_response.get("stdout_sanitized") is not True
        or b13_response.get("stderr_sanitized") is not True
        or b13_response.get("diagnostics_sanitized") is not True
        or b13_response.get("output_truncated") is not False
        or b13_response.get("stderr_truncated") is not False
        or not all(isinstance(b13_response.get(key), str) for key in ("output", "stderr", "diagnostics"))
        or creation.retired_snapshot_state(creation.RETIRED_SNAPSHOT_B13_KICKBACK, b13_response.get("output", ""))
        is not creation.RetiredSnapshotState.MATCH
        or not isinstance(b13_reads, list)
        or len(b13_reads) != 2
        or not isinstance(b13_ledger, dict)
        or b13_ledger.get("framing") != waiting.B13_FRAMING_COMPLETE
        or b13_ledger.get("record_count") != waiting.B13_ATTEMPTS_EXPECTED_RECORDS
        or b13_ledger.get("read_error") != _EMPTY
        or b13_ledger.get("parse_error") != _EMPTY
        or type(b13_ledger.get("original_byte_count")) is not int
        or b13_ledger.get("original_byte_count") <= 0
        or not isinstance(b13_ledger.get("original_sha256"), str)
        or not isinstance(b13_ledger.get("sanitized_text"), str)
        or type(b13_ledger.get("sanitized_text_truncated")) is not bool
        or not isinstance(b13_carrier, dict)
        or b13_carrier.get("carrier_sha256") != hashlib.sha256(b13_payload_bytes).hexdigest()
        or b13_carrier.get("carrier_byte_count") != len(b13_payload_bytes)
        or b13_carrier.get("owned") is not True
        or b13_carrier.get(waiting.B13_ATTEMPTS_PATH_FIELD) != b13_ledger.get("path")
        or b13_carrier.get(waiting.B13_ATTEMPTS_SHA_FIELD) != b13_ledger.get("original_sha256")
        or b13_carrier.get(waiting.B13_ATTEMPTS_BYTES_FIELD) != b13_ledger.get("original_byte_count")
        or type(b13_carrier.get("marker_byte_count")) is not int
        or b13_carrier.get("marker_byte_count") <= 0
        or not isinstance(b13_carrier.get("marker_sha256"), str)
        or b13_carrier.get("sanitized") is not True
        or b13_carrier.get("carrier_truncated") is not False
    ):
        raise ValueError
    baseline_item = b13_before.get("item")
    baseline_sessions = b13_before.get("session_ids")
    baseline_slugs = b13_before.get("slugs")
    expected_read_argv = [list(argv) for argv in waiting.B13_READ_ARGV]
    if (
        b13_before.get("argv") != expected_read_argv
        or not isinstance(baseline_item, dict)
        or not isinstance(baseline_sessions, list)
        or not isinstance(baseline_slugs, list)
    ):
        raise ValueError
    for expected_when, readback in zip(
        (waiting.B13_OBSERVATION_IMMEDIATE, waiting.B13_OBSERVATION_SETTLED), b13_reads, strict=True
    ):
        if (
            not isinstance(readback, dict)
            or readback.get("argv") != expected_read_argv
            or readback.get("when") != expected_when
            or readback.get("item") != baseline_item
            or readback.get("session_ids") != baseline_sessions
            or readback.get("slugs") != baseline_slugs
        ):
            raise ValueError


def _validate_r4_snapshot_commands(scenario: Mapping[str, object]) -> None:
    """Require the three retained R4 target commands to match their full reviewed output snapshots."""
    commands = scenario.get(_COMMAND_EVIDENCE_COMMANDS_FIELD)
    if not isinstance(commands, list):
        raise ValueError
    matched_indices: list[int] = []
    for expected_arguments, snapshot_id in _R4_SNAPSHOT_COMMANDS:
        matches = [
            (index, command)
            for index, command in enumerate(commands)
            if isinstance(command, dict)
            and isinstance(command.get(_COMMAND_EVIDENCE_ARGV_FIELD), list)
            and command[_COMMAND_EVIDENCE_ARGV_FIELD][1:] == list(expected_arguments)
        ]
        if len(matches) != 1:
            raise ValueError
        index, command = matches[0]
        matched_indices.append(index)
        output = command.get(_COMMAND_EVIDENCE_STDOUT_FIELD)
        if (
            type(command.get(_COMMAND_EVIDENCE_EXIT_STATUS_FIELD)) is not int
            or command[_COMMAND_EVIDENCE_EXIT_STATUS_FIELD] == 0
            or command.get(_COMMAND_EVIDENCE_DIAGNOSTICS_FIELD) != _EMPTY
            or not isinstance(output, str)
            or creation.retired_snapshot_state(snapshot_id, output) is not creation.RetiredSnapshotState.MATCH
        ):
            raise ValueError
    if matched_indices != sorted(matched_indices):
        raise ValueError


def _validate_b12_report(report: Mapping[str, object], source_revision: str, source_tree: str) -> None:
    """Apply the existing complete B12 evidence checks for either full or selected coverage."""
    retired = report[creation.B12Field.RETIRED_ACT_EVIDENCE]
    if not isinstance(retired, dict):
        raise ValueError
    retired_fields = {
        creation.B12Field.SCHEMA_VERSION,
        creation.B12Field.STATUS,
        creation.B12Field.SELECTED_AMENDMENT,
        creation.B12Field.ASSERTION_PATH,
        creation.B12Field.ASSERTION_SHA256,
        creation.B12Field.SOURCE_REVISION,
        creation.B12Field.SOURCE_TREE,
        creation.B12Field.ISSUE_REVISION,
        creation.B12Field.ORDERED_CASES,
        creation.B12Field.ORDERED_CASE_PLAN,
        creation.B12Field.PREREQUISITES,
        creation.B12Field.BASELINES,
        creation.B12Field.CASES,
        creation.B12Field.CARRIER,
        creation.B12Field.DURATION_SECONDS,
        creation.B12Field.PRIMARY_FAILURE,
        creation.B12Field.EVIDENCE_FAILURE,
    }
    if (
        set(retired) != retired_fields
        or type(retired[creation.B12Field.SCHEMA_VERSION]) is not int
        or retired[creation.B12Field.SCHEMA_VERSION] != creation.B12_JSON_SCHEMA
        or retired[creation.B12Field.STATUS] != creation.B12_STATUS_COMPLETE
        or retired[creation.B12Field.SELECTED_AMENDMENT] != creation.B12_AMENDMENT
        or retired[creation.B12Field.ASSERTION_PATH] != creation.B12_ARTIFACT_PATH
        or retired[creation.B12Field.ASSERTION_SHA256] != creation.B12_ARTIFACT_SHA
        or retired[creation.B12Field.SOURCE_REVISION] != source_revision
        or retired[creation.B12Field.SOURCE_TREE] != source_tree
        or retired[creation.B12Field.ISSUE_REVISION] != creation.B12_ISSUE_REVISION
        or retired[creation.B12Field.ORDERED_CASES] != [case_id for case_id, _, _ in creation.B12_CASES]
        or retired[creation.B12Field.ORDERED_CASE_PLAN]
        != [
            {
                creation.B12Field.CASE_ID: case_id,
                creation.B12Field.ARGV: list(argv),
                creation.B12Field.RETIRED_TYPE: retired_type,
            }
            for case_id, argv, retired_type in creation.B12_CASES
        ]
        or not isinstance(retired[creation.B12Field.PREREQUISITES], dict)
        or not isinstance(retired[creation.B12Field.BASELINES], dict)
        or not isinstance(retired[creation.B12Field.CARRIER], dict)
        or retired[creation.B12Field.PRIMARY_FAILURE] != _EMPTY
        or retired[creation.B12Field.EVIDENCE_FAILURE] != _EMPTY
        or type(retired[creation.B12Field.DURATION_SECONDS]) not in (int, float)
        or not math.isfinite(retired[creation.B12Field.DURATION_SECONDS])
        or retired[creation.B12Field.DURATION_SECONDS] > creation.B12_SCENARIO_SECONDS
        or retired[creation.B12Field.BASELINES].get(creation.B12Field.STABLE_SHOW_READS) != 2
        or retired[creation.B12Field.BASELINES].get(creation.B12Field.SEPARATION_SECONDS)
        != creation.B12_INITIAL_STABILITY_SECONDS
        or not isinstance(retired[creation.B12Field.BASELINES].get(creation.B12Field.S0), dict)
        or not isinstance(retired[creation.B12Field.BASELINES].get(creation.B12Field.B0), list)
        or not isinstance(retired[creation.B12Field.BASELINES].get(creation.B12Field.T0), list)
        or not isinstance(retired[creation.B12Field.BASELINES].get(creation.B12Field.INITIAL_SHOW_READS), list)
        or len(retired[creation.B12Field.BASELINES][creation.B12Field.INITIAL_SHOW_READS]) != 2
        or retired[creation.B12Field.PREREQUISITES].get(creation.B12Field.MANUAL_RUNNER) is not True
        or not isinstance(retired[creation.B12Field.PREREQUISITES].get(creation.B12Field.PROJECT_CWD), str)
        or not isinstance(retired[creation.B12Field.PREREQUISITES].get(creation.B12Field.CLEARANCE), str)
        or not isinstance(retired[creation.B12Field.PREREQUISITES].get(creation.B12Field.OWNER_IDENTITY), dict)
    ):
        raise ValueError
    if any(
        show != retired[creation.B12Field.BASELINES][creation.B12Field.S0]
        for show in retired[creation.B12Field.BASELINES][creation.B12Field.INITIAL_SHOW_READS]
    ):
        raise ValueError
    retired_cases = retired[creation.B12Field.CASES]
    if not isinstance(retired_cases, list) or len(retired_cases) != len(creation.B12_CASES):
        raise ValueError
    for case, (expected_case_id, expected_argv, expected_type) in zip(retired_cases, creation.B12_CASES, strict=True):
        if (
            not isinstance(case, dict)
            or case.get(creation.B12Field.CASE_ID) != expected_case_id
            or case.get(creation.B12Field.ARGV) != list(expected_argv)
            or case.get(creation.B12Field.RETIRED_TYPE) != expected_type
            or case.get(creation.B12Field.CLASSIFICATION) != creation.B12_CLASS_VERIFIED
            or case.get(creation.B12Field.OUTCOME) != creation.B12_OUTCOME_COMPLETED
            or type(case.get(creation.B12Field.EXIT_STATUS)) is not int
            or case.get(creation.B12Field.EXIT_STATUS) == 0
            or type(case.get(creation.B12Field.DURATION_SECONDS)) not in (int, float)
            or not math.isfinite(case[creation.B12Field.DURATION_SECONDS])
            or case[creation.B12Field.DURATION_SECONDS] < 0
            or not all(
                isinstance(case.get(field), str)
                for field in (creation.B12Field.STDOUT, creation.B12Field.STDERR, creation.B12Field.DIAGNOSTICS)
            )
            or case.get(creation.B12Field.OUTPUT_TRUNCATED) is not False
            or creation.retired_snapshot_state(
                f"{creation.B12_SNAPSHOT_ID_PREFIX}{expected_case_id}",
                case.get(creation.B12Field.STDOUT, ""),
            )
            is not creation.RetiredSnapshotState.MATCH
            or type(case.get(creation.B12Field.STDOUT_BYTE_COUNT)) is not int
            or case.get(creation.B12Field.STDOUT_BYTE_COUNT) < 0
            or not isinstance(case.get(creation.B12Field.STDOUT_SHA256), str)
            or case.get(creation.B12Field.EMBEDDED_STDOUT_SHA256)
            != hashlib.sha256(case[creation.B12Field.STDOUT].encode(_UTF8)).hexdigest()
            or case.get(creation.B12Field.EMBEDDED_STDOUT_BYTE_COUNT)
            != len(case[creation.B12Field.STDOUT].encode(_UTF8))
            or case.get(creation.B12Field.STDERR_CAPTURE) != creation.B12_PTY_CAPTURE
            or not isinstance(case.get(creation.B12Field.READBACKS), list)
            or len(case[creation.B12Field.READBACKS]) != 2
            or not isinstance(case.get(creation.B12Field.BEFORE), dict)
            or case[creation.B12Field.BEFORE].get(creation.B12Field.ITEM)
            != retired[creation.B12Field.BASELINES][creation.B12Field.S0]
            or case[creation.B12Field.BEFORE].get(creation.B12Field.BEFORE_SESSIONS)
            != retired[creation.B12Field.BASELINES][creation.B12Field.B0]
            or case[creation.B12Field.BEFORE].get(creation.B12Field.BEFORE_SLUGS)
            != retired[creation.B12Field.BASELINES][creation.B12Field.T0]
            or case[creation.B12Field.BEFORE].get(creation.B12Field.PRECALL_DIFFERENCES) != []
            or not isinstance(case[creation.B12Field.BEFORE].get(creation.B12Field.BEFORE_SHOW_READS), list)
            or len(case[creation.B12Field.BEFORE][creation.B12Field.BEFORE_SHOW_READS]) != 2
            or case.get(creation.B12Field.UNCHANGED) is not True
            or case.get(creation.B12Field.DIFFERENCES) != []
            or case.get(creation.B12Field.OPERATION_ID) is not None
            or case.get(creation.B12Field.OPERATION_STATUS) != creation.B12_OPERATION_NOT_APPLICABLE
            or case.get(creation.B12Field.REFUSAL_FAILURE) != _EMPTY
            or type(case.get(creation.B12Field.OUTPUT_TRUNCATED)) is not bool
        ):
            raise ValueError
        if any(
            show != retired[creation.B12Field.BASELINES][creation.B12Field.S0]
            for show in case[creation.B12Field.BEFORE][creation.B12Field.BEFORE_SHOW_READS]
        ):
            raise ValueError
        for expected_when, readback in zip(
            (creation.B12_CASE_IMMEDIATE, creation.B12_CASE_SETTLED), case[creation.B12Field.READBACKS], strict=True
        ):
            if (
                not isinstance(readback, dict)
                or readback.get(creation.B12Field.WHEN) != expected_when
                or readback.get(creation.B12Field.ITEM) != retired[creation.B12Field.BASELINES][creation.B12Field.S0]
                or readback.get(creation.B12Field.SESSION_IDS)
                != retired[creation.B12Field.BASELINES][creation.B12Field.B0]
                or readback.get(creation.B12Field.SLUGS) != retired[creation.B12Field.BASELINES][creation.B12Field.T0]
            ):
                raise ValueError
    carrier = retired[creation.B12Field.CARRIER]
    embedded_b12 = json.dumps(
        {
            creation.B12Field.BASELINES: retired[creation.B12Field.BASELINES],
            creation.B12Field.CASES: retired_cases,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=_JSON_SEPARATORS,
    ).encode(_UTF8)
    if (
        carrier.get(creation.B12Field.FRAMING) != creation.B12_FRAMING_COMPLETE
        or carrier.get(creation.B12Field.LINE_COUNT) != len(creation.B12_CASES) * 3
        or type(carrier.get(creation.B12Field.ORIGINAL_BYTE_COUNT)) is not int
        or carrier.get(creation.B12Field.ORIGINAL_BYTE_COUNT) <= 0
        or not isinstance(carrier.get(creation.B12Field.ORIGINAL_SHA256), str)
        or type(carrier.get(creation.B12Field.MARKER_BYTE_COUNT)) is not int
        or carrier.get(creation.B12Field.MARKER_BYTE_COUNT) <= 0
        or not isinstance(carrier.get(creation.B12Field.MARKER_SHA256), str)
        or not isinstance(carrier.get(creation.B12Field.MARKER_PATH), str)
        or type(carrier.get(creation.B12Field.COMPLETED_BYTE_COUNT)) is not int
        or carrier.get(creation.B12Field.COMPLETED_BYTE_COUNT) <= 0
        or not isinstance(carrier.get(creation.B12Field.COMPLETED_SHA256), str)
        or not isinstance(carrier.get(creation.B12Field.COMPLETED_PATH), str)
        or type(carrier.get(creation.B12Field.COMPLETED_RAW_TEXT_TRUNCATED)) is not bool
        or carrier.get(creation.B12Field.COMPLETED_READ_ERROR) != _EMPTY
        or carrier.get(creation.B12Field.EMBEDDED_SCOPE) != creation.B12_EMBEDDED_SCOPE
        or carrier.get(creation.B12Field.EMBEDDED_SHA256) != hashlib.sha256(embedded_b12).hexdigest()
        or carrier.get(creation.B12Field.EMBEDDED_BYTE_COUNT) != len(embedded_b12)
        or carrier.get(creation.B12Field.READ_ERROR) != _EMPTY
    ):
        raise ValueError


def _validate_report_commands(commands: object) -> None:
    """Validate the existing command evidence shape without treating expected refusals as successes."""
    if not isinstance(commands, list):
        raise ValueError
    for command in commands:
        if (
            not isinstance(command, dict)
            or set(command) != {"argv", "exit_status", "duration_seconds", "stdout", "stderr", "diagnostics"}
            or not isinstance(command["argv"], list)
            or not all(isinstance(part, str) for part in command["argv"])
            or (command["exit_status"] is not None and type(command["exit_status"]) is not int)
            or type(command["duration_seconds"]) not in (int, float)
            or not math.isfinite(command["duration_seconds"])
            or command["duration_seconds"] < 0
            or not all(isinstance(command[field], str) for field in ("stdout", "stderr", "diagnostics"))
        ):
            raise ValueError


def validate_full_report_bytes(report_bytes: bytes, *, source_revision: str, source_tree: str) -> None:
    """Require complete, successful structured full-profile evidence for one exact source tree."""
    try:
        report = json.loads(report_bytes)
        expected_fields = {
            "schema_version",
            "source_revision",
            "source_tree",
            "profile",
            "scenario_inventory",
            "scenarios",
            "cleanup",
            "duration_seconds",
            "selection",
            "workflow_event_evidence",
            creation.B12Field.RETIRED_ACT_EVIDENCE,
            "workflow_waiting_retired_kickback_evidence",
        }
        if (
            not isinstance(report, dict)
            or set(report) != expected_fields
            or type(report["schema_version"]) is not int
            or report["schema_version"] != _REPORT_SCHEMA_VERSION
            or report["source_revision"] != source_revision
            or report["source_tree"] != source_tree
            or report["profile"] != _PROFILE_FULL
            or report["selection"] != []
            or report["scenario_inventory"] != list(_FULL_PROFILE_SCENARIOS)
            or type(report["duration_seconds"]) not in (int, float)
            or not math.isfinite(report["duration_seconds"])
            or report["duration_seconds"] < 0
            or not isinstance(report["workflow_event_evidence"], dict)
            or not isinstance(report[creation.B12Field.RETIRED_ACT_EVIDENCE], dict)
            or not isinstance(report["workflow_waiting_retired_kickback_evidence"], dict)
        ):
            raise ValueError
        _validate_b12_report(report, source_revision, source_tree)
        _validate_b13_report(report, source_revision, source_tree)
        scenarios = report["scenarios"]
        if not isinstance(scenarios, list) or len(scenarios) != len(_FULL_PROFILE_SCENARIOS):
            raise ValueError
        for expected_id, scenario in zip(_FULL_PROFILE_SCENARIOS, scenarios, strict=True):
            if (
                not isinstance(scenario, dict)
                or set(scenario) != {"scenario_id", "status", "duration_seconds", "commands", "diagnostics"}
                or scenario["scenario_id"] != expected_id
                or scenario["status"] != ScenarioStatus.PASSED.value
                or type(scenario["duration_seconds"]) not in (int, float)
                or not math.isfinite(scenario["duration_seconds"])
                or scenario["duration_seconds"] < 0
                or not isinstance(scenario["commands"], list)
                or scenario["diagnostics"] != _EMPTY
            ):
                raise ValueError
            _validate_report_commands(scenario["commands"])
            if expected_id == _SCENARIO_WORKFLOW_RETIRED_ACTS:
                _validate_r4_snapshot_commands(scenario)
        cleanup = report["cleanup"]
        if (
            not isinstance(cleanup, dict)
            or set(cleanup) not in ({"status", "detail"}, {"status", "detail", "commands"})
            or cleanup["status"] != ScenarioStatus.PASSED.value
            or cleanup["detail"] != _EMPTY
            or ("commands" in cleanup and cleanup["commands"] != [])
        ):
            raise ValueError
    except (json.JSONDecodeError, UnicodeDecodeError, KeyError, OverflowError, TypeError, ValueError):
        raise ValueError(_FULL_REPORT_INVALID) from None


def _validate_provisional_scenarios(report: JsonObject, selection: frozenset[str]) -> tuple[str, ...]:
    """Require exact ordered coverage, including honest NOT_RUN entries for unselected journeys."""
    if selection - set(_FULL_PROFILE_SCENARIOS) or any(
        not set(_SCENARIO_PREREQUISITES.get(scenario_id, ())) <= selection for scenario_id in selection
    ):
        raise ValueError(_FULL_REPORT_INVALID)
    scenarios = report["scenarios"]
    if not isinstance(scenarios, list) or len(scenarios) != len(_FULL_PROFILE_SCENARIOS):
        raise ValueError(_FULL_REPORT_INVALID)
    covered: list[str] = []
    for expected_id, value in zip(_FULL_PROFILE_SCENARIOS, scenarios, strict=True):
        if not isinstance(value, dict) or set(value) != {
            "scenario_id",
            "status",
            "duration_seconds",
            "commands",
            "diagnostics",
        }:
            raise ValueError(_FULL_REPORT_INVALID)
        duration = value["duration_seconds"]
        selected = not selection or expected_id in selection
        if (
            value["scenario_id"] != expected_id
            or type(duration) not in (int, float)
            or not isinstance(duration, (int, float))
            or not math.isfinite(duration)
            or duration < 0
            or value["status"] != (ScenarioStatus.PASSED.value if selected else ScenarioStatus.NOT_RUN.value)
            or value["diagnostics"] != (_EMPTY if selected else _SCENARIO_NOT_SELECTED)
        ):
            raise ValueError(_FULL_REPORT_INVALID)
        _validate_report_commands(value["commands"])
        if not selected:
            if duration != 0 or value["commands"] != []:
                raise ValueError(_FULL_REPORT_INVALID)
            continue
        covered.append(expected_id)
        if expected_id == _SCENARIO_WORKFLOW_RETIRED_ACTS:
            _validate_r4_snapshot_commands(value)
    return tuple(covered)


def _validate_provisional_cleanup_commands(report: JsonObject) -> None:
    """Require successful recorded public cleanup and the single supported stop, in their actual order."""
    cleanup = report["cleanup"]
    if not isinstance(cleanup, dict):
        raise ValueError(_FULL_REPORT_INVALID)
    commands = cleanup["commands"]
    _validate_report_commands(commands)
    if not isinstance(commands, list) or not commands:
        raise ValueError(_FULL_REPORT_INVALID)
    stop_argv = [
        *_SERVICE_STOP_COMMAND,
        f"{_STOP_OUTCOME_VARIABLE}={_SYNTHETIC_RUNTIME_PLACEHOLDER}/{_STOP_OUTCOME_NAME}",
    ]
    stops: list[int] = []
    for index, command in enumerate(commands):
        if (
            not isinstance(command, dict)
            or type(command["exit_status"]) is not int
            or command["exit_status"] != _PROCESS_SUCCESS
            or command["diagnostics"] != _EMPTY
        ):
            raise ValueError(_FULL_REPORT_INVALID)
        if command["argv"] == stop_argv:
            stops.append(index)
    if stops != [len(commands) - 1]:
        raise ValueError(_FULL_REPORT_INVALID)


def _validate_provisional_matrices(report: JsonObject, covered: tuple[str, ...]) -> None:
    """Reuse the reviewed matrices only for actual coverage; unselected data must remain explicitly unexecuted."""
    source_revision = report["source_revision"]
    source_tree = report["source_tree"]
    if not isinstance(source_revision, str) or not isinstance(source_tree, str):
        raise ValueError(_FULL_REPORT_INVALID)
    if _SCENARIO_WORKFLOW_RETIRED_ACTS_B12 in covered:
        _validate_b12_report(report, source_revision, source_tree)
    elif report[creation.B12Field.RETIRED_ACT_EVIDENCE] != asdict(
        creation.empty_retired_act_evidence(source_revision=source_revision, source_tree=source_tree)
    ):
        raise ValueError(_FULL_REPORT_INVALID)
    if _SCENARIO_WORKFLOW_WAITING in covered:
        _validate_b13_report(report, source_revision, source_tree)
    elif report["workflow_waiting_retired_kickback_evidence"] != asdict(
        waiting.empty_b13_evidence(source_revision=source_revision, source_tree=source_tree)
    ):
        raise ValueError(_FULL_REPORT_INVALID)


def validate_provisional_payload_inputs(report_bytes: bytes, manifest: bytes, package: StaticPackage) -> JsonObject:
    """Check functional coverage and P3 inputs only; P1/P2, actual P4, retention/release and final acceptance remain separate."""
    report = parse_object(report_bytes)
    structure = validate_provisional_bindings(report, manifest, package)
    if structure["purpose"] != Purpose.APPLICATION.value:
        raise ValueError(_FULL_REPORT_INVALID)
    expected_fields = {
        "schema_version",
        "source_revision",
        "source_tree",
        "profile",
        "scenario_inventory",
        "scenarios",
        "cleanup",
        "duration_seconds",
        "selection",
        "workflow_event_evidence",
        creation.B12Field.RETIRED_ACT_EVIDENCE,
        "workflow_waiting_retired_kickback_evidence",
        "stage",
        "payload_provisional",
    }
    duration = report.get("duration_seconds")
    if (
        set(report) != expected_fields
        or report["scenario_inventory"] != list(_FULL_PROFILE_SCENARIOS)
        or type(duration) not in (int, float)
        or not isinstance(duration, (int, float))
        or not math.isfinite(duration)
        or duration < 0
        or not isinstance(report["workflow_event_evidence"], dict)
    ):
        raise ValueError(_FULL_REPORT_INVALID)
    selection = report["selection"]
    if not isinstance(selection, list) or any(not isinstance(item, str) for item in selection):
        raise ValueError(_FULL_REPORT_INVALID)
    selected = frozenset(item for item in selection if isinstance(item, str))
    if selection != sorted(selected):
        raise ValueError(_FULL_REPORT_INVALID)
    covered = _validate_provisional_scenarios(report, selected)
    _validate_provisional_matrices(report, covered)
    cleanup = validate_provisional_cleanup(report)
    _validate_provisional_cleanup_commands(report)
    sessions = validate_flow_session_closure(report)
    starts = validate_flow_start_inputs(report)
    early = validate_early_inputs(report)
    return {
        "binding_and_ledger_structure": structure,
        "functional_coverage": list(covered),
        "selected_run": bool(selected),
        "inner_cleanup": cleanup,
        "shared_flow_sessions": sessions,
        "shared_flow_starts": starts,
        "early_workflow_inputs": early,
        "public_event_inputs": validate_event_inputs(report, sessions, starts, early),
    }


def _unadmitted_full_report(source_revision: str, source_tree: str, selection: frozenset[str]) -> AcceptanceReport:
    """Refuse before resource creation; absent enclosure admission supplies no journey or cleanup result."""
    return AcceptanceReport(
        schema_version=_REPORT_SCHEMA_VERSION,
        source_revision=source_revision,
        source_tree=source_tree,
        profile=Profile.FULL,
        scenario_inventory=_FULL_PROFILE_SCENARIOS,
        scenarios=tuple(
            ScenarioResult(scenario_id, ScenarioStatus.NOT_RUN, 0.0, diagnostics=_ENCLOSURE_REQUIRED)
            for scenario_id in _FULL_PROFILE_SCENARIOS
        ),
        cleanup=CleanupResult(ScenarioStatus.NOT_RUN, _ENCLOSURE_REQUIRED),
        duration_seconds=0.0,
        selection=tuple(sorted(selection)),
    )


def _parse_arguments(arguments: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=_CLI_DESCRIPTION)
    parser.add_argument(_PROFILE_OPTION, choices=[profile.value for profile in Profile])
    parser.add_argument(_ROOT_OPTION, type=Path, default=Path(_DEFAULT_ROOT))
    parser.add_argument(_SOURCE_REVISION_OPTION)
    parser.add_argument(_SOURCE_TREE_OPTION)
    parser.add_argument(_ENCLOSURE_ROLE_OPTION, choices=[role.value for role in Role])
    parser.add_argument(_ENCLOSURE_MANIFEST_OPTION, type=Path)
    parser.add_argument(_ENCLOSURE_ACTION_OPTION, choices=[action.value for action in Action])
    parser.add_argument(_OBSERVATION_KEY_OPTION)
    default_report = Path(tempfile.gettempdir()) / _REPORT_NAME_TEMPLATE.format(identifier=uuid.uuid4().hex)
    parser.add_argument(_REPORT_OPTION, type=Path, default=default_report)
    parser.add_argument(_SELECT_OPTION, default=_EMPTY, help=_SELECT_HELP)
    parsed = parser.parse_args(arguments)
    if parsed.enclosure_role is not None and parsed.enclosure_manifest is None:
        parser.error(_ENCLOSURE_MANIFEST_REQUIRED)
    if parsed.enclosure_action is not None and parsed.enclosure_role != Role.PRIVILEGED:
        parser.error(_ENCLOSURE_ACTION_ROLE)
    if parsed.enclosure_role in (None, Role.PAYLOAD, Role.SUPERVISOR) and not (
        parsed.profile and parsed.source_revision and parsed.source_tree
    ):
        parser.error(_PROFILE_ARGUMENTS_REQUIRED)
    if parsed.enclosure_role in (Role.PAYLOAD, Role.SUPERVISOR) and parsed.profile != Profile.FULL:
        parser.error(_ENCLOSED_FULL_REQUIRED)
    return parsed


def _selection_with_prerequisites(requested: str, profile: Profile) -> frozenset[str]:
    """The scenarios a selected run executes: those asked for and everything they need first."""
    asked = [part.strip() for part in requested.split(_SELECTION_SEPARATOR) if part.strip()]
    if not asked:
        return frozenset()
    inventory = _FULL_PROFILE_SCENARIOS if profile is Profile.FULL else _COLD_PROFILE_SCENARIOS
    selected: set[str] = set()
    for scenario_id in asked:
        if scenario_id not in inventory:
            raise SystemExit(_SELECTION_UNKNOWN.format(scenario_id=scenario_id))
        pending = [scenario_id]
        while pending:
            current = pending.pop()
            if current in selected:
                continue
            selected.add(current)
            pending.extend(_SCENARIO_PREREQUISITES.get(current, ()))
    return frozenset(selected)


def _handle_profile_termination(_signum: int, _frame: FrameType | None) -> None:
    """Turn runner cancellation into the profile's cleanup path before exit."""
    raise KeyboardInterrupt(_INTERRUPTED)


def main(arguments: list[str] | None = None) -> int:
    """Run the requested profile and write a structured result for the checked source."""
    parsed = _parse_arguments(sys.argv[1:] if arguments is None else arguments)
    role = Role(parsed.enclosure_role) if parsed.enclosure_role is not None else None
    if role is Role.PRIVILEGED:
        if parsed.enclosure_action is None:
            print(_ENCLOSURE_ACTION_REQUIRED, file=sys.stderr)
            return _PROCESS_FAILURE
        try:
            result = run_helper(parsed.enclosure_manifest, Action(parsed.enclosure_action))
        except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
            print(_ENCLOSURE_ENTRY_FAILED.format(error_class=type(error).__name__, detail=error), file=sys.stderr)
            return _PROCESS_FAILURE
        return _PROCESS_SUCCESS if result.status is EnclosureOutcome.SUCCEEDED else _PROCESS_FAILURE
    if role is Role.GUEST_POWEROFF:
        try:
            outcome = request_guest_poweroff(GuestContext.load(parsed.enclosure_manifest))
        except (OSError, ValueError, RuntimeError) as error:
            print(_ENCLOSURE_ENTRY_FAILED.format(error_class=type(error).__name__, detail=error), file=sys.stderr)
            return _PROCESS_FAILURE
        return _PROCESS_SUCCESS if outcome is GuestShutdownRecord.ACKNOWLEDGED else _PROCESS_FAILURE
    if role is Role.GUEST_SETUP:
        try:
            facts = run_guest_setup(GuestContext.load(parsed.enclosure_manifest, Role.GUEST_SETUP))
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            print(_ENCLOSURE_ENTRY_FAILED.format(error_class=type(error).__name__, detail=error), file=sys.stderr)
            return _PROCESS_FAILURE
        print(json.dumps(asdict(facts), sort_keys=True))
        return _PROCESS_SUCCESS
    if role is not None and role is not Role.PAYLOAD:
        print(_ENCLOSURE_UNAVAILABLE.format(role=role), file=sys.stderr)
        return _PROCESS_FAILURE
    admission = GuestContext.load_payload(parsed.enclosure_manifest) if role is Role.PAYLOAD else None
    selected_profile = Profile(parsed.profile)
    previous_termination_handler = signal.signal(signal.SIGTERM, _handle_profile_termination)
    try:
        selection = _selection_with_prerequisites(parsed.select, selected_profile)
        report = run_profile(
            selected_profile,
            source_root=parsed.root,
            source_revision=parsed.source_revision,
            source_tree=parsed.source_tree,
            selection=selection,
            report_path=parsed.report,
            payload_admission=admission,
        )
        report = write_report(report, parsed.report)
        if report.selection:
            if report.selection_passed:
                print(_PARTIAL_PASSED, file=sys.stderr)
                return _EXIT_PARTIAL
            return _PROCESS_FAILURE
        return 0 if report.passed else 1
    finally:
        signal.signal(signal.SIGTERM, previous_termination_handler)


if __name__ == "__main__":
    raise SystemExit(main())
