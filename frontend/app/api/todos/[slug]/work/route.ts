import { NextResponse } from 'next/server';
import { auth } from '@/auth';
import { daemonRequest, normalizeUpstreamError } from '@/lib/proxy/daemon-client';
import { buildIdentityHeaders } from '@/lib/proxy/identity-headers';

export async function POST(request: Request, { params }: { params: Promise<{ slug: string }> }) {
  const session = await auth();
  if (!session) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const { slug } = await params;
  const { project_path: projectPath } = (await request.json().catch(() => ({}))) as { project_path?: string };

  try {
    const res = await daemonRequest({
      method: 'POST',
      path: '/todos/work',
      body: { slug, cwd: projectPath },
      headers: buildIdentityHeaders(session),
    });

    if (res.status >= 400) {
      return NextResponse.json(normalizeUpstreamError(res.status, res.body), { status: res.status });
    }

    return new NextResponse(res.body, {
      status: res.status,
      headers: { 'Content-Type': 'application/json' },
    });
  } catch (err) {
    console.error(`[api/todos/${slug}/work POST] daemon unreachable:`, (err as Error).message);
    return NextResponse.json({ error: 'Service unavailable' }, { status: 503 });
  }
}
