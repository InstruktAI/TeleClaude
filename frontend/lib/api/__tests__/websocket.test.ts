import { describe, expect, it } from 'vitest';

import { WebSocketManager } from '../websocket';
import type { TodoRenamedEvent } from '../types';

const TODO_RENAMED_EVENT_TYPE = 'todo_renamed';
const OLD_SLUG = 'rename-source';
const NEW_SLUG = 'rename-target';
const COMPUTER = 'local';
const PROJECT_PATH = '/workspace/project';

interface MessageReceiver {
  handleMessage(data: string): void;
}

function receiveMessage(manager: WebSocketManager, event: TodoRenamedEvent): void {
  (manager as unknown as MessageReceiver).handleMessage(JSON.stringify(event));
}

describe('WebSocketManager', () => {
  it('dispatches todo rename frames through the typed event path', () => {
    const manager = new WebSocketManager({ initialSubscriptions: [] });
    const received: TodoRenamedEvent[] = [];
    const event = {
      event: TODO_RENAMED_EVENT_TYPE,
      data: {
        old_slug: OLD_SLUG,
        new_slug: NEW_SLUG,
        computer: COMPUTER,
        project_path: PROJECT_PATH,
      },
    } satisfies TodoRenamedEvent;

    manager.onEvent<TodoRenamedEvent>(TODO_RENAMED_EVENT_TYPE, (renamedEvent) => {
      received.push(renamedEvent);
    });

    receiveMessage(manager, event);

    expect(received).toEqual([event]);
  });
});
