# EventEnvelope — Event Schema

```json
{
  "$defs": {
    "ActionDescriptor": {
      "description": "Human- or agent-facing action affordance attached to an event.",
      "properties": {
        "description": {
          "title": "Description",
          "type": "string"
        },
        "produces": {
          "title": "Produces",
          "type": "string"
        },
        "outcome_shape": {
          "anyOf": [
            {
              "additionalProperties": {
                "type": "string"
              },
              "type": "object"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Outcome Shape"
        }
      },
      "required": ["description", "produces"],
      "title": "ActionDescriptor",
      "type": "object"
    },
    "EventLevel": {
      "description": "Priority level for event routing and notification decisions.",
      "enum": [0, 1, 2, 3],
      "title": "EventLevel",
      "type": "integer"
    },
    "EventVisibility": {
      "description": "Visibility scope for an event.",
      "enum": ["local", "cluster", "public"],
      "title": "EventVisibility",
      "type": "string"
    }
  },
  "additionalProperties": true,
  "description": "Canonical event payload stored on the stream and in downstream projections.",
  "properties": {
    "event": {
      "title": "Event",
      "type": "string"
    },
    "version": {
      "default": 1,
      "title": "Version",
      "type": "integer"
    },
    "source": {
      "title": "Source",
      "type": "string"
    },
    "timestamp": {
      "format": "date-time",
      "title": "Timestamp",
      "type": "string"
    },
    "idempotency_key": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Idempotency Key"
    },
    "level": {
      "$ref": "#/$defs/EventLevel"
    },
    "domain": {
      "default": "",
      "title": "Domain",
      "type": "string"
    },
    "entity": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Entity"
    },
    "description": {
      "default": "",
      "title": "Description",
      "type": "string"
    },
    "visibility": {
      "$ref": "#/$defs/EventVisibility",
      "default": "local"
    },
    "payload": {
      "additionalProperties": true,
      "title": "Payload",
      "type": "object"
    },
    "actions": {
      "anyOf": [
        {
          "additionalProperties": {
            "$ref": "#/$defs/ActionDescriptor"
          },
          "type": "object"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Actions"
    },
    "terminal_when": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Terminal When"
    },
    "resolution_shape": {
      "anyOf": [
        {
          "additionalProperties": {
            "type": "string"
          },
          "type": "object"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Resolution Shape"
    }
  },
  "required": ["event", "source", "level"],
  "title": "EventEnvelope",
  "type": "object"
}
```
