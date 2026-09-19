/**
 * Closed message set for the Python supervisor <-> Node sidecar bridge.
 *
 * Every message carries `v: 1` and `generation` (stale-generation rejection
 * lives in the supervisor). Mirrored one-to-one in
 * `teleclaude/adapters/discord/voice_bridge_messages.py` — a change here is
 * not complete until that mirror is updated too.
 */

export type UtteranceDiscardReason = 'no_stop_sequence' | 'continuity_unproven';
export type SpeakerIgnoredReason = 'not_configured_user';

export interface VoiceStateUpdateMessage {
  v: 1;
  type: 'voice_state_update';
  generation: number;
  payload: Record<string, unknown>;
}

export interface VoiceServerUpdateMessage {
  v: 1;
  type: 'voice_server_update';
  generation: number;
  payload: Record<string, unknown>;
}

export interface JoinMessage {
  v: 1;
  type: 'join';
  generation: number;
  guildId: string;
  channelId: string;
}

export interface LeaveMessage {
  v: 1;
  type: 'leave';
  generation: number;
}

export interface PlayArtifactMessage {
  v: 1;
  type: 'play_artifact';
  generation: number;
  path: string;
}

export interface CancelPlaybackMessage {
  v: 1;
  type: 'cancel_playback';
  generation: number;
}

/** Messages the supervisor sends to the sidecar. */
export type InboundMessage =
  | VoiceStateUpdateMessage
  | VoiceServerUpdateMessage
  | JoinMessage
  | LeaveMessage
  | PlayArtifactMessage
  | CancelPlaybackMessage;

export interface ReadyMessage {
  v: 1;
  type: 'ready';
  generation: number;
}

export interface VoiceStateRequestMessage {
  v: 1;
  type: 'voice_state_request';
  generation: number;
  payload: Record<string, unknown>;
}

export interface UtteranceOpenedMessage {
  v: 1;
  type: 'utterance_opened';
  generation: number;
  utteranceId: string;
}

export interface UtteranceClosedMessage {
  v: 1;
  type: 'utterance_closed';
  generation: number;
  utteranceId: string;
  frames: number;
  audioPath: string;
}

export interface UtteranceDiscardedMessage {
  v: 1;
  type: 'utterance_discarded';
  generation: number;
  utteranceId: string;
  reason: UtteranceDiscardReason;
}

export interface SpeakerIgnoredMessage {
  v: 1;
  type: 'speaker_ignored';
  generation: number;
  reason: SpeakerIgnoredReason;
}

export interface PlaybackFinishedMessage {
  v: 1;
  type: 'playback_finished';
  generation: number;
}

export interface ProtocolErrorMessage {
  v: 1;
  type: 'protocol_error';
  generation: number;
  message: string;
}

/** Messages the sidecar sends to the supervisor. */
export type OutboundMessage =
  | ReadyMessage
  | VoiceStateRequestMessage
  | UtteranceOpenedMessage
  | UtteranceClosedMessage
  | UtteranceDiscardedMessage
  | SpeakerIgnoredMessage
  | PlaybackFinishedMessage
  | ProtocolErrorMessage;

const INBOUND_TYPES: ReadonlySet<string> = new Set([
  'voice_state_update',
  'voice_server_update',
  'join',
  'leave',
  'play_artifact',
  'cancel_playback',
]);

/** Structural validation only — never trusts field types beyond presence + typeof. */
export function parseInboundMessage(raw: unknown): InboundMessage | null {
  if (typeof raw !== 'object' || raw === null) {
    return null;
  }
  const candidate = raw as Record<string, unknown>;
  if (candidate.v !== 1) {
    return null;
  }
  if (typeof candidate.type !== 'string' || !INBOUND_TYPES.has(candidate.type)) {
    return null;
  }
  if (typeof candidate.generation !== 'number') {
    return null;
  }

  switch (candidate.type) {
    case 'voice_state_update':
    case 'voice_server_update':
      if (typeof candidate.payload !== 'object' || candidate.payload === null) {
        return null;
      }
      break;
    case 'join':
      if (typeof candidate.guildId !== 'string' || typeof candidate.channelId !== 'string') {
        return null;
      }
      break;
    case 'play_artifact':
      if (typeof candidate.path !== 'string') {
        return null;
      }
      break;
    case 'leave':
    case 'cancel_playback':
      break;
    default:
      return null;
  }

  return candidate as unknown as InboundMessage;
}
