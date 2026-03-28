"use client"

import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react"

type InitialValue<T> = T | (() => T)

interface UsePersistentStateOptions<T> {
  serialize?: (value: T) => string
  deserialize?: (raw: string) => T
}

interface PersistentStateMeta {
  hasStoredValue: boolean
  isHydrated: boolean
}

function defaultSerialize<T>(value: T): string {
  return JSON.stringify(value)
}

function defaultDeserialize<T>(raw: string): T {
  return JSON.parse(raw) as T
}

function resolveInitialValue<T>(value: InitialValue<T>): T {
  return typeof value === "function" ? (value as () => T)() : value
}

export function usePersistentState<T>(
  key: string,
  initialValue: InitialValue<T>,
  options: UsePersistentStateOptions<T> = {},
): [T, Dispatch<SetStateAction<T>>, PersistentStateMeta] {
  const serialize = options.serialize ?? defaultSerialize<T>
  const deserialize = options.deserialize ?? defaultDeserialize<T>
  const initialValueRef = useRef(initialValue)
  initialValueRef.current = initialValue

  const [state, setState] = useState<T>(() => resolveInitialValue(initialValue))
  const [hasStoredValue, setHasStoredValue] = useState(false)
  const [isHydrated, setIsHydrated] = useState(false)

  useEffect(() => {
    const fallback = resolveInitialValue(initialValueRef.current)

    if (typeof window === "undefined") {
      setState(fallback)
      setHasStoredValue(false)
      setIsHydrated(true)
      return
    }

    try {
      const raw = window.localStorage.getItem(key)
      if (raw === null) {
        setState(fallback)
        setHasStoredValue(false)
      } else {
        setState(deserialize(raw))
        setHasStoredValue(true)
      }
    } catch {
      setState(fallback)
      setHasStoredValue(false)
    }

    setIsHydrated(true)
  }, [deserialize, key])

  useEffect(() => {
    if (!isHydrated || typeof window === "undefined") return

    try {
      window.localStorage.setItem(key, serialize(state))
    } catch {
      // Ignore persistence failures and keep the UI usable.
    }
  }, [isHydrated, key, serialize, state])

  return [state, setState, { hasStoredValue, isHydrated }]
}
