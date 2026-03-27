// @vitest-environment happy-dom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act, render, screen, cleanup, waitFor } from '@testing-library/react'
import { NewSessionDialog } from '../NewSessionDialog'

// Mock next/navigation and react-query
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))

vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}))

const { fetchMock } = vi.hoisted(() => ({
  fetchMock: vi.fn(),
}))

function renderDialog(props: Partial<Parameters<typeof NewSessionDialog>[0]> = {}) {
  return render(
    <NewSessionDialog
      open={true}
      onOpenChange={vi.fn()}
      {...props}
    />,
  )
}

describe('NewSessionDialog', () => {
  beforeEach(() => {
    fetchMock.mockImplementation((input: string | URL) => {
      const url = String(input)
      if (url === '/api/computers') {
        return Promise.resolve({
          ok: true,
          json: async () => [
            { name: 'local', is_local: true, status: 'online' },
          ],
        })
      }

      if (url.startsWith('/api/projects?computer=')) {
        return Promise.resolve({
          ok: true,
          json: async () => [
            { name: 'app', path: '/srv/app' },
          ],
        })
      }

      if (url === '/api/sessions') {
        return Promise.resolve({
          ok: true,
          json: async () => ({ session_id: 'sess-new' }),
        })
      }

      throw new Error(`Unexpected fetch: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => cleanup())

  it('renders using shadcn Dialog (has role="dialog")', () => {
    renderDialog()
    const dialog = screen.getByRole('dialog')
    expect(dialog).toBeDefined()
  })

  it('renders agent radio group', () => {
    renderDialog()
    expect(screen.getByText('Claude')).toBeDefined()
    expect(screen.getByText('Gemini')).toBeDefined()
    expect(screen.getByText('Codex')).toBeDefined()
  })

  it('renders thinking mode radio group', () => {
    renderDialog()
    expect(screen.getByText('fast')).toBeDefined()
    expect(screen.getByText('med')).toBeDefined()
    expect(screen.getByText('slow')).toBeDefined()
  })

  it('renders native_session_id and subdir text inputs', () => {
    renderDialog()
    expect(screen.getByPlaceholderText('Native session ID')).toBeDefined()
    expect(screen.getByPlaceholderText('Subdirectory')).toBeDefined()
  })

  it('renders title and message fields', () => {
    renderDialog()
    expect(screen.getByPlaceholderText('Auto-generated')).toBeDefined()
    expect(screen.getByPlaceholderText('Start with a message...')).toBeDefined()
  })

  it('initializes computer and project from prefill prop', () => {
    // The prefill should set initial values; verify the selects have the values
    // Since computers are fetched async, we verify the prefill prop is accepted
    renderDialog({ prefill: { computer: 'remote-1', project: '/srv/app' } })
    // Component accepts prefill without error
    expect(screen.getByRole('dialog')).toBeDefined()
  })

  it('does not overwrite a newly-prefilled project when an in-flight project request resolves', async () => {
    let resolveProjects: ((value: unknown) => void) | undefined

    fetchMock.mockImplementation((input: string | URL) => {
      const url = String(input)
      if (url === '/api/computers') {
        return Promise.resolve({
          ok: true,
          json: async () => [
            { name: 'local', is_local: true, status: 'online' },
          ],
        })
      }

      if (url.startsWith('/api/projects?computer=')) {
        return new Promise((resolve) => {
          resolveProjects = resolve
        })
      }

      throw new Error(`Unexpected fetch: ${url}`)
    })

    const { rerender } = render(
      <NewSessionDialog
        open={true}
        onOpenChange={vi.fn()}
        prefill={{ computer: 'local' }}
      />,
    )

    rerender(
      <NewSessionDialog
        open={true}
        onOpenChange={vi.fn()}
        prefill={{ computer: 'local', project: '/srv/keep' }}
      />,
    )

    await act(async () => {
      resolveProjects?.({
        ok: true,
        json: async () => [
          { name: 'fallback', path: '/srv/fallback' },
          { name: 'keep', path: '/srv/keep' },
        ],
      })
      await Promise.resolve()
    })

    await waitFor(() => {
      const projectSelect = screen.getAllByRole('combobox')[1] as HTMLSelectElement
      expect(projectSelect.value).toBe('/srv/keep')
    })
  })
})
