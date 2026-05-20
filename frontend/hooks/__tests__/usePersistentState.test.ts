// @vitest-environment happy-dom
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { usePersistentState } from '../usePersistentState';

function installLocalStorageMock() {
  const store = new Map<string, string>();

  Object.defineProperty(window, 'localStorage', {
    configurable: true,
    value: {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => {
        store.set(key, value);
      },
      removeItem: (key: string) => {
        store.delete(key);
      },
      clear: () => {
        store.clear();
      },
    },
  });
}

describe('usePersistentState', () => {
  beforeEach(() => {
    installLocalStorageMock();
  });

  it('restores a stored value after hydration', async () => {
    window.localStorage.setItem('teleclaude.test', JSON.stringify({ activeTab: 'jobs' }));

    const { result } = renderHook(() => usePersistentState('teleclaude.test', { activeTab: 'sessions' }));

    await waitFor(() => {
      expect(result.current[2].isHydrated).toBe(true);
    });

    expect(result.current[0]).toEqual({ activeTab: 'jobs' });
    expect(result.current[2].hasStoredValue).toBe(true);
  });

  it('writes updates back to local storage', async () => {
    const { result } = renderHook(() => usePersistentState('teleclaude.test', { activeTab: 'sessions' }));

    await waitFor(() => {
      expect(result.current[2].isHydrated).toBe(true);
    });

    act(() => {
      result.current[1]({ activeTab: 'preparation' });
    });

    await waitFor(() => {
      expect(window.localStorage.getItem('teleclaude.test')).toBe(JSON.stringify({ activeTab: 'preparation' }));
    });
  });

  it('falls back to the initial value when storage is invalid', async () => {
    window.localStorage.setItem('teleclaude.test', 'not-json');

    const { result } = renderHook(() => usePersistentState('teleclaude.test', { activeTab: 'sessions' }));

    await waitFor(() => {
      expect(result.current[2].isHydrated).toBe(true);
    });

    expect(result.current[0]).toEqual({ activeTab: 'sessions' });
    expect(result.current[2].hasStoredValue).toBe(false);
  });

  it('uses the latest initial value on hydration if it changes before hydration', async () => {
    const { result, rerender } = renderHook((props) => usePersistentState(props.key, props.initial), {
      initialProps: { key: 'teleclaude.test', initial: { activeTab: 'sessions' } },
    });

    // Rerender with a new key to trigger re-hydration with a new initial value
    rerender({ key: 'teleclaude.test2', initial: { activeTab: 'preparation' } });

    await waitFor(() => {
      expect(result.current[0]).toEqual({ activeTab: 'preparation' });
    });

    expect(result.current[2].hasStoredValue).toBe(false);
  });
});
