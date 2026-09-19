/**
 * Local-artifact playback into a voice connection.
 *
 * FFmpeg is the only decoder — no JS decoder covers MP3/AIFF/WAV, so the
 * process boundary is justified: it decodes the artifact to raw PCM, which
 * opusscript then encodes frame-by-frame into the Opus stream
 * `createAudioResource` plays. One player, one queue; a new artifact or a
 * cancel always stops whatever is currently playing first.
 */

import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { Readable } from 'node:stream';
import {
  AudioPlayerStatus,
  StreamType,
  createAudioPlayer,
  createAudioResource,
  type AudioPlayer,
  type VoiceConnection,
} from '@discordjs/voice';
import OpusScript = require('opusscript');

const SAMPLE_RATE = 48000;
const CHANNELS = 2;
const BYTES_PER_SAMPLE = 2;
const FRAME_SAMPLES = 960; // 20ms @ 48kHz
const FRAME_BYTES = FRAME_SAMPLES * CHANNELS * BYTES_PER_SAMPLE;

class OpusEncodingStream extends Readable {
  private readonly encoder: InstanceType<typeof OpusScript>;
  private readonly ffmpeg: ChildProcessWithoutNullStreams;
  private residual: Buffer = Buffer.alloc(0);

  constructor(path: string) {
    super({ objectMode: true });
    this.encoder = new OpusScript(SAMPLE_RATE, CHANNELS, OpusScript.Application.AUDIO);
    this.ffmpeg = spawn('ffmpeg', [
      '-i',
      path,
      '-f',
      's16le',
      '-ar',
      String(SAMPLE_RATE),
      '-ac',
      String(CHANNELS),
      'pipe:1',
    ]);
    this.ffmpeg.stdout.on('data', (chunk: Buffer) => this.handleChunk(chunk));
    this.ffmpeg.once('close', () => this.flushTail());
    this.ffmpeg.once('error', (error) => this.destroy(error));
  }

  private handleChunk(chunk: Buffer): void {
    this.residual = Buffer.concat([this.residual, chunk]);
    while (this.residual.length >= FRAME_BYTES) {
      const frame = this.residual.subarray(0, FRAME_BYTES);
      this.residual = this.residual.subarray(FRAME_BYTES);
      this.push(this.encoder.encode(frame, FRAME_SAMPLES));
    }
  }

  private flushTail(): void {
    if (this.residual.length > 0) {
      const padded = Buffer.alloc(FRAME_BYTES);
      this.residual.copy(padded);
      this.push(this.encoder.encode(padded, FRAME_SAMPLES));
      this.residual = Buffer.alloc(0);
    }
    this.push(null);
  }

  override _read(): void {
    // Backpressure is driven by ffmpeg's own stdout pace; nothing to pull on demand.
  }

  override _destroy(error: Error | null, callback: (error?: Error | null) => void): void {
    this.ffmpeg.kill();
    this.encoder.delete();
    callback(error);
  }
}

export class PlaybackQueue {
  private readonly connection: VoiceConnection;
  private readonly player: AudioPlayer;

  constructor(connection: VoiceConnection) {
    this.connection = connection;
    this.player = createAudioPlayer();
    this.connection.subscribe(this.player);
  }

  playArtifact(path: string): void {
    this.cancel();
    const opusStream = new OpusEncodingStream(path);
    const resource = createAudioResource(opusStream, { inputType: StreamType.Opus });
    this.player.play(resource);
  }

  cancel(): void {
    if (this.player.state.status !== AudioPlayerStatus.Idle) {
      this.player.stop(true);
    }
  }

  onIdle(callback: () => void): void {
    this.player.on(AudioPlayerStatus.Idle, callback);
  }

  destroy(): void {
    this.cancel();
    this.player.removeAllListeners();
  }
}
