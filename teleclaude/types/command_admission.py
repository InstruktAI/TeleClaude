"""Admission class of every internal command: whether accepting it begins business work."""

from enum import StrEnum

from teleclaude.types.commands import CommandType


class AdmissionClass(StrEnum):
    """What a command does to the daemon when it is accepted."""

    BUSINESS_WORK = "business_work"
    OBSERVATION = "observation"


COMMAND_ADMISSION: dict[CommandType, AdmissionClass] = {
    CommandType.CREATE_SESSION: AdmissionClass.BUSINESS_WORK,
    CommandType.HANDLE_VOICE: AdmissionClass.BUSINESS_WORK,
    CommandType.HANDLE_FILE: AdmissionClass.BUSINESS_WORK,
    CommandType.KEYS: AdmissionClass.BUSINESS_WORK,
    CommandType.START_AGENT: AdmissionClass.BUSINESS_WORK,
    CommandType.RESUME_AGENT: AdmissionClass.BUSINESS_WORK,
    CommandType.PROCESS_MESSAGE: AdmissionClass.BUSINESS_WORK,
    CommandType.RUN_AGENT_COMMAND: AdmissionClass.BUSINESS_WORK,
    CommandType.RESTART_AGENT: AdmissionClass.BUSINESS_WORK,
    CommandType.HANDOFF_AGENT: AdmissionClass.BUSINESS_WORK,
    CommandType.REVIVE_AGENT: AdmissionClass.BUSINESS_WORK,
    CommandType.UNSUBSCRIBE_SESSION: AdmissionClass.BUSINESS_WORK,
    CommandType.GET_SESSION_DATA: AdmissionClass.OBSERVATION,
    CommandType.CLOSE_SESSION: AdmissionClass.BUSINESS_WORK,
    CommandType.SYSTEM: AdmissionClass.BUSINESS_WORK,
    CommandType.SET_VOICE_FOCUS: AdmissionClass.BUSINESS_WORK,
    CommandType.DISCORD_THREAD_CLAIM: AdmissionClass.BUSINESS_WORK,
    CommandType.ACTIVATE_PROCEDURE: AdmissionClass.BUSINESS_WORK,
}
