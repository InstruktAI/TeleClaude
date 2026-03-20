# TeleClaude Configuration Surface

## Global Config

Model: `GlobalConfig`

| Field | Type | Description |
|-------|------|-------------|
| `business` | BusinessConfig |  |
| `channel_subscriptions` | array | Channel Subscriptions |
| `deployment` | DeploymentConfig |  |
| `description` | string | null | Description |
| `event_domains` | DomainsConfig | null |  |
| `git` | GitConfig |  |
| `hooks` | HooksConfig |  |
| `integrator` | IntegratorConfig |  |
| `interests` | array | Interests |
| `jobs` | object | Jobs |
| `people` | array | People |
| `project_name` | string | null | Project Name |
| `subscriptions` | array | Subscriptions |

### Global Config — Nested Types

#### AutonomyLevel

#### AutonomyMatrix

| Field | Type | Description |
|-------|------|-------------|
| `by_cartridge` | object | By Cartridge |
| `by_domain` | object | By Domain |
| `by_event_type` | object | By Event Type |
| `global_default` | AutonomyLevel |  |

#### BusinessConfig

| Field | Type | Description |
|-------|------|-------------|
| `domains` | object | Domains |

#### ChannelSubscription

| Field | Type | Description |
|-------|------|-------------|
| `channel` | string | Channel |
| `filter` | object | null | Filter |
| `target` | object | Target |

#### DeploymentConfig

| Field | Type | Description |
|-------|------|-------------|
| `channel` | string | Channel |
| `pinned_minor` | string | Pinned Minor |

#### DomainConfig

| Field | Type | Description |
|-------|------|-------------|
| `autonomy` | AutonomyMatrix |  |
| `cartridge_path` | string | null | Cartridge Path |
| `enabled` | boolean | Enabled |
| `guardian` | DomainGuardianConfig |  |
| `name` | string | Name |

#### DomainGuardianConfig

| Field | Type | Description |
|-------|------|-------------|
| `agent` | string | Agent |
| `enabled` | boolean | Enabled |
| `evaluation_prompt` | string | null | Evaluation Prompt |
| `mode` | string | Mode |

#### DomainsConfig

| Field | Type | Description |
|-------|------|-------------|
| `base_path` | string | Base Path |
| `domains` | object | Domains |
| `enabled` | boolean | Enabled |
| `helpdesk_path` | string | Helpdesk Path |
| `personal_base_path` | string | Personal Base Path |

#### GitConfig

| Field | Type | Description |
|-------|------|-------------|
| `checkout_root` | string | null | Checkout Root |

#### HooksConfig

| Field | Type | Description |
|-------|------|-------------|
| `inbound` | object | Inbound |
| `subscriptions` | array | Subscriptions |

#### InboundSourceConfig

| Field | Type | Description |
|-------|------|-------------|
| `normalizer` | string | null | Normalizer |
| `path` | string | null | Path |
| `secret` | string | null | Secret |
| `verify_token` | string | null | Verify Token |

#### IntegratorConfig

| Field | Type | Description |
|-------|------|-------------|
| `cutover` | IntegratorCutoverConfig |  |

#### IntegratorCutoverConfig

| Field | Type | Description |
|-------|------|-------------|
| `enabled` | boolean | Enabled |
| `parity_evidence_accepted` | boolean | Parity Evidence Accepted |
| `rollback_on_incomplete_parity` | boolean | Rollback On Incomplete Parity |

#### JobScheduleConfig

| Field | Type | Description |
|-------|------|-------------|
| `agent` | string | null | Agent |
| `category` | string | Category |
| `job` | string | null | Job |
| `message` | string | null | Message |
| `preferred_day` | integer | Preferred Day |
| `preferred_hour` | integer | Preferred Hour |
| `preferred_weekday` | integer | Preferred Weekday |
| `schedule` | string | null | Schedule |
| `script` | string | null | Script |
| `thinking_mode` | string | null | Thinking Mode |
| `timeout` | integer | null | Timeout |
| `type` | string | null | Type |
| `when` | JobWhenConfig | null |  |

#### JobSubscription

| Field | Type | Description |
|-------|------|-------------|
| `enabled` | boolean | Enabled |
| `job` | string | Job |
| `notification` | SubscriptionNotification |  |
| `type` | string | Type |
| `when` | JobWhenConfig | null |  |

#### JobWhenConfig

| Field | Type | Description |
|-------|------|-------------|
| `at` | string | array | null | At |
| `every` | string | null | Every |
| `weekdays` | array | Weekdays |

#### PersonEntry

| Field | Type | Description |
|-------|------|-------------|
| `email` | string | Email |
| `expertise` | object | null | Expertise |
| `name` | string | Name |
| `proficiency` | string | null | Proficiency |
| `role` | string | Role |
| `username` | string | null | Username |

#### SubscriptionConfig

| Field | Type | Description |
|-------|------|-------------|
| `contract` | object | Contract |
| `id` | string | Id |
| `target` | object | Target |

#### SubscriptionNotification

| Field | Type | Description |
|-------|------|-------------|
| `email` | string | null | Email |
| `preferred_channel` | string | Preferred Channel |

#### YoutubeSubscription

| Field | Type | Description |
|-------|------|-------------|
| `enabled` | boolean | Enabled |
| `notification` | SubscriptionNotification |  |
| `source` | string | Source |
| `tags` | array | Tags |
| `type` | string | Type |

## Project Config

Model: `ProjectConfig`

| Field | Type | Description |
|-------|------|-------------|
| `business` | BusinessConfig |  |
| `channel_subscriptions` | array | Channel Subscriptions |
| `deployment` | DeploymentConfig |  |
| `description` | string | null | Description |
| `git` | GitConfig |  |
| `hooks` | HooksConfig |  |
| `integrator` | IntegratorConfig |  |
| `jobs` | object | Jobs |
| `project_name` | string | null | Project Name |

### Project Config — Nested Types

#### BusinessConfig

| Field | Type | Description |
|-------|------|-------------|
| `domains` | object | Domains |

#### ChannelSubscription

| Field | Type | Description |
|-------|------|-------------|
| `channel` | string | Channel |
| `filter` | object | null | Filter |
| `target` | object | Target |

#### DeploymentConfig

| Field | Type | Description |
|-------|------|-------------|
| `channel` | string | Channel |
| `pinned_minor` | string | Pinned Minor |

#### GitConfig

| Field | Type | Description |
|-------|------|-------------|
| `checkout_root` | string | null | Checkout Root |

#### HooksConfig

| Field | Type | Description |
|-------|------|-------------|
| `inbound` | object | Inbound |
| `subscriptions` | array | Subscriptions |

#### InboundSourceConfig

| Field | Type | Description |
|-------|------|-------------|
| `normalizer` | string | null | Normalizer |
| `path` | string | null | Path |
| `secret` | string | null | Secret |
| `verify_token` | string | null | Verify Token |

#### IntegratorConfig

| Field | Type | Description |
|-------|------|-------------|
| `cutover` | IntegratorCutoverConfig |  |

#### IntegratorCutoverConfig

| Field | Type | Description |
|-------|------|-------------|
| `enabled` | boolean | Enabled |
| `parity_evidence_accepted` | boolean | Parity Evidence Accepted |
| `rollback_on_incomplete_parity` | boolean | Rollback On Incomplete Parity |

#### JobScheduleConfig

| Field | Type | Description |
|-------|------|-------------|
| `agent` | string | null | Agent |
| `category` | string | Category |
| `job` | string | null | Job |
| `message` | string | null | Message |
| `preferred_day` | integer | Preferred Day |
| `preferred_hour` | integer | Preferred Hour |
| `preferred_weekday` | integer | Preferred Weekday |
| `schedule` | string | null | Schedule |
| `script` | string | null | Script |
| `thinking_mode` | string | null | Thinking Mode |
| `timeout` | integer | null | Timeout |
| `type` | string | null | Type |
| `when` | JobWhenConfig | null |  |

#### JobWhenConfig

| Field | Type | Description |
|-------|------|-------------|
| `at` | string | array | null | At |
| `every` | string | null | Every |
| `weekdays` | array | Weekdays |

#### SubscriptionConfig

| Field | Type | Description |
|-------|------|-------------|
| `contract` | object | Contract |
| `id` | string | Id |
| `target` | object | Target |

## Person Config

Model: `PersonConfig`

| Field | Type | Description |
|-------|------|-------------|
| `creds` | CredsConfig |  |
| `interests` | array | Interests |
| `invite_token` | string | null | Invite Token |
| `subscriptions` | array | Subscriptions |

### Person Config — Nested Types

#### CredsConfig

| Field | Type | Description |
|-------|------|-------------|
| `discord` | DiscordCreds | null |  |
| `telegram` | TelegramCreds | null |  |
| `whatsapp` | WhatsAppCreds | null |  |

#### DiscordCreds

| Field | Type | Description |
|-------|------|-------------|
| `user_id` | string | User Id |

#### JobSubscription

| Field | Type | Description |
|-------|------|-------------|
| `enabled` | boolean | Enabled |
| `job` | string | Job |
| `notification` | SubscriptionNotification |  |
| `type` | string | Type |
| `when` | JobWhenConfig | null |  |

#### JobWhenConfig

| Field | Type | Description |
|-------|------|-------------|
| `at` | string | array | null | At |
| `every` | string | null | Every |
| `weekdays` | array | Weekdays |

#### SubscriptionNotification

| Field | Type | Description |
|-------|------|-------------|
| `email` | string | null | Email |
| `preferred_channel` | string | Preferred Channel |

#### TelegramCreds

| Field | Type | Description |
|-------|------|-------------|
| `chat_id` | string | null | Chat Id |
| `user_id` | integer | User Id |
| `user_name` | string | User Name |

#### WhatsAppCreds

| Field | Type | Description |
|-------|------|-------------|
| `phone_number` | string | Phone Number |

#### YoutubeSubscription

| Field | Type | Description |
|-------|------|-------------|
| `enabled` | boolean | Enabled |
| `notification` | SubscriptionNotification |  |
| `source` | string | Source |
| `tags` | array | Tags |
| `type` | string | Type |

## Raw JSON Schema

```json
{
  "$defs": {
    "AutonomyLevel": {
      "description": "Execution autonomy levels for domain cartridges.",
      "enum": [
        "manual",
        "notify",
        "auto_notify",
        "autonomous"
      ],
      "title": "AutonomyLevel",
      "type": "string"
    },
    "AutonomyMatrix": {
      "additionalProperties": true,
      "description": "Priority-ordered autonomy overrides for domains, cartridges, and events.",
      "properties": {
        "global_default": {
          "$ref": "#/$defs/AutonomyLevel",
          "default": "notify"
        },
        "by_domain": {
          "additionalProperties": {
            "$ref": "#/$defs/AutonomyLevel"
          },
          "title": "By Domain",
          "type": "object"
        },
        "by_cartridge": {
          "additionalProperties": {
            "$ref": "#/$defs/AutonomyLevel"
          },
          "title": "By Cartridge",
          "type": "object"
        },
        "by_event_type": {
          "additionalProperties": {
            "$ref": "#/$defs/AutonomyLevel"
          },
          "title": "By Event Type",
          "type": "object"
        }
      },
      "title": "AutonomyMatrix",
      "type": "object"
    },
    "BusinessConfig": {
      "additionalProperties": true,
      "description": "Business domain configuration.",
      "properties": {
        "domains": {
          "additionalProperties": {
            "type": "string"
          },
          "default": {},
          "title": "Domains",
          "type": "object"
        }
      },
      "title": "BusinessConfig",
      "type": "object"
    },
    "ChannelSubscription": {
      "additionalProperties": true,
      "description": "A subscription that routes messages from a Redis Stream channel to a target.",
      "properties": {
        "channel": {
          "title": "Channel",
          "type": "string"
        },
        "filter": {
          "anyOf": [
            {
              "additionalProperties": true,
              "type": "object"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Filter"
        },
        "target": {
          "additionalProperties": true,
          "default": {},
          "title": "Target",
          "type": "object"
        }
      },
      "required": [
        "channel"
      ],
      "title": "ChannelSubscription",
      "type": "object"
    },
    "DeploymentConfig": {
      "additionalProperties": true,
      "description": "Release channel and version pinning.",
      "properties": {
        "channel": {
          "default": "alpha",
          "enum": [
            "alpha",
            "beta",
            "stable"
          ],
          "title": "Channel",
          "type": "string"
        },
        "pinned_minor": {
          "default": "",
          "title": "Pinned Minor",
          "type": "string"
        }
      },
      "title": "DeploymentConfig",
      "type": "object"
    },
    "DomainConfig": {
      "additionalProperties": true,
      "description": "Configuration for a single domain-specific event pipeline.",
      "properties": {
        "name": {
          "title": "Name",
          "type": "string"
        },
        "enabled": {
          "default": true,
          "title": "Enabled",
          "type": "boolean"
        },
        "cartridge_path": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Cartridge Path"
        },
        "guardian": {
          "$ref": "#/$defs/DomainGuardianConfig"
        },
        "autonomy": {
          "$ref": "#/$defs/AutonomyMatrix"
        }
      },
      "required": [
        "name"
      ],
      "title": "DomainConfig",
      "type": "object"
    },
    "DomainGuardianConfig": {
      "additionalProperties": true,
      "description": "Guardian agent settings used when a domain requires evaluation.",
      "properties": {
        "agent": {
          "default": "claude",
          "title": "Agent",
          "type": "string"
        },
        "mode": {
          "default": "med",
          "title": "Mode",
          "type": "string"
        },
        "enabled": {
          "default": true,
          "title": "Enabled",
          "type": "boolean"
        },
        "evaluation_prompt": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Evaluation Prompt"
        }
      },
      "title": "DomainGuardianConfig",
      "type": "object"
    },
    "DomainsConfig": {
      "additionalProperties": true,
      "description": "Top-level configuration for all domain and personal event pipelines.",
      "properties": {
        "enabled": {
          "default": true,
          "title": "Enabled",
          "type": "boolean"
        },
        "base_path": {
          "default": "~/.teleclaude/company",
          "title": "Base Path",
          "type": "string"
        },
        "personal_base_path": {
          "default": "~/.teleclaude/personal",
          "title": "Personal Base Path",
          "type": "string"
        },
        "helpdesk_path": {
          "default": "~/.teleclaude/helpdesk",
          "title": "Helpdesk Path",
          "type": "string"
        },
        "domains": {
          "additionalProperties": {
            "$ref": "#/$defs/DomainConfig"
          },
          "title": "Domains",
          "type": "object"
        }
      },
      "title": "DomainsConfig",
      "type": "object"
    },
    "GitConfig": {
      "additionalProperties": true,
      "description": "Git repository configuration.",
      "properties": {
        "checkout_root": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Checkout Root"
        }
      },
      "title": "GitConfig",
      "type": "object"
    },
    "HooksConfig": {
      "additionalProperties": true,
      "description": "Hooks and subscriptions configuration.",
      "properties": {
        "inbound": {
          "additionalProperties": {
            "$ref": "#/$defs/InboundSourceConfig"
          },
          "default": {},
          "title": "Inbound",
          "type": "object"
        },
        "subscriptions": {
          "default": [],
          "items": {
            "$ref": "#/$defs/SubscriptionConfig"
          },
          "title": "Subscriptions",
          "type": "array"
        }
      },
      "title": "HooksConfig",
      "type": "object"
    },
    "InboundSourceConfig": {
      "additionalProperties": true,
      "description": "Inbound webhook source configuration.",
      "properties": {
        "path": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Path"
        },
        "verify_token": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Verify Token"
        },
        "secret": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Secret"
        },
        "normalizer": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Normalizer"
        }
      },
      "title": "InboundSourceConfig",
      "type": "object"
    },
    "IntegratorConfig": {
      "additionalProperties": true,
      "description": "Integrator subsystem configuration.",
      "properties": {
        "cutover": {
          "$ref": "#/$defs/IntegratorCutoverConfig",
          "default": {
            "enabled": false,
            "parity_evidence_accepted": false,
            "rollback_on_incomplete_parity": true
          }
        }
      },
      "title": "IntegratorConfig",
      "type": "object"
    },
    "IntegratorCutoverConfig": {
      "additionalProperties": true,
      "description": "Integrator cutover feature flags.",
      "properties": {
        "enabled": {
          "default": false,
          "title": "Enabled",
          "type": "boolean"
        },
        "parity_evidence_accepted": {
          "default": false,
          "title": "Parity Evidence Accepted",
          "type": "boolean"
        },
        "rollback_on_incomplete_parity": {
          "default": true,
          "title": "Rollback On Incomplete Parity",
          "type": "boolean"
        }
      },
      "title": "IntegratorCutoverConfig",
      "type": "object"
    },
    "JobScheduleConfig": {
      "additionalProperties": true,
      "description": "Job scheduling and execution configuration.",
      "properties": {
        "category": {
          "default": "subscription",
          "enum": [
            "subscription",
            "system"
          ],
          "title": "Category",
          "type": "string"
        },
        "when": {
          "anyOf": [
            {
              "$ref": "#/$defs/JobWhenConfig"
            },
            {
              "type": "null"
            }
          ],
          "default": null
        },
        "schedule": {
          "anyOf": [
            {
              "enum": [
                "hourly",
                "daily",
                "weekly",
                "monthly"
              ],
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Schedule"
        },
        "preferred_hour": {
          "default": 6,
          "maximum": 23,
          "minimum": 0,
          "title": "Preferred Hour",
          "type": "integer"
        },
        "preferred_weekday": {
          "default": 0,
          "maximum": 6,
          "minimum": 0,
          "title": "Preferred Weekday",
          "type": "integer"
        },
        "preferred_day": {
          "default": 1,
          "maximum": 31,
          "minimum": 1,
          "title": "Preferred Day",
          "type": "integer"
        },
        "type": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Type"
        },
        "script": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Script"
        },
        "job": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Job"
        },
        "agent": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": "claude",
          "title": "Agent"
        },
        "thinking_mode": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": "fast",
          "title": "Thinking Mode"
        },
        "message": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Message"
        },
        "timeout": {
          "anyOf": [
            {
              "type": "integer"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Timeout"
        }
      },
      "title": "JobScheduleConfig",
      "type": "object"
    },
    "JobSubscription": {
      "additionalProperties": true,
      "description": "Job-triggered subscription.",
      "properties": {
        "enabled": {
          "default": true,
          "title": "Enabled",
          "type": "boolean"
        },
        "notification": {
          "$ref": "#/$defs/SubscriptionNotification",
          "default": {
            "preferred_channel": "telegram",
            "email": null
          }
        },
        "type": {
          "const": "job",
          "default": "job",
          "title": "Type",
          "type": "string"
        },
        "job": {
          "title": "Job",
          "type": "string"
        },
        "when": {
          "anyOf": [
            {
              "$ref": "#/$defs/JobWhenConfig"
            },
            {
              "type": "null"
            }
          ],
          "default": null
        }
      },
      "required": [
        "job"
      ],
      "title": "JobSubscription",
      "type": "object"
    },
    "JobWhenConfig": {
      "additionalProperties": true,
      "description": "Job scheduling time configuration.",
      "properties": {
        "every": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Every"
        },
        "at": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "items": {
                "type": "string"
              },
              "type": "array"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "At"
        },
        "weekdays": {
          "default": [],
          "items": {
            "enum": [
              "mon",
              "tue",
              "wed",
              "thu",
              "fri",
              "sat",
              "sun"
            ],
            "type": "string"
          },
          "title": "Weekdays",
          "type": "array"
        }
      },
      "title": "JobWhenConfig",
      "type": "object"
    },
    "PersonEntry": {
      "additionalProperties": true,
      "description": "Person identity and role configuration.",
      "properties": {
        "name": {
          "title": "Name",
          "type": "string"
        },
        "email": {
          "title": "Email",
          "type": "string"
        },
        "username": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Username"
        },
        "role": {
          "default": "member",
          "enum": [
            "admin",
            "member",
            "contributor",
            "newcomer"
          ],
          "title": "Role",
          "type": "string"
        },
        "expertise": {
          "anyOf": [
            {
              "additionalProperties": {
                "anyOf": [
                  {
                    "enum": [
                      "novice",
                      "intermediate",
                      "advanced",
                      "expert"
                    ],
                    "type": "string"
                  },
                  {
                    "additionalProperties": {
                      "enum": [
                        "novice",
                        "intermediate",
                        "advanced",
                        "expert"
                      ],
                      "type": "string"
                    },
                    "type": "object"
                  }
                ]
              },
              "type": "object"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Expertise"
        },
        "proficiency": {
          "anyOf": [
            {
              "enum": [
                "novice",
                "intermediate",
                "advanced",
                "expert"
              ],
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Proficiency"
        }
      },
      "required": [
        "name",
        "email"
      ],
      "title": "PersonEntry",
      "type": "object"
    },
    "SubscriptionConfig": {
      "additionalProperties": true,
      "description": "Hook subscription configuration.",
      "properties": {
        "id": {
          "title": "Id",
          "type": "string"
        },
        "contract": {
          "additionalProperties": true,
          "default": {},
          "title": "Contract",
          "type": "object"
        },
        "target": {
          "additionalProperties": true,
          "default": {},
          "title": "Target",
          "type": "object"
        }
      },
      "required": [
        "id"
      ],
      "title": "SubscriptionConfig",
      "type": "object"
    },
    "SubscriptionNotification": {
      "additionalProperties": true,
      "description": "Notification channel preference for a subscription.",
      "properties": {
        "preferred_channel": {
          "default": "telegram",
          "enum": [
            "telegram",
            "discord",
            "whatsapp",
            "email"
          ],
          "title": "Preferred Channel",
          "type": "string"
        },
        "email": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Email"
        }
      },
      "title": "SubscriptionNotification",
      "type": "object"
    },
    "YoutubeSubscription": {
      "additionalProperties": true,
      "description": "YouTube channel subscription.",
      "properties": {
        "enabled": {
          "default": true,
          "title": "Enabled",
          "type": "boolean"
        },
        "notification": {
          "$ref": "#/$defs/SubscriptionNotification",
          "default": {
            "preferred_channel": "telegram",
            "email": null
          }
        },
        "type": {
          "const": "youtube",
          "default": "youtube",
          "title": "Type",
          "type": "string"
        },
        "source": {
          "title": "Source",
          "type": "string"
        },
        "tags": {
          "default": [],
          "items": {
            "type": "string"
          },
          "title": "Tags",
          "type": "array"
        }
      },
      "required": [
        "source"
      ],
      "title": "YoutubeSubscription",
      "type": "object"
    }
  },
  "additionalProperties": true,
  "description": "Global-level configuration extending project config.",
  "properties": {
    "project_name": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Project Name"
    },
    "description": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Description"
    },
    "business": {
      "$ref": "#/$defs/BusinessConfig",
      "default": {
        "domains": {}
      }
    },
    "hooks": {
      "$ref": "#/$defs/HooksConfig",
      "default": {
        "inbound": {},
        "subscriptions": []
      }
    },
    "jobs": {
      "additionalProperties": {
        "$ref": "#/$defs/JobScheduleConfig"
      },
      "default": {},
      "title": "Jobs",
      "type": "object"
    },
    "git": {
      "$ref": "#/$defs/GitConfig",
      "default": {
        "checkout_root": null
      }
    },
    "integrator": {
      "$ref": "#/$defs/IntegratorConfig",
      "default": {
        "cutover": {
          "enabled": false,
          "parity_evidence_accepted": false,
          "rollback_on_incomplete_parity": true
        }
      }
    },
    "channel_subscriptions": {
      "default": [],
      "items": {
        "$ref": "#/$defs/ChannelSubscription"
      },
      "title": "Channel Subscriptions",
      "type": "array"
    },
    "deployment": {
      "$ref": "#/$defs/DeploymentConfig",
      "default": {
        "channel": "alpha",
        "pinned_minor": ""
      }
    },
    "people": {
      "default": [],
      "items": {
        "$ref": "#/$defs/PersonEntry"
      },
      "title": "People",
      "type": "array"
    },
    "subscriptions": {
      "default": [],
      "items": {
        "discriminator": {
          "mapping": {
            "job": "#/$defs/JobSubscription",
            "youtube": "#/$defs/YoutubeSubscription"
          },
          "propertyName": "type"
        },
        "oneOf": [
          {
            "$ref": "#/$defs/JobSubscription"
          },
          {
            "$ref": "#/$defs/YoutubeSubscription"
          }
        ]
      },
      "title": "Subscriptions",
      "type": "array"
    },
    "interests": {
      "default": [],
      "items": {
        "type": "string"
      },
      "title": "Interests",
      "type": "array"
    },
    "event_domains": {
      "anyOf": [
        {
          "$ref": "#/$defs/DomainsConfig"
        },
        {
          "type": "null"
        }
      ],
      "default": null
    }
  },
  "title": "GlobalConfig",
  "type": "object"
}
```

