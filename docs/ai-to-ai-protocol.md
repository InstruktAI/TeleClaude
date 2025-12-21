# AI-to-AI Collaboration Protocol

This document specifies the protocol for communication and collaboration between AI agents within the TeleClaude system. This protocol ensures efficient, clear, and standardized interactions when one AI delegates tasks to another.

## Example Flows

### Delegating a Task

1.  **Master AI**: Identifies a task to delegate to a worker AI.
2.  **Master AI**: Calls `teleclaude__run_agent_command(computer='remote_machine', project_dir='/path/to/project', title='Worker Task', agent='codex', command='/next-work')`. This initiates a new session for the worker AI and sends the initial command.
3.  **Worker AI**: Receives the `/next-work` command from the master AI.
4.  **Worker AI**: Proceeds to execute its internal workflow for `/next-work`.
5.  **Master AI**: Can optionally monitor the worker's progress using `teleclaude__get_session_data(computer='remote_machine', session_id='worker_session_id')`.
6.  **Worker AI**: Completes its task and its session stops.
7.  **Master AI**: Is automatically notified of the worker session's completion.

### Long-Running Task with Health Check

1.  **Master AI**: Delegates a long-running task to a worker AI.
2.  **Worker AI**: Starts executing the task.
3.  **Master AI**: After a predefined interval (e.g., 10 minutes), calls `teleclaude__get_session_data(computer='worker_machine', session_id='worker_session_id')`.

This protocol aims to streamline AI-to-AI interactions, ensuring clarity, autonomy for worker AIs, and effective monitoring for master AIs.
