/**
 * Sidecar entry point. Reads the bridge stream from the fd named by `--fd N`
 * (inherited from the Python supervisor's socketpair — the private channel
 * that is what makes this bridge safe), speaks JSON-lines over it, and never
 * opens a listening socket of its own.
 */

import { Socket } from 'node:net';
import { createInterface } from 'node:readline';
import { entersState, joinVoiceChannel, VoiceConnectionStatus, type VoiceConnection } from '@discordjs/voice';
import { createBridgedAdapter } from './adapter.js';
import { parseInboundMessage, type InboundMessage, type OutboundMessage } from './protocol.js';
import { UtteranceCapture } from './receive.js';
import { PlaybackQueue } from './playback.js';

const READY_TIMEOUT_MS = 20_000;

function parseFdArg(argv: readonly string[]): number {
  const flagIndex = argv.indexOf('--fd');
  if (flagIndex === -1 || flagIndex + 1 >= argv.length) {
    process.stderr.write('missing --fd argument\n');
    process.exit(1);
  }
  const fd = Number(argv[flagIndex + 1]);
  if (!Number.isInteger(fd) || fd < 0) {
    process.stderr.write('invalid --fd argument\n');
    process.exit(1);
  }
  return fd;
}

class Bridge {
  private readonly socket: Socket;
  private connection: VoiceConnection | null = null;
  private playback: PlaybackQueue | null = null;
  private currentGeneration = 0;

  constructor(fd: number) {
    this.socket = new Socket({ fd });
    const lines = createInterface({ input: this.socket });
    lines.on('line', (line) => this.handleLine(line));
    this.socket.once('close', () => process.exit(0));
  }

  send(message: OutboundMessage): void {
    this.socket.write(`${JSON.stringify(message)}\n`);
  }

  announceReady(): void {
    this.send({ v: 1, type: 'ready', generation: this.currentGeneration });
  }

  private handleLine(line: string): void {
    const trimmed = line.trim();
    if (!trimmed) {
      return;
    }
    let raw: unknown;
    try {
      raw = JSON.parse(trimmed);
    } catch {
      this.protocolError(`invalid JSON: ${trimmed.slice(0, 200)}`);
      return;
    }
    const message = parseInboundMessage(raw);
    if (!message) {
      this.protocolError(`unrecognized message: ${trimmed.slice(0, 200)}`);
      return;
    }
    this.currentGeneration = message.generation;
    this.handleMessage(message);
  }

  private protocolError(detail: string): void {
    this.send({ v: 1, type: 'protocol_error', generation: this.currentGeneration, message: detail });
    process.exit(1);
  }

  private handleMessage(message: InboundMessage): void {
    switch (message.type) {
      case 'join':
        this.handleJoin(message.guildId, message.channelId);
        break;
      case 'leave':
        this.handleLeave();
        break;
      case 'voice_state_update':
        this.adapterBridge?.applyVoiceStateUpdate(message.payload);
        break;
      case 'voice_server_update':
        this.adapterBridge?.applyVoiceServerUpdate(message.payload);
        break;
      case 'play_artifact':
        this.playback?.playArtifact(message.path);
        break;
      case 'cancel_playback':
        this.playback?.cancel();
        break;
    }
  }

  private adapterBridge: ReturnType<typeof createBridgedAdapter> | undefined;

  private handleJoin(guildId: string, channelId: string): void {
    this.adapterBridge = createBridgedAdapter((payload) => {
      this.send({ v: 1, type: 'voice_state_request', generation: this.currentGeneration, payload });
    });

    this.connection = joinVoiceChannel({
      guildId,
      channelId,
      adapterCreator: this.adapterBridge.creator,
      selfDeaf: false,
    });

    entersState(this.connection, VoiceConnectionStatus.Ready, READY_TIMEOUT_MS)
      .then(() => {
        if (!this.connection) {
          return;
        }
        new UtteranceCapture(
          this.connection,
          process.env.TELECLAUDE_CONFIGURED_USER_ID ?? '',
          process.env.TELECLAUDE_VOICE_RECORDING_DIR ?? '.',
          {
          onOpened: (utteranceId) =>
            this.send({ v: 1, type: 'utterance_opened', generation: this.currentGeneration, utteranceId }),
          onClosed: (result) =>
            this.send({
              v: 1,
              type: 'utterance_closed',
              generation: this.currentGeneration,
              utteranceId: result.utteranceId,
              frames: result.frames,
              audioPath: result.audioPath,
            }),
          onDiscarded: (discard) =>
            this.send({
              v: 1,
              type: 'utterance_discarded',
              generation: this.currentGeneration,
              utteranceId: discard.utteranceId,
              reason: discard.reason,
            }),
          onSpeakerIgnored: () =>
            this.send({
              v: 1,
              type: 'speaker_ignored',
              generation: this.currentGeneration,
              reason: 'not_configured_user',
            }),
          },
        );
        this.playback = new PlaybackQueue(this.connection);
        this.playback.onIdle(() => this.send({ v: 1, type: 'playback_finished', generation: this.currentGeneration }));
      })
      .catch(() => {
        this.send({
          v: 1,
          type: 'protocol_error',
          generation: this.currentGeneration,
          message: 'voice_ready_failed',
        });
        this.handleLeave();
      });
  }

  private handleLeave(): void {
    this.playback?.destroy();
    this.playback = null;
    this.connection?.destroy();
    this.connection = null;
    this.adapterBridge?.destroy();
    this.adapterBridge = undefined;
  }
}

function main(): void {
  const fd = parseFdArg(process.argv.slice(2));
  const bridge = new Bridge(fd);
  bridge.announceReady();
}

main();
