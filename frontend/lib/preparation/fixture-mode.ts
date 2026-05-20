import type { ComputerInfo, ProjectWithTodosInfo } from '@/lib/api/types';
import { SMOKE_COMPUTERS, SMOKE_PROJECTS } from './__fixtures__/smoke';

export interface PreparationFixtures {
  projects: readonly ProjectWithTodosInfo[];
  computers: readonly ComputerInfo[];
}

const ALLOWED_FIXTURE_NAMES = new Set(['smoke']);

/**
 * Returns the static preparation fixture for the given name, or null when the
 * env-guard fails or the name is unknown.
 *
 * Defense in depth — both checks must pass:
 *   - NODE_ENV !== "production": guards against build misconfiguration so the
 *     fixture loader is dead code in any production build.
 *   - NEXT_PUBLIC_E2E_FIXTURES === "1": dedicated public env var; only set in
 *     test runs and dev so accidental dev usage stays opt-in.
 */
export function loadPreparationFixture(fixtureName: string | null | undefined): PreparationFixtures | null {
  if (process.env.NODE_ENV === 'production') return null;
  if (process.env.NEXT_PUBLIC_E2E_FIXTURES !== '1') return null;
  if (!fixtureName || !ALLOWED_FIXTURE_NAMES.has(fixtureName)) return null;

  // Allowlist above prevents arbitrary names from selecting modules.
  if (fixtureName === 'smoke') {
    return { projects: SMOKE_PROJECTS, computers: SMOKE_COMPUTERS };
  }
  return null;
}
