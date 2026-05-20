/**
 * Test specifications for panel-related proxy routes.
 *
 * Behavioral contract: the frontend proxies panel actions through authenticated
 * Next.js route handlers, validates input at the boundary, and preserves admin
 * authorization rules for privileged operations.
 *
 * All tests are marked as expected failures (it.fails) until implementation exists.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

vi.mock('@/auth', () => ({
  auth: vi.fn(),
}));

vi.mock('@/lib/proxy/daemon-client', () => ({
  daemonRequest: vi.fn(),
  normalizeUpstreamError: vi.fn((status: number, body: string) => {
    let message = 'Upstream service error';
    try {
      const parsed = JSON.parse(body) as { detail?: string; message?: string };
      if (parsed.detail) message = String(parsed.detail);
      else if (parsed.message) message = String(parsed.message);
    } catch {
      // body is not JSON
    }
    return { error: message, upstream_status: status };
  }),
}));

import { auth } from '@/auth';
import { daemonRequest } from '@/lib/proxy/daemon-client';

const mockAuth = vi.mocked(auth);
const mockDaemonRequest = vi.mocked(daemonRequest);

function makeSession(overrides?: Record<string, unknown>) {
  return {
    user: {
      id: 'user-1',
      email: 'builder@example.com',
      name: 'Spec Builder',
      role: 'member',
      ...overrides,
    },
    expires: '2099-01-01T00:00:00Z',
  };
}

function makeRequest(url: string, method = 'GET', body?: unknown): NextRequest {
  const init: ConstructorParameters<typeof NextRequest>[1] = { method };
  if (body !== undefined) {
    init.body = JSON.stringify(body);
    init.headers = { 'Content-Type': 'application/json' };
  }
  return new NextRequest(new URL(url, 'http://localhost:3000'), init);
}

beforeEach(() => {
  vi.clearAllMocks();
  mockDaemonRequest.mockResolvedValue({
    status: 200,
    headers: {},
    body: JSON.stringify({ ok: true }),
  });
});

describe('POST /api/todos', () => {
  it('returns 401 if unauthenticated', async () => {
    mockAuth.mockResolvedValue(null as never);

    const modulePath = '@/app/api/todos/route' as string;
    const { POST } = await import(modulePath);
    const res = await POST(
      makeRequest('http://localhost:3000/api/todos', 'POST', {
        slug: 'web-tui-panels',
      }),
    );

    expect(res.status).toBe(401);
  });

  it('rejects an invalid slug before proxying', async () => {
    mockAuth.mockResolvedValue(makeSession() as never);

    const modulePath = '@/app/api/todos/route' as string;
    const { POST } = await import(modulePath);
    const res = await POST(
      makeRequest('http://localhost:3000/api/todos', 'POST', {
        slug: 'Not Valid',
      }),
    );

    expect(res.status).toBe(400);
    expect(mockDaemonRequest).not.toHaveBeenCalled();
  });

  it('proxies a valid slug to the daemon create endpoint', async () => {
    mockAuth.mockResolvedValue(makeSession() as never);

    const modulePath = '@/app/api/todos/route' as string;
    const { POST } = await import(modulePath);
    const res = await POST(
      makeRequest('http://localhost:3000/api/todos', 'POST', {
        slug: 'web-tui-panels',
      }),
    );

    expect(res.status).toBe(200);
    expect(mockDaemonRequest).toHaveBeenCalledWith(
      expect.objectContaining({
        method: 'POST',
        path: '/todos/create',
        body: { slug: 'web-tui-panels' },
      }),
    );
  });
});

describe('GET /api/jobs', () => {
  it('returns 401 if unauthenticated', async () => {
    mockAuth.mockResolvedValue(null as never);

    const modulePath = '@/app/api/jobs/route' as string;
    const { GET } = await import(modulePath);
    const res = await GET();

    expect(res.status).toBe(401);
  });

  it('proxies authenticated job listing requests to the daemon', async () => {
    mockAuth.mockResolvedValue(makeSession() as never);
    mockDaemonRequest.mockResolvedValue({
      status: 200,
      headers: {},
      body: JSON.stringify([
        {
          name: 'nightly-sync',
          type: 'script',
          schedule: '0 2 * * *',
          last_run: null,
          status: 'idle',
        },
      ]),
    });

    const modulePath = '@/app/api/jobs/route' as string;
    const { GET } = await import(modulePath);
    const res = await GET();

    expect(res.status).toBe(200);
    expect(mockDaemonRequest).toHaveBeenCalledWith(
      expect.objectContaining({
        method: 'GET',
        path: '/jobs',
      }),
    );
  });
});

describe('POST /api/jobs/[name]/run', () => {
  it('returns 403 for non-admin users', async () => {
    mockAuth.mockResolvedValue(makeSession({ role: 'member' }) as never);

    const modulePath = '@/app/api/jobs/[name]/run/route' as string;
    const { POST } = await import(modulePath);
    const res = await POST(makeRequest('http://localhost:3000/api/jobs/nightly-sync/run', 'POST'), {
      params: Promise.resolve({ name: 'nightly-sync' }),
    });

    expect(res.status).toBe(403);
  });

  it('allows admins to trigger the selected job', async () => {
    mockAuth.mockResolvedValue(makeSession({ role: 'admin' }) as never);
    mockDaemonRequest.mockResolvedValue({
      status: 202,
      headers: {},
      body: JSON.stringify({ name: 'nightly-sync' }),
    });

    const modulePath = '@/app/api/jobs/[name]/run/route' as string;
    const { POST } = await import(modulePath);
    const res = await POST(makeRequest('http://localhost:3000/api/jobs/nightly-sync/run', 'POST'), {
      params: Promise.resolve({ name: 'nightly-sync' }),
    });

    expect(res.status).toBe(202);
    expect(mockDaemonRequest).toHaveBeenCalledWith(
      expect.objectContaining({
        method: 'POST',
        path: '/jobs/nightly-sync/run',
      }),
    );
  });
});

describe('POST /api/todos/[slug]/prepare', () => {
  it('returns 401 if unauthenticated', async () => {
    mockAuth.mockResolvedValue(null as never);

    const modulePath = '@/app/api/todos/[slug]/prepare/route' as string;
    const { POST } = await import(modulePath);
    const res = await POST(makeRequest('http://localhost:3000/api/todos/web-tui-panels/prepare', 'POST'), {
      params: Promise.resolve({ slug: 'web-tui-panels' }),
    });

    expect(res.status).toBe(401);
  });

  it('proxies authenticated prepare requests to the daemon', async () => {
    mockAuth.mockResolvedValue(makeSession() as never);

    const modulePath = '@/app/api/todos/[slug]/prepare/route' as string;
    const { POST } = await import(modulePath);
    const res = await POST(makeRequest('http://localhost:3000/api/todos/web-tui-panels/prepare', 'POST'), {
      params: Promise.resolve({ slug: 'web-tui-panels' }),
    });

    expect(res.status).toBe(200);
    expect(mockDaemonRequest).toHaveBeenCalledWith(
      expect.objectContaining({
        method: 'POST',
        path: '/todos/web-tui-panels/prepare',
      }),
    );
  });
});

describe('POST /api/todos/[slug]/work', () => {
  it('returns 401 if unauthenticated', async () => {
    mockAuth.mockResolvedValue(null as never);

    const modulePath = '@/app/api/todos/[slug]/work/route' as string;
    const { POST } = await import(modulePath);
    const res = await POST(makeRequest('http://localhost:3000/api/todos/web-tui-panels/work', 'POST'), {
      params: Promise.resolve({ slug: 'web-tui-panels' }),
    });

    expect(res.status).toBe(401);
  });

  it('proxies authenticated work requests to the daemon', async () => {
    mockAuth.mockResolvedValue(makeSession() as never);

    const modulePath = '@/app/api/todos/[slug]/work/route' as string;
    const { POST } = await import(modulePath);
    const res = await POST(makeRequest('http://localhost:3000/api/todos/web-tui-panels/work', 'POST'), {
      params: Promise.resolve({ slug: 'web-tui-panels' }),
    });

    expect(res.status).toBe(200);
    expect(mockDaemonRequest).toHaveBeenCalledWith(
      expect.objectContaining({
        method: 'POST',
        path: '/todos/web-tui-panels/work',
      }),
    );
  });
});

describe('POST /api/todos/[slug]/refine', () => {
  it('returns 401 if unauthenticated', async () => {
    mockAuth.mockResolvedValue(null as never);

    const modulePath = '@/app/api/todos/[slug]/refine/route' as string;
    const { POST } = await import(modulePath);
    const res = await POST(makeRequest('http://localhost:3000/api/todos/web-tui-panels/refine', 'POST'), {
      params: Promise.resolve({ slug: 'web-tui-panels' }),
    });

    expect(res.status).toBe(401);
  });

  it('proxies authenticated refine requests to the daemon', async () => {
    mockAuth.mockResolvedValue(makeSession() as never);

    const modulePath = '@/app/api/todos/[slug]/refine/route' as string;
    const { POST } = await import(modulePath);
    const res = await POST(makeRequest('http://localhost:3000/api/todos/web-tui-panels/refine', 'POST'), {
      params: Promise.resolve({ slug: 'web-tui-panels' }),
    });

    expect(res.status).toBe(200);
    expect(mockDaemonRequest).toHaveBeenCalledWith(
      expect.objectContaining({
        method: 'POST',
        path: '/todos/web-tui-panels/refine',
      }),
    );
  });
});
