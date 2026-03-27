import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  test: {
    include: [
      'lib/__tests__/**/*.test.ts',
      'cli/__tests__/**/*.test.ts',
      'components/**/__tests__/**/*.test.{ts,tsx}',
      'hooks/__tests__/**/*.test.{ts,tsx}',
      'lib/keys/__tests__/**/*.test.ts',
    ],
    environment: 'node',
    setupFiles: ['lib/__tests__/setup.ts'],
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, '.'),
    },
  },
})
