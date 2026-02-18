import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { auth } from "@/auth";
import { daemonRequest, normalizeUpstreamError } from "@/lib/proxy/daemon-client";
import { buildIdentityHeaders } from "@/lib/proxy/identity-headers";
import { requireOwnership } from "@/lib/proxy/auth-guards";

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const session = await auth();
  if (!session) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const { id } = await params;

  try {
    // GET /sessions/{id} does not exist on the daemon; list all and filter by session_id
    const metaRes = await daemonRequest({
      method: "GET",
      path: "/sessions",
      headers: buildIdentityHeaders(session),
    });

    if (metaRes.status >= 400) {
      return NextResponse.json(
        normalizeUpstreamError(metaRes.status, metaRes.body),
        { status: metaRes.status },
      );
    }

    let ownerEmail: string | null = null;
    try {
      const sessions = JSON.parse(metaRes.body) as Array<{
        session_id: string;
        human_email?: string;
      }>;
      const found = sessions.find((s) => s.session_id === id);
      if (!found) {
        return NextResponse.json({ error: "Session not found" }, { status: 404 });
      }
      ownerEmail = found.human_email ?? null;
    } catch {
      // malformed response — deny
    }

    const ownershipErr = requireOwnership(session, ownerEmail);
    if (ownershipErr) return ownershipErr;

    const computer = request.nextUrl.searchParams.get("computer");
    const queryStr = computer ? `?computer=${encodeURIComponent(computer)}` : "";

    const res = await daemonRequest({
      method: "DELETE",
      path: `/sessions/${encodeURIComponent(id)}${queryStr}`,
      headers: buildIdentityHeaders(session),
    });

    if (res.status >= 400) {
      return NextResponse.json(
        normalizeUpstreamError(res.status, res.body),
        { status: res.status },
      );
    }

    return new NextResponse(res.body, {
      status: res.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch (err) {
    console.error(
      `[api/sessions/${id} DELETE] daemon unreachable:`,
      (err as Error).message,
    );
    return NextResponse.json(
      { error: "Service unavailable" },
      { status: 503 },
    );
  }
}
