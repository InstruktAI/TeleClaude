# A2A Agent Card

## What it is

The Agent Card is the discovery mechanism for A2A agents. Published at `/.well-known/agent-card.json`, it describes an agent's identity, capabilities, skills, and authentication requirements.

## Schema

```json
{
  "id": "https://example.com/agent/travel-planner",
  "name": "Travel Planner",
  "description": "Plans trips with flights, hotels, and activities",
  "provider": {
    "organization": "Example Corp",
    "url": "https://example.com"
  },
  "version": "1.0.0",
  "capabilities": {
    "streaming": true,
    "pushNotifications": true,
    "stateTransitionHistory": true
  },
  "skills": [
    {
      "id": "flight-search",
      "name": "Flight Search",
      "description": "Search and book flights",
      "tags": ["travel", "flights"],
      "examples": ["Find flights from NYC to London next week"]
    }
  ],
  "interfaces": [
    {
      "protocol": "a2a",
      "url": "https://example.com/a2a/v1"
    }
  ],
  "securitySchemes": {
    "oauth2": {
      "type": "oauth2",
      "flows": {
        "authorizationCode": {
          "authorizationUrl": "https://example.com/oauth/authorize",
          "tokenUrl": "https://example.com/oauth/token",
          "scopes": {
            "agent:read": "Read agent data",
            "agent:write": "Execute tasks"
          }
        }
      }
    }
  },
  "security": ["oauth2"],
  "signature": {
    "algorithm": "RS256",
    "keyId": "key-001",
    "value": "base64-signature..."
  }
}
```

## Field Reference

| Field             | Type               | Required | Description                                |
| ----------------- | ------------------ | -------- | ------------------------------------------ |
| `id`              | string             | yes      | Unique agent identifier (URI)              |
| `name`            | string             | yes      | Human-readable name                        |
| `description`     | string             | yes      | What the agent does                        |
| `provider`        | AgentProvider      | no       | Organization details                       |
| `version`         | string             | no       | Implementation version                     |
| `capabilities`    | AgentCapabilities  | no       | Feature flags (streaming, push, history)   |
| `skills`          | AgentSkill[]       | no       | Available functions with examples          |
| `interfaces`      | AgentInterface[]   | yes      | Protocol bindings (URLs)                   |
| `securitySchemes` | map                | no       | Auth schemes (API Key, OAuth2, OIDC, mTLS) |
| `security`        | string[]           | no       | Required schemes for access                |
| `extensions`      | AgentExtension[]   | no       | Protocol extensions                        |
| `signature`       | AgentCardSignature | no       | Card authenticity verification (v0.3+)     |

## Discovery Flow

1. Client GETs `https://{domain}/.well-known/agent-card.json`
2. Public card may indicate `supportsExtendedAgentCard: true`
3. If extended card supported, client authenticates and GETs extended card via `GetExtendedAgentCard` method
4. Client inspects `capabilities`, `skills`, and `security` to decide how to interact

## Authentication Schemes

A2A supports enterprise-grade auth with OpenAPI parity:

- **API Key** — simple token-based
- **HTTP Auth** — Basic/Bearer
- **OAuth 2.0** — authorization code, client credentials, etc.
- **OpenID Connect** — identity federation
- **mTLS** — mutual certificate authentication

## Sources

- https://a2a-protocol.org/latest/specification
- https://a2a-protocol.org/latest/definitions
- /websites/a2a-protocol
- /google/a2a
