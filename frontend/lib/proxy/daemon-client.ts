import http from "node:http";

const SOCKET_PATH =
  process.env.DAEMON_SOCKET_PATH ?? "/tmp/teleclaude-api.sock";

interface ProxyOptions {
  method: string;
  path: string;
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

interface ProxyResponse {
  status: number;
  headers: http.IncomingHttpHeaders;
  body: string;
}

export async function daemonRequest(opts: ProxyOptions): Promise<ProxyResponse> {
  const requestId = crypto.randomUUID().slice(0, 8);
  const start = performance.now();

  return new Promise((resolve, reject) => {
    const payload = opts.body ? JSON.stringify(opts.body) : undefined;

    const req = http.request(
      {
        socketPath: SOCKET_PATH,
        method: opts.method,
        path: opts.path,
        headers: {
          "Content-Type": "application/json",
          "X-Request-Id": requestId,
          ...opts.headers,
        },
        signal: opts.signal,
      },
      (res) => {
        const chunks: Buffer[] = [];
        res.on("data", (chunk: Buffer) => chunks.push(chunk));
        res.on("end", () => {
          const elapsed = Math.round(performance.now() - start);
          console.log(
            `[proxy] ${opts.method} ${opts.path} -> ${res.statusCode} (${elapsed}ms) req=${requestId}`,
          );
          resolve({
            status: res.statusCode ?? 500,
            headers: res.headers,
            body: Buffer.concat(chunks).toString("utf-8"),
          });
        });
        res.on("error", reject);
      },
    );

    req.on("error", (err) => {
      const elapsed = Math.round(performance.now() - start);
      console.error(
        `[proxy] ${opts.method} ${opts.path} -> ERROR (${elapsed}ms) req=${requestId}: ${err.message}`,
      );
      reject(err);
    });

    if (payload) {
      req.write(payload);
    }
    req.end();
  });
}

export async function daemonStream(
  opts: ProxyOptions,
): Promise<{ status: number; headers: http.IncomingHttpHeaders; stream: http.IncomingMessage }> {
  const requestId = crypto.randomUUID().slice(0, 8);
  const start = performance.now();

  return new Promise((resolve, reject) => {
    const payload = opts.body ? JSON.stringify(opts.body) : undefined;

    const req = http.request(
      {
        socketPath: SOCKET_PATH,
        method: opts.method,
        path: opts.path,
        headers: {
          "Content-Type": "application/json",
          "X-Request-Id": requestId,
          ...opts.headers,
        },
        signal: opts.signal,
      },
      (res) => {
        const elapsed = Math.round(performance.now() - start);
        console.log(
          `[proxy-stream] ${opts.method} ${opts.path} -> ${res.statusCode} (${elapsed}ms connect) req=${requestId}`,
        );
        resolve({
          status: res.statusCode ?? 500,
          headers: res.headers,
          stream: res,
        });
      },
    );

    req.on("error", (err) => {
      const elapsed = Math.round(performance.now() - start);
      console.error(
        `[proxy-stream] ${opts.method} ${opts.path} -> ERROR (${elapsed}ms) req=${requestId}: ${err.message}`,
      );
      reject(err);
    });

    if (payload) {
      req.write(payload);
    }
    req.end();
  });
}

export function normalizeUpstreamError(
  status: number,
  body: string,
): { error: string; upstream_status: number } {
  let message = "Upstream service error";
  try {
    const parsed = JSON.parse(body);
    if (parsed.detail) message = String(parsed.detail);
    else if (parsed.message) message = String(parsed.message);
  } catch {
    // body is not JSON
  }
  return { error: message, upstream_status: status };
}
