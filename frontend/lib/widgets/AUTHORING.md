# Widget Expression Format — Authoring Guide

Use `telec sessions widget` to render structured UI in the web interface.
Non-web adapters (Telegram, terminal) receive a text summary with file attachments.

## Tool Call

```json
{
  "name": "telec sessions widget",
  "arguments": {
    "session_id": "<current session>",
    "data": { ... }
  }
}
```

## Expression Format

The `data` object is the widget expression:

| Field         | Type      | Required | Description                                                 |
| ------------- | --------- | -------- | ----------------------------------------------------------- |
| `name`        | string    | no       | Library slug (e.g. `person-details-form`). Triggers storage |
| `title`       | string    | no       | Display heading                                             |
| `description` | string    | no       | Agent-facing note. Not rendered; stored with library entry  |
| `hints`       | object    | no       | Freeform rendering hints (`compact`, `collapsible`, etc.)   |
| `sections`    | Section[] | **yes**  | Ordered content array                                       |
| `footer`      | string    | no       | Closing text below all sections                             |
| `status`      | string    | no       | Card treatment: `info`, `success`, `warning`, `error`       |

## Section Types

Every section has these common fields:

| Field     | Type   | Required | Description                                                      |
| --------- | ------ | -------- | ---------------------------------------------------------------- |
| `type`    | string | **yes**  | Section type discriminator                                       |
| `id`      | string | no       | Reference ID                                                     |
| `label`   | string | no       | Heading above the section content                                |
| `variant` | string | no       | Visual treatment: `info`, `success`, `warning`, `error`, `muted` |

### text

Markdown text block.

```json
{ "type": "text", "content": "## Heading\n\nParagraph with **bold** text." }
```

| Field     | Type   | Required |
| --------- | ------ | -------- |
| `content` | string | **yes**  |

### input

Form with typed fields. User submits values as a message to the agent.

```json
{
  "type": "input",
  "fields": [
    { "name": "email", "label": "Email", "input": "text", "required": true, "placeholder": "you@example.com" },
    { "name": "role", "label": "Role", "input": "select", "options": ["Admin", "Editor", "Viewer"] },
    { "name": "notify", "label": "Notifications", "input": "checkbox", "helpText": "Send email alerts" }
  ]
}
```

**InputField:**

| Field         | Type     | Required | Description                                    |
| ------------- | -------- | -------- | ---------------------------------------------- |
| `name`        | string   | **yes**  | Field key in submitted values                  |
| `label`       | string   | **yes**  | Display label                                  |
| `input`       | string   | **yes**  | `text`, `select`, `checkbox`, `number`, `date` |
| `options`     | string[] | no       | Choices for `select` input                     |
| `required`    | boolean  | no       | Mark field required                            |
| `placeholder` | string   | no       | Placeholder text                               |
| `default`     | string   | no       | Default value                                  |
| `helpText`    | string   | no       | Help text below field                          |
| `disabled`    | boolean  | no       | Disable field                                  |
| `readonly`    | boolean  | no       | Read-only field                                |
| `width`       | string   | no       | `half` or `full`                               |
| `validation`  | object   | no       | `{ min?, max?, pattern?, message? }`           |

### actions

Button row. Click sends `"Action: {button.action}"` as a message to the agent.

```json
{
  "type": "actions",
  "layout": "horizontal",
  "buttons": [
    { "label": "Approve", "action": "approve", "style": "primary" },
    { "label": "Reject", "action": "reject", "style": "destructive", "confirm": "Are you sure?" }
  ]
}
```

**Button:**

| Field      | Type    | Required | Description                                     |
| ---------- | ------- | -------- | ----------------------------------------------- |
| `label`    | string  | **yes**  | Button text                                     |
| `action`   | string  | **yes**  | Action identifier sent to agent                 |
| `style`    | string  | no       | `primary` (default), `secondary`, `destructive` |
| `icon`     | string  | no       | Icon name                                       |
| `disabled` | boolean | no       | Disable button                                  |
| `confirm`  | string  | no       | Confirmation prompt before sending              |

**Layout:** `horizontal` (default) or `vertical`.

### image

Inline image served from session workspace.

```json
{ "type": "image", "src": "output/chart.png", "alt": "Revenue chart", "caption": "Q4 2025" }
```

| Field     | Type   | Required | Description                        |
| --------- | ------ | -------- | ---------------------------------- |
| `src`     | string | **yes**  | Path relative to session workspace |
| `alt`     | string | no       | Alt text                           |
| `caption` | string | no       | Caption below image                |
| `width`   | number | no       | Display width in pixels            |
| `height`  | number | no       | Display height in pixels           |

### table

Data table from headers and rows.

```json
{
  "type": "table",
  "headers": ["Name", "Status", "Count"],
  "rows": [
    ["Service A", "Running", 42],
    ["Service B", "Stopped", 0]
  ],
  "caption": "Service status"
}
```

| Field      | Type                 | Required | Description           |
| ---------- | -------------------- | -------- | --------------------- |
| `headers`  | string[]             | **yes**  | Column headers        |
| `rows`     | (string\|number)[][] | **yes**  | Row data              |
| `caption`  | string               | no       | Table caption         |
| `sortable` | boolean              | no       | Enable column sorting |
| `maxRows`  | number               | no       | Max visible rows      |

### file

Download link for a file in the session workspace.

```json
{ "type": "file", "path": "output/report.pdf", "label": "Download Report", "size": 204800 }
```

| Field   | Type   | Required | Description                         |
| ------- | ------ | -------- | ----------------------------------- |
| `path`  | string | **yes**  | Path relative to session workspace  |
| `label` | string | no       | Display name (defaults to filename) |
| `size`  | number | no       | File size in bytes                  |
| `mime`  | string | no       | MIME type                           |

### code

Syntax-highlighted code block.

```json
{ "type": "code", "language": "python", "content": "def hello():\n    print('world')", "title": "Example" }
```

| Field         | Type    | Required | Description                   |
| ------------- | ------- | -------- | ----------------------------- |
| `content`     | string  | **yes**  | Code text                     |
| `language`    | string  | no       | Language for syntax highlight |
| `title`       | string  | no       | Block title                   |
| `collapsible` | boolean | no       | Collapse by default           |

### divider

Horizontal rule separator.

```json
{ "type": "divider" }
```

No additional fields.

## Adapter Rendering

| Adapter      | Behavior                                                          |
| ------------ | ----------------------------------------------------------------- |
| **Web**      | Full rich rendering: cards, forms, buttons, inline images, tables |
| **Telegram** | Text summary of all sections + file attachments for images/files  |
| **Terminal** | Text summary only                                                 |

Agents describe intent through the expression format. Each adapter translates to its capabilities.

## Library Storage

Set `name` on the expression to automatically store it in the widget library:

```json
{
  "name": "service-dashboard",
  "title": "Service Dashboard",
  "description": "Live service status overview",
  "sections": [ ... ]
}
```

Stored to `widgets/{name}.json`. The index at `widgets/index.json` tracks all entries for discovery.

## Example Compositions

### Notification with actions

```json
{
  "data": {
    "title": "Deployment Complete",
    "status": "success",
    "sections": [
      { "type": "text", "content": "Version **2.4.1** deployed to production." },
      {
        "type": "actions",
        "buttons": [
          { "label": "View Logs", "action": "view_logs", "style": "secondary" },
          {
            "label": "Rollback",
            "action": "rollback",
            "style": "destructive",
            "confirm": "Roll back to previous version?"
          }
        ]
      }
    ]
  }
}
```

### Onboarding form

```json
{
  "data": {
    "title": "New Team Member",
    "sections": [
      { "type": "text", "content": "Fill in the details for the new team member." },
      {
        "type": "input",
        "fields": [
          { "name": "name", "label": "Full Name", "input": "text", "required": true },
          { "name": "email", "label": "Email", "input": "text", "required": true },
          { "name": "role", "label": "Role", "input": "select", "options": ["Engineer", "Designer", "PM"] },
          { "name": "admin", "label": "Admin Access", "input": "checkbox", "helpText": "Grant admin privileges" }
        ]
      }
    ]
  }
}
```

### Data report with download

```json
{
  "data": {
    "title": "Monthly Report",
    "sections": [
      { "type": "text", "content": "Summary for **January 2026**." },
      {
        "type": "table",
        "headers": ["Metric", "Value", "Change"],
        "rows": [
          ["Revenue", "$142,000", "+12%"],
          ["Users", "8,421", "+340"],
          ["Uptime", "99.97%", "+0.02%"]
        ]
      },
      { "type": "divider" },
      { "type": "file", "path": "output/report-2026-01.pdf", "label": "Full Report PDF", "size": 524288 }
    ]
  }
}
```

### Image gallery

```json
{
  "data": {
    "title": "Generated Charts",
    "sections": [
      { "type": "image", "src": "output/revenue.png", "alt": "Revenue trend", "caption": "Revenue over 12 months" },
      { "type": "image", "src": "output/users.png", "alt": "User growth", "caption": "Active users" },
      { "type": "divider" },
      { "type": "file", "path": "output/charts.zip", "label": "Download All Charts" }
    ]
  }
}
```
