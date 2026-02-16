import type { Session } from "next-auth";

export function buildIdentityHeaders(
  session: Session | null,
): Record<string, string> {
  if (!session?.user?.email) return {};

  const headers: Record<string, string> = {
    "X-Web-User-Email": session.user.email,
  };

  if (session.user.name) {
    headers["X-Web-User-Name"] = session.user.name;
  }
  if ("role" in session.user && session.user.role) {
    headers["X-Web-User-Role"] = session.user.role as string;
  }
  return headers;
}
