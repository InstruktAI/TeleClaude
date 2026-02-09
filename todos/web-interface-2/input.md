# Web Interface — Phase 2: Next.js Scaffold & Auth

## Context

This is phase 2 of the web-interface breakdown. Depends on phase 1
(daemon SSE plumbing). See the parent todo's `input.md` for full context.

## Intended Outcome

Bootstrap the Next.js 15 application with NextAuth v5 email OTP authentication
against the people config, Brevo SMTP transport, and basic project structure.

## What to Build

1. **Next.js 15 project** — App Router, standalone output, shadcn/ui, Tailwind.
2. **Drizzle ORM** — SQLite for localhost, user/session/verificationToken tables.
3. **NextAuth v5** — Email provider with Brevo SMTP, 6-digit OTP, 3-minute expiry.
4. **People config verification** — signIn callback rejects emails not in people config.
5. **Role enrichment** — session callback adds role from config.
6. **Login page** — people dropdown → email resolution → OTP flow → code entry.

## Key Architectural Notes

- User table is a cache of verification state; source of truth is people config.
- No self-registration — unknown emails rejected.
- SQLite for NextAuth storage (localhost deployment).
- 30-day cookie lifetime.
- Login page fetches people list from daemon `GET /api/people`.

## Verification

- Full login flow: select person → OTP email sent → enter code → session created.
- Unknown email rejected.
- Session contains person name and role.
