# TeleClaude Configuration Surface

## Global Config

Model: `GlobalConfig`

| Field | Type | Description |
|-------|------|-------------|
| `checkout_root` | string | null | Checkout Root |
| `env_allow_list` | array | Env Allow List |
| `hooks` | GlobalHooksConfig |  |
| `interests` | array | Interests |
| `jobs` | array | Jobs |
| `kind` | string | Kind |
| `people` | array | People |
| `schema_version` | integer | Schema Version |
| `subscriptions` | array | Subscriptions |

### Global Config — Nested Types

#### AgentName

#### GlobalHooksConfig

| Field | Type | Description |
|-------|------|-------------|
| `inbound` | GlobalInboundSources |  |

#### GlobalInboundSources

| Field | Type | Description |
|-------|------|-------------|
| `whatsapp` | WhatsAppInboundSource | null |  |

#### JobCategory

#### JobScheduleConfig

| Field | Type | Description |
|-------|------|-------------|
| `agent` | array | null | Agent |
| `category` | JobCategory |  |
| `enabled` | boolean | Enabled |
| `job` | string | null | Job |
| `name` | string | Name |
| `script` | string | null | Script |
| `thinking_mode` | string | null | Thinking Mode |
| `timeout` | integer | null | Timeout |
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
| `preferences` | string | null | Preferences |
| `role` | string | null | Role |
| `slug` | string | null | Slug |
| `username` | string | null | Username |

#### SubscriptionNotification

| Field | Type | Description |
|-------|------|-------------|
| `email` | string | null | Email |
| `preferred_channel` | string | Preferred Channel |

#### WhatsAppInboundSource

| Field | Type | Description |
|-------|------|-------------|
| `secret` | string | null | Secret |
| `verify_token` | string | null | Verify Token |

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
| `agents` | CapabilityConfig |  |
| `business` | BusinessConfig |  |
| `checkpoint` | CheckpointConfig | null |  |
| `code` | CapabilityConfig |  |
| `company` | string | null | Company |
| `description` | string | null | Description |
| `docs` | CapabilityConfig |  |
| `env_allow_list` | array | Env Allow List |
| `frontend_root` | string | null | Frontend Root |
| `help_desk` | ProjectHelpDeskConfig |  |
| `hooks` | HooksConfig |  |
| `jobs` | array | Jobs |
| `kind` | string | Kind |
| `person` | string | null | Person |
| `project_name` | string | null | Project Name |
| `project_slug` | string | null | Project Slug |
| `schema_version` | integer | Schema Version |

### Project Config — Nested Types

#### AgentName

#### BusinessConfig

| Field | Type | Description |
|-------|------|-------------|
| `publishes` | array | Publishes |

#### CapabilityConfig

| Field | Type | Description |
|-------|------|-------------|
| `enabled` | boolean | Enabled |

#### CheckpointActionConfig

| Field | Type | Description |
|-------|------|-------------|
| `evidence` | array | Evidence |
| `evidence_must_follow_last_mutation` | boolean | Evidence Must Follow Last Mutation |
| `main_only` | boolean | Main Only |
| `precedence` | integer | Precedence |
| `run` | string | Run |

#### CheckpointActivation

#### CheckpointBindingConfig

| Field | Type | Description |
|-------|------|-------------|
| `actions` | array | Actions |
| `activation` | CheckpointActivation | null |  |
| `events` | array | null | Events |
| `scope` | CheckpointScopeConfig |  |

#### CheckpointCodeConfig

| Field | Type | Description |
|-------|------|-------------|
| `scope` | CheckpointScopeConfig |  |

#### CheckpointConfig

| Field | Type | Description |
|-------|------|-------------|
| `actions` | object | Actions |
| `agents` | CheckpointExtraActionsConfig | null |  |
| `bindings` | array | Bindings |
| `code` | CheckpointCodeConfig | null |  |
| `docs` | CheckpointExtraActionsConfig | null |  |
| `integrator_judgment` | array | Integrator Judgment |
| `maintenance` | object | Maintenance |

#### CheckpointExtraActionsConfig

| Field | Type | Description |
|-------|------|-------------|
| `actions` | array | Actions |

#### CheckpointMaintenanceConfig

| Field | Type | Description |
|-------|------|-------------|
| `command` | array | Command |
| `main_only` | boolean | Main Only |
| `on_demand` | OnDemandDisposition |  |
| `owed_probe` | array | null | Owed Probe |
| `precedence` | integer | Precedence |

#### CheckpointScopeConfig

| Field | Type | Description |
|-------|------|-------------|
| `exclude` | array | Exclude |
| `include` | array | Include |
| `override` | array | Override |

#### HooksConfig

| Field | Type | Description |
|-------|------|-------------|
| `inbound` | ProjectInboundSources |  |

#### JobCategory

#### JobScheduleConfig

| Field | Type | Description |
|-------|------|-------------|
| `agent` | array | null | Agent |
| `category` | JobCategory |  |
| `enabled` | boolean | Enabled |
| `job` | string | null | Job |
| `name` | string | Name |
| `script` | string | null | Script |
| `thinking_mode` | string | null | Thinking Mode |
| `timeout` | integer | null | Timeout |
| `when` | JobWhenConfig | null |  |

#### JobWhenConfig

| Field | Type | Description |
|-------|------|-------------|
| `at` | string | array | null | At |
| `every` | string | null | Every |
| `weekdays` | array | Weekdays |

#### OnDemandDisposition

#### ProjectHelpDeskConfig

| Field | Type | Description |
|-------|------|-------------|
| `enabled` | boolean | Enabled |

#### ProjectInboundSources

| Field | Type | Description |
|-------|------|-------------|
| `github` | SignedInboundSource | null |  |
| `native` | SignedInboundSource | null |  |

#### PublishesEntry

| Field | Type | Description |
|-------|------|-------------|
| `slug` | string | Slug |
| `trigger` | string | Trigger |

#### SignedInboundSource

| Field | Type | Description |
|-------|------|-------------|
| `secret` | string | null | Secret |

## Person Config

Model: `PersonConfig`

| Field | Type | Description |
|-------|------|-------------|
| `color` | PersonChipColor | null |  |
| `creds` | CredsConfig |  |
| `description` | string | null | Description |
| `hooks` | HomeHooksConfig |  |
| `interests` | array | Interests |
| `kind` | string | Kind |
| `mail_accounts` | array | Mail Accounts |
| `name` | string | null | Name |
| `notifications` | object | Notifications |
| `preferred_channel` | MessagingChannel | null |  |
| `schema_version` | integer | Schema Version |
| `settings` | PersonSettings |  |
| `slug` | string | Slug |
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
| `avatar_url` | string | null | Avatar Url |
| `nick` | string | null | Nick |
| `user_id` | string | User Id |
| `voice_bot_token` | string | null | Voice Bot Token |

#### HomeHooksConfig

| Field | Type | Description |
|-------|------|-------------|
| `inbound` | NativeInboundSources |  |

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

#### MailAccount

| Field | Type | Description |
|-------|------|-------------|
| `address` | string | Address |
| `connector` | MailConnector |  |

#### MailConnector

#### MessagingChannel

#### NativeInboundSources

| Field | Type | Description |
|-------|------|-------------|
| `native` | SignedInboundSource | null |  |

#### NotificationCategory

| Field | Type | Description |
|-------|------|-------------|
| `enabled` | boolean | Enabled |
| `events` | array | Events |

#### OutputVisibilitySettings

| Field | Type | Description |
|-------|------|-------------|
| `system_messages` | string | null | System Messages |
| `tool_calls` | string | null | Tool Calls |

#### PersonChipColor

| Field | Type | Description |
|-------|------|-------------|
| `background` | PersonChipColorPair |  |
| `text` | PersonChipColorPair |  |

#### PersonChipColorPair

| Field | Type | Description |
|-------|------|-------------|
| `dark` | string | null | Dark |
| `light` | string | null | Light |

#### PersonSettings

| Field | Type | Description |
|-------|------|-------------|
| `output_visibility` | OutputVisibilitySettings |  |

#### SignedInboundSource

| Field | Type | Description |
|-------|------|-------------|
| `secret` | string | null | Secret |

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
  "Global Config": {
    "$defs": {
      "AgentName": {
        "description": "The closed set of AI agents TeleClaude can launch and dispatch to.",
        "enum": [
          "claude",
          "codex",
          "gemini",
          "deepseek"
        ],
        "title": "AgentName",
        "type": "string"
      },
      "GlobalHooksConfig": {
        "additionalProperties": false,
        "description": "The global configuration's inbound sources.",
        "properties": {
          "inbound": {
            "$ref": "#/$defs/GlobalInboundSources",
            "default": {
              "whatsapp": null
            }
          }
        },
        "title": "GlobalHooksConfig",
        "type": "object"
      },
      "GlobalInboundSources": {
        "additionalProperties": false,
        "description": "Inbound protocols the global configuration may declare.",
        "properties": {
          "whatsapp": {
            "anyOf": [
              {
                "$ref": "#/$defs/WhatsAppInboundSource"
              },
              {
                "type": "null"
              }
            ],
            "default": null
          }
        },
        "title": "GlobalInboundSources",
        "type": "object"
      },
      "JobCategory": {
        "description": "The scheduling relationship a job declaration has to a project.",
        "enum": [
          "subscription",
          "system"
        ],
        "title": "JobCategory",
        "type": "string"
      },
      "JobScheduleConfig": {
        "additionalProperties": false,
        "description": "One declarative scheduled job or subscription override.",
        "properties": {
          "name": {
            "title": "Name",
            "type": "string"
          },
          "category": {
            "$ref": "#/$defs/JobCategory",
            "default": "subscription"
          },
          "enabled": {
            "default": true,
            "title": "Enabled",
            "type": "boolean"
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
                "items": {
                  "$ref": "#/$defs/AgentName"
                },
                "type": "array"
              },
              {
                "type": "null"
              }
            ],
            "default": null,
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
            "default": null,
            "title": "Thinking Mode"
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
        "required": [
          "name"
        ],
        "title": "JobScheduleConfig",
        "type": "object"
      },
      "JobSubscription": {
        "additionalProperties": false,
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
        "additionalProperties": false,
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
        "additionalProperties": false,
        "description": "Person identity and role configuration.",
        "properties": {
          "name": {
            "title": "Name",
            "type": "string"
          },
          "email": {
            "minLength": 1,
            "title": "Email",
            "type": "string"
          },
          "slug": {
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "default": null,
            "title": "Slug"
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
            "anyOf": [
              {
                "enum": [
                  "admin",
                  "member"
                ],
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "default": null,
            "title": "Role"
          },
          "preferences": {
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "default": null,
            "title": "Preferences"
          },
          "expertise": {
            "anyOf": [
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
              },
              {
                "type": "null"
              }
            ],
            "default": null,
            "title": "Expertise"
          }
        },
        "required": [
          "name",
          "email"
        ],
        "title": "PersonEntry",
        "type": "object"
      },
      "SubscriptionNotification": {
        "additionalProperties": false,
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
      "WhatsAppInboundSource": {
        "additionalProperties": false,
        "description": "The WhatsApp Cloud API source: Meta's signature secret and its subscription handshake token.",
        "properties": {
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
          }
        },
        "title": "WhatsAppInboundSource",
        "type": "object"
      },
      "YoutubeSubscription": {
        "additionalProperties": false,
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
    "additionalProperties": false,
    "description": "Global-level configuration: the cross-project overlay (people, interests, overlay roots).\n\nLike ``ProjectConfig``, this is an overlay, not the machine runtime config; the\npublic/editable machine surface is the per-field ``tier`` markers on\n``TeleclaudeConfig`` (``local/projects/teleclaude/policy/config-public-surface``). ``checkout_root``\nis the surviving git overlay key, marked ``internal`` \u2014 not human-edited in the\nwizard.",
    "properties": {
      "kind": {
        "const": "global",
        "tier": "internal",
        "title": "Kind",
        "type": "string"
      },
      "schema_version": {
        "default": 21,
        "minimum": 0,
        "tier": "internal",
        "title": "Schema Version",
        "type": "integer"
      },
      "env_allow_list": {
        "default": [],
        "items": {
          "type": "string"
        },
        "title": "Env Allow List",
        "type": "array"
      },
      "people": {
        "default": [],
        "items": {
          "$ref": "#/$defs/PersonEntry"
        },
        "title": "People",
        "type": "array"
      },
      "jobs": {
        "default": [],
        "items": {
          "$ref": "#/$defs/JobScheduleConfig"
        },
        "title": "Jobs",
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
        "tier": "internal",
        "title": "Checkout Root"
      },
      "hooks": {
        "$ref": "#/$defs/GlobalHooksConfig",
        "default": {
          "inbound": {
            "whatsapp": null
          }
        }
      }
    },
    "required": [
      "kind"
    ],
    "title": "GlobalConfig",
    "type": "object"
  },
  "Project Config": {
    "$defs": {
      "AgentName": {
        "description": "The closed set of AI agents TeleClaude can launch and dispatch to.",
        "enum": [
          "claude",
          "codex",
          "gemini",
          "deepseek"
        ],
        "title": "AgentName",
        "type": "string"
      },
      "BusinessConfig": {
        "additionalProperties": false,
        "description": "Business domain configuration.",
        "properties": {
          "publishes": {
            "default": [],
            "items": {
              "$ref": "#/$defs/PublishesEntry"
            },
            "title": "Publishes",
            "type": "array"
          }
        },
        "title": "BusinessConfig",
        "type": "object"
      },
      "CapabilityConfig": {
        "additionalProperties": false,
        "description": "Subscription state; an omitted block makes no capability claim.",
        "properties": {
          "enabled": {
            "default": false,
            "title": "Enabled",
            "type": "boolean"
          }
        },
        "title": "CapabilityConfig",
        "type": "object"
      },
      "CheckpointActionConfig": {
        "additionalProperties": false,
        "description": "A project-declared checkpoint action (verb) overlaid on the base registry.",
        "properties": {
          "run": {
            "minLength": 1,
            "title": "Run",
            "type": "string"
          },
          "evidence": {
            "default": [],
            "items": {
              "type": "string"
            },
            "title": "Evidence",
            "type": "array"
          },
          "main_only": {
            "default": false,
            "title": "Main Only",
            "type": "boolean"
          },
          "precedence": {
            "default": 0,
            "title": "Precedence",
            "type": "integer"
          },
          "evidence_must_follow_last_mutation": {
            "default": false,
            "title": "Evidence Must Follow Last Mutation",
            "type": "boolean"
          }
        },
        "required": [
          "run"
        ],
        "title": "CheckpointActionConfig",
        "type": "object"
      },
      "CheckpointActivation": {
        "description": "Closed activation events that can select main-only maintenance.",
        "enum": [
          "canonical_main"
        ],
        "title": "CheckpointActivation",
        "type": "string"
      },
      "CheckpointBindingConfig": {
        "additionalProperties": false,
        "description": "Maps exactly one path, event, or canonical-main trigger to action ids.",
        "properties": {
          "scope": {
            "$ref": "#/$defs/CheckpointScopeConfig",
            "default": {
              "include": [],
              "exclude": [],
              "override": []
            }
          },
          "events": {
            "anyOf": [
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
            "title": "Events"
          },
          "activation": {
            "anyOf": [
              {
                "$ref": "#/$defs/CheckpointActivation"
              },
              {
                "type": "null"
              }
            ],
            "default": null
          },
          "actions": {
            "default": [],
            "items": {
              "type": "string"
            },
            "title": "Actions",
            "type": "array"
          }
        },
        "title": "CheckpointBindingConfig",
        "type": "object"
      },
      "CheckpointCodeConfig": {
        "additionalProperties": false,
        "description": "The conventional ``code`` kind: a scope onto which base ``test`` / ``log-check`` attach.",
        "properties": {
          "scope": {
            "$ref": "#/$defs/CheckpointScopeConfig",
            "default": {
              "include": [],
              "exclude": [],
              "override": []
            }
          }
        },
        "title": "CheckpointCodeConfig",
        "type": "object"
      },
      "CheckpointConfig": {
        "additionalProperties": false,
        "description": "Project checkpoint maintenance overlay merged atop the platform-universal base.\n\nAuthored at analyze-time by intelligence (``telec sessions run --command\n/projects-analyze``) per ``local/projects/teleclaude/procedure/checkpoint-overlay-projection``;\nconsumed structurally by\nthe checkpoint engine. An unreadable overlay degrades to base-only (fail-open).",
        "properties": {
          "actions": {
            "additionalProperties": {
              "$ref": "#/$defs/CheckpointActionConfig"
            },
            "default": {},
            "title": "Actions",
            "type": "object"
          },
          "maintenance": {
            "additionalProperties": {
              "$ref": "#/$defs/CheckpointMaintenanceConfig"
            },
            "default": {},
            "title": "Maintenance",
            "type": "object"
          },
          "integrator_judgment": {
            "default": [],
            "items": {
              "type": "string"
            },
            "title": "Integrator Judgment",
            "type": "array"
          },
          "code": {
            "anyOf": [
              {
                "$ref": "#/$defs/CheckpointCodeConfig"
              },
              {
                "type": "null"
              }
            ],
            "default": null
          },
          "bindings": {
            "default": [],
            "items": {
              "$ref": "#/$defs/CheckpointBindingConfig"
            },
            "title": "Bindings",
            "type": "array"
          },
          "docs": {
            "anyOf": [
              {
                "$ref": "#/$defs/CheckpointExtraActionsConfig"
              },
              {
                "type": "null"
              }
            ],
            "default": null
          },
          "agents": {
            "anyOf": [
              {
                "$ref": "#/$defs/CheckpointExtraActionsConfig"
              },
              {
                "type": "null"
              }
            ],
            "default": null
          }
        },
        "title": "CheckpointConfig",
        "type": "object"
      },
      "CheckpointExtraActionsConfig": {
        "additionalProperties": false,
        "description": "Optional extra actions appended atop a conventional base binding (``docs`` / ``agents``).",
        "properties": {
          "actions": {
            "default": [],
            "items": {
              "type": "string"
            },
            "title": "Actions",
            "type": "array"
          }
        },
        "title": "CheckpointExtraActionsConfig",
        "type": "object"
      },
      "CheckpointMaintenanceConfig": {
        "additionalProperties": false,
        "description": "A project-declared deterministic action overlaid on the maintenance registry.",
        "properties": {
          "command": {
            "items": {
              "type": "string"
            },
            "minItems": 1,
            "title": "Command",
            "type": "array"
          },
          "main_only": {
            "default": false,
            "title": "Main Only",
            "type": "boolean"
          },
          "precedence": {
            "default": 0,
            "title": "Precedence",
            "type": "integer"
          },
          "on_demand": {
            "$ref": "#/$defs/OnDemandDisposition",
            "default": "run"
          },
          "owed_probe": {
            "anyOf": [
              {
                "items": {
                  "type": "string"
                },
                "minItems": 1,
                "type": "array"
              },
              {
                "type": "null"
              }
            ],
            "default": null,
            "title": "Owed Probe"
          }
        },
        "required": [
          "command"
        ],
        "title": "CheckpointMaintenanceConfig",
        "type": "object"
      },
      "CheckpointScopeConfig": {
        "additionalProperties": false,
        "description": "A glob scope: ``include`` minus ``exclude``, re-added by ``override``.",
        "properties": {
          "include": {
            "default": [],
            "items": {
              "type": "string"
            },
            "title": "Include",
            "type": "array"
          },
          "exclude": {
            "default": [],
            "items": {
              "type": "string"
            },
            "title": "Exclude",
            "type": "array"
          },
          "override": {
            "default": [],
            "items": {
              "type": "string"
            },
            "title": "Override",
            "type": "array"
          }
        },
        "title": "CheckpointScopeConfig",
        "type": "object"
      },
      "HooksConfig": {
        "additionalProperties": false,
        "description": "A project's own inbound sources.",
        "properties": {
          "inbound": {
            "$ref": "#/$defs/ProjectInboundSources",
            "default": {
              "native": null,
              "github": null
            }
          }
        },
        "title": "HooksConfig",
        "type": "object"
      },
      "JobCategory": {
        "description": "The scheduling relationship a job declaration has to a project.",
        "enum": [
          "subscription",
          "system"
        ],
        "title": "JobCategory",
        "type": "string"
      },
      "JobScheduleConfig": {
        "additionalProperties": false,
        "description": "One declarative scheduled job or subscription override.",
        "properties": {
          "name": {
            "title": "Name",
            "type": "string"
          },
          "category": {
            "$ref": "#/$defs/JobCategory",
            "default": "subscription"
          },
          "enabled": {
            "default": true,
            "title": "Enabled",
            "type": "boolean"
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
                "items": {
                  "$ref": "#/$defs/AgentName"
                },
                "type": "array"
              },
              {
                "type": "null"
              }
            ],
            "default": null,
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
            "default": null,
            "title": "Thinking Mode"
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
        "required": [
          "name"
        ],
        "title": "JobScheduleConfig",
        "type": "object"
      },
      "JobWhenConfig": {
        "additionalProperties": false,
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
      "OnDemandDisposition": {
        "description": "What an on-demand run does with a maintenance action.",
        "enum": [
          "run",
          "defer"
        ],
        "title": "OnDemandDisposition",
        "type": "string"
      },
      "ProjectHelpDeskConfig": {
        "additionalProperties": false,
        "description": "Whether a project keeps a help desk; its folder launches a confined agent, so the project subscribes `agents`.",
        "properties": {
          "enabled": {
            "default": false,
            "title": "Enabled",
            "type": "boolean"
          }
        },
        "title": "ProjectHelpDeskConfig",
        "type": "object"
      },
      "ProjectInboundSources": {
        "additionalProperties": false,
        "description": "Inbound protocols a project home may declare.",
        "properties": {
          "native": {
            "anyOf": [
              {
                "$ref": "#/$defs/SignedInboundSource"
              },
              {
                "type": "null"
              }
            ],
            "default": null
          },
          "github": {
            "anyOf": [
              {
                "$ref": "#/$defs/SignedInboundSource"
              },
              {
                "type": "null"
              }
            ],
            "default": null
          }
        },
        "title": "ProjectInboundSources",
        "type": "object"
      },
      "PublishesEntry": {
        "additionalProperties": false,
        "description": "A published domain and its required always-on activation trigger.\n\nWith domain-resident triggered procedures scoped out of the always-on\nglobal catalog, this trigger is a published domain's only always-on\ntripwire, so both fields are required \u2014 a domain must never be\ndeliverable undiscoverable.",
        "properties": {
          "slug": {
            "minLength": 1,
            "title": "Slug",
            "type": "string"
          },
          "trigger": {
            "title": "Trigger",
            "type": "string"
          }
        },
        "required": [
          "slug",
          "trigger"
        ],
        "title": "PublishesEntry",
        "type": "object"
      },
      "SignedInboundSource": {
        "additionalProperties": false,
        "description": "One inbound source whose requests are verified under the declaring home's secret.\n\nThe secret is absent on a computer whose `.env` holds no value for its reference; only the\ningress verifies requests, and it refuses a request it cannot verify.",
        "properties": {
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
          }
        },
        "title": "SignedInboundSource",
        "type": "object"
      }
    },
    "additionalProperties": false,
    "allOf": [
      {
        "if": {
          "not": {
            "properties": {
              "agents": {
                "properties": {
                  "enabled": {
                    "const": true
                  }
                },
                "required": [
                  "enabled"
                ]
              }
            },
            "required": [
              "agents"
            ]
          }
        },
        "then": {
          "properties": {
            "help_desk": {
              "properties": {
                "enabled": {
                  "const": false,
                  "errorMessage": "help_desk.enabled requires agents.enabled: true"
                }
              }
            }
          }
        }
      }
    ],
    "description": "Project-level configuration: per-project ``teleclaude.yml`` overlay.\n\nThis is the project-scoped overlay, not the machine runtime config \u2014 the\npublic/editable machine surface is declared by the per-field ``tier`` markers\non ``TeleclaudeConfig`` (``local/projects/teleclaude/policy/config-public-surface``). Keys that\nbelong machine-wide (the release channel, the workflow control plane) live on\nthe machine config, not here.",
    "properties": {
      "kind": {
        "const": "project",
        "tier": "internal",
        "title": "Kind",
        "type": "string"
      },
      "schema_version": {
        "default": 21,
        "minimum": 0,
        "tier": "internal",
        "title": "Schema Version",
        "type": "integer"
      },
      "project_slug": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "default": null,
        "title": "Project Slug"
      },
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
      "company": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "default": null,
        "title": "Company"
      },
      "person": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "default": null,
        "title": "Person"
      },
      "env_allow_list": {
        "default": [],
        "items": {
          "type": "string"
        },
        "title": "Env Allow List",
        "type": "array"
      },
      "frontend_root": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "default": null,
        "title": "Frontend Root"
      },
      "business": {
        "$ref": "#/$defs/BusinessConfig",
        "default": {
          "publishes": []
        }
      },
      "hooks": {
        "$ref": "#/$defs/HooksConfig",
        "default": {
          "inbound": {
            "github": null,
            "native": null
          }
        }
      },
      "jobs": {
        "default": [],
        "items": {
          "$ref": "#/$defs/JobScheduleConfig"
        },
        "title": "Jobs",
        "type": "array"
      },
      "checkpoint": {
        "anyOf": [
          {
            "$ref": "#/$defs/CheckpointConfig"
          },
          {
            "type": "null"
          }
        ],
        "default": null
      },
      "code": {
        "$ref": "#/$defs/CapabilityConfig",
        "default": {
          "enabled": false
        }
      },
      "docs": {
        "$ref": "#/$defs/CapabilityConfig",
        "default": {
          "enabled": false
        }
      },
      "agents": {
        "$ref": "#/$defs/CapabilityConfig",
        "default": {
          "enabled": false
        }
      },
      "help_desk": {
        "$ref": "#/$defs/ProjectHelpDeskConfig",
        "default": {
          "enabled": false
        }
      }
    },
    "required": [
      "kind"
    ],
    "title": "ProjectConfig",
    "type": "object"
  },
  "Person Config": {
    "$defs": {
      "CredsConfig": {
        "additionalProperties": false,
        "description": "Multi-platform credential container.",
        "properties": {
          "telegram": {
            "anyOf": [
              {
                "$ref": "#/$defs/TelegramCreds"
              },
              {
                "type": "null"
              }
            ],
            "default": null
          },
          "discord": {
            "anyOf": [
              {
                "$ref": "#/$defs/DiscordCreds"
              },
              {
                "type": "null"
              }
            ],
            "default": null
          },
          "whatsapp": {
            "anyOf": [
              {
                "$ref": "#/$defs/WhatsAppCreds"
              },
              {
                "type": "null"
              }
            ],
            "default": null
          }
        },
        "title": "CredsConfig",
        "type": "object"
      },
      "DiscordCreds": {
        "additionalProperties": false,
        "description": "Discord platform credentials.",
        "properties": {
          "user_id": {
            "title": "User Id",
            "type": "string"
          },
          "nick": {
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "default": null,
            "title": "Nick"
          },
          "avatar_url": {
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "default": null,
            "title": "Avatar Url"
          },
          "voice_bot_token": {
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "default": null,
            "title": "Voice Bot Token"
          }
        },
        "required": [
          "user_id"
        ],
        "title": "DiscordCreds",
        "type": "object"
      },
      "HomeHooksConfig": {
        "additionalProperties": false,
        "description": "A company's or person's own inbound sources.",
        "properties": {
          "inbound": {
            "$ref": "#/$defs/NativeInboundSources",
            "default": {
              "native": null
            }
          }
        },
        "title": "HomeHooksConfig",
        "type": "object"
      },
      "JobSubscription": {
        "additionalProperties": false,
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
        "additionalProperties": false,
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
      "MailAccount": {
        "additionalProperties": false,
        "description": "One declared mail account available to a person's assistant.",
        "properties": {
          "connector": {
            "$ref": "#/$defs/MailConnector"
          },
          "address": {
            "minLength": 1,
            "title": "Address",
            "type": "string"
          }
        },
        "required": [
          "connector",
          "address"
        ],
        "title": "MailAccount",
        "type": "object"
      },
      "MailConnector": {
        "description": "Connector vocabulary for mail accounts an assistant may invoke.",
        "enum": [
          "google",
          "microsoft"
        ],
        "title": "MailConnector",
        "type": "string"
      },
      "MessagingChannel": {
        "description": "Named delivery channel vocabulary for person-addressed messaging routing.",
        "enum": [
          "telegram",
          "discord",
          "whatsapp",
          "email"
        ],
        "title": "MessagingChannel",
        "type": "string"
      },
      "NativeInboundSources": {
        "additionalProperties": false,
        "description": "Inbound protocols a company or person home may declare.",
        "properties": {
          "native": {
            "anyOf": [
              {
                "$ref": "#/$defs/SignedInboundSource"
              },
              {
                "type": "null"
              }
            ],
            "default": null
          }
        },
        "title": "NativeInboundSources",
        "type": "object"
      },
      "NotificationCategory": {
        "additionalProperties": false,
        "description": "One category of a person's notification interests: a switch and type patterns.\n\nPatterns stay strings so one unusable entry never fails the person's document;\n``teleclaude.config.notification_interests`` owns what a usable pattern is.",
        "properties": {
          "enabled": {
            "default": true,
            "title": "Enabled",
            "type": "boolean"
          },
          "events": {
            "items": {
              "type": "string"
            },
            "title": "Events",
            "type": "array"
          }
        },
        "title": "NotificationCategory",
        "type": "object"
      },
      "OutputVisibilitySettings": {
        "additionalProperties": false,
        "description": "Per-person visibility preferences for projected output categories.",
        "properties": {
          "system_messages": {
            "anyOf": [
              {
                "enum": [
                  "mobile",
                  "full",
                  "both",
                  "off"
                ],
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "default": null,
            "title": "System Messages"
          },
          "tool_calls": {
            "anyOf": [
              {
                "enum": [
                  "mobile",
                  "full",
                  "both",
                  "off"
                ],
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "default": null,
            "title": "Tool Calls"
          }
        },
        "title": "OutputVisibilitySettings",
        "type": "object"
      },
      "PersonChipColor": {
        "additionalProperties": false,
        "description": "Per-person chip color: a background and a text color, each theme-split.\n\nEvery leaf is independently optional and defaults to ``None``. ``None`` is\nthe renderer-default signal, not a stored color \u2014 the chip renderer fills it\nfrom the theme for the active mode. The nested pairs default to empty\ninstances so the whole block can be instantiated as an empty tree and a\nsingle leaf can be set without pre-populating its siblings.",
        "properties": {
          "background": {
            "$ref": "#/$defs/PersonChipColorPair",
            "default": {
              "light": null,
              "dark": null
            }
          },
          "text": {
            "$ref": "#/$defs/PersonChipColorPair",
            "default": {
              "light": null,
              "dark": null
            }
          }
        },
        "title": "PersonChipColor",
        "type": "object"
      },
      "PersonChipColorPair": {
        "additionalProperties": false,
        "description": "A theme-split color pair: one value for light mode, one for dark.",
        "properties": {
          "light": {
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "default": null,
            "title": "Light"
          },
          "dark": {
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "default": null,
            "title": "Dark"
          }
        },
        "title": "PersonChipColorPair",
        "type": "object"
      },
      "PersonSettings": {
        "additionalProperties": false,
        "description": "Per-person settings container.",
        "properties": {
          "output_visibility": {
            "$ref": "#/$defs/OutputVisibilitySettings",
            "default": {
              "system_messages": null,
              "tool_calls": null
            }
          }
        },
        "title": "PersonSettings",
        "type": "object"
      },
      "SignedInboundSource": {
        "additionalProperties": false,
        "description": "One inbound source whose requests are verified under the declaring home's secret.\n\nThe secret is absent on a computer whose `.env` holds no value for its reference; only the\ningress verifies requests, and it refuses a request it cannot verify.",
        "properties": {
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
          }
        },
        "title": "SignedInboundSource",
        "type": "object"
      },
      "SubscriptionNotification": {
        "additionalProperties": false,
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
      "TelegramCreds": {
        "additionalProperties": false,
        "description": "Telegram platform credentials.",
        "properties": {
          "user_name": {
            "title": "User Name",
            "type": "string"
          },
          "user_id": {
            "title": "User Id",
            "type": "integer"
          },
          "chat_id": {
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "default": null,
            "title": "Chat Id"
          }
        },
        "required": [
          "user_name",
          "user_id"
        ],
        "title": "TelegramCreds",
        "type": "object"
      },
      "WhatsAppCreds": {
        "additionalProperties": false,
        "description": "WhatsApp platform credentials.",
        "properties": {
          "phone_number": {
            "title": "Phone Number",
            "type": "string"
          }
        },
        "required": [
          "phone_number"
        ],
        "title": "WhatsAppCreds",
        "type": "object"
      },
      "YoutubeSubscription": {
        "additionalProperties": false,
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
    "additionalProperties": false,
    "description": "Per-person configuration.",
    "properties": {
      "kind": {
        "const": "person",
        "tier": "internal",
        "title": "Kind",
        "type": "string"
      },
      "schema_version": {
        "default": 21,
        "minimum": 0,
        "tier": "internal",
        "title": "Schema Version",
        "type": "integer"
      },
      "slug": {
        "tier": "internal",
        "title": "Slug",
        "type": "string"
      },
      "name": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "default": null,
        "title": "Name"
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
      "creds": {
        "$ref": "#/$defs/CredsConfig",
        "default": {
          "telegram": null,
          "discord": null,
          "whatsapp": null
        }
      },
      "subscriptions": {
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
        "tier": "internal",
        "title": "Subscriptions",
        "type": "array"
      },
      "mail_accounts": {
        "items": {
          "$ref": "#/$defs/MailAccount"
        },
        "tier": "internal",
        "title": "Mail Accounts",
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
      "notifications": {
        "additionalProperties": {
          "$ref": "#/$defs/NotificationCategory"
        },
        "title": "Notifications",
        "type": "object"
      },
      "settings": {
        "$ref": "#/$defs/PersonSettings",
        "default": {
          "output_visibility": {
            "system_messages": null,
            "tool_calls": null
          }
        }
      },
      "color": {
        "anyOf": [
          {
            "$ref": "#/$defs/PersonChipColor"
          },
          {
            "type": "null"
          }
        ],
        "default": null
      },
      "preferred_channel": {
        "anyOf": [
          {
            "$ref": "#/$defs/MessagingChannel"
          },
          {
            "type": "null"
          }
        ],
        "default": null
      },
      "hooks": {
        "$ref": "#/$defs/HomeHooksConfig",
        "default": {
          "inbound": {
            "native": null
          }
        }
      }
    },
    "required": [
      "kind",
      "slug"
    ],
    "title": "PersonConfig",
    "type": "object"
  }
}
```

