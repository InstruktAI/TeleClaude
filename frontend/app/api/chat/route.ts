import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { auth } from "@/auth";
import { daemonStream } from "@/lib/proxy/daemon-client";
import { buildIdentityHeaders } from "@/lib/proxy/identity-headers";

/**
 * Extract text content from an AI SDK UIMessage parts array or content array.
 */
function partsToText(parts: unknown): string {
  if (!Array.isArray(parts)) return "";
  return parts
    .map((p: unknown) => {
      if (typeof p === "string") return p;
      if (typeof p === "object" && p !== null) {
        const part = p as { type?: string; text?: string; content?: string };
        return part.text ?? part.content ?? "";
      }
      return "";
    })
    .filter(Boolean)
    .join("\n\n");
}

/**
 * Transform AI SDK request body to daemon ChatStreamRequest format.
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
      (msg: { role?: string; content?: unknown; parts?: unknown }) => {
        let content = "";
        if (typeof msg.content === "string") {
          content = msg.content;
        } else if (Array.isArray(msg.content)) {
          content = partsToText(msg.content);
        } else if (Array.isArray(msg.parts)) {
          content = partsToText(msg.parts);
        }
        return {
          role: msg.role ?? "user",
          content,
        };
      },
    );
  }

  return result;
}

function toUint8Array(chunk: unknown): Uint8Array {
  if (chunk instanceof Uint8Array) {
    return chunk;
  }
  if (Buffer.isBuffer(chunk)) {
    return new Uint8Array(chunk);
  }
  return new TextEncoder().encode(String(chunk ?? ""));
}

function nodeStreamToWeb(
  stream: AsyncIterable<unknown> & { destroy?: (error?: Error) => void },
): ReadableStream<Uint8Array> {
  const iterator = stream[Symbol.asyncIterator]();

  return new ReadableStream<Uint8Array>({
    async pull(controller) {
      const { done, value } = await iterator.next();
      if (done) {
        controller.close();
        return;
      }
      controller.enqueue(toUint8Array(value));
    },
    async cancel(reason) {
      if (typeof stream.destroy === "function") {
        stream.destroy(reason instanceof Error ? reason : undefined);
      }
      if (typeof iterator.return === "function") {
        await iterator.return();
      }
    },
  });
}

export async function POST(request: NextRequest) {
  const session = await auth();
  if (!session) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  let body: Record<string, unknown>;
  try {
    body = await request.json();
  } catch {
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

    return new NextResponse(nodeStreamToWeb(res.stream), {
      status: res.status,
      headers: {
        "Content-Type": "text/event-stream",
        "x-vercel-ai-ui-message-stream": "v1",
        "Cache-Control": "no-cache",
        Connection: "keep-alive",
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

