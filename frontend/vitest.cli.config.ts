import { defineConfig } from 'vitest/config'
import path from 'path'

export default defineConfig({
  test: {
    include: ['lib/__tests__/**/*.test.ts', 'cli/__tests__/**/*.test.ts'],
    environment: 'node',
    setupFiles: ['lib/__tests__/setup.ts'],
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, '.'),
    },
  },
})
