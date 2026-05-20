import nextVitals from 'eslint-config-next/core-web-vitals';
import snapshotTesting from './eslint-plugins/snapshot-testing/index.js';

export default [
  ...nextVitals,
  {
    files: ['**/__tests__/**/*.{ts,tsx}', '**/*.test.{ts,tsx}'],
    plugins: {
      'snapshot-testing': snapshotTesting,
    },
    rules: {
      'snapshot-testing/no-string-assertions': 'error',
    },
  },
];
