/**
 * HTTP client for the TeleClaude daemon API over Unix socket.
 *
 * Reuses the socket transport pattern from frontend/lib/proxy/daemon-client.ts
 * but provides typed, domain-specific methods.
 */

import http from "node:http";

import type {
  AgentAvailabilityInfo,
  ComputerInfo,
  CreateSessionRequest,
  CreateSessionResponse,
  HealthResponse,
  PersonInfo,
  ProjectInfo,
  ProjectWithTodosInfo,
  SessionInfo,
  SessionMessagesResponse,
  Settings,
  SettingsPatch,
  StatusResponse,
  TodoInfo,
} from "./types.js";

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

const DEFAULT_SOCKET_PATH = "/tmp/teleclaude-api.sock";
const DEFAULT_TIMEOUT_MS = 5_000;
const SESSION_CREATE_TIMEOUT_MS = 30_000;

// ---------------------------------------------------------------------------
// Error
// ---------------------------------------------------------------------------

export class APIError extends Error {
  readonly statusCode: number | undefined;
  readonly detail: string;

  constructor(message: string, statusCode?: number, detail?: string) {
    super(message);
    this.name = "APIError";
    this.statusCode = statusCode;
    this.detail = detail ?? message;
  }
}

// ---------------------------------------------------------------------------
// Low-level request helper
// ---------------------------------------------------------------------------

interface RequestOptions {
  method: string;
  path: string;
  body?: unknown;
  timeout?: number;
  params?: Record<string, string>;
}

interface RawResponse {
  status: number;
  headers: http.IncomingHttpHeaders;
  body: string;
}

function buildQueryString(params: Record<string, string>): string {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== null);
  if (entries.length === 0) return "";
  return "?" + entries.map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join("&");
}

function rawRequest(socketPath: string, opts: RequestOptions): Promise<RawResponse> {
  const qs = opts.params ? buildQueryString(opts.params) : "";
  const fullPath = opts.path + qs;
  const payload = opts.body !== undefined ? JSON.stringify(opts.body) : undefined;
  const timeout = opts.timeout ?? DEFAULT_TIMEOUT_MS;

  return new Promise<RawResponse>((resolve, reject) => {
    const req = http.request(
      {
        socketPath,
        method: opts.method,
        path: fullPath,
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        timeout,
      },
      (res) => {
        const chunks: Buffer[] = [];
        res.on("data", (chunk: Buffer) => chunks.push(chunk));
        res.on("end", () => {
          resolve({
            status: res.statusCode ?? 500,
            headers: res.headers,
            body: Buffer.concat(chunks).toString("utf-8"),
          });
        });
        res.on("error", reject);
      },
    );

    req.on("timeout", () => {
      req.destroy();
      reject(new APIError("Request timed out", undefined, "Request timed out"));
    });

    req.on("error", (err) => {
      reject(
        new APIError(
          `Connection error: ${err.message}`,
          undefined,
          err.message,
        ),
      );
    });

    if (payload) {
      req.write(payload);
    }
    req.end();
  });
}

// ---------------------------------------------------------------------------
// Parse helpers
// ---------------------------------------------------------------------------

function parseJsonBody<T>(raw: RawResponse): T {
  if (raw.status >= 400) {
    let detail: string | undefined;
    try {
      const parsed = JSON.parse(raw.body);
      detail = parsed.detail ?? parsed.message ?? raw.body;
    } catch {
      detail = raw.body;
    }
    throw new APIError(
      `API error ${raw.status}: ${detail}`,
      raw.status,
      detail,
    );
  }
  try {
    return JSON.parse(raw.body) as T;
  } catch {
    throw new APIError("Invalid JSON response", raw.status, raw.body);
  }
}

function assertOk(raw: RawResponse): void {
  if (raw.status >= 400) {
    let detail: string | undefined;
    try {
      const parsed = JSON.parse(raw.body);
      detail = parsed.detail ?? parsed.message;
    } catch {
      detail = raw.body;
    }
    throw new APIError(
      `API error ${raw.status}: ${detail}`,
      raw.status,
      detail,
    );
  }
}

// ---------------------------------------------------------------------------
// Client
// ---------------------------------------------------------------------------

export interface TelecAPIClientOptions {
  socketPath?: string;
}

export class TelecAPIClient {
  private readonly socketPath: string;

  constructor(opts?: TelecAPIClientOptions) {
    this.socketPath =
      opts?.socketPath ??
      process.env.DAEMON_SOCKET_PATH ??
      DEFAULT_SOCKET_PATH;
  }

  // ---- generic request plumbing -----------------------------------------

  private async request<T>(opts: RequestOptions): Promise<T> {
    const raw = await rawRequest(this.socketPath, opts);
    return parseJsonBody<T>(raw);
  }

  private async requestOk(opts: RequestOptions): Promise<boolean> {
    const raw = await rawRequest(this.socketPath, opts);
    assertOk(raw);
    return true;
  }

  // ---- health -----------------------------------------------------------

  async health(): Promise<HealthResponse> {
    return this.request<HealthResponse>({ method: "GET", path: "/health" });
  }

  // ---- sessions ---------------------------------------------------------

  async getSessions(computer?: string): Promise<SessionInfo[]> {
    const params: Record<string, string> = {};
    if (computer) params.computer = computer;
    return this.request<SessionInfo[]>({
      method: "GET",
      path: "/sessions",
      params,
    });
  }

  async createSession(req: CreateSessionRequest): Promise<CreateSessionResponse> {
    return this.request<CreateSessionResponse>({
      method: "POST",
      path: "/sessions",
      body: req,
      timeout: SESSION_CREATE_TIMEOUT_MS,
    });
  }

  async endSession(sessionId: string, computer: string): Promise<boolean> {
    return this.requestOk({
      method: "DELETE",
      path: `/sessions/${encodeURIComponent(sessionId)}`,
      params: { computer },
    });
  }

  async sendMessage(sessionId: string, computer: string, message: string): Promise<boolean> {
    return this.requestOk({
      method: "POST",
      path: `/sessions/${encodeURIComponent(sessionId)}/message`,
      params: { computer },
      body: { message },
    });
  }

  async sendKeys(
    sessionId: string,
    computer: string,
    key: string,
    count?: number,
  ): Promise<boolean> {
    const body: Record<string, unknown> = { key };
    if (count !== undefined) body.count = count;
    return this.requestOk({
      method: "POST",
      path: `/sessions/${encodeURIComponent(sessionId)}/keys`,
      params: { computer },
      body,
    });
  }

  async sendVoice(
    sessionId: string,
    computer: string,
    filePath: string,
    opts?: { duration?: number; messageId?: string; messageThreadId?: number },
  ): Promise<boolean> {
    return this.requestOk({
      method: "POST",
      path: `/sessions/${encodeURIComponent(sessionId)}/voice`,
      params: { computer },
      body: {
        file_path: filePath,
        duration: opts?.duration,
        message_id: opts?.messageId,
        message_thread_id: opts?.messageThreadId,
      },
    });
  }

  async sendFile(
    sessionId: string,
    computer: string,
    filePath: string,
    filename: string,
    opts?: { caption?: string; fileSize?: number },
  ): Promise<boolean> {
    return this.requestOk({
      method: "POST",
      path: `/sessions/${encodeURIComponent(sessionId)}/file`,
      params: { computer },
      body: {
        file_path: filePath,
        filename,
        caption: opts?.caption,
        file_size: opts?.fileSize ?? 0,
      },
    });
  }

  async agentRestart(sessionId: string): Promise<StatusResponse> {
    return this.request<StatusResponse>({
      method: "POST",
      path: `/sessions/${encodeURIComponent(sessionId)}/agent-restart`,
    });
  }

  async reviveSession(sessionId: string): Promise<CreateSessionResponse> {
    return this.request<CreateSessionResponse>({
      method: "POST",
      path: `/sessions/${encodeURIComponent(sessionId)}/revive`,
      timeout: SESSION_CREATE_TIMEOUT_MS,
    });
  }

  async getSessionMessages(
    sessionId: string,
    opts?: { since?: string; includeTools?: boolean; includeThinking?: boolean },
  ): Promise<SessionMessagesResponse> {
    const params: Record<string, string> = {};
    if (opts?.since) params.since = opts.since;
    if (opts?.includeTools) params.include_tools = "true";
    if (opts?.includeThinking) params.include_thinking = "true";
    return this.request<SessionMessagesResponse>({
      method: "GET",
      path: `/sessions/${encodeURIComponent(sessionId)}/messages`,
      params,
    });
  }

  // ---- computers --------------------------------------------------------

  async getComputers(): Promise<ComputerInfo[]> {
    return this.request<ComputerInfo[]>({ method: "GET", path: "/computers" });
  }

  // ---- projects ---------------------------------------------------------

  async getProjects(computer?: string): Promise<ProjectInfo[]> {
    const params: Record<string, string> = {};
    if (computer) params.computer = computer;
    return this.request<ProjectInfo[]>({
      method: "GET",
      path: "/projects",
      params,
    });
  }

  // ---- todos ------------------------------------------------------------

  async getTodos(opts?: { project?: string; computer?: string }): Promise<TodoInfo[]> {
    const params: Record<string, string> = {};
    if (opts?.project) params.project = opts.project;
    if (opts?.computer) params.computer = opts.computer;
    return this.request<TodoInfo[]>({
      method: "GET",
      path: "/todos",
      params,
    });
  }

  /** Convenience: fetch projects then enrich each with its todos. */
  async getProjectsWithTodos(): Promise<ProjectWithTodosInfo[]> {
    const [projects, todos] = await Promise.all([
      this.getProjects(),
      this.getTodos(),
    ]);
    const todoMap = new Map<string, TodoInfo[]>();
    for (const todo of todos) {
      if (!todo.computer || !todo.project_path) continue;
      const key = `${todo.computer}:${todo.project_path}`;
      const list = todoMap.get(key) ?? [];
      list.push(todo);
      todoMap.set(key, list);
    }
    return projects.map((p) => ({
      ...p,
      todos: todoMap.get(`${p.computer}:${p.path}`) ?? [],
    }));
  }

  // ---- agents -----------------------------------------------------------

  async getAgentAvailability(): Promise<Record<string, AgentAvailabilityInfo>> {
    return this.request<Record<string, AgentAvailabilityInfo>>({
      method: "GET",
      path: "/agents/availability",
    });
  }

  // ---- people -----------------------------------------------------------

  async getPeople(): Promise<PersonInfo[]> {
    return this.request<PersonInfo[]>({ method: "GET", path: "/api/people" });
  }

  // ---- settings ---------------------------------------------------------

  async getSettings(): Promise<Settings> {
    return this.request<Settings>({ method: "GET", path: "/settings" });
  }

  async patchSettings(patch: SettingsPatch): Promise<Settings> {
    return this.request<Settings>({
      method: "PATCH",
      path: "/settings",
      body: patch,
    });
  }
}
