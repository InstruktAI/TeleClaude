# AI-to-AI Collaboration Protocol

This document specifies the protocol for communication and collaboration between AI agents within the TeleClaude system. This protocol ensures efficient, clear, and standardized interactions when one AI delegates tasks to another.

## Message Format

All messages originating from one AI agent and intended for another AI agent MUST adhere to the following format:

```
AI[computer:session_id] | message content here
```

### Fields:

- **`AI`**: A literal string indicating the message originates from an AI agent.
- **`computer`**: The name of the computer where the sending AI agent's session is running. This can be:
    - `"local"`: If the sending agent is on the same machine as the receiving agent.
    - A specific remote computer name (e.g., `"workstation"`, `"server"`, `"raspi"`).
- **`session_id`**: The unique UUID of the sending AI agent's session. This allows the receiving agent to identify the origin of the request and potentially reply or update the status of the delegating session if necessary.
- **`|`**: A literal pipe character acting as a separator between the header (sender identification) and the actual message content.
- **`message content here`**: The actual task, command, or information being conveyed by the sending AI agent to the receiving AI agent.

### Example:

```
AI[local:f1a2b3c4-d5e6-7890-1234-567890abcdef] | /next-work
```

In this example:
- The message is from an AI.
- The sending AI's session is running on the local computer.
- The session ID of the sending AI is `f1a2b3c4-d5e6-7890-1234-567890abcdef`.
- The message content is the command `/next-work`, indicating a request for the receiving AI to proceed with its next task.

## Collaboration Protocol

When an AI agent receives a message prefixed with `AI[...]`, it signifies that the message is from another AI, not a human user. The receiving AI MUST follow these guidelines:

1.  **Recognize AI Origin**: Immediately identify the message as originating from another AI based on the `AI[...]` prefix.
2.  **Execute Task**: Understand and complete the requested task specified in the `message content`.
3.  **Automatic Completion Notification**: The calling AI (sender) is automatically notified when the receiving AI's session stops (e.g., after completing the task or encountering a terminal error). The receiving AI does NOT need to explicitly send a completion message back to the sender.
4.  **Health Checks**: For long-running tasks (typically exceeding 10 minutes), the sending AI may issue a health check message to the receiving AI. If such a message is received, the working AI SHOULD use `teleclaude__send_message` to report its progress, and then continue with its work.
5.  **Session Lifecycle Management**:
    -   **`teleclaude__stop_notifications(computer, session_id)`**: The calling AI can use this to unsubscribe from a worker session's events without terminating the session. This is useful when the master AI no longer needs to monitor a completed worker.
    -   **`teleclaude__end_session(computer, session_id)`**: The calling AI can use this to gracefully terminate a worker session. This is typically used when a worker has completed its work, exhausted its context, or needs to be replaced.

## Example Flows

### Delegating a Task

1.  **Master AI**: Identifies a task to delegate to a worker AI.
2.  **Master AI**: Calls `teleclaude__start_session(computer='remote_machine', project_dir='/path/to/project', title='Worker Task', message='/next-work')`. This initiates a new session for the worker AI and sends the initial command.
3.  **Worker AI**: Receives the `/next-work` command from the master AI.
4.  **Worker AI**: Proceeds to execute its internal workflow for `/next-work`.
5.  **Master AI**: Can optionally monitor the worker's progress using `teleclaude__get_session_data(computer='remote_machine', session_id='worker_session_id')`.
6.  **Worker AI**: Completes its task and its session stops.
7.  **Master AI**: Is automatically notified of the worker session's completion.

### Long-Running Task with Health Check

1.  **Master AI**: Delegates a long-running task to a worker AI.
2.  **Worker AI**: Starts executing the task.
3.  **Master AI**: After a predefined interval (e.g., 10 minutes), sends a health check message: `teleclaude__send_message(computer='worker_machine', session_id='worker_session_id', message='AI[master_computer:master_session_id] | Status check: Are you still working on X?')`.
4.  **Worker AI**: Receives the health check.
5.  **Worker AI**: Responds with a status update: `teleclaude__send_message(computer='master_computer', session_id='master_session_id', message='AI[worker_computer:worker_session_id] | Progress update: Currently at step 3 of 5, ETA 5 more minutes.')`.
6.  **Worker AI**: Continues its task.
7.  **Master AI**: Receives the update and continues monitoring.

This protocol aims to streamline AI-to-AI interactions, ensuring clarity, autonomy for worker AIs, and effective monitoring for master AIs.
