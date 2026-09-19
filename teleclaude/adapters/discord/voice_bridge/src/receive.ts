/**
 * Per-SSRC Opus capture, filtered to the configured user, with a
 * continuity-gated stop-sequence close.
 *
 * The stop-sequence rule (three consecutive `F8 FF FE` Opus payloads) closes
 * an utterance only when that run is sequence-contiguous with the audio
 * before it — a gap or reorder touching the boundary, an unmatched frame, or
 * a run that never completes discards the utterance instead of trusting a
 * possibly-torn recording. Header/payload pairing uses the raw RTP header
 * (sequence, timestamp, SSRC) read from the UDP socket's `message` event —
 * the encrypted datagram, before `@discordjs/voice` decrypts it — paired by
 * SSRC and arrival order with the decrypted Opus payload the library then
 * emits on the matching `AudioReceiveStream`.
 */

import { randomUUID } from 'node:crypto';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import type { Readable } from 'node:stream';
import { EndBehaviorType, type VoiceConnection, type VoiceUDPSocket } from '@discordjs/voice';
import OpusScript = require('opusscript');
import type { UtteranceDiscardReason } from './protocol.js';

const SAMPLE_RATE = 48000;
const CHANNELS = 2;
const STOP_MARKER = Buffer.from([0xf8, 0xff, 0xfe]);
const RTP_HEADER_MIN_BYTES = 12;

interface RtpHeader {
  sequence: number;
  timestamp: number;
  ssrc: number;
}

function parseRtpHeader(datagram: Buffer): RtpHeader | null {
  if (datagram.length < RTP_HEADER_MIN_BYTES) {
    return null;
  }
  return {
    sequence: datagram.readUInt16BE(2),
    timestamp: datagram.readUInt32BE(4),
    ssrc: datagram.readUInt32BE(8),
  };
}

function writeWavFile(path: string, pcm: Buffer): void {
  const header = Buffer.alloc(44);
  const byteRate = SAMPLE_RATE * CHANNELS * 2;
  const blockAlign = CHANNELS * 2;
  header.write('RIFF', 0, 'ascii');
  header.writeUInt32LE(36 + pcm.length, 4);
  header.write('WAVE', 8, 'ascii');
  header.write('fmt ', 12, 'ascii');
  header.writeUInt32LE(16, 16);
  header.writeUInt16LE(1, 20); // PCM
  header.writeUInt16LE(CHANNELS, 22);
  header.writeUInt32LE(SAMPLE_RATE, 24);
  header.writeUInt32LE(byteRate, 28);
  header.writeUInt16LE(blockAlign, 32);
  header.writeUInt16LE(16, 34);
  header.write('data', 36, 'ascii');
  header.writeUInt32LE(pcm.length, 40);
  writeFileSync(path, Buffer.concat([header, pcm]));
}

export interface UtteranceResult {
  utteranceId: string;
  frames: number;
  audioPath: string;
}

export interface UtteranceDiscard {
  utteranceId: string;
  reason: UtteranceDiscardReason;
}

export interface CaptureCallbacks {
  onOpened: (utteranceId: string) => void;
  onClosed: (result: UtteranceResult) => void;
  onDiscarded: (discard: UtteranceDiscard) => void;
  onSpeakerIgnored: () => void;
}

/**
 * Attaches capture to a voice connection, filtered to `configuredSsrc`.
 * Any other speaking SSRC is never subscribed — `onSpeakerIgnored` fires
 * once per ignored transmission start instead.
 */
export class UtteranceCapture {
  private readonly connection: VoiceConnection;
  private readonly configuredUserId: string;
  private readonly recordingDir: string;
  private readonly callbacks: CaptureCallbacks;
  private readonly decoder: InstanceType<typeof OpusScript>;

  private attachedUdp: VoiceUDPSocket | undefined;
  private readonly pendingHeadersBySsrc = new Map<number, RtpHeader[]>();

  private active: {
    utteranceId: string;
    ssrc: number;
    frames: Buffer[];
    frameCount: number;
    expectedSequence: number | null;
    continuityBroken: boolean;
    stream: Readable;
  } | null = null;

  constructor(
    connection: VoiceConnection,
    configuredUserId: string,
    recordingDir: string,
    callbacks: CaptureCallbacks,
  ) {
    this.connection = connection;
    this.configuredUserId = configuredUserId;
    this.recordingDir = recordingDir;
    this.callbacks = callbacks;
    this.decoder = new OpusScript(SAMPLE_RATE, CHANNELS, OpusScript.Application.VOIP);
    mkdirSync(recordingDir, { recursive: true });

    this.connection.receiver.speaking.on('start', (userId) => this.handleSpeakingStart(userId));
    this.attachUdpListener();
    this.connection.on('stateChange', () => this.attachUdpListener());
  }

  private attachUdpListener(): void {
    const state = this.connection.state as { networking?: { state: { udp?: VoiceUDPSocket } } };
    const udp = state.networking?.state.udp;
    if (!udp || udp === this.attachedUdp) {
      return;
    }
    this.attachedUdp = udp;
    udp.on('message', (datagram: Buffer) => this.handleRawDatagram(datagram));
  }

  private handleRawDatagram(datagram: Buffer): void {
    const header = parseRtpHeader(datagram);
    if (!header) {
      return;
    }
    const queue = this.pendingHeadersBySsrc.get(header.ssrc) ?? [];
    queue.push(header);
    this.pendingHeadersBySsrc.set(header.ssrc, queue);
  }

  private handleSpeakingStart(userId: string): void {
    if (userId !== this.configuredUserId) {
      this.callbacks.onSpeakerIgnored();
      return;
    }
    if (this.active) {
      return; // Already capturing this user's utterance.
    }
    const userData = this.connection.receiver.ssrcMap.get(userId);
    if (!userData) {
      return;
    }
    const utteranceId = randomUUID();
    const receiveStream = this.connection.receiver.subscribe(userId, { end: { behavior: EndBehaviorType.Manual } });
    this.active = {
      utteranceId,
      ssrc: userData.audioSSRC,
      frames: [],
      frameCount: 0,
      expectedSequence: null,
      continuityBroken: false,
      stream: receiveStream,
    };
    this.callbacks.onOpened(utteranceId);

    receiveStream.on('data', (payload: Buffer) => this.handleOpusPayload(payload));
    receiveStream.once('close', () => this.finalizeIfStillOpen('no_stop_sequence'));
    receiveStream.once('error', () => this.finalizeIfStillOpen('continuity_unproven'));
  }

  private handleOpusPayload(payload: Buffer): void {
    const active = this.active;
    if (!active) {
      return;
    }
    const queue = this.pendingHeadersBySsrc.get(active.ssrc);
    const header = queue?.shift();
    if (!header) {
      active.continuityBroken = true;
    } else if (active.expectedSequence !== null && header.sequence !== active.expectedSequence) {
      active.continuityBroken = true;
    }
    if (header) {
      active.expectedSequence = (header.sequence + 1) & 0xffff;
    }

    const isStopMarkerFrame = payload.length === STOP_MARKER.length && payload.equals(STOP_MARKER);
    if (isStopMarkerFrame) {
      this.closeUtterance();
      return;
    }

    try {
      const pcm = this.decoder.decode(payload);
      active.frames.push(pcm);
      active.frameCount += 1;
    } catch {
      active.continuityBroken = true;
    }
  }

  private closeUtterance(): void {
    const active = this.active;
    if (!active) {
      return;
    }
    this.active = null;
    active.stream.destroy();
    if (active.continuityBroken) {
      this.callbacks.onDiscarded({ utteranceId: active.utteranceId, reason: 'continuity_unproven' });
      return;
    }
    const audioPath = join(this.recordingDir, `${active.utteranceId}.wav`);
    writeWavFile(audioPath, Buffer.concat(active.frames));
    this.callbacks.onClosed({ utteranceId: active.utteranceId, frames: active.frameCount, audioPath });
  }

  private finalizeIfStillOpen(reason: UtteranceDiscardReason): void {
    const active = this.active;
    if (!active) {
      return;
    }
    this.active = null;
    active.stream.destroy();
    this.callbacks.onDiscarded({ utteranceId: active.utteranceId, reason });
  }
}
