/**
 * Custom server for Next.js + WebSocket support.
 *
 * Next.js App Router doesn't support WebSocket upgrades in route handlers.
 * This custom server intercepts upgrade requests on /api/ws, validates auth
 * via session cookies, and bridges to the daemon WebSocket.
 *
 * Usage:
 *   Development: tsx watch server.ts
 *   Production:  node server.js (after next build)
 */

import { createServer } from "node:http";
import { parse } from "node:url";
import next from "next";
import { WebSocketServer, type WebSocket } from "ws";
import { bridgeConnection } from "./lib/proxy/ws-bridge.js";

const dev = process.env.NODE_ENV !== "production";
const hostname = process.env.HOSTNAME ?? "0.0.0.0";
const port = parseInt(process.env.PORT ?? "3000", 10);

const app = next({ dev, hostname, port });
const handle = app.getRequestHandler();

app.prepare().then(() => {
  const server = createServer((req, res) => {
    const parsedUrl = parse(req.url!, true);
    handle(req, res, parsedUrl);
  });

  const wss = new WebSocketServer({ noServer: true });

  server.on("upgrade", async (req, socket, head) => {
    const { pathname } = parse(req.url ?? "", true);

    if (pathname !== "/api/ws") {
      socket.destroy();
      return;
    }

    // Validate auth by checking session cookie
    // NextAuth stores session in a cookie — extract and validate it
    const cookieHeader = req.headers.cookie ?? "";
    const extracted = extractSessionToken(cookieHeader);

    if (!extracted) {
      socket.write("HTTP/1.1 401 Unauthorized\r\n\r\n");
      socket.destroy();
      return;
    }

    // Validate the session token by calling the NextAuth session API
    const identity = await validateSession(extracted.token, extracted.cookieName, req.headers.host);
    if (!identity) {
      socket.write("HTTP/1.1 401 Unauthorized\r\n\r\n");
      socket.destroy();
      return;
    }

    wss.handleUpgrade(req, socket, head, (ws: WebSocket) => {
      wss.emit("connection", ws, req);
      bridgeConnection(ws, identity);
    });
  });

  server.listen(port, hostname, () => {
    console.log(`> Ready on http://${hostname}:${port}`);
  });
});

function extractSessionToken(
  cookieHeader: string,
): { token: string; cookieName: string } | null {
  const cookies = cookieHeader.split(";").reduce(
    (acc, cookie) => {
      const [key, ...valParts] = cookie.trim().split("=");
      if (key) acc[key] = valParts.join("=");
      return acc;
    },
    {} as Record<string, string>,
  );

  if (cookies["__Secure-authjs.session-token"]) {
    return {
      token: cookies["__Secure-authjs.session-token"],
      cookieName: "__Secure-authjs.session-token",
    };
  }
  if (cookies["authjs.session-token"]) {
    return {
      token: cookies["authjs.session-token"],
      cookieName: "authjs.session-token",
    };
  }
  return null;
}

async function validateSession(
  sessionToken: string,
  cookieName: string,
  host: string | undefined,
): Promise<{ email: string; name?: string; role?: string } | null> {
  try {
    // Call the NextAuth session endpoint to validate the token
    const protocol = process.env.NODE_ENV === "production" ? "https" : "http";
    const baseUrl = `${protocol}://${host ?? `localhost:${port}`}`;
    const res = await fetch(`${baseUrl}/api/auth/session`, {
      headers: {
        cookie: `${cookieName}=${sessionToken}`,
      },
      signal: AbortSignal.timeout(5000),
    });

    if (!res.ok) return null;

    const session = (await res.json()) as {
      user?: { email?: string; name?: string; role?: string };
    };
    if (!session.user?.email) return null;

    return {
      email: session.user.email,
      name: session.user.name,
      role: session.user.role,
    };
  } catch {
    return null;
  }
}
