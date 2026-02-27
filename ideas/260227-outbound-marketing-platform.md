# Outbound Marketing & Publication Platform

TeleClaude currently handles ingress (customers, notifications, adapters). The platform
needs egress — the ability to speak to the world, not just listen.

## Capabilities

- **Blog publication**: automated or assisted publishing from conversations and work.
- **Social media**: cross-platform posting (Twitter/X, LinkedIn, Mastodon, YouTube).
- **Campaigning**: scheduled content, audience targeting, engagement tracking.
- **PR**: press releases, announcement distribution.
- **Newsletter**: email-based content delivery.

## Why this belongs in TeleClaude

The same platform that orchestrates agent work and manages context can orchestrate
outbound communication. The content is already being produced — insights, discoveries,
architectural decisions. The missing piece is the publication pipeline.

This is not a marketing tool bolted on. It is the natural exhale of a system that
already breathes.

## Phasing

1. Public website with blog (todo: public-website-blog) — the anchor.
2. Session-to-blog pipeline — automated content from conversations.
3. Social media adapters — outbound equivalents of the existing inbound adapters.
4. Campaigning and scheduling — strategic content delivery.

## Dependencies

- Public website (todo: public-website-blog).
- Adapter architecture extension for outbound.
