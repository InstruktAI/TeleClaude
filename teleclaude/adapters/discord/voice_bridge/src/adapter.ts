/**
 * Discord gateway adapter bridging @discordjs/voice to the parent's own
 * Gateway connection. Python remains sole Gateway owner: this adapter never
 * opens a socket of its own — it forwards the payload the library wants sent
 * on the main gateway to the parent process, and applies
 * VOICE_STATE_UPDATE/VOICE_SERVER_UPDATE payloads the parent forwards back.
 */

import type {
  DiscordGatewayAdapterCreator,
  DiscordGatewayAdapterImplementerMethods,
  DiscordGatewayAdapterLibraryMethods,
} from '@discordjs/voice';
import type { GatewayVoiceServerUpdateDispatchData, GatewayVoiceStateUpdateDispatchData } from 'discord-api-types/v10';

export type SendToParent = (payload: Record<string, unknown>) => void;

/**
 * Build one adapter creator bound to a single guild's voice connection.
 * `sendVoiceStateRequest` forwards the payload @discordjs/voice wants sent
 * on the main gateway; the returned `apply*` functions feed inbound
 * VOICE_STATE_UPDATE/VOICE_SERVER_UPDATE payloads back into the library.
 */
export function createBridgedAdapter(sendVoiceStateRequest: SendToParent): {
  creator: DiscordGatewayAdapterCreator;
  applyVoiceStateUpdate: (data: Record<string, unknown>) => void;
  applyVoiceServerUpdate: (data: Record<string, unknown>) => void;
  destroy: () => void;
} {
  let libraryMethods: DiscordGatewayAdapterLibraryMethods | undefined;

  const creator: DiscordGatewayAdapterCreator = (methods) => {
    libraryMethods = methods;
    const implementerMethods: DiscordGatewayAdapterImplementerMethods = {
      sendPayload(payload: unknown): boolean {
        sendVoiceStateRequest(payload as Record<string, unknown>);
        return true;
      },
      destroy(): void {
        libraryMethods = undefined;
      },
    };
    return implementerMethods;
  };

  return {
    creator,
    applyVoiceStateUpdate(data) {
      libraryMethods?.onVoiceStateUpdate(data as unknown as GatewayVoiceStateUpdateDispatchData);
    },
    applyVoiceServerUpdate(data) {
      libraryMethods?.onVoiceServerUpdate(data as unknown as GatewayVoiceServerUpdateDispatchData);
    },
    destroy() {
      libraryMethods?.destroy();
      libraryMethods = undefined;
    },
  };
}
