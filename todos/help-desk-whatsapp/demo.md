# Demo: help-desk-whatsapp

## Medium

WhatsApp (customer-facing) + TeleClaude TUI/Discord (operator-facing) + CLI (`telec config`).

Demo follows a linear walkthrough: account setup, credential provisioning, configuration, webhook wiring, template creation, then functional scenarios with validation.

---

## Part 1: WhatsApp Business Account Setup

### Step 1.1: Create a Meta Developer Account

**What the operator does:**

1. Go to [Meta for Developers](https://developers.facebook.com/) and log in (or create an account).
2. Accept the Meta Platform Terms.
3. In the top nav, click **My Apps** > **Create App**.
4. Select **Business** as the app type.
5. Enter an app name (e.g., "TeleClaude Support") and contact email.
6. Click **Create App**.

**What the operator observes:**

- The Meta App Dashboard opens for the new app.
- The App ID is visible in the top bar (e.g., `123456789012345`).

### Step 1.2: Add WhatsApp to the App

**What the operator does:**

1. In the App Dashboard, scroll to **Add Products to Your App**.
2. Find **WhatsApp** and click **Set Up**.
3. If prompted, select or create a Meta Business Account.
4. The WhatsApp Getting Started page opens with a test phone number.

**What the operator observes:**

- A temporary test phone number is provisioned (can only message numbers added to the "To" list).
- The **Phone Number ID** is visible on the Getting Started page (e.g., `109876543210`).
- A temporary **Access Token** is displayed (valid ~24h; you'll generate a permanent one in Step 1.4).

### Step 1.3: Add a Test Recipient

**What the operator does:**

1. On the Getting Started page, under **Send and receive messages**, click **To** dropdown > **Manage phone number list**.
2. Enter the WhatsApp number you want to test with (your personal number).
3. Verify via the OTP code sent to that number.

**What the operator observes:**

- The test number appears in the **To** dropdown and can receive messages from the API.

### Step 1.4: Generate a Permanent System User Token

**What the operator does:**

1. Go to [Meta Business Suite](https://business.facebook.com/) > **Settings** > **Users** > **System Users**.
2. Click **Add** to create a system user (name: "TeleClaude API", role: Admin).
3. Click **Generate New Token** for this system user.
4. Select the app created in Step 1.1.
5. Under permissions, enable: `whatsapp_business_messaging`, `whatsapp_business_management`.
6. Set token expiration to **Never** (for production use).
7. Click **Generate Token** and **copy the token immediately** (it won't be shown again).

**What the operator observes:**

- A long access token string (starts with `EAA...`).

> **Save this token.** You will enter it in TeleClaude config in Step 2.1.

### Step 1.5: Create a Verify Token

**What the operator does:**

- Generate a random string to use as your webhook verify token. This can be anything you choose:

```bash
openssl rand -hex 32
```

**What the operator observes:**

- A 64-character hex string (e.g., `a3b8c1d4e5f6...`).

> **Save this token.** You will enter it in TeleClaude config in Step 2.1 and Meta Dashboard in Step 3.1.

---

## Part 2: Configure TeleClaude

### Step 2.1: Enter WhatsApp Credentials

**What the operator does:**

Provide the following values to the AI assistant (or enter them via `telec config`):

| Value           | Source                     | Example           |
| --------------- | -------------------------- | ----------------- |
| Phone Number ID | Step 1.2 Getting Started   | `109876543210`    |
| Access Token    | Step 1.4 System User       | `EAAxxxxxxx...`   |
| Verify Token    | Step 1.5 Generated string  | `a3b8c1d4e5f6...` |
| Webhook Secret  | App Dashboard > App Secret | `abc123def456...` |

The AI writes these to `teleclaude.yml` under the `whatsapp` section:

```yaml
whatsapp:
  enabled: true
  phone_number_id: '109876543210'
  access_token: '${WHATSAPP_ACCESS_TOKEN}'
  verify_token: 'a3b8c1d4e5f6...'
  webhook_secret: '${WHATSAPP_WEBHOOK_SECRET}'
  api_version: 'v21.0'
```

For the access token and webhook secret, set them as environment variables (avoids secrets in YAML):

```bash
telec config env set WHATSAPP_ACCESS_TOKEN "EAAxxxxxxx..."
telec config env set WHATSAPP_WEBHOOK_SECRET "abc123def456..."
```

**Validation:**

```bash
# Verify config was written
telec config get whatsapp

# Verify env vars are set
telec config env list | grep WHATSAPP
```

### Step 2.2: Register a Known Customer (Optional)

**What the operator does:**

Add a person entry with a WhatsApp phone number for identity resolution:

```bash
telec config people add --name "Demo Customer" --role member
```

Then edit the person's credentials to include their WhatsApp number:

```yaml
# In teleclaude.yml under people:
- name: Demo Customer
  role: member
  creds:
    whatsapp:
      phone_number: '14155551234' # E.164, no + prefix
```

**What the operator observes:**

- The person appears in `telec config people` output with WhatsApp credentials.

**Validation:**

```bash
telec config people
```

### Step 2.3: Configure a Message Template (Required for 24h Window)

**What the operator does:**

1. In Meta App Dashboard, go to **WhatsApp** > **Message Templates**.
2. Click **Create Template**.
3. Category: **Utility**. Name: `session_followup`. Language: `en_US`.
4. Body: `"Hi {{1}}, we have an update on your support request. Please reply to continue the conversation."`
5. Submit for approval (usually approved within minutes for utility templates).

Then add the template name to TeleClaude config:

```yaml
whatsapp:
  # ... existing fields ...
  template_name: 'session_followup'
  template_language: 'en_US'
```

**Validation:**

- In Meta Dashboard, template status shows **Approved**.

```bash
telec config get whatsapp.template_name
```

### Step 2.4: Restart the Daemon

**What the operator does:**

```bash
make restart
```

**What the operator observes:**

- Daemon restarts. WhatsApp adapter initializes.

**Validation:**

```bash
make status

# Check daemon logs for WhatsApp adapter startup
instrukt-ai-logs teleclaude --since 1m --grep "whatsapp"
```

Expected log output includes: `WhatsApp adapter started` (or similar adapter initialization message).

---

## Part 3: Webhook Wiring

### Step 3.1: Configure the Webhook URL in Meta Dashboard

**What the operator does:**

1. In Meta App Dashboard, go to **WhatsApp** > **Configuration**.
2. Under **Webhook**, click **Edit**.
3. Enter the callback URL: `https://<your-domain>/hooks/whatsapp`
   - This must be a publicly reachable HTTPS endpoint.
   - If testing locally, use a tunnel (e.g., ngrok, Cloudflare Tunnel).
4. Enter the **Verify Token** from Step 1.5.
5. Click **Verify and Save**.

**What the operator observes:**

- Meta sends a GET verification challenge to the callback URL.
- TeleClaude's inbound hook service responds with the challenge string.
- The webhook shows as **Verified** in the dashboard.

6. Under **Webhook fields**, subscribe to: `messages` (required).

**Validation:**

```bash
# Check daemon logs for verification challenge
instrukt-ai-logs teleclaude --since 2m --grep "verify"
```

### Step 3.2: Verify End-to-End Connectivity

**What the operator does:**

- Send a test message from the WhatsApp Getting Started page:
  1. In Meta App Dashboard > WhatsApp > Getting Started
  2. Select a message template (e.g., `hello_world`)
  3. Send to your test number from Step 1.3

**What the operator observes:**

- The template message arrives on the test phone's WhatsApp.

**Validation:**

```bash
# Check daemon logs for outbound API call
instrukt-ai-logs teleclaude --since 2m --grep "whatsapp"
```

---

## Part 4: Functional Scenarios

### Scenario 4.1: Customer Sends First Message

**What the customer does:**

- Opens WhatsApp and sends "Hi, I need help with my account" to the TeleClaude business number.

**What happens behind the scenes:**

1. Meta delivers the webhook to `/hooks/whatsapp`.
2. The WhatsApp normalizer parses `entry[0].changes[0].value.messages[0]`.
3. Identity resolution: `whatsapp:14155551234` resolves to "Demo Customer" (or `customer` role if unknown).
4. A new customer session is created in the help desk workspace.
5. The AI agent receives the message and generates a response.
6. The response is sent back via `POST /{phone_number_id}/messages`.

**What the customer observes:**

- Blue ticks (read receipt) appear almost immediately after sending.
- The AI's response arrives within seconds.

**What the operator observes:**

- A new session appears in `telec list --all` with WhatsApp origin.
- The session is visible in the TUI session list.
- If Discord is configured, the session appears in the help desk forum.

**Validation:**

```bash
# Verify session was created
telec list --all | grep whatsapp

# Check daemon logs for the full flow
instrukt-ai-logs teleclaude --since 5m --grep "customer"
```

### Scenario 4.2: Voice Message Transcription

**What the customer does:**

- Sends a voice note via WhatsApp (hold the mic button and speak).

**What happens behind the scenes:**

1. Webhook delivers message with `type: "audio"` and `voice: true`.
2. Adapter downloads the voice note: `GET /{media_id}` for URL, then downloads from the temporary URL.
3. Audio file (OGG/Opus) is saved to the session workspace.
4. Whisper transcription pipeline converts audio to text.
5. Transcribed text is injected into the AI session context.

**What the customer observes:**

- Blue ticks on the voice note.
- AI responds based on the spoken content.

**Validation:**

```bash
# Check workspace for downloaded audio file
ls /tmp/teleclaude-workspaces/*/
```

### Scenario 4.3: Image/Document Sharing

**What the customer does:**

- Sends a screenshot or PDF document via WhatsApp.

**What happens behind the scenes:**

1. Webhook delivers message with `type: "image"` or `type: "document"`.
2. Adapter calls `GET /{media_id}` to get the download URL (expires in ~5 minutes).
3. File is downloaded with Bearer token authentication.
4. File is saved to the session workspace.

**What the customer observes:**

- Blue ticks on the media message.
- AI acknowledges the file and can reference its content.

**What the operator observes:**

- The file appears in the session workspace directory.

### Scenario 4.4: Escalation to Human Operator

**What happens:**

1. During the AI conversation, the agent determines escalation is needed and calls `telec sessions escalate()`.
2. A Discord escalation thread is created with conversation context summary.
3. The session enters relay mode.

**What the customer observes:**

- Subsequent messages are forwarded to the Discord relay thread.
- Admin replies in Discord appear as WhatsApp messages from the business number.

**What the operator observes:**

- Escalation thread appears in Discord escalation forum.
- Operator replies in the thread are relayed to WhatsApp.
- Operator tags `@agent` to hand back to AI.

**Validation:**

```bash
# Check escalation status
instrukt-ai-logs teleclaude --since 5m --grep "escalat"
```

### Scenario 4.5: 24-Hour Window Boundary

**Setup:** Wait 24+ hours after the last customer message (or simulate by setting `last_customer_message_at` to >24h ago in adapter metadata).

**What happens:**

1. AI attempts to send a follow-up message.
2. Adapter detects the 24h window has expired.
3. Instead of free-form text, the adapter sends the configured template message (`session_followup`).
4. If no template is configured, the message is not sent and a warning is logged.

**What the customer observes:**

- Receives the template message (not free-form text).
- Replying reopens the 24h service window.

**Validation:**

```bash
# Check daemon logs for template usage
instrukt-ai-logs teleclaude --since 5m --grep "template"
```

### Scenario 4.6: Identity Resolution

**What the operator verifies:**

1. A message from a phone number in people config (Step 2.2) resolves to the configured person and role.
2. A message from an unknown phone number gets the `customer` role automatically.
3. Session metadata shows the resolved identity.

**Validation:**

```bash
# Check people config for WhatsApp credentials
telec config people

# Compare session metadata with expected identity
telec list --all
```

---

## Part 5: Teardown (Test Environment)

After the demo:

1. In Meta App Dashboard, remove the webhook subscription (optional — sandbox doesn't auto-send).
2. Revoke the test access token if it was temporary.
3. Remove test environment variables:

```bash
telec config env set WHATSAPP_ACCESS_TOKEN ""
telec config env set WHATSAPP_WEBHOOK_SECRET ""
```

4. Disable the adapter in config:

```yaml
whatsapp:
  enabled: false
```

5. Restart: `make restart`

---

## Checklist

| Step | Description                          | Verified |
| ---- | ------------------------------------ | -------- |
| 1.1  | Meta Developer account created       | [ ]      |
| 1.2  | WhatsApp product added, phone ID     | [ ]      |
| 1.3  | Test recipient added                 | [ ]      |
| 1.4  | Permanent access token generated     | [ ]      |
| 1.5  | Verify token created                 | [ ]      |
| 2.1  | Credentials in teleclaude.yml + env  | [ ]      |
| 2.2  | Known customer registered (optional) | [ ]      |
| 2.3  | Message template created & approved  | [ ]      |
| 2.4  | Daemon restarted, adapter running    | [ ]      |
| 3.1  | Webhook verified in Meta Dashboard   | [ ]      |
| 3.2  | End-to-end connectivity confirmed    | [ ]      |
| 4.1  | Customer first message → AI reply    | [ ]      |
| 4.2  | Voice message → transcription        | [ ]      |
| 4.3  | Image/document → workspace           | [ ]      |
| 4.4  | Escalation → Discord relay           | [ ]      |
| 4.5  | 24h window → template fallback       | [ ]      |
| 4.6  | Identity resolution correct          | [ ]      |
