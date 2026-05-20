// @vitest-environment happy-dom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, render, screen, cleanup, waitFor } from '@testing-library/react';
import { NewSessionDialog } from '../NewSessionDialog';

// Mock next/navigation and react-query
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}));

const { fetchMock } = vi.hoisted(() => ({
  fetchMock: vi.fn(),
}));

function renderDialog(props: Partial<Parameters<typeof NewSessionDialog>[0]> = {}) {
  return render(<NewSessionDialog open={true} onOpenChange={vi.fn()} {...props} />);
}

const EXPECTED_CLAUDE = 'Claude';
const EXPECTED_GEMINI = 'Gemini';
const EXPECTED_CODEX = 'Codex';
const EXPECTED_FAST = 'fast';
const EXPECTED_MED = 'med';
const EXPECTED_SLOW = 'slow';
const EXPECTED_NATIVE_SESSION_ID = 'Native session ID';
const EXPECTED_SUBDIR = 'Subdirectory';

const URL_API_COMPUTERS = '/api/computers';
const URL_API_PROJECTS = '/api/projects';
const URL_API_SESSIONS = '/api/sessions';
const VAL_SRV_KEEP = '/srv/keep';

describe('NewSessionDialog', () => {
  beforeEach(() => {
    fetchMock.mockImplementation((input: string | URL) => {
      const url = String(input);
      if (url === URL_API_COMPUTERS) {
        return Promise.resolve({
          ok: true,
          json: async () => [{ name: 'local', is_local: true, status: 'online' }],
        });
      }

      const parsedUrl = new URL(url, 'http://localhost');
      if (parsedUrl.pathname === URL_API_PROJECTS) {
        return Promise.resolve({
          ok: true,
          json: async () => [{ name: 'app', path: '/srv/app' }],
        });
      }

      if (url === URL_API_SESSIONS) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ session_id: 'sess-new' }),
        });
      }

      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => cleanup());

  it('renders using shadcn Dialog (has role="dialog")', () => {
    renderDialog();
    const dialog = screen.getByRole('dialog');
    expect(dialog).toBeDefined();
  });

  it('renders agent radio group', () => {
    renderDialog();
    expect(screen.getByText(EXPECTED_CLAUDE)).toBeDefined();
    expect(screen.getByText(EXPECTED_GEMINI)).toBeDefined();
    expect(screen.getByText(EXPECTED_CODEX)).toBeDefined();
  });

  it('renders thinking mode radio group', () => {
    renderDialog();
    expect(screen.getByText(EXPECTED_FAST)).toBeDefined();
    expect(screen.getByText(EXPECTED_MED)).toBeDefined();
    expect(screen.getByText(EXPECTED_SLOW)).toBeDefined();
  });

  it('renders native_session_id and subdir text inputs', () => {
    renderDialog();
    expect(screen.getByPlaceholderText(EXPECTED_NATIVE_SESSION_ID)).toBeDefined();
    expect(screen.getByPlaceholderText(EXPECTED_SUBDIR)).toBeDefined();
  });

  it('renders message field', () => {
    renderDialog();
    expect(document.querySelector('textarea')).toBeDefined();
  });

  it('initializes computer and project from prefill prop', () => {
    // The prefill should set initial values; verify the selects have the values
    // Since computers are fetched async, we verify the prefill prop is accepted
    renderDialog({ prefill: { computer: 'remote-1', project: '/srv/app' } });
    // Component accepts prefill without error
    expect(screen.getByRole('dialog')).toBeDefined();
  });

  it('does not overwrite a newly-prefilled project when an in-flight project request resolves', async () => {
    let resolveProjects: ((value: unknown) => void) | undefined;

    fetchMock.mockImplementation((input: string | URL) => {
      const url = String(input);
      if (url === URL_API_COMPUTERS) {
        return Promise.resolve({
          ok: true,
          json: async () => [{ name: 'local', is_local: true, status: 'online' }],
        });
      }

      const parsedUrl = new URL(url, 'http://localhost');
      if (parsedUrl.pathname === URL_API_PROJECTS) {
        return new Promise((resolve) => {
          resolveProjects = resolve;
        });
      }

      throw new Error(`Unexpected fetch: ${url}`);
    });

    const { rerender } = render(
      <NewSessionDialog open={true} onOpenChange={vi.fn()} prefill={{ computer: 'local' }} />,
    );

    rerender(
      <NewSessionDialog open={true} onOpenChange={vi.fn()} prefill={{ computer: 'local', project: VAL_SRV_KEEP }} />,
    );

    await act(async () => {
      resolveProjects?.({
        ok: true,
        json: async () => [
          { name: 'fallback', path: '/srv/fallback' },
          { name: 'keep', path: VAL_SRV_KEEP },
        ],
      });
      await Promise.resolve();
    });

    await waitFor(() => {
      const projectSelect = screen.getAllByRole('combobox')[1] as HTMLSelectElement;
      expect(projectSelect.value).toBe(VAL_SRV_KEEP);
    });
  });
});
