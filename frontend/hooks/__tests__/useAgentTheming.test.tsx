// @vitest-environment happy-dom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, beforeEach, afterEach } from 'vitest'
import { AgentThemingProvider, useAgentTheming, STORAGE_KEY } from '../useAgentTheming'

function installLocalStorageMock() {
  const store = new Map<string, string>()
  const localStorageMock = {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => {
      store.set(key, value)
    },
    removeItem: (key: string) => {
      store.delete(key)
    },
    clear: () => {
      store.clear()
    },
  }

  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: localStorageMock,
  })
  Object.defineProperty(window, 'localStorage', {
    configurable: true,
    value: localStorageMock,
  })
}

function TestConsumer() {
  const { isThemed, setThemed } = useAgentTheming()
  return (
    <div>
      <input data-testid="is-themed" type="checkbox" checked={isThemed} readOnly />
      <button data-testid="set-true" onClick={() => setThemed(true)}>Set True</button>
      <button data-testid="set-false" onClick={() => setThemed(false)}>Set False</button>
    </div>
  )
}

describe('useAgentTheming', () => {
  beforeEach(() => {
    installLocalStorageMock()
    localStorage.clear()
  })

  afterEach(() => {
    cleanup()
    localStorage.clear()
  })

  it('observes the value seeded in localStorage', () => {
    localStorage.setItem(STORAGE_KEY, 'false')
    render(
      <AgentThemingProvider>
        <TestConsumer />
      </AgentThemingProvider>
    )
    expect((screen.getByTestId('is-themed') as HTMLInputElement).checked).toBe(false)
  })

  it('updates the same mounted consumer without a remount when setThemed is called', () => {
    render(
      <AgentThemingProvider>
        <TestConsumer />
      </AgentThemingProvider>
    )

    expect((screen.getByTestId('is-themed') as HTMLInputElement).checked).toBe(true)

    fireEvent.click(screen.getByTestId('set-false'))

    expect((screen.getByTestId('is-themed') as HTMLInputElement).checked).toBe(false)
  })

  it('restores the persisted value from the same storage mock when remounting', () => {
    const { unmount } = render(
      <AgentThemingProvider>
        <TestConsumer />
      </AgentThemingProvider>
    )

    fireEvent.click(screen.getByTestId('set-false'))

    unmount()

    render(
      <AgentThemingProvider>
        <TestConsumer />
      </AgentThemingProvider>
    )

    expect((screen.getByTestId('is-themed') as HTMLInputElement).checked).toBe(false)
  })
})
