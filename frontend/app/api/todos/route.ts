import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { auth } from "@/auth";
import { daemonRequest, normalizeUpstreamError } from "@/lib/proxy/daemon-client";
import { buildIdentityHeaders } from "@/lib/proxy/identity-headers";

export async function GET(request: NextRequest) {
  const session = await auth();
  if (!session) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const searchParams = request.nextUrl.searchParams;
  const qs = new URLSearchParams();
  for (const key of ["project", "computer"]) {
    const val = searchParams.get(key);
    if (val) qs.set(key, val);
  }
  const queryStr = qs.toString() ? `?${qs.toString()}` : "";

  try {
    const res = await daemonRequest({
      method: "GET",
      path: `/todos${queryStr}`,
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
    console.error("[api/todos GET] daemon unreachable:", (err as Error).message);
    return NextResponse.json(
      { error: "Service unavailable" },
      { status: 503 },
    );
  }
}
