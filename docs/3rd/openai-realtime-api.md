# OpenAI Realtime API Events

Source: https://platform.openai.com/docs/api-reference/realtime-server-events
Last Updated: 2026-01-15

## Overview
The OpenAI Realtime API is a WebSocket-based API that allows for full-duplex, low-latency communication. It uses JSON-formatted events for both client-to-server and server-to-client communication.

## Key Server Events
- **session.created**: Sent when a new session is established.
- **session.updated**: Sent when session configuration is updated.
- **conversation.item.created**: Sent when a new item (message, function call) is added.
- **response.created**: Sent when a new response starts.
- **response.audio.delta**: Streamed audio data from the model.
- **response.audio_transcript.delta**: Streamed transcript of the audio.
- **response.done**: Sent when a response is completed.
- **error**: Sent when an error occurs.

## Key Client Events
- **session.update**: Update session configuration (modalities, instructions, tools).
- **input_audio_buffer.append**: Send audio data to the server.
- **input_audio_buffer.commit**: Finish the current audio input.
- **response.create**: Manually trigger a model response.
- **response.cancel**: Interrupt an ongoing response.

## Modalities
Supported modalities include `text` and `audio`.
