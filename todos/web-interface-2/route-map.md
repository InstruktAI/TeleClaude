# Web Interface Phase 2 Route Map

Architecture reference: `docs/project/design/architecture/web-api-facade.md`

| Public Route (Next.js)            | Daemon Target                 | Mode     | Owner           | Notes                                                      |
| --------------------------------- | ----------------------------- | -------- | --------------- | ---------------------------------------------------------- |
| `POST /api/chat`                  | `POST /api/chat/stream`       | `proxy`  | web-interface-2 | Passthrough; daemon endpoint pending (web-interface-1 dep) |
| `GET /api/people`                 | n/a (reads teleclaude.yml)    | `native` | web-interface-2 | Resolved from people config with 60s cache TTL             |
| `GET /api/sessions`               | `GET /sessions`               | `proxy`  | web-interface-2 | Supports `?computer=` filter                               |
| `POST /api/sessions`              | `POST /sessions`              | `proxy`  | web-interface-2 | Injects human_email and human_role from auth session       |
| `POST /api/sessions/:id/messages` | `POST /sessions/{id}/message` | `proxy`  | web-interface-2 | Fire-and-forget message send                               |

All proxy routes include:

- Auth check (401 if no session)
- Request ID generation and proxy logging
- Identity headers (`X-Web-User-Email`, `X-Web-User-Name`, `X-Web-User-Role`)
- Upstream error normalization to `{ error, upstream_status }`
- 503 on daemon unreachable
