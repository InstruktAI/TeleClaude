import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { auth } from "@/auth";
import { daemonRequest, normalizeUpstreamError } from "@/lib/proxy/daemon-client";
import { buildIdentityHeaders } from "@/lib/proxy/identity-headers";

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const session = await auth();
  if (!session) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const { id } = await params;
  const computer = request.nextUrl.searchParams.get("computer");
  const queryStr = computer ? `?computer=${encodeURIComponent(computer)}` : "";

  try {
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
