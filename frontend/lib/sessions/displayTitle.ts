/**
 * Frontend mirror of UiAdapter.headless_prefix / display_title in Python.
 *
 * Every UI surface that renders a session title must apply the universal
 * headless marker so users see at a glance whether the session is unattended
 * and may be adoptable. Define the prefix string and the condition once here.
 *
 * Note: the wire field is named ``status`` (SessionDTO.status). Core Python
 * names the same field ``lifecycle_status``; the API serializer maps it to
 * ``status`` on the way out. Read ``status`` here — that is the value
 * actually delivered by the API.
 */

type SessionTitleFields = {
  title?: string | null;
  status?: string | null;
};

export function headlessPrefix(session: SessionTitleFields): string {
  return session.status === "headless" ? "[HEADLESS] " : "";
}

export function displayTitle(session: SessionTitleFields, fallback: string = "Untitled"): string {
  const body = (session.title && session.title.trim()) || fallback;
  return `${headlessPrefix(session)}${body}`;
}
