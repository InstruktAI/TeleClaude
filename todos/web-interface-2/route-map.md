# Web Interface Phase 2 Route Map

Architecture reference: `docs/project/design/architecture/web-api-facade.md`

| Public Route (Next.js)            | Daemon Target                                | Mode    | Owner           | Notes                                   |
| --------------------------------- | -------------------------------------------- | ------- | --------------- | --------------------------------------- |
| `POST /api/chat`                  | `POST /api/chat/stream`                      | `proxy` | web-interface-2 | Streaming passthrough                   |
| `GET /api/people`                 | `GET /api/people`                            | `proxy` | web-interface-2 | Identity directory                      |
| `GET /api/sessions`               | `GET /sessions`                              | `proxy` | web-interface-2 | Session list                            |
| `POST /api/sessions`              | `POST /sessions`                             | `proxy` | web-interface-2 | Session create                          |
| `POST /api/sessions/:id/messages` | `POST /sessions/{id}/messages` or equivalent | `proxy` | web-interface-2 | Final daemon target to confirm in build |
