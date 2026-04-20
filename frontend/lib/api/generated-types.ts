/**
 * Auto-generated from teleclaude.api_models.
 * Do not edit by hand.
 */

export type AgentActivityEvent = UserPromptSubmitActivityEvent | ToolUseActivityEvent | ToolDoneActivityEvent | AgentStopActivityEvent;
export type AgentName = "claude" | "gemini" | "codex";
export type AgentStatus = "available" | "unavailable" | "degraded";
export type ErrorSeverity = "warning" | "error" | "critical";
export type HumanRole = "admin" | "member" | "contributor" | "newcomer";
export type LaunchKind = "empty" | "agent" | "agent_then_message" | "agent_resume";
export type MessageRole = "user" | "assistant" | "system";
export type MessageType = "text" | "compaction" | "tool_use" | "tool_result" | "thinking";
export type RefreshEventType = "computer_updated" | "project_updated" | "projects_updated" | "todos_updated" | "todo_created" | "todo_updated" | "todo_removed";
export type SessionLifecycleStatusEvent = SessionStatusEvent;
export type ThinkingMode = "fast" | "med" | "slow";

export interface AgentStatusRequest {
  status?: AgentStatus | null;
  reason?: string | null;
  duration_minutes?: number | null;
  unavailable_until?: string | null;
  clear?: boolean;
}

export interface CreateSessionRequest {
  computer: string;
  project_path: string;
  launch_kind?: LaunchKind;
  agent?: AgentName | null;
  thinking_mode?: "fast" | "med" | "slow" | "default" | null;
  title?: string | null;
  message?: string | null;
  direct?: boolean;
  skip_listener_registration?: boolean;
  native_session_id?: string | null;
  subdir?: string | null;
  human_email?: string | null;
  human_role?: HumanRole | null;
  metadata?: Record<string, unknown> | null;
  origin?: string | null;
  origin_metadata?: Record<string, unknown> | null;
}

export interface EscalateRequest {
  customer_name: string;
  reason: string;
  context_summary?: string | null;
}

export interface FileUploadRequest {
  file_path: string;
  filename: string;
  caption?: string | null;
  file_size?: number;
}

export interface KeysRequest {
  key: string;
  count?: number | null;
}

export interface RenderWidgetRequest {
  data: Record<string, unknown>;
}

export interface RunSessionRequest {
  computer?: string;
  command: string;
  args?: string;
  project: string;
  agent?: AgentName;
  subfolder?: string;
  thinking_mode?: ThinkingMode;
  detach?: boolean;
  additional_context?: string;
}

export interface SendMessageRequest {
  message?: string | null;
  direct?: boolean;
  close_link?: boolean;
}

export interface SendResultRequest {
  content: string;
  output_format?: "markdown" | "html";
}

export interface SetAgentStatusRequest {
  status: AgentStatus;
  reason?: string | null;
  duration_minutes?: number | null;
}

export interface SettingsPatch {
  tts?: TTSSettingsPatch | null;
}

export interface TTSSettingsPatch {
  enabled?: boolean | null;
}

export interface TodoDumpRequest {
  slug: string;
  content: string;
  after?: string[] | null;
  kind?: "bug" | "prepped" | null;
  cwd?: string | null;
}

export interface VoiceInputRequest {
  file_path: string;
  duration?: number | null;
  message_id?: string | null;
  message_thread_id?: number | null;
}

export interface AgentAvailabilityEvent {
  event: "agent_availability";
  data: AgentAvailabilityInfo;
}

export interface AgentAvailabilityInfo {
  agent: AgentName;
  available: boolean | null;
  status?: AgentStatus | null;
  unavailable_until?: string | null;
  degraded_until?: string | null;
  reason?: string | null;
  error?: string | null;
}

export interface AgentStopActivityEvent extends BaseAgentActivityEvent {
  type: "agent_stop";
  summary?: string | null;
}

export interface BaseAgentActivityEvent {
  event: "agent_activity";
  session_id: string;
  timestamp?: string | null;
  canonical_type?: string | null;
  message_intent?: string | null;
  delivery_scope?: string | null;
}

export interface ChiptunesCommandReceipt {
  status: "accepted";
  command_id: string;
  action: "resume" | "pause" | "next" | "prev";
}

export interface ChiptunesStateEvent {
  event: "chiptunes_state";
  playback: "cold" | "loading" | "playing" | "paused";
  state_version: number;
  loaded: boolean;
  playing: boolean;
  paused: boolean;
  position_seconds: number;
  track: string;
  sid_path: string;
  pending_command_id: string;
  pending_action: "" | "resume" | "pause" | "next" | "prev";
}

export interface ChiptunesStatus {
  playback: "cold" | "loading" | "playing" | "paused";
  state_version: number;
  loaded: boolean;
  playing: boolean;
  paused: boolean;
  position_seconds: number;
  track: string;
  sid_path: string;
  pending_command_id: string;
  pending_action: "" | "resume" | "pause" | "next" | "prev";
}

export interface ChiptunesTrackEvent {
  event: "chiptunes_track";
  track: string;
  sid_path: string;
}

export interface ComputerInfo {
  name: string;
  status: string;
  user?: string | null;
  host?: string | null;
  is_local: boolean;
  tmux_binary?: string | null;
}

export interface CreateSessionResponse {
  status: "success" | "error";
  session_id: string;
  tmux_session_name: string;
  agent?: AgentName | null;
  error?: string | null;
}

export interface ErrorEvent {
  event: "error";
  data: ErrorEventData;
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

export interface JobInfo {
  name: string;
  type: "agent" | "script";
  schedule: string | null;
  last_run: string | null;
  status: string;
}

export interface MessageInfo {
  role: MessageRole;
  type: MessageType;
  text: string;
  timestamp?: string | null;
  entry_index: number;
  file_index: number;
}

export interface OperationStatus {
  operation_id: string;
  kind: string;
  state: "queued" | "running" | "completed" | "failed" | "stale" | "cancelled";
  poll_after_ms: number;
  status_path: string;
  recovery_command: string;
  slug?: string | null;
  completion_event?: string | null;
  progress_phase?: string | null;
  progress_decision?: string | null;
  progress_reason?: string | null;
  result?: string | null;
  error?: string | null;
  client_request_id?: string | null;
}

export interface PersonInfo {
  name: string;
  email?: string | null;
  role: HumanRole;
  expertise?: Record<string, string | Record<string, string>> | null;
  proficiency?: "novice" | "intermediate" | "advanced" | "expert" | null;
}

export interface ProjectInfo {
  computer: string;
  name: string;
  path: string;
  description?: string | null;
}

export interface ProjectWithTodosInfo extends ProjectInfo {
  todos: TodoInfo[];
  has_roadmap?: boolean;
}

export interface ProjectsInitialData {
  projects: (ProjectWithTodosInfo | ProjectInfo)[];
  computer?: string | null;
}

export interface ProjectsInitialEvent {
  event: "projects_initial" | "preparation_initial";
  data: ProjectsInitialData;
}

export interface RefreshData {
  computer?: string | null;
  project_path?: string | null;
}

export interface RefreshEvent {
  event: RefreshEventType;
  data: RefreshData;
}

export interface SendMessageResponse {
  status: "success" | "error";
  mode?: "work" | "direct" | null;
  action?: "closed" | null;
  link_id?: string | null;
  link_state?: "created" | null;
  delivered_to?: number | null;
  members?: number | null;
  message?: string | null;
}

export interface SessionClosedData {
  session_id: string;
}

export interface SessionClosedEvent {
  event: "session_closed";
  data: SessionClosedData;
}

export interface SessionInfo {
  last_output_digest?: string | null;
  native_session_id?: string | null;
  tmux_session_name?: string | null;
  initiator_session_id?: string | null;
  computer?: string | null;
  human_email?: string | null;
  human_name?: string | null;
  human_role?: string | null;
  created_at?: string | null;
  last_activity?: string | null;
  closed_at?: string | null;
  last_input?: string | null;
  last_input_at?: string | null;
  last_agent_stop_at?: string | null;
  last_output_summary?: string | null;
  last_output_summary_at?: string | null;
  session_id: string;
  last_input_origin?: string | null;
  title: string;
  project_path?: string | null;
  subdir?: string | null;
  thinking_mode?: string | null;
  active_agent?: string | null;
  status: string;
  visibility?: string;
  system_role?: string | null;
  job?: string | null;
  agent_status?: "active" | "idle" | "unknown" | null;
}

export interface SessionMessagesResponse {
  session_id: string;
  agent?: string | null;
  last_activity?: string | null;
  last_input_at?: string | null;
  last_agent_stop_at?: string | null;
  agent_status?: "active" | "idle" | "unknown" | null;
  messages: MessageInfo[];
}

export interface SessionStartedEvent {
  event: "session_started";
  data: SessionInfo;
}

export interface SessionStatusEvent {
  event: "session_status";
  session_id: string;
  status: string;
  reason: string;
  timestamp: string;
  last_activity_at?: string | null;
  message_intent?: string | null;
  delivery_scope?: string | null;
}

export interface SessionUpdatedEvent {
  event: "session_updated";
  data: SessionInfo;
}

export interface SessionsInitialData {
  sessions: SessionInfo[];
  computer?: string | null;
}

export interface SessionsInitialEvent {
  event: "sessions_initial";
  data: SessionsInitialData;
}

export interface Settings {
  tts: TTSSettings;
}

export interface TTSSettings {
  enabled: boolean;
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
  after?: string[];
  group?: string | null;
  delivered_at?: string | null;
  prepare_phase?: string | null;
  integration_phase?: string | null;
  finalize_status?: string | null;
}

export interface ToolDoneActivityEvent extends BaseAgentActivityEvent {
  type: "tool_done";
}

export interface ToolUseActivityEvent extends BaseAgentActivityEvent {
  type: "tool_use";
  tool_name?: string | null;
  tool_preview?: string | null;
}

export interface UserPromptSubmitActivityEvent extends BaseAgentActivityEvent {
  type: "user_prompt_submit";
}
