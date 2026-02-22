import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { auth } from "@/auth";
import { daemonStream } from "@/lib/proxy/daemon-client";
import { buildIdentityHeaders } from "@/lib/proxy/identity-headers";

/**
 * Extract text content from an AI SDK UIMessage parts array.
 */
function partsToText(parts: unknown): string {
  if (!Array.isArray(parts)) return "";
  return parts
    .filter(
      (p: unknown): p is { type: string; text: string } =>
        typeof p === "object" && p !== null && (p as { type: string }).type === "text",
    )
    .map((p) => p.text)
    .join("\n\n");
}

/**
 * Transform AI SDK request body to daemon ChatStreamRequest format.
 *
 * AI SDK sends: { sessionId, messages: UIMessage[], callSettings, system, ... }
 * Daemon expects: { sessionId, messages?: [{role, content}], since_timestamp? }
 */
function toDaemonBody(body: Record<string, unknown>): Record<string, unknown> {
  const result: Record<string, unknown> = {
    sessionId: body.sessionId,
  };

  if (body.since_timestamp) {
    result.since_timestamp = body.since_timestamp;
  }

  if (Array.isArray(body.messages) && body.messages.length > 0) {
    result.messages = body.messages.map(
      (msg: { role?: string; content?: string; parts?: unknown }) => ({
        role: msg.role ?? "user",
        content: msg.content ?? partsToText(msg.parts),
      }),
    );
  }

  return result;
}

export async function POST(request: NextRequest) {
  const session = await auth();
  if (!session) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  let body: Record<string, unknown>;
  try {
    body = await request.json();
  } catch (err) {
    return NextResponse.json(
      { error: "Invalid JSON in request body" },
      { status: 400 },
    );
  }

  try {
    const res = await daemonStream({
      method: "POST",
      path: "/api/chat/stream",
      body: toDaemonBody(body),
      headers: buildIdentityHeaders(session),
    });

    if (res.status >= 400) {
      const chunks: Buffer[] = [];
      for await (const chunk of res.stream) {
        chunks.push(chunk);
      }
      const errorBody = Buffer.concat(chunks).toString("utf-8");
      let message = "Upstream service error";
      try {
        const parsed = JSON.parse(errorBody);
        if (parsed.detail) message = String(parsed.detail);
        else if (parsed.message) message = String(parsed.message);
      } catch {
        // body is not JSON
      }
      return NextResponse.json(
        { error: message, upstream_status: res.status },
        { status: res.status },
      );
    }

    return new NextResponse(res.stream as unknown as ReadableStream, {
      status: res.status,
      headers: {
        "Content-Type":
          res.headers["content-type"] ?? "application/json",
      },
    });
  } catch (err) {
    console.error("[api/chat POST] daemon unreachable:", (err as Error).message);
    return NextResponse.json(
      { error: "Service unavailable" },
      { status: 503 },
    );
  }
}
