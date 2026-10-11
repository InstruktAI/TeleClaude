# Platform Event Model — Event Schema

```json
{
  "title": "Platform Event Model",
  "received_event": {
    "$defs": {
      "EventHomeKind": {
        "description": "Configuration homes an event can belong to.",
        "enum": [
          "project",
          "person",
          "company"
        ],
        "title": "EventHomeKind",
        "type": "string"
      },
      "EventHomeMarker": {
        "description": "Explicit home states that are not registered homes: none is a claim, unknown makes none.",
        "enum": [
          "none",
          "unknown"
        ],
        "title": "EventHomeMarker",
        "type": "string"
      },
      "EventHomeOwnerMarker": {
        "description": "Explicit project-owner states that are not registry references.",
        "enum": [
          "none",
          "ownerless",
          "unresolved"
        ],
        "title": "EventHomeOwnerMarker",
        "type": "string"
      },
      "EventHomeRef": {
        "properties": {
          "kind": {
            "$ref": "#/$defs/EventHomeKind"
          },
          "instance": {
            "title": "Instance",
            "type": "string"
          }
        },
        "required": [
          "kind",
          "instance"
        ],
        "title": "EventHomeRef",
        "type": "object"
      },
      "EventOwnerKind": {
        "description": "Registered project-owner kinds that may appear on an event.",
        "enum": [
          "company",
          "person"
        ],
        "title": "EventOwnerKind",
        "type": "string"
      },
      "EventOwnerRef": {
        "properties": {
          "kind": {
            "$ref": "#/$defs/EventOwnerKind"
          },
          "instance": {
            "title": "Instance",
            "type": "string"
          }
        },
        "required": [
          "kind",
          "instance"
        ],
        "title": "EventOwnerRef",
        "type": "object"
      },
      "EventRef": {
        "properties": {
          "kind": {
            "title": "Kind",
            "type": "string"
          },
          "identity": {
            "title": "Identity",
            "type": "string"
          }
        },
        "required": [
          "kind",
          "identity"
        ],
        "title": "EventRef",
        "type": "object"
      },
      "JsonDict": {
        "additionalProperties": {
          "$ref": "#/$defs/JsonValue"
        },
        "type": "object"
      },
      "JsonPrimitive": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "integer"
          },
          {
            "type": "number"
          },
          {
            "type": "boolean"
          },
          {
            "type": "null"
          }
        ]
      },
      "JsonValue": {
        "anyOf": [
          {
            "$ref": "#/$defs/JsonPrimitive"
          },
          {
            "items": {
              "$ref": "#/$defs/JsonValue"
            },
            "type": "array"
          },
          {
            "additionalProperties": {
              "$ref": "#/$defs/JsonValue"
            },
            "type": "object"
          }
        ]
      }
    },
    "description": "A platform event as every reader sees it: its attributes, exactly as the producer stated them.\n\nThe id, type, source, time and home are on every event. The subject, related\nreferences and causation id are absent on an event an older computer emitted\nand on events that have none; absent states nothing and is never unknown.\nThe data is opaque to every reader that has not matched the type.",
    "properties": {
      "id": {
        "title": "Id",
        "type": "string"
      },
      "type": {
        "title": "Type",
        "type": "string"
      },
      "source": {
        "title": "Source",
        "type": "string"
      },
      "subject": {
        "anyOf": [
          {
            "$ref": "#/$defs/EventRef"
          },
          {
            "type": "null"
          }
        ],
        "default": null
      },
      "time": {
        "format": "date-time",
        "title": "Time",
        "type": "string"
      },
      "data": {
        "$ref": "#/$defs/JsonDict"
      },
      "home": {
        "anyOf": [
          {
            "$ref": "#/$defs/EventHomeRef"
          },
          {
            "$ref": "#/$defs/EventHomeMarker"
          }
        ],
        "title": "Home"
      },
      "home_owner": {
        "anyOf": [
          {
            "$ref": "#/$defs/EventOwnerRef"
          },
          {
            "$ref": "#/$defs/EventHomeOwnerMarker"
          }
        ],
        "default": "none",
        "title": "Home Owner"
      },
      "related": {
        "default": [],
        "items": {
          "$ref": "#/$defs/EventRef"
        },
        "title": "Related",
        "type": "array"
      },
      "causationid": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "default": null,
        "title": "Causationid"
      }
    },
    "required": [
      "id",
      "type",
      "source",
      "time",
      "home"
    ],
    "title": "ReceivedEvent",
    "type": "object"
  },
  "event_types": [
    {
      "name": "sdlc.branch.pushed",
      "version": 1,
      "description": "Worktree branch pushed to remote, candidate ready for integration",
      "subject_kind": "todo",
      "home_kinds": [
        "project"
      ],
      "data_fields": [
        {
          "name": "branch",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "pushed_at",
          "kind": "any",
          "nullable": true
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "sdlc.build.completed",
      "version": 1,
      "description": "Build phase completed for a work item",
      "subject_kind": "todo",
      "home_kinds": [
        "project"
      ],
      "data_fields": [
        {
          "name": "slug",
          "kind": "string",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "sdlc.deploy.failed",
      "version": 1,
      "description": "Deployment failed and requires attention",
      "subject_kind": "deployment",
      "home_kinds": [
        "project"
      ],
      "data_fields": [
        {
          "name": "error",
          "kind": "any",
          "nullable": true
        },
        {
          "name": "slug",
          "kind": "string",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "sdlc.deploy.succeeded",
      "version": 1,
      "description": "Deployment completed successfully",
      "subject_kind": "deployment",
      "home_kinds": [
        "project"
      ],
      "data_fields": [
        {
          "name": "slug",
          "kind": "string",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "sdlc.deploy.triggered",
      "version": 1,
      "description": "Deployment was triggered for a work item",
      "subject_kind": "deployment",
      "home_kinds": [
        "project"
      ],
      "data_fields": [
        {
          "name": "environment",
          "kind": "any",
          "nullable": true
        },
        {
          "name": "slug",
          "kind": "string",
          "nullable": true
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "sdlc.deployment.completed",
      "version": 1,
      "description": "Integrated to main, delivery bookkeeping done",
      "subject_kind": "deployment",
      "home_kinds": [
        "project"
      ],
      "data_fields": [
        {
          "name": "branch",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "integrated_at",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "merge_commit",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "sha",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "slug",
          "kind": "string",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "sdlc.deployment.failed",
      "version": 1,
      "description": "Integration blocked, needs attention",
      "subject_kind": "deployment",
      "home_kinds": [
        "project"
      ],
      "data_fields": [
        {
          "name": "blocked_at",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "branch",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "conflict_evidence",
          "kind": "array",
          "nullable": false
        },
        {
          "name": "diagnostics",
          "kind": "array",
          "nullable": false
        },
        {
          "name": "sha",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "slug",
          "kind": "string",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "sdlc.deployment.started",
      "version": 1,
      "description": "Finalize ready, candidate queued for integration",
      "subject_kind": "deployment",
      "home_kinds": [
        "project"
      ],
      "data_fields": [
        {
          "name": "ready_at",
          "kind": "any",
          "nullable": true
        },
        {
          "name": "slug",
          "kind": "string",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "sdlc.integration.candidate.blocked",
      "version": 1,
      "description": "An integration candidate was blocked",
      "subject_kind": "todo",
      "home_kinds": [
        "project"
      ],
      "data_fields": [
        {
          "name": "blocked_at",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "branch",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "reason",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "sha",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "slug",
          "kind": "string",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "sdlc.integration.candidate.delivered",
      "version": 1,
      "description": "An integration candidate completed delivery",
      "subject_kind": "todo",
      "home_kinds": [
        "project"
      ],
      "data_fields": [
        {
          "name": "branch",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "integrated_at",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "merge_commit_sha",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "slug",
          "kind": "string",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "sdlc.integration.candidate.parked",
      "version": 1,
      "description": "An integration candidate was parked for the current drain",
      "subject_kind": "todo",
      "home_kinds": [
        "project"
      ],
      "data_fields": [
        {
          "name": "branch",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "parked_at",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "reason",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "sha",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "slug",
          "kind": "string",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "sdlc.integration.drain.completed",
      "version": 1,
      "description": "An integration drain completed with delivered and parked outcomes",
      "subject_kind": "session",
      "home_kinds": [
        "project"
      ],
      "data_fields": [
        {
          "name": "completed_at",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "delivered_count",
          "kind": "integer",
          "nullable": false
        },
        {
          "name": "parked",
          "kind": "array",
          "nullable": false
        },
        {
          "name": "session_id",
          "kind": "string",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "sdlc.integration.started",
      "version": 1,
      "description": "An integrator began processing a candidate",
      "subject_kind": "todo",
      "home_kinds": [
        "project"
      ],
      "data_fields": [
        {
          "name": "queue_depth",
          "kind": "integer",
          "nullable": false
        },
        {
          "name": "session_id",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "slug",
          "kind": "string",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "sdlc.planning.dor_assessed",
      "version": 1,
      "description": "Definition of Ready was assessed for a work item",
      "subject_kind": "todo",
      "home_kinds": [
        "project"
      ],
      "data_fields": [
        {
          "name": "score",
          "kind": "any",
          "nullable": true
        },
        {
          "name": "slug",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "verdict",
          "kind": "any",
          "nullable": true
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "sdlc.planning.todo_finalize_ready",
      "version": 1,
      "description": "Finalize-ready worker claim is ready for integration handoff",
      "subject_kind": "todo",
      "home_kinds": [
        "project"
      ],
      "data_fields": [
        {
          "name": "branch",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "project_path",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "ready_at",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "sha",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "slug",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "worker_session_id",
          "kind": "string",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "sdlc.prepare.artifact_invalidated",
      "version": 1,
      "description": "Upstream change cascaded staleness to a prepare artifact",
      "subject_kind": "todo",
      "home_kinds": [
        "project"
      ],
      "data_fields": [
        {
          "name": "slug",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "stale_artifacts",
          "kind": "any",
          "nullable": true
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "sdlc.prepare.artifact_produced",
      "version": 1,
      "description": "Prepare artifact written and lifecycle-tracked in state",
      "subject_kind": "todo",
      "home_kinds": [
        "project"
      ],
      "data_fields": [
        {
          "name": "artifact",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "digest",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "slug",
          "kind": "string",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "sdlc.prepare.blocked",
      "version": 1,
      "description": "Preparation blocked, requires human decision",
      "subject_kind": "todo",
      "home_kinds": [
        "project"
      ],
      "data_fields": [
        {
          "name": "blocker",
          "kind": "any",
          "nullable": true
        },
        {
          "name": "slug",
          "kind": "string",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "sdlc.prepare.completed",
      "version": 1,
      "description": "Preparation complete, todo ready for build",
      "subject_kind": "todo",
      "home_kinds": [
        "project"
      ],
      "data_fields": [
        {
          "name": "slug",
          "kind": "string",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "sdlc.prepare.discovery_started",
      "version": 1,
      "description": "Requirements discovery phase dispatched",
      "subject_kind": "todo",
      "home_kinds": [
        "project"
      ],
      "data_fields": [
        {
          "name": "slug",
          "kind": "string",
          "nullable": true
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "sdlc.prepare.input_consumed",
      "version": 1,
      "description": "Input consumed by discovery worker, requirements production started",
      "subject_kind": "todo",
      "home_kinds": [
        "project"
      ],
      "data_fields": [
        {
          "name": "slug",
          "kind": "string",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "sdlc.prepare.input_refined",
      "version": 1,
      "description": "Human thinking was captured or updated in input.md",
      "subject_kind": "todo",
      "home_kinds": [
        "project"
      ],
      "data_fields": [
        {
          "name": "slug",
          "kind": "string",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "sdlc.prepare.phase_skipped",
      "version": 1,
      "description": "Prepare phase skipped via inheritance from parent todo",
      "subject_kind": "todo",
      "home_kinds": [
        "project"
      ],
      "data_fields": [
        {
          "name": "phase",
          "kind": "any",
          "nullable": true
        },
        {
          "name": "reason",
          "kind": "any",
          "nullable": true
        },
        {
          "name": "slug",
          "kind": "string",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "sdlc.prepare.plan_approved",
      "version": 1,
      "description": "Implementation plan reviewed and approved",
      "subject_kind": "todo",
      "home_kinds": [
        "project"
      ],
      "data_fields": [
        {
          "name": "slug",
          "kind": "string",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "sdlc.prepare.plan_drafted",
      "version": 1,
      "description": "Implementation plan drafted from approved requirements",
      "subject_kind": "todo",
      "home_kinds": [
        "project"
      ],
      "data_fields": [
        {
          "name": "slug",
          "kind": "string",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "sdlc.prepare.requirements_approved",
      "version": 1,
      "description": "Requirements reviewed and approved, ready for plan drafting",
      "subject_kind": "todo",
      "home_kinds": [
        "project"
      ],
      "data_fields": [
        {
          "name": "slug",
          "kind": "string",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "sdlc.prepare.requirements_drafted",
      "version": 1,
      "description": "Requirements derived from triangulation",
      "subject_kind": "todo",
      "home_kinds": [
        "project"
      ],
      "data_fields": [
        {
          "name": "slug",
          "kind": "string",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "sdlc.prepare.review_scoped",
      "version": 1,
      "description": "Scoped re-review dispatched with a findings artifact",
      "subject_kind": "todo",
      "home_kinds": [
        "project"
      ],
      "data_fields": [
        {
          "name": "findings_artifact",
          "kind": "any",
          "nullable": true
        },
        {
          "name": "slug",
          "kind": "string",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "sdlc.review.approved",
      "version": 1,
      "description": "Review passed, candidate eligible for finalization",
      "subject_kind": "todo",
      "home_kinds": [
        "project"
      ],
      "data_fields": [
        {
          "name": "approved_at",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "review_round",
          "kind": "integer",
          "nullable": false
        },
        {
          "name": "reviewer_session_id",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "slug",
          "kind": "string",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "sdlc.review.needs_decision",
      "version": 1,
      "description": "Review requires a human decision before proceeding",
      "subject_kind": "todo",
      "home_kinds": [
        "project"
      ],
      "data_fields": [
        {
          "name": "question",
          "kind": "any",
          "nullable": true
        },
        {
          "name": "round",
          "kind": "any",
          "nullable": true
        },
        {
          "name": "slug",
          "kind": "string",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "sdlc.review.verdict_ready",
      "version": 1,
      "description": "Code review verdict is ready",
      "subject_kind": "todo",
      "home_kinds": [
        "project"
      ],
      "data_fields": [
        {
          "name": "round",
          "kind": "any",
          "nullable": true
        },
        {
          "name": "slug",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "verdict",
          "kind": "any",
          "nullable": true
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "sdlc.roadmap.entry_moved",
      "version": 1,
      "description": "A roadmap entry moved between queues or dependency positions",
      "subject_kind": "todo",
      "home_kinds": [
        "project"
      ],
      "data_fields": [
        {
          "name": "slug",
          "kind": "string",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "sdlc.todo.created",
      "version": 1,
      "description": "A workflow todo was created and may require lifecycle-runner evaluation",
      "subject_kind": "todo",
      "home_kinds": [
        "project"
      ],
      "data_fields": [
        {
          "name": "context",
          "kind": "string",
          "nullable": true
        },
        {
          "name": "created_at",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "creation_mode",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "entry_point",
          "kind": "string",
          "nullable": true
        },
        {
          "name": "human_involved",
          "kind": "boolean",
          "nullable": false
        },
        {
          "name": "kind",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "lifecycle_phase",
          "kind": "string",
          "nullable": true
        },
        {
          "name": "lineage",
          "kind": "string",
          "nullable": true
        },
        {
          "name": "pickup_requested",
          "kind": "boolean",
          "nullable": false
        },
        {
          "name": "project_path",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "slug",
          "kind": "string",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "sdlc.todo.delivered",
      "version": 1,
      "description": "A workflow todo was delivered and may unblock dependents",
      "subject_kind": "todo",
      "home_kinds": [
        "project"
      ],
      "data_fields": [
        {
          "name": "delivered_at",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "delivery_commit",
          "kind": "string",
          "nullable": true
        },
        {
          "name": "project_path",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "slug",
          "kind": "string",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "sdlc.todo.phase_advanced",
      "version": 1,
      "description": "A workflow todo advanced lifecycle phase and may unblock runner work",
      "subject_kind": "todo",
      "home_kinds": [
        "project"
      ],
      "data_fields": [
        {
          "name": "lifecycle_phase",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "prior_lifecycle_phase",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "project_path",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "slug",
          "kind": "string",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "sdlc.todo.updated",
      "version": 1,
      "description": "A workflow todo control-plane field changed and may affect runner eligibility",
      "subject_kind": "todo",
      "home_kinds": [
        "project"
      ],
      "data_fields": [
        {
          "name": "project_path",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "slug",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "updated_at",
          "kind": "string",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "teleclaude.agent_runtime.session.ended.help_desk",
      "version": 1,
      "description": "A help-desk conversation session ended",
      "subject_kind": "session",
      "home_kinds": [
        "project",
        "person",
        "company"
      ],
      "data_fields": [
        {
          "name": "ended_at",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "project_path",
          "kind": "string",
          "nullable": true
        },
        {
          "name": "session_id",
          "kind": "string",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "teleclaude.agent_runtime.session.ended.person",
      "version": 1,
      "description": "A session a person started and talks to ended",
      "subject_kind": "session",
      "home_kinds": [
        "project",
        "person",
        "company"
      ],
      "data_fields": [
        {
          "name": "ended_at",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "project_path",
          "kind": "string",
          "nullable": true
        },
        {
          "name": "session_id",
          "kind": "string",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "teleclaude.agent_runtime.session.ended.system",
      "version": 1,
      "description": "A session the system started ended",
      "subject_kind": "session",
      "home_kinds": [
        "project",
        "person",
        "company"
      ],
      "data_fields": [
        {
          "name": "ended_at",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "project_path",
          "kind": "string",
          "nullable": true
        },
        {
          "name": "session_id",
          "kind": "string",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "teleclaude.agent_runtime.session.ended.unknown",
      "version": 1,
      "description": "A session ended whose record does not establish what kind of session it was",
      "subject_kind": "session",
      "home_kinds": [
        "project",
        "person",
        "company"
      ],
      "data_fields": [
        {
          "name": "ended_at",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "project_path",
          "kind": "string",
          "nullable": true
        },
        {
          "name": "session_id",
          "kind": "string",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "teleclaude.agent_runtime.session.restart_failed",
      "version": 1,
      "description": "An agent restart failed before the agent could resume, and the session was kept alive for inspection",
      "subject_kind": "session",
      "home_kinds": [
        "project",
        "person",
        "company"
      ],
      "data_fields": [
        {
          "name": "computer",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "phase",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "reason",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "restart_group",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "session_id",
          "kind": "string",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "teleclaude.config.effective.updated",
      "version": 1,
      "description": "Effective project configuration changed and may affect workflow runner eligibility",
      "subject_kind": "configuration",
      "home_kinds": [
        "project"
      ],
      "data_fields": [
        {
          "name": "changed_sections",
          "kind": "array",
          "nullable": false
        },
        {
          "name": "project_path",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "updated_at",
          "kind": "string",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "teleclaude.config.validation.failed",
      "version": 1,
      "description": "A configuration document on this computer does not validate and was not applied; it needs correcting",
      "subject_kind": "configuration",
      "home_kinds": [],
      "data_fields": [
        {
          "name": "document",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "findings",
          "kind": "array",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": {
        "family": "teleclaude.config.validation",
        "state": "failed",
        "standing": "failing"
      }
    },
    {
      "name": "teleclaude.config.validation.recovered",
      "version": 1,
      "description": "A configuration document that did not validate on this computer validates again",
      "subject_kind": "configuration",
      "home_kinds": [],
      "data_fields": [
        {
          "name": "document",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "findings",
          "kind": "array",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": {
        "family": "teleclaude.config.validation",
        "state": "recovered",
        "standing": "ok"
      }
    },
    {
      "name": "teleclaude.content.dumped",
      "version": 1,
      "description": "Raw content was captured and queued for processing",
      "subject_kind": "captured_item",
      "home_kinds": [
        "project",
        "person",
        "company"
      ],
      "data_fields": [
        {
          "name": "author",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "inbox_path",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "tags",
          "kind": "array",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "teleclaude.content.published",
      "version": 1,
      "description": "Content was made available externally",
      "subject_kind": "captured_item",
      "home_kinds": [
        "project",
        "person",
        "company"
      ],
      "data_fields": [
        {
          "name": "content_id",
          "kind": "any",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "teleclaude.content.refined",
      "version": 1,
      "description": "Content was processed or edited",
      "subject_kind": "captured_item",
      "home_kinds": [
        "project",
        "person",
        "company"
      ],
      "data_fields": [
        {
          "name": "content_id",
          "kind": "any",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "teleclaude.deployment.failed",
      "version": 1,
      "description": "Deployment failed and requires attention",
      "subject_kind": "deployment",
      "home_kinds": [
        "project"
      ],
      "data_fields": [
        {
          "name": "reason",
          "kind": "any",
          "nullable": true
        },
        {
          "name": "slug",
          "kind": "any",
          "nullable": true
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": {
        "family": "teleclaude.deployment",
        "state": "failed",
        "standing": "failing"
      }
    },
    {
      "name": "teleclaude.deployment.rolled_back",
      "version": 1,
      "description": "Rollback executed after deployment failure",
      "subject_kind": "deployment",
      "home_kinds": [
        "project"
      ],
      "data_fields": [
        {
          "name": "slug",
          "kind": "any",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "teleclaude.deployment.started",
      "version": 1,
      "description": "Deployment initiated",
      "subject_kind": "deployment",
      "home_kinds": [
        "project"
      ],
      "data_fields": [
        {
          "name": "slug",
          "kind": "any",
          "nullable": true
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "teleclaude.deployment.succeeded",
      "version": 1,
      "description": "Deployment succeeded",
      "subject_kind": "deployment",
      "home_kinds": [
        "project"
      ],
      "data_fields": [
        {
          "name": "slug",
          "kind": "any",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": {
        "family": "teleclaude.deployment",
        "state": "succeeded",
        "standing": "ok"
      }
    },
    {
      "name": "teleclaude.job.run.failed",
      "version": 1,
      "description": "A recurring job run failed and requires operator attention",
      "subject_kind": "job",
      "home_kinds": [
        "project"
      ],
      "data_fields": [
        {
          "name": "items",
          "kind": "integer",
          "nullable": false
        },
        {
          "name": "job_name",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "message",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "run_started_at",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "status",
          "kind": "string",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": {
        "family": "teleclaude.job.run",
        "state": "failed",
        "standing": "failing"
      }
    },
    {
      "name": "teleclaude.job.run.stalled",
      "version": 1,
      "description": "A recurring job run stalled before reporting an outcome",
      "subject_kind": "job",
      "home_kinds": [
        "project"
      ],
      "data_fields": [
        {
          "name": "items",
          "kind": "integer",
          "nullable": false
        },
        {
          "name": "job_name",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "message",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "run_started_at",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "status",
          "kind": "string",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": {
        "family": "teleclaude.job.run",
        "state": "stalled",
        "standing": "failing"
      }
    },
    {
      "name": "teleclaude.job.run.succeeded",
      "version": 1,
      "description": "A recurring job run completed successfully",
      "subject_kind": "job",
      "home_kinds": [
        "project"
      ],
      "data_fields": [
        {
          "name": "items",
          "kind": "integer",
          "nullable": false
        },
        {
          "name": "job_name",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "message",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "run_started_at",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "status",
          "kind": "string",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": {
        "family": "teleclaude.job.run",
        "state": "succeeded",
        "standing": "ok"
      }
    },
    {
      "name": "teleclaude.node.alive",
      "version": 1,
      "description": "Node heartbeat or presence announcement",
      "subject_kind": "computer",
      "home_kinds": [],
      "data_fields": [],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "teleclaude.node.descriptor_updated",
      "version": 1,
      "description": "Node metadata or capabilities changed",
      "subject_kind": "computer",
      "home_kinds": [],
      "data_fields": [],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "teleclaude.node.leaving",
      "version": 1,
      "description": "Node is departing the cluster gracefully",
      "subject_kind": "computer",
      "home_kinds": [],
      "data_fields": [],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "teleclaude.notification.escalation",
      "version": 1,
      "description": "An issue was escalated to a human for action",
      "subject_kind": "escalation",
      "home_kinds": [
        "project",
        "person",
        "company"
      ],
      "data_fields": [
        {
          "name": "escalation_id",
          "kind": "any",
          "nullable": true
        },
        {
          "name": "reason",
          "kind": "any",
          "nullable": true
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "teleclaude.notification.resolution",
      "version": 1,
      "description": "An escalation was resolved",
      "subject_kind": "escalation",
      "home_kinds": [
        "project",
        "person",
        "company"
      ],
      "data_fields": [
        {
          "name": "escalation_id",
          "kind": "any",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "teleclaude.scheduler.tick.minute",
      "version": 1,
      "description": "Daemon minute wake-up for schedule-gated workflow evaluation",
      "subject_kind": "computer",
      "home_kinds": [],
      "data_fields": [
        {
          "name": "computer",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "ticked_at",
          "kind": "string",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "teleclaude.schema.adopted",
      "version": 1,
      "description": "A proposed schema change was merged and is now active",
      "subject_kind": "schema_proposal",
      "home_kinds": [],
      "data_fields": [],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "teleclaude.schema.proposed",
      "version": 1,
      "description": "A schema change was proposed for adoption",
      "subject_kind": "schema_proposal",
      "home_kinds": [],
      "data_fields": [],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "teleclaude.signal.cluster.formed",
      "version": 1,
      "description": "A group of related ingested signals formed a cluster.",
      "subject_kind": "signal_cluster",
      "home_kinds": [],
      "data_fields": [
        {
          "name": "cluster_id",
          "kind": "integer",
          "nullable": false
        },
        {
          "name": "is_burst",
          "kind": "boolean",
          "nullable": false
        },
        {
          "name": "is_novel",
          "kind": "boolean",
          "nullable": false
        },
        {
          "name": "member_count",
          "kind": "integer",
          "nullable": false
        },
        {
          "name": "summary",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "tags",
          "kind": "array",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "teleclaude.signal.ingest.received",
      "version": 1,
      "description": "A single feed item was ingested and normalised.",
      "subject_kind": "signal_item",
      "home_kinds": [],
      "data_fields": [
        {
          "name": "fetched_at",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "item_url",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "published_at",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "raw_title",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "source_id",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "tags",
          "kind": "array",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "teleclaude.signal.synthesis.ready",
      "version": 1,
      "description": "A cluster has been synthesised into a structured artifact.",
      "subject_kind": "signal_synthesis",
      "home_kinds": [],
      "data_fields": [
        {
          "name": "cluster_id",
          "kind": "integer",
          "nullable": false
        },
        {
          "name": "synthesis",
          "kind": "object",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "teleclaude.system.burst.detected",
      "version": 1,
      "description": "A burst of events of the same type was detected within a short window",
      "subject_kind": "event_type",
      "home_kinds": [
        "project",
        "person",
        "company"
      ],
      "data_fields": [
        {
          "name": "count",
          "kind": "integer",
          "nullable": false
        },
        {
          "name": "event_type",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "window_start",
          "kind": "string",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": {
        "family": "teleclaude.system.burst",
        "state": "detected",
        "standing": "failing"
      }
    },
    {
      "name": "teleclaude.system.burst.subsided",
      "version": 1,
      "description": "Events of a type that burst no longer reach the burst threshold within the detection window",
      "subject_kind": "event_type",
      "home_kinds": [
        "project",
        "person",
        "company"
      ],
      "data_fields": [
        {
          "name": "episode_start",
          "kind": "string",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": {
        "family": "teleclaude.system.burst",
        "state": "subsided",
        "standing": "ok"
      }
    },
    {
      "name": "teleclaude.system.daemon.restarted",
      "version": 1,
      "description": "Daemon process restarted on a computer",
      "subject_kind": "computer",
      "home_kinds": [],
      "data_fields": [
        {
          "name": "computer",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "pid",
          "kind": "integer",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "teleclaude.system.entity.degraded",
      "version": 1,
      "description": "Repeated failures detected for the same thing within a short window",
      "subject_kind": null,
      "home_kinds": [
        "project",
        "person",
        "company"
      ],
      "data_fields": [
        {
          "name": "entity",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "failure_count",
          "kind": "integer",
          "nullable": false
        },
        {
          "name": "window_start",
          "kind": "string",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": {
        "family": "teleclaude.system.entity",
        "state": "degraded",
        "standing": "failing"
      }
    },
    {
      "name": "teleclaude.system.entity.recovered",
      "version": 1,
      "description": "None of a degraded thing's failing event types reaches the degradation threshold any more",
      "subject_kind": null,
      "home_kinds": [
        "project",
        "person",
        "company"
      ],
      "data_fields": [
        {
          "name": "episode_start",
          "kind": "string",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": {
        "family": "teleclaude.system.entity",
        "state": "recovered",
        "standing": "ok"
      }
    },
    {
      "name": "teleclaude.system.event.dead_lettered",
      "version": 1,
      "description": "An event exhausted its retry ceiling and transitioned to the dead-letter destination",
      "subject_kind": "stream_entry",
      "home_kinds": [],
      "data_fields": [
        {
          "name": "attempt_count",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "consumer",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "consumer_id",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "dlq_destination",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "failing_stage",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "original_entry_id",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "original_stream",
          "kind": "string",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "teleclaude.system.failure_cascade.detected",
      "version": 1,
      "description": "Multiple worker crashes detected within a short window",
      "subject_kind": "computer",
      "home_kinds": [],
      "data_fields": [
        {
          "name": "crash_count",
          "kind": "integer",
          "nullable": false
        },
        {
          "name": "window_start",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "workers",
          "kind": "array",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": {
        "family": "teleclaude.system.failure_cascade",
        "state": "detected",
        "standing": "failing"
      }
    },
    {
      "name": "teleclaude.system.failure_cascade.subsided",
      "version": 1,
      "description": "Worker crashes no longer reach the failure-cascade threshold within the detection window",
      "subject_kind": "computer",
      "home_kinds": [],
      "data_fields": [
        {
          "name": "episode_start",
          "kind": "string",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": {
        "family": "teleclaude.system.failure_cascade",
        "state": "subsided",
        "standing": "ok"
      }
    },
    {
      "name": "teleclaude.system.process.reaped",
      "version": 1,
      "description": "Process janitor reaped or observed a reapable process",
      "subject_kind": "computer",
      "home_kinds": [],
      "data_fields": [
        {
          "name": "lease_expires_at",
          "kind": "string",
          "nullable": true
        },
        {
          "name": "observe_only",
          "kind": "boolean",
          "nullable": false
        },
        {
          "name": "owner",
          "kind": "string",
          "nullable": true
        },
        {
          "name": "pid",
          "kind": "integer",
          "nullable": false
        },
        {
          "name": "reason",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "signature_id",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "signature_name",
          "kind": "string",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "teleclaude.system.session.bootstrap_failed",
      "version": 1,
      "description": "A session's tmux/identity bootstrap failed, stranding it before it reached active",
      "subject_kind": "session",
      "home_kinds": [
        "project",
        "person",
        "company"
      ],
      "data_fields": [
        {
          "name": "project_path",
          "kind": "string",
          "nullable": true
        },
        {
          "name": "reason",
          "kind": "string",
          "nullable": false
        },
        {
          "name": "session_id",
          "kind": "string",
          "nullable": false
        }
      ],
      "related_kinds": [
        "session"
      ],
      "state": null
    },
    {
      "name": "teleclaude.system.worker.crashed",
      "version": 1,
      "description": "A background worker crashed unexpectedly",
      "subject_kind": "computer",
      "home_kinds": [],
      "data_fields": [],
      "related_kinds": [
        "session"
      ],
      "state": null
    }
  ]
}
```

