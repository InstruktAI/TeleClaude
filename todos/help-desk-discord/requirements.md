# help-desk-discord — Requirements

## Goal

Implement a Discord adapter for TeleClaude that maps Discord users to "Customer" identities and routes their messages to the Help Desk lobby.

## Success Criteria

1.  **Ingress**: A message from a Discord user (who is not the bot) creates a jailed session in the `help-desk` project.
2.  **Identity Mapping**: Discord Snowflake IDs are mapped to `IdentityContext` with `Role: Customer`.
3.  **Threading**: Each session is mapped to a dedicated **Forum Thread** (Type 15) if the adapter is configured for a Forum Channel.
4.  **Egress**: Agent responses from the TeleClaude session are delivered back to the same Discord thread/DM.
5.  **Multi-Room Support**: The adapter correctly handles multiple concurrent customer sessions in distinct forum threads.

## Constraints

- Must use `discord.py` for the implementation.
- Must follow the `BaseAdapter` and `UiAdapter` contracts.
- Must NOT use "self-bot" tokens; only official Bot tokens are allowed.
- Must require `MESSAGE_CONTENT` intent.

## Research References

- `docs/third-party/discord/bot-api.md` (Forum Channels, Snowflakes).
