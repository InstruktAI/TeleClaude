// Unit tests for the CC-faithful payload helpers (fork v2).
// Run: node --test test/*.test.mjs

import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  foldPermissionMode,
  lastAssistantMessageText,
  resolveTranscriptPath,
  hookInputBase,
} from '../index.mjs'

test('foldPermissionMode: default when no knob events', () => {
  assert.equal(foldPermissionMode([]), 'default')
  assert.equal(foldPermissionMode(undefined), 'default')
})

test('foldPermissionMode: plan mode wins over everything', () => {
  const events = [
    { type: 'plan/mode', data: { active: true } },
    { type: 'sandbox/mode', data: { mode: 'danger-full-access' } },
    { type: 'approval/policy', data: { policy: 'never' } },
  ]
  assert.equal(foldPermissionMode(events), 'plan')
  // last plan/mode wins
  assert.equal(foldPermissionMode([...events, { type: 'plan/mode', data: { active: false } }]), 'bypassPermissions')
})

test('foldPermissionMode: bypassPermissions for danger-full-access', () => {
  assert.equal(
    foldPermissionMode([{ type: 'sandbox/mode', data: { mode: 'danger-full-access' } }]),
    'bypassPermissions',
  )
  assert.equal(
    foldPermissionMode([{ type: 'sandbox/mode', data: { mode: 'workspace-write' } }]),
    'default',
  )
})

test('foldPermissionMode: acceptEdits when approval never', () => {
  assert.equal(
    foldPermissionMode([{ type: 'approval/policy', data: { policy: 'never' } }]),
    'acceptEdits',
  )
  assert.equal(
    foldPermissionMode([{ type: 'approval/policy', data: { policy: 'ask' } }]),
    'default',
  )
})

test('lastAssistantMessageText: last assistant/message text blocks', () => {
  const events = [
    { type: 'user/message', data: { message: { content: [{ type: 'text', text: 'hi' }] } } },
    { type: 'assistant/message', data: { message: { content: [{ type: 'text', text: 'hello' }, { type: 'tool-call' }] } } },
    { type: 'assistant/message', data: { message: { content: [{ type: 'tool-call', id: 'x' }] } } }, // no text — skipped
    { type: 'assistant/message', data: { message: { content: [{ type: 'text', text: 'final' }] } } },
  ]
  assert.equal(lastAssistantMessageText(events), 'final')
})

test('lastAssistantMessageText: empty content or no assistant message', () => {
  assert.equal(lastAssistantMessageText([{ type: 'user/message', data: {} }]), undefined)
  assert.equal(lastAssistantMessageText([]), undefined)
  assert.equal(lastAssistantMessageText(undefined), undefined)
})

test('resolveTranscriptPath: uses persistence.locate(session.header).path', () => {
  const persistence = {
    locate(meta) {
      assert.equal(meta.id, 'sess-1')
      assert.equal(meta.cwd, '/tmp/proj')
      return { kind: 'jsonl', path: '/tmp/proj/.dsh/storage/sess-1/session.jsonl.zstd' }
    },
  }
  const session = { header: { id: 'sess-1', cwd: '/tmp/proj' } }
  assert.equal(resolveTranscriptPath(persistence, session), '/tmp/proj/.dsh/storage/sess-1/session.jsonl.zstd')
})

test('resolveTranscriptPath: undefined when no locate or no session', () => {
  assert.equal(resolveTranscriptPath(undefined, { header: { id: 'x', cwd: '/t' } }), undefined)
  assert.equal(resolveTranscriptPath({ locate: 'not-a-function' }, { header: { id: 'x', cwd: '/t' } }), undefined)
  assert.equal(resolveTranscriptPath({ locate: () => ({}) }, { header: { id: 'x', cwd: '/t' } }), undefined)
  assert.equal(resolveTranscriptPath({ locate: () => ({ path: '/p' }) }, undefined), undefined)
})

test('hookInputBase: CC base fields for a top-level agent', () => {
  const ctx = {
    get(service) {
      assert.equal(service, 'sessionPersistence')
      return { locate: (meta) => ({ kind: 'jsonl', path: `/store/${meta.id}/session.jsonl` }) }
    },
  }
  const agent = {
    id: 'sess-1',
    session: {
      header: { id: 'sess-1', cwd: '/tmp/proj' },
      events: [{ type: 'sandbox/mode', data: { mode: 'danger-full-access' } }],
    },
  }
  assert.deepEqual(hookInputBase(ctx, agent, 'PreToolUse'), {
    session_id: 'sess-1',
    transcript_path: '/store/sess-1/session.jsonl',
    cwd: '/tmp/proj',
    permission_mode: 'bypassPermissions',
    hook_event_name: 'PreToolUse',
  })
})

test('hookInputBase: subagent extras when delegated', () => {
  const agent = {
    id: 'child-1',
    session: {
      header: { id: 'child-1', cwd: '/tmp/proj', delegationDepth: 2, origin: 'subagent', agentPreset: 'coder' },
      events: [],
    },
  }
  const input = hookInputBase(undefined, agent, 'SubagentEnd')
  assert.equal(input.session_id, 'child-1')
  assert.equal(input.permission_mode, 'default')
  assert.equal(input.agent_id, 'child-1')
  assert.equal(input.agent_type, 'subagent')
  assert.equal(input.delegation_depth, 2)
})

test('parseHookConfig: CC nested settings shape with $schema', async () => {
  const { parseHookConfig } = await import('../index.mjs')
  const text = JSON.stringify({
    $schema: 'https://json.schemastore.org/claude-code-settings.json',
    hooks: {
      SessionStart: [{ matcher: '*', hooks: [{ type: 'command', command: 'echo hi' }] }],
      PreToolUse: [{ matcher: 'Read', hooks: [{ type: 'command', command: 'echo read' }] }],
    },
  })
  const byEvent = parseHookConfig(text)
  assert.ok(byEvent.has('SessionStart'))
  assert.ok(byEvent.has('PreToolUse'))
  assert.equal(byEvent.get('SessionStart')[0].hooks[0].command, 'echo hi')
  // unknown top-level keys are ignored, flat shape still works
  assert.ok(parseHookConfig(JSON.stringify({ SessionStart: [] })).has('SessionStart'))
  // a "hooks" key that is not an object is rejected
  assert.throws(() => parseHookConfig(JSON.stringify({ hooks: [] })))
})
