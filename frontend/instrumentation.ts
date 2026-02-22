export async function register() {
  // Node.js v22+ exposes a broken localStorage when --localstorage-file
  // is passed without a valid path (Turbopack workers trigger this).
  // Patch it with a no-op implementation to prevent SSR crashes.
  if (typeof globalThis.localStorage !== "undefined") {
    const ls = globalThis.localStorage;
    if (typeof ls.getItem !== "function") {
      const store = new Map<string, string>();
      Object.defineProperty(globalThis, "localStorage", {
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
  }
}
