import { describe, it, expect } from 'vitest'
import { reduce } from '@/lib/store/reducer'
import type { TuiState, Intent } from '@/lib/store/types'

// ---------------------------------------------------------------------------
// Factory: creates a clean initial state for each test
// ---------------------------------------------------------------------------

function freshState(): TuiState {
  return {
    sessions: {
      selectedIndex: 0,
      selectedSessionId: null,
      lastSelectionSource: 'system',
      lastSelectionSessionId: null,
      scrollOffset: 0,
      selectionMethod: 'arrow',
      collapsedSessions: new Set<string>(),
      stickySessions: [],
      preview: null,
      inputHighlights: new Set<string>(),
      outputHighlights: new Set<string>(),
      tempOutputHighlights: new Set<string>(),
      activeTool: {},
      activityTimerReset: new Set<string>(),
      lastOutputSummary: {},
      lastOutputSummaryAt: {},
      lastActivityAt: {},
    },
    preparation: {
      selectedIndex: 0,
      scrollOffset: 0,
      expandedTodos: new Set<string>(),
      filePaneId: null,
      preview: null,
    },
    config: {
      activeSubtab: 'adapters',
      guidedMode: false,
    },
    animationMode: 'periodic',
  }
}

// ---------------------------------------------------------------------------
// SET_PREVIEW
// ---------------------------------------------------------------------------

describe('reducer', () => {
  describe('SET_PREVIEW', () => {
    it('should set session preview', () => {
      const state = freshState()
      const next = reduce(state, { type: 'SET_PREVIEW', sessionId: 'abc' })
      expect(next.sessions.preview).toEqual({ sessionId: 'abc' })
    })

    it('should clear preparation preview when setting session preview', () => {
      const state = freshState()
      state.preparation.preview = { docId: 'd1', command: 'cat', title: 'x' }
      const next = reduce(state, { type: 'SET_PREVIEW', sessionId: 'abc' })
      expect(next.preparation.preview).toBeNull()
    })

    it('should remove output highlight for non-codex agent', () => {
      const state = freshState()
      state.sessions.outputHighlights.add('abc')
      const next = reduce(state, {
        type: 'SET_PREVIEW',
        sessionId: 'abc',
        activeAgent: 'claude',
      })
      expect(next.sessions.outputHighlights.has('abc')).toBe(false)
    })

    it('should preserve output highlight for codex agent', () => {
      const state = freshState()
      state.sessions.outputHighlights.add('abc')
      const next = reduce(state, {
        type: 'SET_PREVIEW',
        sessionId: 'abc',
        activeAgent: 'codex',
      })
      expect(next.sessions.outputHighlights.has('abc')).toBe(true)
    })

    it('should not set preview when sessionId is empty string', () => {
      const state = freshState()
      const next = reduce(state, {
        type: 'SET_PREVIEW',
        sessionId: '',
      } as Intent)
      expect(next.sessions.preview).toBeNull()
    })

    it('should not set preview when sticky panes are at max', () => {
      const state = freshState()
      state.sessions.stickySessions = [
        { sessionId: 's1' },
        { sessionId: 's2' },
        { sessionId: 's3' },
        { sessionId: 's4' },
        { sessionId: 's5' },
      ]
      const next = reduce(state, { type: 'SET_PREVIEW', sessionId: 'new' })
      expect(next.sessions.preview).toBeNull()
    })
  })

  // ---------------------------------------------------------------------------
  // CLEAR_PREVIEW
  // ---------------------------------------------------------------------------

  describe('CLEAR_PREVIEW', () => {
    it('should clear session preview', () => {
      const state = freshState()
      state.sessions.preview = { sessionId: 'abc' }
      const next = reduce(state, { type: 'CLEAR_PREVIEW' })
      expect(next.sessions.preview).toBeNull()
    })

    it('should be a no-op when preview is already null', () => {
      const state = freshState()
      const next = reduce(state, { type: 'CLEAR_PREVIEW' })
      expect(next.sessions.preview).toBeNull()
    })
  })

  // ---------------------------------------------------------------------------
  // TOGGLE_STICKY
  // ---------------------------------------------------------------------------

  describe('TOGGLE_STICKY', () => {
    it('should add session to sticky list', () => {
      const state = freshState()
      const next = reduce(state, { type: 'TOGGLE_STICKY', sessionId: 's1' })
      expect(next.sessions.stickySessions).toEqual([{ sessionId: 's1' }])
    })

    it('should remove session from sticky list when already present', () => {
      const state = freshState()
      state.sessions.stickySessions = [{ sessionId: 's1' }, { sessionId: 's2' }]
      const next = reduce(state, { type: 'TOGGLE_STICKY', sessionId: 's1' })
      expect(next.sessions.stickySessions).toEqual([{ sessionId: 's2' }])
    })

    it('should enforce max 5 limit when adding', () => {
      const state = freshState()
      state.sessions.stickySessions = [
        { sessionId: 's1' },
        { sessionId: 's2' },
        { sessionId: 's3' },
        { sessionId: 's4' },
        { sessionId: 's5' },
      ]
      const next = reduce(state, { type: 'TOGGLE_STICKY', sessionId: 's6' })
      expect(next.sessions.stickySessions).toHaveLength(5)
      expect(next.sessions.stickySessions.find((s) => s.sessionId === 's6')).toBeUndefined()
    })

    it('should allow removal even when at max', () => {
      const state = freshState()
      state.sessions.stickySessions = [
        { sessionId: 's1' },
        { sessionId: 's2' },
        { sessionId: 's3' },
        { sessionId: 's4' },
        { sessionId: 's5' },
      ]
      const next = reduce(state, { type: 'TOGGLE_STICKY', sessionId: 's3' })
      expect(next.sessions.stickySessions).toHaveLength(4)
    })

    it('should clear preview when session being stickied is previewed', () => {
      const state = freshState()
      state.sessions.preview = { sessionId: 'abc' }
      const next = reduce(state, { type: 'TOGGLE_STICKY', sessionId: 'abc' })
      expect(next.sessions.preview).toBeNull()
      expect(next.sessions.stickySessions).toEqual([{ sessionId: 'abc' }])
    })

    it('should preserve order when toggling off a middle element', () => {
      const state = freshState()
      state.sessions.stickySessions = [
        { sessionId: 'a' },
        { sessionId: 'b' },
        { sessionId: 'c' },
      ]
      const next = reduce(state, { type: 'TOGGLE_STICKY', sessionId: 'b' })
      expect(next.sessions.stickySessions.map((s) => s.sessionId)).toEqual(['a', 'c'])
    })

    it('should not add when sessionId is empty', () => {
      const state = freshState()
      const next = reduce(state, { type: 'TOGGLE_STICKY', sessionId: '' } as Intent)
      expect(next.sessions.stickySessions).toHaveLength(0)
    })

    it('should remove output highlight for non-codex agent on add', () => {
      const state = freshState()
      state.sessions.outputHighlights.add('s1')
      const next = reduce(state, {
        type: 'TOGGLE_STICKY',
        sessionId: 's1',
        activeAgent: 'claude',
      })
      expect(next.sessions.outputHighlights.has('s1')).toBe(false)
    })
  })

  // ---------------------------------------------------------------------------
  // SET_PREP_PREVIEW
  // ---------------------------------------------------------------------------

  describe('SET_PREP_PREVIEW', () => {
    it('should set preparation preview', () => {
      const state = freshState()
      const next = reduce(state, {
        type: 'SET_PREP_PREVIEW',
        docId: 'd1',
        command: 'cat d1',
        title: 'My Doc',
      })
      expect(next.preparation.preview).toEqual({
        docId: 'd1',
        command: 'cat d1',
        title: 'My Doc',
      })
    })

    it('should clear session preview when setting prep preview', () => {
      const state = freshState()
      state.sessions.preview = { sessionId: 'abc' }
      const next = reduce(state, {
        type: 'SET_PREP_PREVIEW',
        docId: 'd1',
        command: 'cat d1',
      })
      expect(next.sessions.preview).toBeNull()
    })

    it('should default title to empty string when not provided', () => {
      const state = freshState()
      const next = reduce(state, {
        type: 'SET_PREP_PREVIEW',
        docId: 'd1',
        command: 'cat d1',
      })
      expect(next.preparation.preview?.title).toBe('')
    })

    it('should not set when docId is empty', () => {
      const state = freshState()
      const next = reduce(state, {
        type: 'SET_PREP_PREVIEW',
        docId: '',
        command: 'cat',
      } as Intent)
      expect(next.preparation.preview).toBeNull()
    })

    it('should not set when command is empty', () => {
      const state = freshState()
      const next = reduce(state, {
        type: 'SET_PREP_PREVIEW',
        docId: 'd1',
        command: '',
      } as Intent)
      expect(next.preparation.preview).toBeNull()
    })

    it('should not set when sticky panes are at max', () => {
      const state = freshState()
      state.sessions.stickySessions = [
        { sessionId: 's1' },
        { sessionId: 's2' },
        { sessionId: 's3' },
        { sessionId: 's4' },
        { sessionId: 's5' },
      ]
      const next = reduce(state, {
        type: 'SET_PREP_PREVIEW',
        docId: 'd1',
        command: 'cat d1',
      })
      expect(next.preparation.preview).toBeNull()
    })
  })

  // ---------------------------------------------------------------------------
  // CLEAR_PREP_PREVIEW
  // ---------------------------------------------------------------------------

  describe('CLEAR_PREP_PREVIEW', () => {
    it('should clear preparation preview', () => {
      const state = freshState()
      state.preparation.preview = { docId: 'd1', command: 'cat', title: 'x' }
      const next = reduce(state, { type: 'CLEAR_PREP_PREVIEW' })
      expect(next.preparation.preview).toBeNull()
    })
  })

  // ---------------------------------------------------------------------------
  // COLLAPSE_SESSION / EXPAND_SESSION
  // ---------------------------------------------------------------------------

  describe('COLLAPSE_SESSION', () => {
    it('should add session to collapsed set', () => {
      const state = freshState()
      const next = reduce(state, { type: 'COLLAPSE_SESSION', sessionId: 's1' })
      expect(next.sessions.collapsedSessions.has('s1')).toBe(true)
    })

    it('should be idempotent', () => {
      const state = freshState()
      state.sessions.collapsedSessions.add('s1')
      const next = reduce(state, { type: 'COLLAPSE_SESSION', sessionId: 's1' })
      expect(next.sessions.collapsedSessions.has('s1')).toBe(true)
    })

    it('should be a no-op for empty sessionId', () => {
      const state = freshState()
      const next = reduce(state, { type: 'COLLAPSE_SESSION', sessionId: '' } as Intent)
      expect(next.sessions.collapsedSessions.size).toBe(0)
    })
  })

  describe('EXPAND_SESSION', () => {
    it('should remove session from collapsed set', () => {
      const state = freshState()
      state.sessions.collapsedSessions.add('s1')
      const next = reduce(state, { type: 'EXPAND_SESSION', sessionId: 's1' })
      expect(next.sessions.collapsedSessions.has('s1')).toBe(false)
    })

    it('should be a no-op for non-collapsed session', () => {
      const state = freshState()
      const next = reduce(state, { type: 'EXPAND_SESSION', sessionId: 's1' })
      expect(next.sessions.collapsedSessions.has('s1')).toBe(false)
    })
  })

  // ---------------------------------------------------------------------------
  // EXPAND_ALL_SESSIONS / COLLAPSE_ALL_SESSIONS
  // ---------------------------------------------------------------------------

  describe('EXPAND_ALL_SESSIONS', () => {
    it('should clear all collapsed sessions', () => {
      const state = freshState()
      state.sessions.collapsedSessions = new Set(['a', 'b', 'c'])
      const next = reduce(state, { type: 'EXPAND_ALL_SESSIONS' })
      expect(next.sessions.collapsedSessions.size).toBe(0)
    })
  })

  describe('COLLAPSE_ALL_SESSIONS', () => {
    it('should collapse all provided session IDs', () => {
      const state = freshState()
      const next = reduce(state, {
        type: 'COLLAPSE_ALL_SESSIONS',
        sessionIds: ['a', 'b', 'c'],
      })
      expect(next.sessions.collapsedSessions).toEqual(new Set(['a', 'b', 'c']))
    })

    it('should replace existing collapsed set', () => {
      const state = freshState()
      state.sessions.collapsedSessions = new Set(['x', 'y'])
      const next = reduce(state, {
        type: 'COLLAPSE_ALL_SESSIONS',
        sessionIds: ['a'],
      })
      expect(next.sessions.collapsedSessions).toEqual(new Set(['a']))
    })
  })

  // ---------------------------------------------------------------------------
  // EXPAND_TODO / COLLAPSE_TODO
  // ---------------------------------------------------------------------------

  describe('EXPAND_TODO', () => {
    it('should add todo to expanded set', () => {
      const state = freshState()
      const next = reduce(state, { type: 'EXPAND_TODO', todoId: 't1' })
      expect(next.preparation.expandedTodos.has('t1')).toBe(true)
    })

    it('should be a no-op for empty todoId', () => {
      const state = freshState()
      const next = reduce(state, { type: 'EXPAND_TODO', todoId: '' } as Intent)
      expect(next.preparation.expandedTodos.size).toBe(0)
    })
  })

  describe('COLLAPSE_TODO', () => {
    it('should remove todo from expanded set', () => {
      const state = freshState()
      state.preparation.expandedTodos.add('t1')
      const next = reduce(state, { type: 'COLLAPSE_TODO', todoId: 't1' })
      expect(next.preparation.expandedTodos.has('t1')).toBe(false)
    })
  })

  // ---------------------------------------------------------------------------
  // EXPAND_ALL_TODOS / COLLAPSE_ALL_TODOS
  // ---------------------------------------------------------------------------

  describe('EXPAND_ALL_TODOS', () => {
    it('should expand all provided todo IDs', () => {
      const state = freshState()
      const next = reduce(state, {
        type: 'EXPAND_ALL_TODOS',
        todoIds: ['t1', 't2', 't3'],
      })
      expect(next.preparation.expandedTodos).toEqual(new Set(['t1', 't2', 't3']))
    })

    it('should merge with existing expanded todos', () => {
      const state = freshState()
      state.preparation.expandedTodos.add('t0')
      const next = reduce(state, {
        type: 'EXPAND_ALL_TODOS',
        todoIds: ['t1'],
      })
      expect(next.preparation.expandedTodos.has('t0')).toBe(true)
      expect(next.preparation.expandedTodos.has('t1')).toBe(true)
    })
  })

  describe('COLLAPSE_ALL_TODOS', () => {
    it('should clear all expanded todos', () => {
      const state = freshState()
      state.preparation.expandedTodos = new Set(['t1', 't2'])
      const next = reduce(state, { type: 'COLLAPSE_ALL_TODOS' })
      expect(next.preparation.expandedTodos.size).toBe(0)
    })
  })

  // ---------------------------------------------------------------------------
  // SET_SELECTION
  // ---------------------------------------------------------------------------

  describe('SET_SELECTION', () => {
    it('should set sessions view selection index and session ID', () => {
      const state = freshState()
      const next = reduce(state, {
        type: 'SET_SELECTION',
        view: 'sessions',
        index: 3,
        sessionId: 'abc',
        source: 'user',
      })
      expect(next.sessions.selectedIndex).toBe(3)
      expect(next.sessions.selectedSessionId).toBe('abc')
      expect(next.sessions.lastSelectionSessionId).toBe('abc')
      expect(next.sessions.lastSelectionSource).toBe('user')
    })

    it('should set preparation view selection index', () => {
      const state = freshState()
      const next = reduce(state, {
        type: 'SET_SELECTION',
        view: 'preparation',
        index: 7,
      })
      expect(next.preparation.selectedIndex).toBe(7)
    })

    it('should clear output highlight when changing sessions (non-codex)', () => {
      const state = freshState()
      state.sessions.selectedSessionId = 'old'
      state.sessions.outputHighlights.add('new')
      const next = reduce(state, {
        type: 'SET_SELECTION',
        view: 'sessions',
        index: 1,
        sessionId: 'new',
        source: 'user',
        activeAgent: 'claude',
      })
      expect(next.sessions.outputHighlights.has('new')).toBe(false)
    })

    it('should preserve output highlight for codex agent', () => {
      const state = freshState()
      state.sessions.selectedSessionId = 'old'
      state.sessions.outputHighlights.add('new')
      const next = reduce(state, {
        type: 'SET_SELECTION',
        view: 'sessions',
        index: 1,
        sessionId: 'new',
        source: 'user',
        activeAgent: 'codex',
      })
      expect(next.sessions.outputHighlights.has('new')).toBe(true)
    })

    it('should not clear output highlight when re-selecting same session', () => {
      const state = freshState()
      state.sessions.selectedSessionId = 'same'
      state.sessions.outputHighlights.add('same')
      const next = reduce(state, {
        type: 'SET_SELECTION',
        view: 'sessions',
        index: 0,
        sessionId: 'same',
        source: 'user',
      })
      expect(next.sessions.outputHighlights.has('same')).toBe(true)
    })

    it('should not clear output highlight for system source', () => {
      const state = freshState()
      state.sessions.selectedSessionId = 'old'
      state.sessions.outputHighlights.add('new')
      const next = reduce(state, {
        type: 'SET_SELECTION',
        view: 'sessions',
        index: 1,
        sessionId: 'new',
        source: 'system',
      })
      expect(next.sessions.outputHighlights.has('new')).toBe(true)
    })
  })

  // ---------------------------------------------------------------------------
  // SET_SCROLL_OFFSET
  // ---------------------------------------------------------------------------

  describe('SET_SCROLL_OFFSET', () => {
    it('should set sessions scroll offset', () => {
      const state = freshState()
      const next = reduce(state, {
        type: 'SET_SCROLL_OFFSET',
        view: 'sessions',
        offset: 42,
      })
      expect(next.sessions.scrollOffset).toBe(42)
    })

    it('should set preparation scroll offset', () => {
      const state = freshState()
      const next = reduce(state, {
        type: 'SET_SCROLL_OFFSET',
        view: 'preparation',
        offset: 10,
      })
      expect(next.preparation.scrollOffset).toBe(10)
    })
  })

  // ---------------------------------------------------------------------------
  // SET_SELECTION_METHOD
  // ---------------------------------------------------------------------------

  describe('SET_SELECTION_METHOD', () => {
    it('should set selection method to click', () => {
      const state = freshState()
      const next = reduce(state, { type: 'SET_SELECTION_METHOD', method: 'click' })
      expect(next.sessions.selectionMethod).toBe('click')
    })

    it('should set selection method to pane', () => {
      const state = freshState()
      const next = reduce(state, { type: 'SET_SELECTION_METHOD', method: 'pane' })
      expect(next.sessions.selectionMethod).toBe('pane')
    })

    it('should ignore invalid method', () => {
      const state = freshState()
      state.sessions.selectionMethod = 'arrow'
      const next = reduce(state, {
        type: 'SET_SELECTION_METHOD',
        method: 'invalid' as any,
      })
      expect(next.sessions.selectionMethod).toBe('arrow')
    })
  })

  // ---------------------------------------------------------------------------
  // SESSION_ACTIVITY (legacy)
  // ---------------------------------------------------------------------------

  describe('SESSION_ACTIVITY', () => {
    it('should set input highlight on user_input', () => {
      const state = freshState()
      const next = reduce(state, {
        type: 'SESSION_ACTIVITY',
        sessionId: 's1',
        reason: 'user_input',
      })
      expect(next.sessions.inputHighlights.has('s1')).toBe(true)
      expect(next.sessions.outputHighlights.has('s1')).toBe(false)
      expect(next.sessions.tempOutputHighlights.has('s1')).toBe(false)
    })

    it('should set temp output highlight on tool_done', () => {
      const state = freshState()
      state.sessions.inputHighlights.add('s1')
      const next = reduce(state, {
        type: 'SESSION_ACTIVITY',
        sessionId: 's1',
        reason: 'tool_done',
      })
      expect(next.sessions.inputHighlights.has('s1')).toBe(false)
      expect(next.sessions.tempOutputHighlights.has('s1')).toBe(true)
    })

    it('should set output highlight on agent_stopped', () => {
      const state = freshState()
      state.sessions.inputHighlights.add('s1')
      state.sessions.tempOutputHighlights.add('s1')
      const next = reduce(state, {
        type: 'SESSION_ACTIVITY',
        sessionId: 's1',
        reason: 'agent_stopped',
      })
      expect(next.sessions.inputHighlights.has('s1')).toBe(false)
      expect(next.sessions.tempOutputHighlights.has('s1')).toBe(false)
      expect(next.sessions.outputHighlights.has('s1')).toBe(true)
    })

    it('should not change highlights on state_change', () => {
      const state = freshState()
      state.sessions.inputHighlights.add('s1')
      const next = reduce(state, {
        type: 'SESSION_ACTIVITY',
        sessionId: 's1',
        reason: 'state_change',
      })
      expect(next.sessions.inputHighlights.has('s1')).toBe(true)
    })

    it('should be a no-op for empty sessionId', () => {
      const state = freshState()
      const next = reduce(state, {
        type: 'SESSION_ACTIVITY',
        sessionId: '',
        reason: 'user_input',
      } as Intent)
      expect(next.sessions.inputHighlights.size).toBe(0)
    })
  })

  // ---------------------------------------------------------------------------
  // AGENT_ACTIVITY (hook-based)
  // ---------------------------------------------------------------------------

  describe('AGENT_ACTIVITY', () => {
    it('should set input highlight on user_prompt_submit', () => {
      const state = freshState()
      const next = reduce(state, {
        type: 'AGENT_ACTIVITY',
        sessionId: 's1',
        eventType: 'user_prompt_submit',
      })
      expect(next.sessions.inputHighlights.has('s1')).toBe(true)
      expect(next.sessions.outputHighlights.has('s1')).toBe(false)
      expect(next.sessions.tempOutputHighlights.has('s1')).toBe(false)
    })

    it('should set temp highlight and active tool on tool_use', () => {
      const state = freshState()
      const next = reduce(state, {
        type: 'AGENT_ACTIVITY',
        sessionId: 's1',
        eventType: 'tool_use',
        toolName: 'Read',
        toolPreview: 'Reading file.ts',
      })
      expect(next.sessions.inputHighlights.has('s1')).toBe(false)
      expect(next.sessions.tempOutputHighlights.has('s1')).toBe(true)
      expect(next.sessions.activityTimerReset.has('s1')).toBe(true)
      expect(next.sessions.activeTool['s1']).toBe('Reading file.ts')
    })

    it('should prefer toolPreview over toolName', () => {
      const state = freshState()
      const next = reduce(state, {
        type: 'AGENT_ACTIVITY',
        sessionId: 's1',
        eventType: 'tool_use',
        toolName: 'Read',
        toolPreview: 'Reading config.json',
      })
      expect(next.sessions.activeTool['s1']).toBe('Reading config.json')
    })

    it('should fall back to toolName when toolPreview is empty', () => {
      const state = freshState()
      const next = reduce(state, {
        type: 'AGENT_ACTIVITY',
        sessionId: 's1',
        eventType: 'tool_use',
        toolName: 'Bash',
        toolPreview: '',
      })
      expect(next.sessions.activeTool['s1']).toBe('Bash')
    })

    it('should clear active tool on tool_done', () => {
      const state = freshState()
      state.sessions.activeTool['s1'] = 'Read'
      const next = reduce(state, {
        type: 'AGENT_ACTIVITY',
        sessionId: 's1',
        eventType: 'tool_done',
      })
      expect(next.sessions.activeTool['s1']).toBeUndefined()
      expect(next.sessions.tempOutputHighlights.has('s1')).toBe(true)
    })

    it('should set output highlight and summary on agent_stop', () => {
      const state = freshState()
      state.sessions.inputHighlights.add('s1')
      state.sessions.tempOutputHighlights.add('s1')
      state.sessions.activeTool['s1'] = 'Read'
      const next = reduce(state, {
        type: 'AGENT_ACTIVITY',
        sessionId: 's1',
        eventType: 'agent_stop',
        summary: 'Task completed',
        timestamp: '2025-01-01T12:00:00Z',
      })
      expect(next.sessions.inputHighlights.has('s1')).toBe(false)
      expect(next.sessions.tempOutputHighlights.has('s1')).toBe(false)
      expect(next.sessions.outputHighlights.has('s1')).toBe(true)
      expect(next.sessions.activeTool['s1']).toBeUndefined()
      expect(next.sessions.lastOutputSummary['s1']).toBe('Task completed')
      expect(next.sessions.lastOutputSummaryAt['s1']).toBe('2025-01-01T12:00:00Z')
    })

    it('should store activity timestamp from any event', () => {
      const state = freshState()
      const next = reduce(state, {
        type: 'AGENT_ACTIVITY',
        sessionId: 's1',
        eventType: 'tool_use',
        toolName: 'Bash',
        timestamp: '2025-06-15T10:00:00Z',
      })
      expect(next.sessions.lastActivityAt['s1']).toBe('2025-06-15T10:00:00Z')
    })

    it('should be a no-op for empty sessionId', () => {
      const state = freshState()
      const next = reduce(state, {
        type: 'AGENT_ACTIVITY',
        sessionId: '',
        eventType: 'tool_use',
      } as Intent)
      expect(next.sessions.tempOutputHighlights.size).toBe(0)
    })
  })

  // ---------------------------------------------------------------------------
  // CLEAR_TEMP_HIGHLIGHT
  // ---------------------------------------------------------------------------

  describe('CLEAR_TEMP_HIGHLIGHT', () => {
    it('should clear temp highlight and set output highlight', () => {
      const state = freshState()
      state.sessions.tempOutputHighlights.add('s1')
      state.sessions.activeTool['s1'] = 'Read'
      const next = reduce(state, { type: 'CLEAR_TEMP_HIGHLIGHT', sessionId: 's1' })
      expect(next.sessions.tempOutputHighlights.has('s1')).toBe(false)
      expect(next.sessions.activeTool['s1']).toBeUndefined()
      expect(next.sessions.outputHighlights.has('s1')).toBe(true)
    })

    it('should be a no-op for empty sessionId', () => {
      const state = freshState()
      const next = reduce(state, {
        type: 'CLEAR_TEMP_HIGHLIGHT',
        sessionId: '',
      } as Intent)
      expect(next.sessions.outputHighlights.size).toBe(0)
    })
  })

  // ---------------------------------------------------------------------------
  // SYNC_SESSIONS
  // ---------------------------------------------------------------------------

  describe('SYNC_SESSIONS', () => {
    it('should prune stale preview reference', () => {
      const state = freshState()
      state.sessions.preview = { sessionId: 'gone' }
      const next = reduce(state, {
        type: 'SYNC_SESSIONS',
        sessionIds: ['alive'],
      })
      expect(next.sessions.preview).toBeNull()
    })

    it('should keep valid preview reference', () => {
      const state = freshState()
      state.sessions.preview = { sessionId: 'alive' }
      const next = reduce(state, {
        type: 'SYNC_SESSIONS',
        sessionIds: ['alive'],
      })
      expect(next.sessions.preview).toEqual({ sessionId: 'alive' })
    })

    it('should prune stale sticky sessions', () => {
      const state = freshState()
      state.sessions.stickySessions = [
        { sessionId: 'alive' },
        { sessionId: 'gone' },
      ]
      const next = reduce(state, {
        type: 'SYNC_SESSIONS',
        sessionIds: ['alive'],
      })
      expect(next.sessions.stickySessions).toEqual([{ sessionId: 'alive' }])
    })

    it('should prune collapsed sessions', () => {
      const state = freshState()
      state.sessions.collapsedSessions = new Set(['alive', 'gone'])
      const next = reduce(state, {
        type: 'SYNC_SESSIONS',
        sessionIds: ['alive'],
      })
      expect(next.sessions.collapsedSessions).toEqual(new Set(['alive']))
    })

    it('should prune highlight sets', () => {
      const state = freshState()
      state.sessions.inputHighlights = new Set(['alive', 'gone'])
      state.sessions.outputHighlights = new Set(['alive', 'gone'])
      state.sessions.tempOutputHighlights = new Set(['gone'])
      const next = reduce(state, {
        type: 'SYNC_SESSIONS',
        sessionIds: ['alive'],
      })
      expect(next.sessions.inputHighlights).toEqual(new Set(['alive']))
      expect(next.sessions.outputHighlights).toEqual(new Set(['alive']))
      expect(next.sessions.tempOutputHighlights.size).toBe(0)
    })

    it('should prune record-based collections', () => {
      const state = freshState()
      state.sessions.lastOutputSummary = { alive: 'ok', gone: 'stale' }
      state.sessions.lastOutputSummaryAt = { alive: 'ts', gone: 'ts' }
      state.sessions.lastActivityAt = { alive: 'ts', gone: 'ts' }
      const next = reduce(state, {
        type: 'SYNC_SESSIONS',
        sessionIds: ['alive'],
      })
      expect(Object.keys(next.sessions.lastOutputSummary)).toEqual(['alive'])
      expect(Object.keys(next.sessions.lastOutputSummaryAt)).toEqual(['alive'])
      expect(Object.keys(next.sessions.lastActivityAt)).toEqual(['alive'])
    })

    it('should prune activityTimerReset set', () => {
      const state = freshState()
      state.sessions.activityTimerReset = new Set(['alive', 'gone'])
      const next = reduce(state, {
        type: 'SYNC_SESSIONS',
        sessionIds: ['alive'],
      })
      expect(next.sessions.activityTimerReset).toEqual(new Set(['alive']))
    })
  })

  // ---------------------------------------------------------------------------
  // SYNC_TODOS
  // ---------------------------------------------------------------------------

  describe('SYNC_TODOS', () => {
    it('should prune expanded todos not in new list', () => {
      const state = freshState()
      state.preparation.expandedTodos = new Set(['alive', 'gone'])
      const next = reduce(state, {
        type: 'SYNC_TODOS',
        todoIds: ['alive'],
      })
      expect(next.preparation.expandedTodos).toEqual(new Set(['alive']))
    })

    it('should handle empty todo list', () => {
      const state = freshState()
      state.preparation.expandedTodos = new Set(['a', 'b'])
      const next = reduce(state, {
        type: 'SYNC_TODOS',
        todoIds: [],
      })
      expect(next.preparation.expandedTodos.size).toBe(0)
    })
  })

  // ---------------------------------------------------------------------------
  // SET_FILE_PANE_ID / CLEAR_FILE_PANE_ID
  // ---------------------------------------------------------------------------

  describe('SET_FILE_PANE_ID', () => {
    it('should set file pane ID', () => {
      const state = freshState()
      const next = reduce(state, { type: 'SET_FILE_PANE_ID', paneId: 'pane-42' })
      expect(next.preparation.filePaneId).toBe('pane-42')
    })
  })

  describe('CLEAR_FILE_PANE_ID', () => {
    it('should clear file pane ID', () => {
      const state = freshState()
      state.preparation.filePaneId = 'pane-42'
      const next = reduce(state, { type: 'CLEAR_FILE_PANE_ID' })
      expect(next.preparation.filePaneId).toBeNull()
    })
  })

  // ---------------------------------------------------------------------------
  // SET_ANIMATION_MODE
  // ---------------------------------------------------------------------------

  describe('SET_ANIMATION_MODE', () => {
    it('should set mode to off', () => {
      const state = freshState()
      const next = reduce(state, { type: 'SET_ANIMATION_MODE', mode: 'off' })
      expect(next.animationMode).toBe('off')
    })

    it('should set mode to party', () => {
      const state = freshState()
      const next = reduce(state, { type: 'SET_ANIMATION_MODE', mode: 'party' })
      expect(next.animationMode).toBe('party')
    })

    it('should ignore invalid mode', () => {
      const state = freshState()
      const next = reduce(state, {
        type: 'SET_ANIMATION_MODE',
        mode: 'invalid' as any,
      })
      expect(next.animationMode).toBe('periodic')
    })
  })

  // ---------------------------------------------------------------------------
  // SET_CONFIG_SUBTAB
  // ---------------------------------------------------------------------------

  describe('SET_CONFIG_SUBTAB', () => {
    it('should set subtab to people', () => {
      const state = freshState()
      const next = reduce(state, { type: 'SET_CONFIG_SUBTAB', subtab: 'people' })
      expect(next.config.activeSubtab).toBe('people')
    })

    it('should accept all valid subtabs', () => {
      const subtabs = ['adapters', 'people', 'notifications', 'environment', 'validate'] as const
      for (const subtab of subtabs) {
        const state = freshState()
        const next = reduce(state, { type: 'SET_CONFIG_SUBTAB', subtab })
        expect(next.config.activeSubtab).toBe(subtab)
      }
    })

    it('should ignore invalid subtab', () => {
      const state = freshState()
      const next = reduce(state, {
        type: 'SET_CONFIG_SUBTAB',
        subtab: 'invalid' as any,
      })
      expect(next.config.activeSubtab).toBe('adapters')
    })
  })

  // ---------------------------------------------------------------------------
  // SET_CONFIG_GUIDED_MODE
  // ---------------------------------------------------------------------------

  describe('SET_CONFIG_GUIDED_MODE', () => {
    it('should enable guided mode', () => {
      const state = freshState()
      const next = reduce(state, { type: 'SET_CONFIG_GUIDED_MODE', enabled: true })
      expect(next.config.guidedMode).toBe(true)
    })

    it('should disable guided mode', () => {
      const state = freshState()
      state.config.guidedMode = true
      const next = reduce(state, { type: 'SET_CONFIG_GUIDED_MODE', enabled: false })
      expect(next.config.guidedMode).toBe(false)
    })
  })

  // ---------------------------------------------------------------------------
  // Immutability
  // ---------------------------------------------------------------------------

  describe('immutability', () => {
    it('should not mutate the original state', () => {
      const state = freshState()
      const stickyCopy = [...state.sessions.stickySessions]
      reduce(state, { type: 'TOGGLE_STICKY', sessionId: 's1' })
      expect(state.sessions.stickySessions).toEqual(stickyCopy)
    })

    it('should return a new reference on change', () => {
      const state = freshState()
      const next = reduce(state, { type: 'SET_ANIMATION_MODE', mode: 'off' })
      expect(next).not.toBe(state)
    })

    it('should return same reference when no change', () => {
      const state = freshState()
      const next = reduce(state, { type: 'CLEAR_PREVIEW' })
      // Preview is already null, so Immer returns the same ref
      expect(next).toBe(state)
    })
  })
})
