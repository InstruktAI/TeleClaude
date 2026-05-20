export async function register() {
  // This is a development-only Next.js workaround.
  //
  // In Node v25, Next's dev overlay path touches globalThis.localStorage during
  // server rendering. Node exposes a server-side localStorage getter backed by
  // --localstorage-file, and when that path is invalid the getter emits a warning
  // and returns a shape without the Storage API methods the overlay expects.
  //
  // We replace it with a tiny in-memory implementation so development SSR keeps
  // working. This is not browser persistence and should never run in production.
  if (process.env.NODE_ENV !== 'development') {
    return;
  }

  // Avoid accessing the getter directly because doing so emits a noisy Node warning.
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
  if (!descriptor?.get) {
    return;
  }

  const store = new Map<string, string>();
  Object.defineProperty(globalThis, 'localStorage', {
    value: {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => store.set(key, String(value)),
      removeItem: (key: string) => store.delete(key),
      clear: () => store.clear(),
      get length() {
        return store.size;
      },
      key: (index: number) => [...store.keys()][index] ?? null,
    },
    writable: true,
    configurable: true,
  });
}
