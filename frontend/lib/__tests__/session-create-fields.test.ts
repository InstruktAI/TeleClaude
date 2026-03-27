/**
 * Test specifications for POST /api/sessions field forwarding.
 *
 * Verifies that native_session_id and subdir fields are forwarded
 * to the daemon when present in the request body (resume-oriented sessions).
 *
 * Forwarding tests: it.fails (current route omits these fields).
 * Omission tests: regular it (current route correctly omits when absent).
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { NextRequest } from 'next/server'

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock('@/auth', () => ({
  auth: vi.fn(),
}))

vi.mock('@/lib/proxy/daemon-client', () => ({
  daemonRequest: vi.fn(),
  normalizeUpstreamError: vi.fn((_status: number, _body: string) => ({
    error: 'Upstream error',
  })),
}))

import { auth } from '@/auth'
import { daemonRequest } from '@/lib/proxy/daemon-client'

const mockAuth = vi.mocked(auth)
const mockDaemonRequest = vi.mocked(daemonRequest)

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeAuthSession(): unknown {
  return {
    user: {
      id: 'user-1',
      email: 'test@example.com',
      name: 'Test User',
      role: 'admin',
    },
    expires: '2099-01-01',
  }
}

function makePostRequest(body: Record<string, unknown>): NextRequest {
  return new NextRequest(new URL('http://localhost:3000/api/sessions'), {
    method: 'POST',
    body: JSON.stringify(body),
    headers: { 'Content-Type': 'application/json' },
  })
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks()
  mockAuth.mockResolvedValue(makeAuthSession() as never)
  mockDaemonRequest.mockResolvedValue({
    status: 200,
    headers: {},
    body: JSON.stringify({
      status: 'success',
      session_id: 'new-sess',
      tmux_session_name: 'tmux-new',
    }),
  })
})

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('POST /api/sessions — resume fields', () => {
  it('forwards native_session_id to daemon when present', async () => {
    const { POST } = await import('@/app/api/sessions/route')
    const req = makePostRequest({
      computer: 'local',
      project_path: '/proj',
      native_session_id: 'native-abc-123',
    })
    await POST(req)
    expect(mockDaemonRequest).toHaveBeenCalledWith(
      expect.objectContaining({
        body: expect.objectContaining({
          native_session_id: 'native-abc-123',
        }),
      }),
    )
  })

  it('forwards subdir to daemon when present', async () => {
    const { POST } = await import('@/app/api/sessions/route')
    const req = makePostRequest({
      computer: 'local',
      project_path: '/proj',
      subdir: 'packages/core',
    })
    await POST(req)
    expect(mockDaemonRequest).toHaveBeenCalledWith(
      expect.objectContaining({
        body: expect.objectContaining({
          subdir: 'packages/core',
        }),
      }),
    )
  })

  it(
    'forwards both native_session_id and subdir together',
    async () => {
      const { POST } = await import('@/app/api/sessions/route')
      const req = makePostRequest({
        computer: 'local',
        project_path: '/proj',
        agent: 'claude',
        native_session_id: 'native-xyz',
        subdir: 'apps/web',
      })
      await POST(req)
      expect(mockDaemonRequest).toHaveBeenCalledWith(
        expect.objectContaining({
          body: expect.objectContaining({
            computer: 'local',
            project_path: '/proj',
            agent: 'claude',
            native_session_id: 'native-xyz',
            subdir: 'apps/web',
          }),
        }),
      )
    },
  )

  it('does not send native_session_id when absent from request', async () => {
    const { POST } = await import('@/app/api/sessions/route')
    const req = makePostRequest({
      computer: 'local',
      project_path: '/proj',
    })
    await POST(req)
    const callArgs = mockDaemonRequest.mock.calls[0]?.[0]
    const sentBody = callArgs?.body as Record<string, unknown> | undefined
    expect(sentBody).toBeDefined()
    // Field should not be present at all (not even as undefined)
    expect('native_session_id' in (sentBody ?? {})).toBe(false)
  })

  it('does not send subdir when absent from request', async () => {
    const { POST } = await import('@/app/api/sessions/route')
    const req = makePostRequest({
      computer: 'local',
      project_path: '/proj',
    })
    await POST(req)
    const callArgs = mockDaemonRequest.mock.calls[0]?.[0]
    const sentBody = callArgs?.body as Record<string, unknown> | undefined
    expect(sentBody).toBeDefined()
    expect('subdir' in (sentBody ?? {})).toBe(false)
  })
})
