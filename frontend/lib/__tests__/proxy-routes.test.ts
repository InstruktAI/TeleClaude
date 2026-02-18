/**
 * Tests for REST proxy route handlers.
 *
 * We mock the auth and daemon-client modules to test the route logic
 * in isolation: auth checks, identity headers, error passthrough, and
 * admin-only guards.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { NextRequest } from "next/server";

// Mock auth
vi.mock("@/auth", () => ({
  auth: vi.fn(),
}));

// Mock daemon-client
vi.mock("@/lib/proxy/daemon-client", () => ({
  daemonRequest: vi.fn(),
  normalizeUpstreamError: vi.fn((status: number, body: string) => {
    let message = "Upstream service error";
    try {
      const parsed = JSON.parse(body);
      if (parsed.detail) message = String(parsed.detail);
      else if (parsed.message) message = String(parsed.message);
    } catch {
      // not JSON
    }
    return { error: message, upstream_status: status };
  }),
}));

import { auth } from "@/auth";
import { daemonRequest } from "@/lib/proxy/daemon-client";

const mockAuth = vi.mocked(auth);
const mockDaemonRequest = vi.mocked(daemonRequest);

function makeSession(overrides?: Record<string, unknown>) {
  return {
    user: {
      id: "user-1",
      email: "test@example.com",
      name: "Test User",
      role: "member",
      ...overrides,
    },
    expires: "2099-01-01",
  };
}

function makeRequest(url: string, method = "GET", body?: unknown): NextRequest {
  const init: RequestInit = { method };
  if (body) {
    init.body = JSON.stringify(body);
    init.headers = { "Content-Type": "application/json" };
  }
  return new NextRequest(new URL(url, "http://localhost:3000"), init);
}

beforeEach(() => {
  vi.clearAllMocks();
  mockDaemonRequest.mockResolvedValue({
    status: 200,
    headers: {},
    body: JSON.stringify({ ok: true }),
  });
});

describe("GET /api/computers", () => {
  it("returns 401 if unauthenticated", async () => {
    mockAuth.mockResolvedValue(null);
    const { GET } = await import("@/app/api/computers/route");
    const res = await GET();
    expect(res.status).toBe(401);
  });

  it("proxies to daemon when authenticated", async () => {
    mockAuth.mockResolvedValue(makeSession() as never);
    mockDaemonRequest.mockResolvedValue({
      status: 200,
      headers: {},
      body: JSON.stringify([{ name: "local", status: "online" }]),
    });
    const { GET } = await import("@/app/api/computers/route");
    const res = await GET();
    expect(res.status).toBe(200);
    expect(mockDaemonRequest).toHaveBeenCalledWith(
      expect.objectContaining({ method: "GET", path: "/computers" }),
    );
  });
});

describe("GET /api/settings", () => {
  it("returns settings for authenticated user", async () => {
    mockAuth.mockResolvedValue(makeSession() as never);
    const { GET } = await import("@/app/api/settings/route");
    const res = await GET();
    expect(res.status).toBe(200);
  });
});

describe("PATCH /api/settings", () => {
  it("returns 403 for non-admin", async () => {
    mockAuth.mockResolvedValue(makeSession({ role: "member" }) as never);
    const { PATCH } = await import("@/app/api/settings/route");
    const req = makeRequest(
      "http://localhost:3000/api/settings",
      "PATCH",
      { tts: { enabled: true } },
    );
    const res = await PATCH(req);
    expect(res.status).toBe(403);
  });

  it("allows admin to update settings", async () => {
    mockAuth.mockResolvedValue(makeSession({ role: "admin" }) as never);
    const { PATCH } = await import("@/app/api/settings/route");
    const req = makeRequest(
      "http://localhost:3000/api/settings",
      "PATCH",
      { tts: { enabled: true } },
    );
    const res = await PATCH(req);
    expect(res.status).toBe(200);
    expect(mockDaemonRequest).toHaveBeenCalledWith(
      expect.objectContaining({
        method: "PATCH",
        path: "/settings",
        body: { tts: { enabled: true } },
      }),
    );
  });

  it("filters unknown settings keys", async () => {
    mockAuth.mockResolvedValue(makeSession({ role: "admin" }) as never);
    const { PATCH } = await import("@/app/api/settings/route");
    const req = makeRequest(
      "http://localhost:3000/api/settings",
      "PATCH",
      { tts: { enabled: true }, __dangerous: "value" },
    );
    const res = await PATCH(req);
    expect(res.status).toBe(200);
    expect(mockDaemonRequest).toHaveBeenCalledWith(
      expect.objectContaining({
        body: { tts: { enabled: true } },
      }),
    );
  });
});

describe("POST /api/sessions/[id]/agent-restart", () => {
  it("returns 403 for non-admin", async () => {
    mockAuth.mockResolvedValue(makeSession({ role: "member" }) as never);
    const { POST } = await import(
      "@/app/api/sessions/[id]/agent-restart/route"
    );
    const req = makeRequest(
      "http://localhost:3000/api/sessions/abc/agent-restart",
      "POST",
    );
    const res = await POST(req, { params: Promise.resolve({ id: "abc" }) });
    expect(res.status).toBe(403);
  });

  it("allows admin to restart agent", async () => {
    mockAuth.mockResolvedValue(makeSession({ role: "admin" }) as never);
    const { POST } = await import(
      "@/app/api/sessions/[id]/agent-restart/route"
    );
    const req = makeRequest(
      "http://localhost:3000/api/sessions/abc/agent-restart",
      "POST",
    );
    const res = await POST(req, { params: Promise.resolve({ id: "abc" }) });
    expect(res.status).toBe(200);
  });
});

describe("DELETE /api/sessions/[id]", () => {
  it("returns 401 if unauthenticated", async () => {
    mockAuth.mockResolvedValue(null);
    const { DELETE } = await import("@/app/api/sessions/[id]/route");
    const req = makeRequest(
      "http://localhost:3000/api/sessions/abc",
      "DELETE",
    );
    const res = await DELETE(req, {
      params: Promise.resolve({ id: "abc" }),
    });
    expect(res.status).toBe(401);
  });

  it("proxies DELETE to daemon for session owner", async () => {
    mockAuth.mockResolvedValue(makeSession() as never);
    // First call: GET /sessions (list), second call: DELETE
    mockDaemonRequest
      .mockResolvedValueOnce({
        status: 200,
        headers: {},
        body: JSON.stringify([{ session_id: "abc", human_email: "test@example.com" }]),
      })
      .mockResolvedValueOnce({
        status: 200,
        headers: {},
        body: JSON.stringify({ ok: true }),
      });
    const { DELETE } = await import("@/app/api/sessions/[id]/route");
    const req = makeRequest(
      "http://localhost:3000/api/sessions/abc",
      "DELETE",
    );
    const res = await DELETE(req, {
      params: Promise.resolve({ id: "abc" }),
    });
    expect(res.status).toBe(200);
    expect(mockDaemonRequest).toHaveBeenCalledWith(
      expect.objectContaining({
        method: "DELETE",
        path: "/sessions/abc",
      }),
    );
  });

  it("returns 403 when non-owner tries to DELETE another user's session", async () => {
    mockAuth.mockResolvedValue(makeSession() as never);
    mockDaemonRequest.mockResolvedValueOnce({
      status: 200,
      headers: {},
      body: JSON.stringify([{ session_id: "abc", human_email: "other@example.com" }]),
    });
    const { DELETE } = await import("@/app/api/sessions/[id]/route");
    const req = makeRequest(
      "http://localhost:3000/api/sessions/abc",
      "DELETE",
    );
    const res = await DELETE(req, {
      params: Promise.resolve({ id: "abc" }),
    });
    expect(res.status).toBe(403);
  });

  it("returns 404 when session is not in the list", async () => {
    mockAuth.mockResolvedValue(makeSession() as never);
    mockDaemonRequest.mockResolvedValueOnce({
      status: 200,
      headers: {},
      body: JSON.stringify([{ session_id: "other-id", human_email: "test@example.com" }]),
    });
    const { DELETE } = await import("@/app/api/sessions/[id]/route");
    const req = makeRequest(
      "http://localhost:3000/api/sessions/abc",
      "DELETE",
    );
    const res = await DELETE(req, {
      params: Promise.resolve({ id: "abc" }),
    });
    expect(res.status).toBe(404);
  });

  it("allows admin to DELETE any session", async () => {
    mockAuth.mockResolvedValue(makeSession({ role: "admin" }) as never);
    mockDaemonRequest
      .mockResolvedValueOnce({
        status: 200,
        headers: {},
        body: JSON.stringify([{ session_id: "abc", human_email: "other@example.com" }]),
      })
      .mockResolvedValueOnce({
        status: 200,
        headers: {},
        body: JSON.stringify({ ok: true }),
      });
    const { DELETE } = await import("@/app/api/sessions/[id]/route");
    const req = makeRequest(
      "http://localhost:3000/api/sessions/abc",
      "DELETE",
    );
    const res = await DELETE(req, {
      params: Promise.resolve({ id: "abc" }),
    });
    expect(res.status).toBe(200);
  });
});

describe("daemon error passthrough", () => {
  it("returns daemon error status and body", async () => {
    mockAuth.mockResolvedValue(makeSession() as never);
    mockDaemonRequest.mockResolvedValue({
      status: 404,
      headers: {},
      body: JSON.stringify({ detail: "Session not found" }),
    });
    const { GET } = await import("@/app/api/computers/route");
    const res = await GET();
    expect(res.status).toBe(404);
  });

  it("returns 503 when daemon is unreachable", async () => {
    mockAuth.mockResolvedValue(makeSession() as never);
    mockDaemonRequest.mockRejectedValue(new Error("ECONNREFUSED"));
    const { GET } = await import("@/app/api/computers/route");
    const res = await GET();
    expect(res.status).toBe(503);
  });
});
