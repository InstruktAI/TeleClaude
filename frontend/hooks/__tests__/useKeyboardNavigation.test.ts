// @vitest-environment happy-dom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useKeyboardNavigation } from '../useKeyboardNavigation'
import type { TabValue } from '@/components/tui/TabBar'

function makeCallbacks() {
  return {
    onSwitchTab: vi.fn(),
    onEscape: vi.fn(),
    onAction: vi.fn(),
  }
}

function fire(key: string, opts: Partial<KeyboardEventInit> = {}) {
  document.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, ...opts }))
}

describe('useKeyboardNavigation', () => {
  let callbacks: ReturnType<typeof makeCallbacks>

  beforeEach(() => {
    callbacks = makeCallbacks()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('keys 1-4 call onSwitchTab with the corresponding tab value', () => {
    renderHook(() =>
      useKeyboardNavigation({
        activeTab: 'sessions',
        ...callbacks,
      }),
    )
    const expected: [string, TabValue][] = [
      ['1', 'sessions'],
      ['2', 'preparation'],
      ['3', 'configuration'],
      ['4', 'monitoring'],
    ]
    for (const [key, tab] of expected) {
      fire(key)
      expect(callbacks.onSwitchTab).toHaveBeenLastCalledWith(tab)
    }
    expect(callbacks.onSwitchTab).toHaveBeenCalledTimes(4)
  })

  it('does NOT call onSwitchTab when an input element has focus', () => {
    const input = document.createElement('input')
    document.body.appendChild(input)
    input.focus()

    renderHook(() =>
      useKeyboardNavigation({
        activeTab: 'sessions',
        ...callbacks,
      }),
    )

    fire('1')
    expect(callbacks.onSwitchTab).not.toHaveBeenCalled()

    document.body.removeChild(input)
  })

  it('does NOT fire context keys when a textarea has focus', () => {
    const textarea = document.createElement('textarea')
    document.body.appendChild(textarea)
    textarea.focus()

    renderHook(() =>
      useKeyboardNavigation({
        activeTab: 'sessions',
        ...callbacks,
      }),
    )

    fire('n')
    expect(callbacks.onAction).not.toHaveBeenCalled()

    document.body.removeChild(textarea)
  })

  it('does NOT fire context keys when a contenteditable has focus', () => {
    const div = document.createElement('div')
    div.setAttribute('contenteditable', 'true')
    document.body.appendChild(div)
    div.focus()

    renderHook(() =>
      useKeyboardNavigation({
        activeTab: 'sessions',
        ...callbacks,
      }),
    )

    fire('n')
    expect(callbacks.onAction).not.toHaveBeenCalled()

    document.body.removeChild(div)
  })

  it('Escape calls onEscape', () => {
    renderHook(() =>
      useKeyboardNavigation({
        activeTab: 'sessions',
        ...callbacks,
      }),
    )
    fire('Escape')
    expect(callbacks.onEscape).toHaveBeenCalledTimes(1)
  })

  it('Escape still calls onEscape when an input has focus', () => {
    const input = document.createElement('input')
    document.body.appendChild(input)
    input.focus()

    renderHook(() =>
      useKeyboardNavigation({
        activeTab: 'sessions',
        ...callbacks,
      }),
    )

    fire('Escape')
    expect(callbacks.onEscape).toHaveBeenCalledTimes(1)

    input.blur()
    document.body.removeChild(input)
  })

  it('context-specific key dispatches onAction with the binding action', () => {
    renderHook(() =>
      useKeyboardNavigation({
        activeTab: 'sessions',
        ...callbacks,
      }),
    )
    fire('n')
    expect(callbacks.onAction).toHaveBeenCalledWith('new_session')
  })

  it('cleans up keydown listener on unmount', () => {
    const spy = vi.spyOn(document, 'removeEventListener')
    const { unmount } = renderHook(() =>
      useKeyboardNavigation({
        activeTab: 'sessions',
        ...callbacks,
      }),
    )
    unmount()
    expect(spy).toHaveBeenCalledWith('keydown', expect.any(Function))
  })
})
