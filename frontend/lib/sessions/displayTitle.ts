/**
 * Frontend mirror of UiAdapter.headless_prefix / display_title in Python.
 *
 * Every UI surface that renders a session title must apply the universal
 * headless marker so users see at a glance whether the session is unattended
 * and may be adoptable. Define the prefix string and the condition once here.
 */

type SessionTitleFields = {
  title?: string | null;
  lifecycle_status?: string | null;
  session_id?: string;
};

export function headlessPrefix(session: SessionTitleFields): string {
  return session.lifecycle_status === "headless" ? "[HEADLESS] " : "";
}

export function displayTitle(session: SessionTitleFields, fallback?: string): string {
  const body =
    (session.title && session.title.trim()) ||
    fallback ||
    (session.session_id ? session.session_id.slice(0, 8) : "Untitled");
  return `${headlessPrefix(session)}${body}`;
}
