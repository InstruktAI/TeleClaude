/**
 * TypeScript types matching Python Pydantic API models.
 *
 * Source of truth: teleclaude/api_models.py
 */

// ---------------------------------------------------------------------------
// Enums as string literal unions
// ---------------------------------------------------------------------------

export type AgentName = "claude" | "gemini" | "codex";
export type ThinkingMode = "fast" | "med" | "slow";
export type HumanRole = "admin" | "member" | "contributor" | "newcomer";
export type LaunchKind = "empty" | "agent" | "agent_then_message" | "agent_resume";
export type AgentStatus = "available" | "unavailable" | "degraded";
export type ErrorSeverity = "warning" | "error" | "critical";
export type MessageRole = "user" | "assistant" | "system";
export type MessageType = "text" | "compaction" | "tool_use" | "tool_result" | "thinking";
export type PaneThemingMode =
  | "off"
  | "highlight"
  | "highlight2"
  | "agent"
  | "agent_plus"
  | "full"
  | "semi";

// ---------------------------------------------------------------------------
// Request DTOs
// ---------------------------------------------------------------------------

export interface CreateSessionRequest {
  computer: string;
  project_path: string;
  launch_kind?: LaunchKind;
  agent?: AgentName | null;
  thinking_mode?: ThinkingMode | null;
  title?: string | null;
  message?: string | null;
  auto_command?: string | null;
  native_session_id?: string | null;
  subdir?: string | null;
  human_email?: string | null;
  human_role?: HumanRole | null;
}

export interface SendMessageRequest {
  message: string;
}

export interface KeysRequest {
  key: string;
  count?: number | null;
}

export interface VoiceInputRequest {
  file_path: string;
  duration?: number | null;
  message_id?: string | null;
  message_thread_id?: number | null;
}

export interface FileUploadRequest {
  file_path: string;
  filename: string;
  caption?: string | null;
  file_size?: number;
}

// ---------------------------------------------------------------------------
// Response / Resource DTOs
// ---------------------------------------------------------------------------

export interface CreateSessionResponse {
  status: "success" | "error";
  session_id: string;
  tmux_session_name: string;
  agent?: AgentName | null;
  error?: string | null;
}

export interface SessionInfo {
  session_id: string;
  last_input_origin?: string | null;
  title: string;
  project_path?: string | null;
  subdir?: string | null;
  thinking_mode?: string | null;
  active_agent?: string | null;
  status: string;
  created_at?: string | null;
  last_activity?: string | null;
  last_input?: string | null;
  last_input_at?: string | null;
  last_output_summary?: string | null;
  last_output_summary_at?: string | null;
  last_output_digest?: string | null;
  native_session_id?: string | null;
  tmux_session_name?: string | null;
  initiator_session_id?: string | null;
  computer?: string | null;
  human_email?: string | null;
  human_role?: string | null;
  visibility?: string | null;
}

export interface PersonInfo {
  name: string;
  email?: string | null;
  role: HumanRole;
}

export interface ComputerInfo {
  name: string;
  status: string;
  user?: string | null;
  host?: string | null;
  is_local: boolean;
  tmux_binary?: string | null;
}

export interface ProjectInfo {
  computer: string;
  name: string;
  path: string;
  description?: string | null;
}

export interface TodoInfo {
  slug: string;
  status: string;
  description?: string | null;
  computer?: string | null;
  project_path?: string | null;
  has_requirements: boolean;
  has_impl_plan: boolean;
  build_status?: string | null;
  review_status?: string | null;
  dor_score?: number | null;
  deferrals_status?: string | null;
  findings_count: number;
  files: string[];
}

export interface ProjectWithTodosInfo extends ProjectInfo {
  todos: TodoInfo[];
  has_roadmap?: boolean;
}

export interface AgentAvailabilityInfo {
  agent: AgentName;
  available: boolean | null;
  status?: AgentStatus | null;
  unavailable_until?: string | null;
  reason?: string | null;
  error?: string | null;
}

export interface MessageInfo {
  role: MessageRole;
  type: MessageType;
  text: string;
  timestamp?: string | null;
  entry_index: number;
  file_index: number;
}

export interface SessionMessagesResponse {
  session_id: string;
  agent?: string | null;
  messages: MessageInfo[];
}

// ---------------------------------------------------------------------------
// Settings DTOs
// ---------------------------------------------------------------------------

export interface TTSSettings {
  enabled: boolean;
}

export interface Settings {
  tts: TTSSettings;
}

export interface TTSSettingsPatch {
  enabled?: boolean;
}

export interface SettingsPatch {
  tts?: TTSSettingsPatch;
}

// ---------------------------------------------------------------------------
// WebSocket Event DTOs (discriminated union on `event` field)
// ---------------------------------------------------------------------------

export interface SessionsInitialData {
  sessions: SessionInfo[];
  computer?: string | null;
}

export interface SessionsInitialEvent {
  event: "sessions_initial";
  data: SessionsInitialData;
}

export interface ProjectsInitialData {
  projects: (ProjectInfo | ProjectWithTodosInfo)[];
  computer?: string | null;
}

export interface ProjectsInitialEvent {
  event: "projects_initial" | "preparation_initial";
  data: ProjectsInitialData;
}

export interface SessionStartedEvent {
  event: "session_started";
  data: SessionInfo;
}

export interface SessionUpdatedEvent {
  event: "session_updated";
  data: SessionInfo;
}

export interface SessionClosedData {
  session_id: string;
}

export interface SessionClosedEvent {
  event: "session_closed";
  data: SessionClosedData;
}

export type RefreshEventType =
  | "computer_updated"
  | "project_updated"
  | "projects_updated"
  | "todos_updated"
  | "todo_created"
  | "todo_updated"
  | "todo_removed";

export interface RefreshData {
  computer?: string | null;
  project_path?: string | null;
}

export interface RefreshEvent {
  event: RefreshEventType;
  data: RefreshData;
}

export interface ErrorEventData {
  session_id?: string | null;
  message: string;
  source?: string | null;
  details?: Record<string, unknown> | null;
  severity: ErrorSeverity;
  retryable: boolean;
  code?: string | null;
}

export interface ErrorEvent {
  event: "error";
  data: ErrorEventData;
}

export interface AgentActivityEvent {
  event: "agent_activity";
  session_id: string;
  type: string;
  tool_name?: string | null;
  tool_preview?: string | null;
  summary?: string | null;
  timestamp?: string | null;
}

/** Discriminated union of all WebSocket events. Discriminator: `event` field. */
export type WsEvent =
  | SessionsInitialEvent
  | ProjectsInitialEvent
  | SessionStartedEvent
  | SessionUpdatedEvent
  | SessionClosedEvent
  | RefreshEvent
  | ErrorEvent
  | AgentActivityEvent;

/** All possible values for the `event` discriminator field. */
export type WsEventType = WsEvent["event"];

// ---------------------------------------------------------------------------
// WebSocket client-to-server messages
// ---------------------------------------------------------------------------

export interface SubscribeMessage {
  subscribe: {
    computer: string;
    types: string[];
  };
}

export interface UnsubscribeMessage {
  unsubscribe: {
    computer: string;
  };
}

export interface RefreshMessage {
  refresh: true;
}

export type WsClientMessage = SubscribeMessage | UnsubscribeMessage | RefreshMessage;

// ---------------------------------------------------------------------------
// Generic API response wrappers
// ---------------------------------------------------------------------------

export interface StatusResponse {
  status: string;
  result?: unknown;
}

export interface HealthResponse {
  status: "ok";
}
