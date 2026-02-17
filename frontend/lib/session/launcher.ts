/**
 * Session creation orchestration.
 *
 * Handles the full lifecycle of creating a new TeleClaude session via the daemon API.
 * Does NOT handle tmux attachment - that's the caller's responsibility.
 */

import { TelecAPIClient, APIError } from "@/lib/api/client.js";
import type {
  CreateSessionRequest,
  CreateSessionResponse,
  SessionInfo,
  AgentName,
  ThinkingMode,
} from "@/lib/api/types.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface LaunchSessionParams {
  computer: string;
  projectPath: string;
  agent: AgentName;
  thinkingMode: ThinkingMode;
  title?: string;
  message?: string;
  subfolder?: string;
}

export interface LaunchResult {
  success: boolean;
  session?: SessionInfo;
  error?: string;
}

// ---------------------------------------------------------------------------
// Session Launcher
// ---------------------------------------------------------------------------

/**
 * Create a new TeleClaude session via the daemon API.
 *
 * This function:
 * - Builds the API request from params
 * - Calls the daemon to spawn tmux + agent
 * - Returns session info on success
 * - Handles all error cases gracefully (never throws)
 *
 * Error cases:
 * - Daemon down (connection error)
 * - Agent unavailable (API returns error)
 * - Project not found (API returns error)
 * - Generic API errors
 *
 * @param params Session creation parameters
 * @returns LaunchResult with success/error status
 */
export async function launchSession(params: LaunchSessionParams): Promise<LaunchResult> {
  const client = new TelecAPIClient();

  // Build API request
  const request: CreateSessionRequest = {
    computer: params.computer,
    project_path: params.projectPath,
    agent: params.agent,
    thinking_mode: params.thinkingMode,
    title: params.title ?? null,
    message: params.message ?? null,
    subdir: params.subfolder ?? null,
  };

  try {
    // Call daemon API (30s timeout for session spawn)
    const response: CreateSessionResponse = await client.createSession(request);

    // Check response status
    if (response.status === "error") {
      return {
        success: false,
        error: response.error ?? "Session creation failed (no error details)",
      };
    }

    // Success - build SessionInfo from response
    // Note: createSession returns CreateSessionResponse, but we need to fetch full SessionInfo
    // The response gives us session_id and tmux_session_name, but not the full SessionInfo
    // For now, we'll construct a minimal SessionInfo from the response
    const session: SessionInfo = {
      session_id: response.session_id,
      tmux_session_name: response.tmux_session_name,
      title: params.title ?? "",
      project_path: params.projectPath,
      subdir: params.subfolder ?? null,
      thinking_mode: params.thinkingMode,
      active_agent: response.agent ?? params.agent,
      status: "running",
      computer: params.computer,
      created_at: new Date().toISOString(),
      last_activity: new Date().toISOString(),
      last_input_origin: null,
      last_input: null,
      last_input_at: null,
      last_output_summary: null,
      last_output_summary_at: null,
      last_output_digest: null,
      native_session_id: null,
      initiator_session_id: null,
      human_email: null,
      human_role: null,
    };

    return {
      success: true,
      session,
    };
  } catch (err) {
    // Handle connection errors (daemon down)
    if (err instanceof APIError) {
      const errorMsg = err.detail || err.message;

      // Classify error types for better user feedback
      if (errorMsg.includes("Connection") || errorMsg.includes("ENOENT")) {
        return {
          success: false,
          error: "Daemon is not running. Please start it with 'make restart'.",
        };
      }

      if (errorMsg.includes("unavailable") || errorMsg.includes("agent")) {
        return {
          success: false,
          error: `Agent "${params.agent}" is unavailable: ${errorMsg}`,
        };
      }

      if (errorMsg.includes("project") || errorMsg.includes("not found")) {
        return {
          success: false,
          error: `Project not found: ${params.projectPath}`,
        };
      }

      return {
        success: false,
        error: errorMsg,
      };
    }

    // Unknown error type
    return {
      success: false,
      error: err instanceof Error ? err.message : "Unknown error occurred",
    };
  }
}
