# String Comparison Audit (Guardrails)

Total findings: **1282**

## Category Summary

- StringLiteral: 1097
- Status: 57
- AdapterType: 27
- ToolName: 25
- AgentType: 25
- ComputerName: 17
- EventName: 17
- NextMachineToken: 7
- UIParseMode: 4
- TmuxSignal: 3
- HttpMethod: 3

## Recommended Canonicalization Targets

- AdapterType: use internal enum for adapter kinds (telegram/redis/api).
- ComputerName: use internal constant/enum for 'local'.
- Status: use internal enum for success/error statuses.
- EventName: use internal enum for event names.
- ToolName: use internal enum registry for tool names.
- HttpMethod: use enum for HTTP methods.
- AgentType: use enum for agent types (claude/codex/gemini).
- UIParseMode: use enum/constant for parse modes.
- TmuxSignal: use enum/constant for signals.
- NextMachineToken: use constants for checklist symbols.
- StringLiteral/Other: investigate; likely error-message matching, markdown tokens, or free-form UI text. Prefer typed sentinel or structured error codes where possible.

## Detailed Checklist

### teleclaude/api_server.py

- L803: `if computer == "local":`
  - Category: **ComputerName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L897: `if event == "session_updated":`
  - Category: **EventName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L901: `if event == "session_created":`
  - Category: **EventName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L812: `elif data_type == "sessions":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L824: `if computer == "local":`
  - Category: **ComputerName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L834: `if not self.cache or not project_path or computer == "local":`
  - Category: **ComputerName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L857: `if data_type == "sessions":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L914: `elif event == "session_removed":`
  - Category: **EventName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L312: `if status != "success":`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L649: `if "subscribe" in data:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L700: `elif "unsubscribe" in data:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L884: `elif data_type == "todos":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L953: `if event == "projects_snapshot":`
  - Category: **EventName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L955: `elif event == "todos_snapshot":`
  - Category: **EventName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L947: `if event == "computer_updated" and computer is None and hasattr(data, "name"):`
  - Category: **EventName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L867: `cached_projects = self.cache.get_projects(computer if computer != "local" else None)`
  - Category: **ComputerName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L880: `event="projects_initial" if data_type == "projects" else "preparation_initial",`
  - Category: **EventName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### teleclaude/daemon.py

- L131: `LAUNCHD_WATCH_ENABLED = os.getenv("TELECLAUDE_LAUNCHD_WATCH", "1") == "1"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L2524: `if __name__ == "__main__":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L156: `if sys.platform == "darwin":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L1030: `if ctx.command == "deploy":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L1236: `if cmd_name == "agent_then_message":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L2239: `if platform.system().lower() != "darwin":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L663: `if isinstance(exc, ValueError) and "not found" in str(exc):`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L675: `if isinstance(exc, ValueError) and "not found" in str(exc):`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L777: `if status == "error":`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L1032: `elif ctx.command == "health_check":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L2285: `if session.origin_adapter == "telegram":`
  - Category: **AdapterType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L757: `"source": str(data.get("source")) if "source" in data else None,`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L2003: `return None if value == "-" else value`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L2103: `elif command == "exit":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### teleclaude/mcp_server.py

- L200: `if envelope.get("status") == "error":`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L330: `if name == "teleclaude__help":`
  - Category: **ToolName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L342: `if name == "teleclaude__list_computers":`
  - Category: **ToolName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L345: `if name == "teleclaude__list_projects":`
  - Category: **ToolName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L348: `if name == "teleclaude__list_sessions":`
  - Category: **ToolName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L353: `if name == "teleclaude__start_session":`
  - Category: **ToolName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L357: `if name == "teleclaude__send_message":`
  - Category: **ToolName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L369: `if name == "teleclaude__run_agent_command":`
  - Category: **ToolName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L373: `if name == "teleclaude__get_session_data":`
  - Category: **ToolName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L389: `if name == "teleclaude__deploy":`
  - Category: **ToolName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L394: `if name == "teleclaude__send_file":`
  - Category: **ToolName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L405: `if name == "teleclaude__send_result":`
  - Category: **ToolName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L414: `if name == "teleclaude__stop_notifications":`
  - Category: **ToolName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L423: `if name == "teleclaude__end_session":`
  - Category: **ToolName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L430: `if name == "teleclaude__next_prepare":`
  - Category: **ToolName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L436: `if name == "teleclaude__next_work":`
  - Category: **ToolName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L441: `if name == "teleclaude__mark_phase":`
  - Category: **ToolName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L455: `if name == "teleclaude__set_dependencies":`
  - Category: **ToolName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L466: `if name == "teleclaude__mark_agent_unavailable":`
  - Category: **ToolName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L617: `if method != "notifications/initialized":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L626: `if method == "notifications/initialized" and self._should_emit_tools_changed():`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### teleclaude/transport/redis_transport.py

- L1004: `if parsed.msg_type == "system":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L1026: `if cmd_name == "stop_notification":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L1600: `if status == "error":`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L1650: `if status == "error":`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L1711: `if status == "error":`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L1055: `elif cmd_name == "input_notification":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L1142: `if event_type == "new_session" and isinstance(result, dict) and result.get("status") == "success":`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L1142: `if event_type == "new_session" and isinstance(result, dict) and result.get("status") == "success":`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L1543: `if status == "error":`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L1603: `if isinstance(error_msg, str) and "list_projects_with_todos" in error_msg:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L1653: `if isinstance(error_msg, str) and "list_projects_with_todos" in error_msg:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L849: `if status == "error":`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L1792: `if event == "session_updated":`
  - Category: **EventName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L1798: `elif event == "session_removed":`
  - Category: **EventName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L1876: `if chunk.startswith("[") or "⏳" in chunk:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L2252: `if "[Output Complete]" in chunk:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### teleclaude/core/db.py

- L345: `if "last_message_sent" in updates and "last_message_sent_at" not in updates:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L345: `if "last_message_sent" in updates and "last_message_sent_at" not in updates:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L347: `if "last_feedback_received" in updates and "last_feedback_received_at" not in updates:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L347: `if "last_feedback_received" in updates and "last_feedback_received_at" not in updates:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L329: `if key == "adapter_metadata" and not isinstance(value, str):`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L1113: `if "no such table" in str(exc).lower():`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### teleclaude/core/codex_watcher.py

- L94: `if session.active_agent == "codex":`
  - Category: **AgentType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L62: `if session.active_agent != "codex" or not session.native_log_file:`
  - Category: **AgentType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L180: `if data.get("type") != "session_meta":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L287: `if entry_type == "event_msg":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### teleclaude/core/agent_parsers.py

- L23: `return file_path.suffix == ".jsonl"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L57: `if entry_type == "event_msg":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L69: `if entry_type == "response_item":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L60: `if payload_type == "agent_message":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L71: `if payload["type"] != "message":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L129: `if block["type"] == "output_text":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L99: `if entry["type"] != "response_item":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L103: `if payload["type"] != "message":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L80: `if block["type"] == "tool_use":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L34: `if isinstance(data, dict) and data.get("type") == "session_meta":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L112: `if block["type"] == "output_text":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L83: `if "question" in tool_name.lower() or "input" in tool_name.lower():`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L83: `if "question" in tool_name.lower() or "input" in tool_name.lower():`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### teleclaude/core/models.py

- L258: `if "kind" not in data or data["kind"] is None:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L366: `if "adapter_metadata" in data and isinstance(data["adapter_metadata"], str):`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L530: `if not arguments or "computer" not in arguments or "command" not in arguments:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L530: `if not arguments or "computer" not in arguments or "command" not in arguments:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### teleclaude/core/session_utils.py

- L210: `subdir = str(rel) if str(rel) != "." else None`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### teleclaude/core/cache.py

- L184: `comp_name = key.split(":", 1)[0] if ":" in key else ""`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L209: `session_computer = local_name if session.computer == "local" else session.computer`
  - Category: **ComputerName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L213: `if computer == "local":`
  - Category: **ComputerName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L262: `comp_name, path = key.split(":", 1) if ":" in key else ("", key)`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### teleclaude/core/adapter_client.py

- L159: `return config.ui_delivery.scope == "all_ui"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L301: `if operation == "delete_message":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L258: `if len(self.adapters) == 1 and "api" in self.adapters:`
  - Category: **AdapterType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L669: `"message thread not found" in error_text or "topic_deleted" in error_text or "topic deleted" in error_text`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L669: `"message thread not found" in error_text or "topic_deleted" in error_text or "topic deleted" in error_text`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L669: `"message thread not found" in error_text or "topic_deleted" in error_text or "topic deleted" in error_text`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L1374: `if adapter_type == "telegram":`
  - Category: **AdapterType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L1410: `if adapter_type == "telegram":`
  - Category: **AdapterType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L1416: `if adapter_type == "telegram" and isinstance(adapter_meta, TelegramAdapterMetadata):`
  - Category: **AdapterType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L193: `if adapter_type == "telegram" and self._is_missing_thread_error(result):`
  - Category: **AdapterType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L609: `if adapter_type == "telegram" and self._is_missing_thread_error(result):`
  - Category: **AdapterType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L1343: `if adapter_type == "telegram":`
  - Category: **AdapterType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L1352: `if adapter_type == "telegram" and isinstance(adapter_meta, TelegramAdapterMetadata):`
  - Category: **AdapterType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L201: `(adapter for adapter_type, adapter in ui_adapters if adapter_type == "telegram"),`
  - Category: **AdapterType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L1345: `elif adapter_type == "redis":`
  - Category: **AdapterType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L1354: `elif adapter_type == "redis" and isinstance(adapter_meta, RedisTransportMetadata):`
  - Category: **AdapterType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### teleclaude/core/lifecycle.py

- L108: `if isinstance(status_raw, dict) and status_raw.get("status") == "restarting":  # type: ignore[misc]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### teleclaude/core/session_listeners.py

- L293: `location_part = f" on {computer}" if computer != "local" else ""`
  - Category: **ComputerName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### teleclaude/core/summarizer.py

- L69: `if role == "user":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L58: `if not isinstance(message, dict) and entry.get("type") == "response_item":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L82: `elif role == "assistant":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L92: `if isinstance(block, dict) and block.get("type") == "text":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### teleclaude/core/command_handlers.py

- L1090: `if target_dir == "TC WORKDIR":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L435: `elif next_line.strip() == "":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### teleclaude/core/tmux_bridge.py

- L589: `send_text = text.replace("!", r"\!") if active_agent == "gemini" else text`
  - Category: **AgentType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L644: `if signal == "SIGKILL":`
  - Category: **TmuxSignal**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L709: `if signal == "SIGINT":`
  - Category: **TmuxSignal**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L711: `elif signal == "SIGTERM":`
  - Category: **TmuxSignal**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L1146: `return all(pane == "1" for pane in panes)`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L1039: `if "tmux" in p.info["name"].lower()  # type: ignore[misc]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### teleclaude/core/session_cleanup.py

- L239: `if ppid_str != "1":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### teleclaude/core/next_machine.py

- L546: `return "[ ]" in content`
  - Category: **NextMachineToken**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L851: `if "[x] APPROVE" in content:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L1190: `if resolved_slug == "input":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L1329: `if current_state == " ":  # Only transition pending -> ready`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L405: `return isinstance(build, str) and build == "complete"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L412: `return isinstance(review, str) and review == "approved"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L419: `return isinstance(review, str) and review == "changes_requested"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L740: `if dep_state != "x":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L832: `if "- [ ]" in content:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L1377: `if state == " ":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L129: `if next_call_display and "(" not in next_call_display:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L1093: `if "scripts" not in data or "worktree:prepare" not in data["scripts"]:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L1093: `if "scripts" not in data or "worktree:prepare" not in data["scripts"]:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### teleclaude/core/computer_registry.py

- L326: `return computer_name in self.computers and self.computers[computer_name]["status"] == "online"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L317: `computers = [c for c in self.computers.values() if c["status"] == "online"]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L200: `if "message to edit not found" in error_lower or "message not found" in error_lower:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L200: `if "message to edit not found" in error_lower or "message not found" in error_lower:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L255: `if "message to edit not found" in error_lower or "message not found" in error_lower:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L255: `if "message to edit not found" in error_lower or "message not found" in error_lower:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L150: `len([c for c in self.computers.values() if c["status"] == "online"]),`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### teleclaude/utils/transcript.py

- L110: `if entry.get("type") == "summary":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L233: `if role == "assistant":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L235: `if role == "user":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L247: `if last_section != "assistant":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L144: `if not isinstance(message, dict) and entry.get("type") == "response_item":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L169: `if last_section != "user" or time_prefix:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L221: `if role == "assistant" and last_section != "assistant":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L221: `if role == "assistant" and last_section != "assistant":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L469: `if entry.get("type") == "session_meta":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L495: `if msg_type == "user":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L507: `if msg_type != "gemini":`
  - Category: **AgentType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L198: `elif block_type == "thinking":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L225: `elif role == "user" and (last_section != "user" or time_prefix):`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L200: `elif block_type == "tool_use":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L225: `elif role == "user" and (last_section != "user" or time_prefix):`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L645: `if not isinstance(role, str) or role != "user":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L202: `elif block_type == "tool_result":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### teleclaude/utils/markdown.py

- L71: `if text[i : i + 3] == "```":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L78: `if text[i] == "`" and not in_code_block:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### teleclaude/mcp/handlers.py

- L674: `if result.get("status") != "success":`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L860: `if output_format == "html":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L371: `if envelope.get("status") == "error":`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L630: `if envelope.get("status") == "error":`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L1015: `if not isinstance(result, dict) or result.get("status") != "success":`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L1025: `if not isinstance(result, dict) or result.get("status") != "success":`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L1036: `return any(p["name"] == computer and p["status"] == "online" for p in peers)`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L164: `if not any(p["name"] == computer and p["status"] == "online" for p in peers):`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L244: `if not any(p["name"] == computer and p["status"] == "online" for p in peers):`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### teleclaude/cli/telec.py

- L221: `if __name__ == "__main__":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L81: `if cmd == "list":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L95: `if os.environ.get("TELEC_TUI_SESSION") != "1":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L108: `if result.stdout.strip() != "tc_tui":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L41: `if key == "TELEC_TUI_SESSION":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### teleclaude/cli/api_client.py

- L256: `if method == "GET":`
  - Category: **HttpMethod**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L258: `elif method == "POST":`
  - Category: **HttpMethod**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L260: `elif method == "DELETE":`
  - Category: **HttpMethod**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### teleclaude/adapters/ui_adapter.py

- L457: `if "title" in updated_fields:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L496: `if "last_feedback_received" in updated_fields:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L237: `if self.ADAPTER_KEY == "telegram":`
  - Category: **AdapterType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L245: `metadata.parse_mode = "MarkdownV2" if self.ADAPTER_KEY == "telegram" else "Markdown"`
  - Category: **AdapterType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L464: `if not title_updated and ("project_path" in updated_fields or "subdir" in updated_fields):`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L464: `if not title_updated and ("project_path" in updated_fields or "subdir" in updated_fields):`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### teleclaude/adapters/telegram_adapter.py

- L832: `if "message to edit not found" in error_lower or "message not found" in error_lower:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L832: `if "message to edit not found" in error_lower or "message not found" in error_lower:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### teleclaude/hooks/receiver.py

- L302: `if __name__ == "__main__":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L159: `if agent == "codex":`
  - Category: **AgentType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L192: `if agent == "claude":`
  - Category: **AgentType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L194: `if agent == "codex":`
  - Category: **AgentType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L196: `if agent == "gemini":`
  - Category: **AgentType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L207: `if agent == "gemini":`
  - Category: **AgentType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L213: `if agent == "claude":`
  - Category: **AgentType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L233: `if args.agent == "codex":`
  - Category: **AgentType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L208: `if normalized == "after_agent":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L210: `if normalized == "before_agent":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L214: `if normalized == "user_prompt_submit":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### teleclaude/adapters/telegram/message_ops.py

- L139: `if "message thread not found" in str(exc).lower():`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L231: `if "message is not modified" in str(e).lower():`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L166: `if "message thread not found" in str(exc).lower():`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### teleclaude/adapters/telegram/callback_handlers.py

- L100: `if action == "download_full":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L95: `if not data or ":" not in data:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L102: `elif action == "ssel":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L104: `elif action == "cd":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L108: `elif action == "ccancel":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L110: `elif action == "s":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### teleclaude/adapters/telegram/input_handlers.py

- L325: `subdir = "photos" if file_type == "photo" else "files"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### teleclaude/cli/tui/theme.py

- L92: `return tmux_mode == "dark"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L100: `return "Dark" in result.stdout`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### teleclaude/cli/tui/todos.py

- L66: `elif next_line.strip() == "":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### teleclaude/cli/tui/app.py

- L833: `if self.notification.level == "error":`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L114: `if level.type == "computer":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L122: `if level.type == "project":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L132: `if level.type == "computer":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L278: `duration = NOTIFICATION_DURATION_ERROR if level == "error" else NOTIFICATION_DURATION_INFO`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L288: `if not current or current == "local":`
  - Category: **ComputerName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L787: `if level.type == "computer":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L835: `elif self.notification.level == "success":`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L134: `elif level.type == "project":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L290: `if computer != "local":`
  - Category: **ComputerName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L789: `elif level.type == "project":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L668: `if selected.type == "session":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### teleclaude/cli/tui/views/sessions.py

- L370: `if selected.type == "session":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L376: `if selected.type == "project":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L400: `if item.type == "computer":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L406: `if item.type == "session":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L432: `if item.type == "session":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L477: `if item.type == "computer":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L773: `if item.type == "computer":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L780: `if item.type == "project":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L787: `if item.type == "session":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L937: `if item.type == "computer":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L944: `if item.type == "project":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L954: `if item.type == "session":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L330: `if node.type == "computer":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L461: `if node.type == "session":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L480: `elif item.type == "project":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L657: `if selected.type == "project":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L666: `if selected.type != "session":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L1033: `input_attr = highlight_attr if active == "input" else muted_attr`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L1034: `output_attr = highlight_attr if active == "output" else muted_attr`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L262: `if node.type == "session":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L338: `elif node.type == "project":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L483: `elif item.type == "session":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L290: `if node.type == "computer" and node.data.computer.name == self.focus.computer:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L301: `if node.type == "project" and node.data.path == self.focus.project:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### teleclaude/cli/tui/views/preparation.py

- L432: `if item.type == "computer":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L434: `if item.type == "project":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L436: `if item.type == "file":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L441: `if item.type == "todo":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L464: `if item.type == "file":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L474: `if item.type == "todo":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L500: `if item.type == "computer":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L506: `if item.type == "todo":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L546: `if item.type == "computer":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L792: `if item.type == "file":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L802: `if item.type == "todo":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L869: `if item.type == "computer":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L876: `if item.type == "project":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L883: `if item.type == "todo":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L886: `if item.type == "file":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L1008: `if item.type == "computer":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L1016: `if item.type == "project":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L1027: `if item.type == "todo":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L1030: `if item.type == "file":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L348: `if node.type == "computer":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L442: `if item.data.todo.status == "ready":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L524: `if item.type == "todo":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L548: `elif item.type == "project":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L355: `elif node.type == "project":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L382: `elif node.type == "todo":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L402: `exists = todo_info.todo.has_requirements if has_flag == "has_requirements" else todo_info.todo.has_impl_plan`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L550: `elif item.type == "todo":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L803: `if key == ord("s") and item.data.todo.status == "ready":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L318: `if node.type == "computer" and node.data.computer.name == self.focus.computer:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L362: `elif node.type == "todo":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L551: `if item.data.todo.status == "ready":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L555: `elif item.type == "file":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### teleclaude/cli/tui/widgets/modal.py

- L255: `if result.status != "success":`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### teleclaude/core/migrations/004_remove_closed_column.py

- L20: `if "closed" not in existing_columns:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### teleclaude/core/migrations/runner.py

- L43: `f for f in MIGRATIONS_DIR.glob("*.py") if re.match(r"^\d{3}_", f.name) and f.name != "__init__.py"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### teleclaude/core/migrations/005_project_path_refactor.py

- L97: `if "working_directory" in existing_columns:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L21: `if "working_directory" not in existing_columns and "project_path" in existing_columns:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L21: `if "working_directory" not in existing_columns and "project_path" in existing_columns:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L109: `if "project_path" in existing_columns:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L111: `if "subdir" in existing_columns:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### teleclaude/core/migrations/003_add_closed_at.py

- L23: `if "closed_at" not in existing_columns:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### teleclaude/core/migrations/006_remove_working_directory.py

- L20: `if "working_directory" not in existing_columns:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### teleclaude/core/migrations/002_add_working_slug.py

- L25: `if "working_slug" not in existing_columns:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### teleclaude/core/migrations/001_add_ux_columns.py

- L54: `if "ux_state" in existing_columns:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### teleclaude/core/migrations/007_split_project_path_subdir.py

- L18: `if "project_path" not in columns or "subdir" not in columns:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L18: `if "project_path" not in columns or "subdir" not in columns:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/conftest.py

- L25: `if "unit" in item.keywords:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L27: `elif "integration" in item.keywords:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_api_client.py

- L213: `assert "request timed out" in str(exc_info.value).lower()`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L80: `assert result[0].session_id == "sess-1"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L128: `assert result[0].name == "local"`
  - Category: **ComputerName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L151: `assert result.session_id == "new-sess"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L198: `assert "Cannot connect to API server" in str(exc_info.value)`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L233: `assert "500" in str(exc_info.value)`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L261: `assert "claude" in result`
  - Category: **AgentType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_base_adapter.py

- L12: `assert str(error) == "Test error"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L19: `assert str(e) == "Test error"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_migration_remove_closed.py

- L62: `assert "closed" not in cols`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_command_handlers.py

- L53: `assert result.user == "testuser"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L54: `assert result.role == "development"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L55: `assert result.host == "test.local"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L62: `assert "memory" in system_stats`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L63: `assert "total_gb" in system_stats["memory"]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L64: `assert "available_gb" in system_stats["memory"]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L65: `assert "percent_used" in system_stats["memory"]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L68: `assert "disk" in system_stats`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L69: `assert "total_gb" in system_stats["disk"]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L70: `assert "free_gb" in system_stats["disk"]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L71: `assert "percent_used" in system_stats["disk"]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L74: `assert "cpu" in system_stats`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L75: `assert "percent_used" in system_stats["cpu"]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L305: `assert updated.project_path == "/some/path"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L414: `assert updated.title == "[TestComputer] New Title"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L450: `assert result[0].session_id == "session-0"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L451: `assert result[0].origin_adapter == "telegram"`
  - Category: **AdapterType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L452: `assert result[0].title == "Test Session 0"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L453: `assert result[0].status == "active"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L455: `assert result[1].session_id == "session-1"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L456: `assert result[1].origin_adapter == "telegram"`
  - Category: **AdapterType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L457: `assert result[1].title == "Test Session 1"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L458: `assert result[1].status == "active"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L481: `assert result["status"] == "error"`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L482: `assert "file" in result["error"].lower()`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L525: `assert result["status"] == "success"`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L526: `assert "Markdown Session" in result["messages"]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L527: `assert "hi" in result["messages"]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L528: `assert "hello" in result["messages"]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L542: `assert result["status"] == "error"`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L543: `assert "not found" in result["error"].lower()`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L561: `assert result[0].name == "Project"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L562: `assert result[0].description == "Test project"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L563: `assert "/tmp" in result[0].path`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L590: `assert "Usage" in messages[0]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L631: `assert "claude" in command`
  - Category: **AgentType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L632: `assert "--model=haiku" in command`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L633: `assert "--test" in command`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L671: `assert "codex" in command`
  - Category: **AgentType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L705: `assert "codex -m deep" in command`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L786: `assert "--yolo" in command`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L787: `assert "--resume" in command`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L788: `assert "native-123-abc" in command`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L834: `assert "--dangerously-skip-permissions" in command`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L836: `assert "--resume" not in command`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L837: `assert "-m " not in command  # continue_template path skips model flag`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L888: `assert "resume" in command`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L889: `assert "native-override-999" in command`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L992: `assert "claude --resume native-abc" in command`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_utils.py

- L17: `assert result == "Hello test_value!"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L29: `assert result == "value1 and value2"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L39: `assert result == "Hello ${NONEXISTENT_VAR}!"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L49: `assert result["path"] == "/home/test/project"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L50: `assert result["name"] == "test"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L63: `assert result["outer"]["inner"]["value"] == "nested_value"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L92: `assert result["settings"]["base"] == "/test/path"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L108: `assert result == "Just a plain string"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L114: `assert result == ""`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_agent_parsers.py

- L14: `assert events[0].event_type == "stop"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L28: `assert events[0].event_type == "notification"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_install_hooks.py

- L25: `assert "SessionStart" in merged`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L27: `assert block["matcher"] == "*"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L30: `assert block["hooks"][0]["command"] == "/tmp/new-hook"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L47: `assert "hooks" in data`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L48: `assert "SessionStart" in data["hooks"]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L50: `assert hooks_block["matcher"] == "*"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L53: `assert hook["type"] == "command"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L54: `assert "receiver.py --agent claude session_start" in hook["command"]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L71: `assert "notify" in data`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L75: `assert notify[2] == "--agent"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L76: `assert notify[3] == "codex"`
  - Category: **AgentType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L77: `assert "receiver.py" in notify[1]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L78: `assert data["mcp_servers"]["teleclaude"]["type"] == "stdio"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L79: `assert "mcp-wrapper.py" in data["mcp_servers"]["teleclaude"]["args"][0]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L100: `assert data["model"] == "gpt-4"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L101: `assert data["sandbox_mode"] == "safe"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L103: `assert "notify" in data`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L104: `assert "receiver.py" in data["notify"][1]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L105: `assert data["mcp_servers"]["teleclaude"]["type"] == "stdio"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L106: `assert "mcp-wrapper.py" in data["mcp_servers"]["teleclaude"]["args"][0]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L136: `assert data_after_second["model"] == "gpt-4"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L137: `assert data_after_second["mcp_servers"]["test"]["type"] == "stdio"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L138: `assert "notify" in data_after_second`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L140: `assert data_after_second["mcp_servers"]["teleclaude"]["type"] == "stdio"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L141: `assert "mcp-wrapper.py" in data_after_second["mcp_servers"]["teleclaude"]["args"][0]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L164: `assert "receiver.py" in data["notify"][1]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L165: `assert "--agent" in data["notify"][2]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L166: `assert "codex" in data["notify"][3]`
  - Category: **AgentType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L168: `assert "/old/venv/python" not in str(data["notify"])`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L169: `assert "/old/path/" not in str(data["notify"])`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L170: `assert data["mcp_servers"]["teleclaude"]["type"] == "stdio"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L171: `assert "mcp-wrapper.py" in data["mcp_servers"]["teleclaude"]["args"][0]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L192: `assert data["mcp_servers"]["teleclaude"]["type"] == "stdio"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L193: `assert "mcp-wrapper.py" in data["mcp_servers"]["teleclaude"]["args"][0]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L197: `assert "not ours" in captured.out`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L222: `assert data["mcp_servers"]["teleclaude"]["type"] == "stdio"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_mcp_wrapper_tool_refresh.py

- L40: `assert wrapper.TOOL_LIST_CACHE[0]["name"] == "teleclaude__one"`
  - Category: **ToolName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L54: `assert wrapper.TOOL_LIST_CACHE[0]["name"] == "teleclaude__two"`
  - Category: **ToolName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_session_listeners.py

- L155: `assert "target-1" not in all_listeners`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L189: `assert listener.target_session_id == "target-123"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L190: `assert listener.caller_session_id == "caller-456"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L191: `assert listener.caller_tmux_session == "tc_caller_session"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L323: `assert listeners[0].caller_session_id == "caller-B"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L334: `assert "target-123" not in session_listeners._listeners`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L170: `assert all(listener.caller_session_id == "caller-A" for listener in listeners)`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_telegram_adapter.py

- L180: `assert result == "123"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L230: `assert result == "999"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L117: `assert call_kwargs["parse_mode"] == "MarkdownV2"`
  - Category: **UIParseMode**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_mcp_server.py

- L144: `assert result["session_id"] == "new-session-456"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L164: `assert "Message sent" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L165: `assert "test-ses" in result  # First 8 chars of session_id`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L267: `assert "Error:" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L268: `assert "File not found" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L387: `assert result["status"] == "success"`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L391: `assert "codex" in metadata.auto_command`
  - Category: **AgentType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L392: `assert "med" in metadata.auto_command`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L414: `assert result["status"] == "sent"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L435: `assert result["status"] == "sent"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L439: `assert event_data["text"] == "/compact"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L455: `assert result["status"] == "sent"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L458: `assert event_data["text"] == "/compact"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L475: `assert result["status"] == "sent"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L478: `assert event_data["text"] == "/next-work my-feature"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L495: `assert result["status"] == "sent"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L498: `assert event_data["text"] == "/prompts:next-work"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L517: `assert result["status"] == "success"`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L518: `assert result["session_id"] == "new-session-789"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L539: `assert result["status"] == "error"`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L540: `assert "project required" in result["message"]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L559: `assert result["status"] == "success"`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L565: `assert metadata.project_path == "/home/user/myproject"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L566: `assert metadata.channel_metadata["subfolder"] == "worktrees/my-feature"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L583: `assert result["status"] == "success"`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L588: `assert "gemini" in metadata.auto_command`
  - Category: **AgentType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L605: `assert "pending" in status_enum`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L625: `assert "ERROR: UNCOMMITTED_CHANGES" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L87: `assert result[0]["name"] == "TestComputer"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L88: `assert result[0]["status"] == "local"`
  - Category: **ComputerName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L90: `assert result[1]["name"] == "RemotePC"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L91: `assert result[1]["status"] == "online"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L117: `assert result[0]["session_id"] == "test-session-123"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L118: `assert result[0]["origin_adapter"] == "telegram"`
  - Category: **AdapterType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L119: `assert result[0]["computer"] == "TestComputer"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L143: `assert result["status"] == "success"`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L221: `assert result["status"] == "success"`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L222: `assert result["session_id"] == "test-session-123"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L223: `assert result["messages"] == "Hello"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L249: `assert result["status"] == "success"`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L319: `assert result["status"] == "success"`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L320: `assert result["session_id"] == "agent-test-123"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L335: `assert result["status"] == "success"`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L336: `assert result["session_id"] == "agent-test-456"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L351: `assert result["status"] == "success"`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L352: `assert result["session_id"] == "agent-test-789"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L367: `assert result["status"] == "success"`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L368: `assert result["session_id"] == "agent-test-fast"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L195: `assert "File sent successfully" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L196: `assert "file-msg-123" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L293: `assert "Error:" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L294: `assert "not found" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L602: `mark_phase_tool = next(tool for tool in tools if tool.name == "teleclaude__mark_phase")`
  - Category: **ToolName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_tui_tree.py

- L65: `assert tree[0].type == "computer"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L66: `assert tree[0].data.computer.name == "local"`
  - Category: **ComputerName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L78: `assert tree[0].type == "computer"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L82: `assert project_node.type == "project"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L83: `assert project_node.data.path == "/home/user/project"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L101: `assert session_node.type == "session"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L102: `assert session_node.data.session.session_id == "sess-1"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L103: `assert session_node.data.session.title == "Main Session"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L121: `assert parent_session.data.session.session_id == "sess-parent"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L125: `assert child_session.data.session.session_id == "sess-child"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L126: `assert child_session.data.session.initiator_session_id == "sess-parent"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L149: `assert sess3.data.session.session_id == "sess-3"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L165: `assert tree[0].data.computer.name == "local"`
  - Category: **ComputerName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L166: `assert tree[1].data.computer.name == "remote"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L15: `is_local=name == "local",`
  - Category: **ComputerName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_telegram_menus.py

- L74: `assert "Tmux Session" in keyboard[0][0].text`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L79: `assert "New Claude" in keyboard[1][0].text`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L81: `assert "Resume Claude" in keyboard[1][1].text`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L86: `assert "New Gemini" in keyboard[2][0].text`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L88: `assert "Resume Gemini" in keyboard[2][1].text`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L93: `assert "New Codex" in keyboard[3][0].text`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L95: `assert "Resume Codex" in keyboard[3][1].text`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_telegram_adapter_discovery.py

- L16: `assert match.group(1) == "macbook"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L17: `assert match.group(2) == "2025-11-04 15:30:45"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L26: `assert match.group(1) == "workstation"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L27: `assert match.group(2) == "2025-11-04 16:45:30"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_task_registry.py

- L27: `assert result == "done"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L165: `assert result == "unnamed"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L191: `assert "exc_info" in call_args.kwargs`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L193: `assert str(call_args.kwargs["exc_info"]) == "Test exception"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_tui_pane_manager.py

- L23: `assert '/remote/tmux-wrapper -u set-option -t tc_123 status-right ""' in cmd`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L24: `assert "set-option -t tc_123 status-right-length 0" in cmd`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L25: `assert 'set-option -t tc_123 status-style "bg=default"' in cmd`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L26: `assert "attach-session -t tc_123" in cmd`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L43: `assert ' tmux -u set-option -t tc_456 status-right ""' in cmd`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L44: `assert "set-option -t tc_456 status-right-length 0" in cmd`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L45: `assert 'set-option -t tc_456 status-style "bg=default"' in cmd`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L46: `assert "attach-session -t tc_456" in cmd`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L47: `assert "/local/tmux-wrapper" not in cmd`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_db.py

- L52: `assert session.title == "[TestPC] Untitled"  # Default title logic`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L70: `assert session.title == "Custom Title"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L72: `assert session.project_path == "/home/user"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L88: `assert retrieved.initiator_session_id == "parent-session"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L100: `assert str(row[0]).lower() == "wal"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L250: `assert updated.title == "New Title"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L260: `assert updated.title == "Updated Title"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L261: `assert updated.project_path == "/new/path"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L481: `assert sessions[0].title == "Has Telegram"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L500: `assert updated.title == "Updated"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L156: `assert all(s.computer_name == "PC1" for s in sessions)`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L168: `assert all(s.origin_adapter == "telegram" for s in sessions)`
  - Category: **AdapterType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_telec_cli.py

- L28: `assert called["name"] == "tc_123"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L45: `assert "name" not in called`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L56: `assert "Error: boom" in capsys.readouterr().out`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_adapter_client.py

- L174: `assert "telegram" in client.adapters`
  - Category: **AdapterType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L175: `assert "redis" in client.adapters`
  - Category: **AdapterType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L210: `assert peers[0]["name"] == "macbook"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L211: `assert peers[1]["name"] == "workstation"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L257: `assert peers[0]["name"] == "macbook"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L258: `assert peers[1]["name"] == "workstation"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L259: `assert peers[2]["name"] == "server"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L282: `assert result == "123"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L333: `assert peers[0]["name"] == "macbook"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L334: `assert peers[0]["adapter_type"] == "telegram"`
  - Category: **AdapterType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L335: `assert peers[1]["name"] == "workstation"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L336: `assert peers[1]["adapter_type"] == "redis"`
  - Category: **AdapterType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L367: `assert peers[0]["name"] == "workstation"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L429: `assert peers[0]["name"] == "server"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L430: `assert peers[0]["role"] == "development"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L431: `assert "system_stats" in peers[0]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L490: `assert result == "msg"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L523: `assert result == "msg"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L553: `assert result == "msg"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L627: `assert message_id == "tg-msg-1"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L705: `assert message_id == "tg-feedback"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_pane_manager.py

- L32: `assert manager.state.parent_pane_id == "%5"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L33: `assert manager.state.child_pane_id == "%6"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L34: `assert manager.state.parent_session == "parent-session"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L35: `assert manager.state.child_session == "child-session"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L37: `assert mock_run.call_args_list[0].args[0] == "split-window"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L38: `assert mock_run.call_args_list[1].args[0] == "split-window"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_output_poller.py

- L97: `assert events[0].session_id == "test-123"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L141: `assert "command output" in events[-1].final_output`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L278: `assert "output 1" in events[0].output`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L374: `assert any("idle: unchanged for" in msg for msg in messages)`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L375: `assert all("SKIPPING yield" not in msg for msg in messages)`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L376: `assert all("Output unchanged" not in msg for msg in messages)`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L176: `assert "line 1" in output_events[-1].output`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L177: `assert "line 2" in output_events[-1].output`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L439: `assert dir_events[0].session_id == "test-dir"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L440: `assert dir_events[0].old_path == "/home/user/projects"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L441: `assert dir_events[0].new_path == "/home/user/projects/teleclaude"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_hook_receiver.py

- L40: `assert session_id == "sess-1"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L41: `assert event_type == "error"`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L42: `assert data["message"] == "boom"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L43: `assert data["source"] == "hook_receiver"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L125: `assert session_id == "sess-native"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L126: `assert event_type == "stop"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L152: `assert session_id == "sess-1"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L153: `assert event_type == "stop"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L178: `assert data["agent_name"] == "claude"`
  - Category: **AgentType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_ui_adapter_command_overrides.py

- L15: `assert "agent_resume" in UiCommands`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L16: `assert TelegramAdapter.COMMAND_HANDLER_OVERRIDES.get("agent_resume") == "_handle_agent_resume_command"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_api_server.py

- L194: `assert data["session_id"] == "new-sess"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L195: `assert data["tmux_session_name"] == "tc_new"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L196: `assert data["status"] == "success"`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L200: `assert call_args.kwargs["metadata"].auto_command == "agent_then_message claude slow Hello"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L221: `assert call_args.kwargs["metadata"].title == "/next-work feature-123"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L242: `assert call_args.kwargs["metadata"].title == "Untitled"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L244: `assert call_args.kwargs["metadata"].auto_command == "agent claude slow"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L265: `assert call_args.kwargs["metadata"].auto_command == "agent gemini med"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L319: `assert data["status"] == "success"`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L320: `assert data["result"]["result"] == "Message sent"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L324: `assert call_args.kwargs["event"] == "message"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L325: `assert call_args.kwargs["payload"]["session_id"] == "sess-123"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L326: `assert call_args.kwargs["payload"]["text"] == "Hello AI"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L339: `assert "transcript" in data`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L343: `assert call_args.kwargs["event"] == "get_session_data"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L504: `assert data[0]["slug"] == "remote-1"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L505: `assert data[0]["computer"] == "remote"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L506: `assert data[0]["project_path"] == "/remote/path"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L527: `assert data[0]["slug"] == "remote-1"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L567: `assert APIServer.ADAPTER_KEY == "api"`
  - Category: **AdapterType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L678: `assert "Failed to create session" in response.json()["detail"]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L690: `assert "Failed to send message" in response.json()["detail"]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L699: `assert "Failed to get transcript" in response.json()["detail"]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L100: `assert data[0]["session_id"] == "sess-1"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L101: `assert "computer" in data[0]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L103: `assert data[1]["session_id"] == "sess-2"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L104: `assert data[1]["computer"] == "remote"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L152: `assert data[0]["session_id"] == "sess-1"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L289: `assert data["tmux_session_name"] == "tc_1234"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L300: `assert data["status"] == "success"`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L305: `assert call_args.args[0] == "sess-123"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L377: `assert data[0]["status"] == "online"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L378: `assert data[0]["user"] == "me"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L379: `assert data[0]["host"] == "localhost"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L381: `assert data[1]["name"] == "remote"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L382: `assert data[1]["status"] == "online"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L383: `assert data[1]["user"] == "you"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L407: `assert data[0]["status"] == "online"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L425: `assert data[0]["name"] == "project1"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L426: `assert data[0]["description"] == "Local project"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L454: `assert data[0]["name"] == "project1"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L470: `assert "claude" in data`
  - Category: **AgentType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L472: `assert data["claude"]["reason"] == "rate_limited"`
  - Category: **AgentType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L547: `assert data[0]["slug"] == "local-1"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L592: `assert summary.session_id == "new-sess"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L593: `assert summary.title == "New Session"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L618: `assert summary.session_id == "sess-1"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L619: `assert summary.title == "Updated"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L666: `assert "Failed to list sessions" in response.json()["detail"]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L711: `assert "Failed to list computers" in response.json()["detail"]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L721: `assert "Failed to list projects" in response.json()["detail"]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L731: `assert "Failed to end session" in response.json()["detail"]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L744: `assert "error" in data["claude"]`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L745: `assert "Database connection failed" in data["claude"]["error"]`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_markdown_utils.py

- L13: `assert result == "print('hello')"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L19: `assert result == "some code"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L25: `assert result == "Outer text\n```inner\ncode\n```\nMore text"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L31: `assert result == "line1\nline2\nline3"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L37: `assert result == "Just plain text"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L43: `assert result == "```python\nsome code"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L48: `assert result == ""`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L54: `assert result == "content"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L73: `assert "```code_with_underscore```" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L79: `assert "`inline_code`" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L85: `assert "\\." in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L86: `assert "\\!" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L92: `assert "```block1```" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L93: `assert "```block2```" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L99: `assert "```outer `inner` outer```" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L104: `assert result == ""`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L119: `assert "\\|" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L120: `assert "\\-" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L66: `assert "\\_" in result or "_" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L66: `assert "\\_" in result or "_" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L112: `assert "\\" in result or "`" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L112: `assert "\\" in result or "`" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_ui_adapter.py

- L117: `assert result == "msg-123"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L147: `assert result == "msg-456"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L168: `assert result == "msg-123"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L172: `assert "```" not in sent_text`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L173: `assert metadata.parse_mode == "MarkdownV2"`
  - Category: **UIParseMode**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L196: `assert "## " not in sent_text`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L197: `assert "📌" not in sent_text`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L198: `assert "✏" not in sent_text`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L199: `assert "*Title*" in sent_text`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L200: `assert "*23:03:31 · 🤖 Assistant*" in sent_text`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L229: `assert result == "msg-123"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L236: `assert session.adapter_metadata.telegram.output_message_id == "msg-123"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L263: `assert "```" in message_text`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L290: `assert "final output" in message_text`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L291: `assert "✅ Process exited" in message_text`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L366: `assert "`\u200b``python" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L367: `assert "`\u200b``\n" in result  # Closing marker also escaped`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L388: `assert "```\nSimple tmux output\nNo code blocks here\n```" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L389: `assert "status line" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L262: `assert "✅" in message_text or "0" in message_text`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L262: `assert "✅" in message_text or "0" in message_text`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_tui_modal.py

- L246: `assert modal.computer == "local"`
  - Category: **ComputerName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L247: `assert modal.project_path == "/home/user/project"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L249: `assert modal.prompt == ""`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L292: `assert "coro" in scheduled`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_tui_sessions_view.py

- L192: `assert "Alpha Session" in output`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L193: `assert "Beta Session" in output`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L202: `assert "claude" in output.lower()`
  - Category: **AgentType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L219: `assert "Test Session" in lines[0]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L220: `assert "Some input" not in "\n".join(lines)`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L221: `assert "Some output" not in "\n".join(lines)`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L238: `assert "test-session-001" in output`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L239: `assert "Test input" in output`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L240: `assert "Test output" in output`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L257: `assert "test-machine" in lines[0]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L258: `assert "(2)" in lines[0]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L271: `assert "/test/project" in lines[0]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L272: `assert "(2)" in lines[0]  # Session count`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L310: `assert pane_manager.args[0] == "tc_123"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L334: `assert "Session 5" in output`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L336: `assert "Session 0" not in output`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L337: `assert "Session 1" not in output`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L355: `assert "[17:43:21] in: hello" in output`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L356: `assert "[17:43:21] out: world" in output`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L404: `assert pane_manager.args[0] == "tc_parent"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L171: `assert any("no items" in line.lower() for line in lines)`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_mcp_wrapper.py

- L549: `assert "caller_session_id" not in out["arguments"]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L582: `assert "caller_session_id" not in out["arguments"]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_summarizer.py

- L21: `assert "User: User 1" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L22: `assert "Assistant: Response 1" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L23: `assert "User: User 2" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L24: `assert "Assistant: Response 2" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L39: `assert "User: Help me" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L40: `assert "I should use a tool" not in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L41: `assert "tool_use" not in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L44: `assert "Assistant: I found the file\nAnd here is the content" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L55: `assert result == ""`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L66: `assert "User: Just saying hi" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L70: `assert "Assistant:" not in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L96: `assert "User: Gemini User 1" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L97: `assert "Assistant: Gemini Response 1" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L98: `assert "Thinking" not in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L125: `assert "User: Codex User 1" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L126: `assert "Assistant: Codex Response 1" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L149: `assert "User: User 3" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L150: `assert "User: User 4" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L151: `assert "User: User 0" not in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_next_machine_breakdown.py

- L23: `return "input.md" in relative_path`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L32: `assert "Read todos/test-slug/input.md and assess Definition of Ready" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L33: `assert "split into smaller todos" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L34: `assert "update state.json and create breakdown.md" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L48: `return "input.md" in relative_path`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L56: `assert "CONTAINER:" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L58: `assert "test-parent-1" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L59: `assert "test-parent-2" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L60: `assert "Work on those first" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L75: `if "input.md" in relative_path:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L87: `assert "Write todos/test-simple/requirements.md" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L88: `assert "CONTAINER" not in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L102: `return "input.md" in relative_path`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L110: `assert "teleclaude__run_agent_command" in result`
  - Category: **ToolName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L111: `assert 'command="next-prepare"' in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L113: `assert "Assess todos/test-slug/input.md for complexity" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L179: `assert content["build"] == "complete"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L180: `assert content["review"] == "pending"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_system_stats.py

- L25: `assert "total_gb" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L26: `assert "used_gb" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L27: `assert "percent" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L54: `assert "total_gb" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L55: `assert "used_gb" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L56: `assert "percent" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L119: `assert "memory" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L120: `assert "disk" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L121: `assert "cpu_percent" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_session_utils.py

- L119: `assert result == "Claude-slow@MozMini"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L127: `assert result == "$MozMini"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L135: `assert result == "Gemini-fast@RasPi"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L147: `assert result == "TeleClaude: $MozMini - Untitled"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L161: `assert result == "TeleClaude: Claude-slow@MozMini - Debug auth flow"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L174: `assert result == "TeleClaude: $MozBook > $RasPi - Untitled"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L191: `assert result == "TeleClaude: Claude-slow@MozBook > Gemini-med@RasPi - Build feature"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L209: `assert result == "TeleClaude: Claude-slow@MozMini > Gemini-fast - Local dispatch"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L217: `assert prefix == "TeleClaude: $MozMini - "`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L218: `assert description == "Debug auth flow"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L226: `assert prefix == "TeleClaude: Claude-slow@MozMini - "`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L227: `assert description == "Debug auth"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L235: `assert prefix == "TeleClaude: $MozBook > $RasPi - "`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L236: `assert description == "Untitled"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L244: `assert prefix == "TeleClaude/fix-bug: Claude-slow@MozMini - "`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L245: `assert description == "Fix auth"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L267: `assert result == "TeleClaude: Claude-slow@MozMini - Untitled"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L281: `assert result == "TeleClaude: $MozBook > Gemini-med@RasPi - Build feature"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L314: `assert result == "TeleClaude: $MozMini > Gemini-fast - Untitled"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L21: `assert result == "My Unique Title"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L39: `assert result == "Duplicate Title (2)"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L60: `assert result == "Foo (4)"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L73: `assert result == "Empty List Title"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L108: `assert result.name == "tmux.txt"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_daemon.py

- L178: `assert call_args[2] == "2026-01-01T00:00:00Z"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L650: `assert "before_snippet" in summary`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L651: `assert "after_snippet" in summary`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L1068: `assert "poll" in call_order`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L320: `assert result["session_id"] == "sess-123"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L321: `assert result["auto_command_status"] == "queued"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L372: `assert result["status"] == "success"`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L418: `assert result["status"] == "success"`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L484: `assert result["status"] == "success"`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L526: `assert result["status"] == "error"`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L527: `assert "Timeout waiting for command acceptance" in result["message"]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L965: `assert kwargs["name"] == "tc_sess-123"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L966: `assert kwargs["working_dir"] == "/tmp/project/subdir"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L967: `assert kwargs["session_id"] == "sess-123"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L968: `assert kwargs["env_vars"]["TELECLAUDE_SESSION_ID"] == "sess-123"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L745: `session_id == "tele-123" and kwargs.get("native_session_id") == "native-123"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L745: `session_id == "tele-123" and kwargs.get("native_session_id") == "native-123"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L798: `c.args == ("tele-123",) and c.kwargs.get("active_agent") == "claude" for c in call_args_list`
  - Category: **AgentType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L1069: `assert call_order.index("poll") > max(i for i, v in enumerate(call_order) if v == "update")`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_computer_registry.py

- L22: `assert match.group(1) == "macbook"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L23: `assert match.group(2) == "2025-11-04 15:30:45"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L32: `assert match.group(1) == "workstation"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L33: `assert match.group(2) == "2025-11-04 16:45:30"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L100: `assert "macbook" in [c["name"] for c in online]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L101: `assert "server" in [c["name"] for c in online]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L102: `assert "workstation" not in [c["name"] for c in online]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L174: `assert info["name"] == "macbook"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L175: `assert info["status"] == "online"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L223: `assert registry.my_ping_message_id == "111"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L229: `assert registry.my_ping_message_id == "111"  # Same ID`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L235: `assert registry.my_pong_message_id == "222"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L241: `assert registry.my_pong_message_id == "222"  # Same ID`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L203: `if "/registry_ping" in kwargs.get("text", ""):`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_research_docs.py

- L65: `if __name__ == "__main__":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_next_machine_git_env.py

- L16: `assert parts[0] == "/tmp/project/.venv/bin"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L17: `assert result["VIRTUAL_ENV"] == "/tmp/project/.venv"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L26: `assert parts[0] == "/tmp/project/.venv/bin"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_tmux_bridge.py

- L178: `assert mock_ensure.await_args.kwargs.get("session_id") == "sid-123"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L154: `assert text_arg == "ls -la"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L231: `assert text_arg == r"Hello\! World\!"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L259: `assert text_arg == "Hello! World!"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L151: `send_keys_call = [call for call in call_args_list if "send-keys" in call[0]]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L228: `send_keys_call = [call for call in call_args_list if "send-keys" in call[0]]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L256: `send_keys_call = [call for call in call_args_list if "send-keys" in call[0]]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_tmux_io_bracketed_paste.py

- L25: `assert tmux_io.wrap_bracketed_paste("") == ""`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_sessions_view.py

- L75: `assert view._active_field["sess-1"] == "none"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L128: `assert tmux_session == "tmux-parent"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L129: `assert child_session == "tmux-child"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L131: `assert computer_info.name == "remote"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_voice_assignment.py

- L28: `assert voice.name == "Test Voice"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L29: `assert voice.elevenlabs_id == "abc123"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L30: `assert voice.macos_voice == "Daniel"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L31: `assert voice.openai_voice == "nova"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L169: `assert "ELEVENLABS_VOICE_ID" not in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L170: `assert "OPENAI_VOICE" not in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L72: `assert result[0].name == "Voice 1"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L73: `assert result[0].elevenlabs_id == "id1"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L74: `assert result[1].name == "Voice 2"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L75: `assert result[1].macos_voice == "Samantha"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L106: `assert result[0].name == "Minimal Voice"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L107: `assert result[0].elevenlabs_id == ""`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L108: `assert result[0].macos_voice == ""`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L109: `assert result[0].openai_voice == ""`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_next_machine_hitl.py

- L296: `assert 'command="/prompts:next-build"' in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L297: `assert "execution script" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L298: `assert "do not re-read" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L312: `assert 'command="next-build"' in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L313: `assert "/prompts:" not in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L314: `assert "execution script" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L315: `assert "do not re-read" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L329: `assert 'command="next-review"' in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L330: `assert "/prompts:" not in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L344: `assert 'Call teleclaude__next_work(slug="test-slug")' in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L345: `assert 'Call teleclaude__next_work(slug="test-slug")()' not in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L32: `assert "Read todos/roadmap.md" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L33: `assert "Before proceeding, read ~/.agents/commands/next-prepare.md" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L49: `assert "Write todos/test-slug/requirements.md" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L50: `assert "Before proceeding, read ~/.agents/commands/next-prepare.md" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L61: `if "requirements.md" in relative_path:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L71: `assert "Write todos/test-slug/implementation-plan.md" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L72: `assert "Before proceeding, read ~/.agents/commands/next-prepare.md" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L84: `if "input.md" in file:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L115: `assert "teleclaude__run_agent_command" in result`
  - Category: **ToolName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L117: `assert 'command="next-prepare"' in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L132: `assert "not in todos/roadmap.md" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L133: `assert "add it to the roadmap" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L134: `assert "Before proceeding, read ~/.agents/commands/next-prepare.md" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L152: `assert "teleclaude__run_agent_command" in result`
  - Category: **ToolName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L154: `assert "not in todos/roadmap.md" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L169: `assert "not in todos/roadmap.md" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L170: `assert "add it to the roadmap and commit" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L232: `assert result["build"] == "complete"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L233: `assert result["review"] == "pending"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L238: `assert content["build"] == "complete"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_redis_adapter.py

- L55: `assert peers[0].name == "RemotePC"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L56: `assert peers[0].status == "online"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L57: `assert peers[0].user == "testuser"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L58: `assert peers[0].host == "remote.local"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L175: `assert payload["data"]["session_id"] == "sess-123"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L176: `assert payload["data"]["source_computer"] == "RemotePC"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L177: `assert "transcript_path" not in payload["data"]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L178: `assert "summary" not in payload["data"]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L240: `assert "key" in captured_data`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L241: `assert captured_data["key"] == "computer:TestPC:heartbeat"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L245: `assert "computer_name" in heartbeat`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L246: `assert "last_seen" in heartbeat`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L247: `assert heartbeat["computer_name"] == "TestPC"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L248: `assert heartbeat["projects_digest"] == "digest-123"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L294: `assert captured_calls[0]["stream"] == "session:test-session-123:output"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_config.py

- L30: `assert result[0].name == "development"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L31: `assert result[0].desc == "dev projects"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L32: `assert result[0].path == "/home/user/dev"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L34: `assert result[1].name == "documents"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L35: `assert result[1].desc == "personal docs"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L36: `assert result[1].path == "/home/user/docs"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L47: `assert result[0].name == "myproject"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L48: `assert result[0].desc == ""`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L49: `assert result[0].path == "/home/user/project"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L101: `assert result[0].name == "teleclaude"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L102: `assert result[0].desc == "TeleClaude folder"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L103: `assert result[0].path == "/home/teleclaude"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L125: `assert result[0].path == "/home/teleclaude"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L126: `assert result[1].path == "/home/projects"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L144: `assert result[0].name == "teleclaude"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L145: `assert result[0].desc == "TeleClaude folder"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L146: `assert result[0].path == "/home/teleclaude"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L168: `assert result[0].path == "/home/teleclaude"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L169: `assert result[1].path == "/a"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L170: `assert result[2].path == "/b"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L171: `assert result[3].path == "/c"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L17: `assert "Invalid trusted_dirs entry type" in str(e)`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L62: `assert "Invalid trusted_dirs entry type" in str(e)`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L77: `assert "Invalid trusted_dirs entry type" in str(e)`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_voice_message_handler.py

- L80: `assert result == "Hello world"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L123: `assert result == "Success on retry"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L189: `assert "requires an active process" in call_args[1]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L266: `assert result == "Transcribed text"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L307: `assert result == "Transcribed text"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L352: `assert "failed" in last_call[0][1].lower()`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_models.py

- L32: `assert data["session_id"] == "test-789"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L33: `assert data["computer_name"] == "TestPC"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L141: `assert data["session_id"] == "session-789"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L142: `assert data["file_path"] == "/tmp/test.txt"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L143: `assert data["recording_type"] == "text"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_adapter_client_terminal_origin.py

- L103: `assert message_id == "msg-1"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_redis_adapter_idle_log_throttle.py

- L30: `assert kwargs["stream"] == "messages:test"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_redis_adapter_cache_pull.py

- L288: `assert call_args[0][0] == "RemotePC"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L363: `assert call_args[0][0] == "RemotePC"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L364: `assert call_args[0][1] == "/home/user/project"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L428: `assert todos_call[0][0] == "RemotePC"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L430: `assert "/home/user/projectA" in todos_by_project`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L431: `assert "/home/user/projectB" in todos_by_project`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L509: `assert call_args[0][0].name == "RemotePC"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L510: `assert call_args[0][0].status == "online"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_tmux_bridge_tmpdir.py

- L56: `assert "tmux" in called_args[0]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L57: `assert "-e" in called_args`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_launch_env.py

- L10: `assert 'PATH=".venv/bin:$PATH"' in wrapper`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L17: `assert "<string>.venv/bin:{{PATH}}</string>" in template`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_session_launcher.py

- L46: `assert result["session_id"] == "s1"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L21: `assert session_id == "s1"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_events.py

- L10: `assert cmd == "new_session"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L20: `assert cmd == "cd"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L30: `assert cmd == "cd"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L40: `assert cmd == "claude"`
  - Category: **AgentType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L72: `assert cmd == "cmd"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L74: `assert "'unclosed" in args`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_mcp_send_result.py

- L38: `assert result["status"] == "success"`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L39: `assert result["message_id"] == "msg-123"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L50: `assert result["status"] == "error"`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L51: `assert "empty" in result["message"].lower()`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L62: `assert result["status"] == "error"`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L63: `assert "empty" in result["message"].lower()`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L76: `assert result["status"] == "error"`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L77: `assert "not found" in result["message"].lower()`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L96: `assert "*bold text*" in sent_text`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L97: `assert "**" not in sent_text`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L115: `assert "Header Title" in sent_text`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L117: `assert "*" in sent_text`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L136: `assert "```md\n" in sent_text`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L175: `assert metadata.parse_mode == "MarkdownV2"`
  - Category: **UIParseMode**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L193: `assert result["status"] == "success"`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L194: `assert result["message_id"] == "msg-456"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L195: `assert "warning" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L215: `assert result["status"] == "error"`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L216: `assert "Network error" in result["message"]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L238: `assert "print" in sent_text`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L265: `assert metadata.parse_mode == "HTML"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L283: `assert metadata.parse_mode == "MarkdownV2"`
  - Category: **UIParseMode**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L138: `assert "\n```\n" not in sent_text or sent_text.count("```") == 2  # opening and closing only`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L242: `assert "```" not in code_block_content or "\\`" in code_block_content or "\u200b" in code_block_content`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L242: `assert "```" not in code_block_content or "\\`" in code_block_content or "\u200b" in code_block_content`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L242: `assert "```" not in code_block_content or "\\`" in code_block_content or "\u200b" in code_block_content`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_tui_todos.py

- L34: `assert result[0].slug == "feature-one"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L35: `assert result[0].status == "pending"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L50: `assert result[0].slug == "feature-two"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L51: `assert result[0].status == "ready"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L63: `assert result[0].slug == "feature-three"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L64: `assert result[0].status == "in_progress"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L80: `assert result[0].slug == "feature-one"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L81: `assert result[0].description == "This is a description that spans multiple lines"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L133: `assert result[0].slug == "feature-one"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L134: `assert result[1].slug == "feature-two"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L135: `assert result[2].slug == "feature-three"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L158: `assert result[0].slug == "feature-one"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L159: `assert result[1].slug == "feature-two"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L177: `assert "First line" in result[0].description`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L178: `assert "Second line" in result[0].description`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_mcp_set_dependencies.py

- L40: `assert "a" in cycle`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L32: `assert "a" in cycle and "b" in cycle`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L32: `assert "a" in cycle and "b" in cycle`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L48: `assert "a" in cycle and "b" in cycle and "c" in cycle`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L48: `assert "a" in cycle and "b" in cycle and "c" in cycle`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L48: `assert "a" in cycle and "b" in cycle and "c" in cycle`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L116: `assert "ERROR: INVALID_SLUG" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L117: `assert "lowercase alphanumeric" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L121: `assert "ERROR: INVALID_SLUG" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L125: `assert "ERROR: INVALID_DEP" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L147: `assert "ERROR: SLUG_NOT_FOUND" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L148: `assert "not found in roadmap" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L170: `assert "ERROR: DEP_NOT_FOUND" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L171: `assert "not found in roadmap" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L193: `assert "ERROR: SELF_REFERENCE" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L194: `assert "cannot depend on itself" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L222: `assert "ERROR: CIRCULAR_DEP" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L223: `assert "Circular dependency detected" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_tui_preparation_view.py

- L190: `assert "Build: complete" in output`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L191: `assert "Review: pending" in output`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L200: `assert "🖥" in lines[0]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L201: `assert "test-machine" in lines[0]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L202: `assert "(3)" in lines[0]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L215: `assert "📁" in lines[0]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L216: `assert "/test/project" in lines[0]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L217: `assert "(2)" in lines[0]  # Todo count`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L255: `assert pane_manager.args[0] == "tc_456"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L269: `assert "1. Requirements" in lines[0]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L281: `assert "test-todo" in lines[0]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L315: `assert "todo-05" in output`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L317: `assert "todo-00" not in output`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L318: `assert "todo-01" not in output`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L158: `assert "[.]" in output or "ready" in output.lower()`
  - Category: **NextMachineToken**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L158: `assert "[.]" in output or "ready" in output.lower()`
  - Category: **NextMachineToken**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L166: `assert "[ ]" in output or "pending" in output.lower()`
  - Category: **NextMachineToken**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L166: `assert "[ ]" in output or "pending" in output.lower()`
  - Category: **NextMachineToken**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L174: `assert "[>]" in output or "in_progress" in output.lower()`
  - Category: **NextMachineToken**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L174: `assert "[>]" in output or "in_progress" in output.lower()`
  - Category: **NextMachineToken**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L150: `assert any("no items" in line.lower() for line in lines)`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_db_crud.py

- L144: `if __name__ == "__main__":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L35: `assert session.title == "Test Session"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L51: `assert updated.title == "Updated Title"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L130: `assert rows[0]["request_id"] == "req-123"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_preparation_view.py

- L97: `assert "split-window" in args`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L98: `assert "session-1" in args[-1]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_adapter_client_protocols.py

- L69: `assert stream_id == "req_123"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L142: `assert stream_id == "req_123"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L154: `assert stream_id == "resp_123"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_transcript.py

- L74: `assert "Transcript file not found" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L240: `assert info.display_name == "Gemini"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L241: `assert info.file_prefix == "gemini"`
  - Category: **AgentType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L271: `assert "# Agent Test" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L272: `assert "hi" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L273: `assert "there" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L298: `assert "```" in raw`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L307: `assert "`\u200b``" in escaped`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L308: `assert "```" not in escaped`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L336: `assert "Codex Test" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L337: `assert "codex user request" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L338: `assert "codex assistant reply" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L370: `assert "EARLY_MARKER" in full`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L371: `assert "LATEST_MARKER" in full`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L374: `assert "truncated" in truncated.lower()`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L375: `assert "LATEST_MARKER" in truncated`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L376: `assert "EARLY_MARKER" not in truncated`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L409: `assert "Gemini Test" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L410: `assert "gemini user input" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L411: `assert "gemini assistant answer" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L412: `assert "Considering options" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L413: `assert "TOOL CALL" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L414: `assert "TOOL RESPONSE" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L415: `assert "> no matches found" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L447: `assert "TOOL RESPONSE (tap to reveal)" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L448: `assert "||secret output||" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L32: `assert "# Test Session" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L35: `assert "## 👤 User" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L36: `assert "hello" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L39: `assert "*User said hello*" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L42: `assert "Hi there" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L60: `assert "```python" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L61: `assert "print('test')" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L62: `assert "```" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L65: `assert "*Check this code:*" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L66: `assert "*Looks good*" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L98: `assert "User 1" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L99: `assert "User 2" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L129: `assert lines[thinking_idx + 1] == ""`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L175: `assert "msg1" not in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L177: `assert "msg2" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L178: `assert "msg3" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L200: `assert "msg1" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L201: `assert "msg2" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L203: `assert "msg3" not in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L230: `assert "truncated" in truncated.lower()`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L232: `assert "END_MARKER" in truncated`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L148: `assert "10:30:00" in result or "2025-11-28 10:30:00" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L148: `assert "10:30:00" in result or "2025-11-28 10:30:00" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L149: `assert "10:30:05" in result or "2025-11-28 10:30:05" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L149: `assert "10:30:05" in result or "2025-11-28 10:30:05" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L120: `thinking_idx = next(i for i, line in enumerate(lines) if "*Processing*" in line)`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L124: `i for i in range(thinking_idx + 1, len(lines)) if lines[i].strip() and not lines[i].strip() == ""`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_cache.py

- L66: `assert computers[0].name == "fresh"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L69: `assert "stale" not in cache._computers`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L108: `assert local_sessions[0].session_id == "sess-1"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L196: `assert "sess-123" not in cache._sessions`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L285: `assert projects[0].name == "fresh"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L298: `assert projects[0].name == "stale"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L325: `assert entries[0].computer == "remote"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L326: `assert entries[0].project_path == "/path"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L352: `assert "test" not in cache._computers`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L356: `assert "sess-123" not in cache._sessions`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L443: `assert local_projects[0].name == "local-proj"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_tmux_bridge_timeouts.py

- L62: `assert exc_info.value.operation == "test operation"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L67: `assert "test operation timed out after 0.1s" in str(exc_info.value)`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L153: `assert exc_info.value.operation == "test operation"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L158: `assert "test operation timed out after 0.1s" in str(exc_info.value)`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_next_machine_state_deps.py

- L186: `assert "item-a" in cycle`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L187: `assert "item-b" in cycle`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L188: `assert "item-c" in cycle`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L203: `assert "item-a" in cycle`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L418: `assert 'command="next-finalize"' in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L419: `assert "Call teleclaude__next_work()" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L420: `assert "Call teleclaude__next_work(slug=" not in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L48: `assert "- [.] test-item" in content`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L63: `assert "- [>] test-item" in content`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L177: `assert "item-a" in cycle and "item-b" in cycle`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L177: `assert "item-a" in cycle and "item-b" in cycle`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L238: `assert "next-bugs" not in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L240: `assert "test-item" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L275: `assert "ready-item" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L276: `assert "blocked-item" not in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L297: `assert "ERROR:" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L298: `assert "DEPS_UNSATISFIED" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L315: `assert "ERROR:" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L316: `assert "ITEM_NOT_READY" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L317: `assert "[ ] (pending)" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L351: `assert "next-review" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L352: `assert "merge-base" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L383: `assert "ERROR:" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L384: `assert "MAIN_AHEAD" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L440: `assert slug == "ready-item"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L467: `assert slug == "ready-item"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L480: `assert slug == "ready-item"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_protocols.py

- L40: `assert "send_request" in protocol_methods`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L41: `assert "send_response" in protocol_methods`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L42: `assert "poll_output_stream" in protocol_methods`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L56: `assert result == "stream_123"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L71: `assert result == "stream_456"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_file_handler.py

- L43: `assert file_handler.sanitize_filename('file<>:"/|?*.txt') == "file________.txt"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L47: `assert file_handler.sanitize_filename("my-file_123.pdf") == "my-file_123.pdf"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L51: `assert file_handler.sanitize_filename("..file...") == "file"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L55: `assert file_handler.sanitize_filename("...") == "file"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L56: `assert file_handler.sanitize_filename("") == "file"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L143: `assert "requires an active process" in sent_messages[0][1]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L181: `assert "not ready yet" in sent_messages[0][1]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L283: `assert "file.pdf" in sent_messages[0][1]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L284: `assert "2.00 MB" in sent_messages[0][1]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L313: `assert "Failed to send" in sent_messages[0][1]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_agents.py

- L66: `assert "-m opus" in cmd`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L88: `assert "exec" in cmd.split()`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L96: `assert "-m opus" not in cmd  # continue_template path skips model flag`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L102: `assert "--resume abc123" in cmd`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L103: `assert "-m gemini-3-pro-preview" in cmd  # model flag included for explicit session resume`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/test_mcp_handlers.py

- L58: `assert result["status"] == "success"`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L59: `assert result["session_id"] == "sess-123"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L60: `assert result["tmux_session_name"] == "tmux-123"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L78: `assert result["status"] == "success"`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L23: `return computer == "local"`
  - Category: **ComputerName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/integration/test_process_exit_detection.py

- L36: `assert output_message_id == "msg-123"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L87: `assert stored_id == "msg-456"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L100: `assert output_message_id == "msg-456"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/integration/conftest.py

- L468: `if daemon.mock_command_mode == "passthrough":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L478: `elif daemon.mock_command_mode == "long":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L472: `if session_outputs[session_name] and "Ready" in session_outputs[session_name]:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/integration/test_state_machine_workflow.py

- L71: `assert slug == "main-item"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L76: `assert "- [x] dep-item" in content`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L77: `assert "- [.] main-item" in content`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L112: `assert "independent-feature" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L113: `assert "blocked-feature" not in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L117: `assert "ERROR:" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L118: `assert "DEPS_UNSATISFIED" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L138: `assert "ERROR:" not in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L139: `assert "DEPS_UNSATISFIED" not in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L174: `assert "DEPS_UNSATISFIED" not in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/integration/test_command_e2e.py

- L140: `if __name__ == "__main__":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L25: `assert daemon.mock_command_mode == "short"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L58: `assert "Command executed" in output, f"Should see mocked command output, got: {output[:300]}"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L113: `assert "Ready" in output, f"Should see initial output, got: {output[:500]}"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L128: `assert "Echo: test message" in output, f"Should see response to input, got: {output[:500]}"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/integration/test_ai_to_ai_session_init_e2e.py

- L276: `if __name__ == "__main__":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L103: `assert session.origin_adapter == "redis"`
  - Category: **AdapterType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L107: `assert "Test AI-to-AI Session" in session.title`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L118: `assert envelope["status"] == "success", f"Response should have success status, got: {envelope}"`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L187: `assert session.origin_adapter == "redis"`
  - Category: **AdapterType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L196: `assert envelope["status"] == "success", f"Response should have success status, got: {envelope}"`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L199: `assert "session_id" in envelope["data"], f"session_id should be in data, got: {envelope['data']}"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/integration/test_mcp_tools.py

- L274: `assert "Error:" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L275: `assert "File not found" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L57: `assert result[0]["name"] == "TestComputer"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L58: `assert result[0]["status"] == "local"`
  - Category: **ComputerName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L61: `assert result[1]["name"] == "testcomp"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L62: `assert result[2]["name"] == "workstation"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L93: `assert "session_id" in session`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L94: `assert "origin_adapter" in session`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L95: `assert "title" in session`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L181: `assert "Message sent" in output`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L183: `assert "teleclaude__get_session_data" in output`
  - Category: **ToolName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L215: `assert "File sent successfully" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L217: `assert "file-msg-789" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L229: `assert call_kwargs.get("caption") == "Test upload from Claude"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L248: `assert "Error:" in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L127: `assert result["status"] == "success"`
  - Category: **Status**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L128: `assert result["session_id"] == "remote-uuid-123"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L141: `assert mock_send.call_args_list[0][1]["command"] == "/new_session"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L142: `assert mock_send.call_args_list[0][1]["computer_name"] == "workstation"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L145: `assert mock_send.call_args_list[1][1]["command"] == "/cd /home/user/project"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L146: `assert mock_send.call_args_list[1][1]["session_id"] == "remote-uuid-123"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L151: `assert "| ls -la'" not in claude_cmd  # message is passed raw`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L153: `assert mock_send.call_args_list[2][1]["session_id"] == "remote-uuid-123"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/integration/test_research_docs_workflow.py

- L106: `if __name__ == "__main__":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/integration/test_worktree_preparation_integration.py

- L110: `assert "CRITICAL: Refuse to run from a git worktree" in content`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L111: `assert "Cannot run 'make install' from a git worktree!" in content`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L112: `assert 'if [ "$GIT_DIR" != "$COMMON_DIR" ]' in content`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L121: `assert "CRITICAL: Refuse to run from a git worktree" in content`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L122: `assert "Cannot run 'make init' from a git worktree!" in content`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L123: `assert 'if [ "$GIT_DIR" != "$COMMON_DIR" ]' in content`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/integration/test_multi_adapter_broadcasting.py

- L727: `if __name__ == "__main__":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L183: `assert call_text == "Test output"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L186: `assert result == "msg-123"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L482: `assert result == "msg-123"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L709: `assert peers[0]["name"] == "RemotePC"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L720: `assert session.computer_name == "LocalPC"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/integration/test_session_lifecycle.py

- L194: `if __name__ == "__main__":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L82: `if "workspace_dir" in locals() and workspace_dir.exists():`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/integration/test_file_upload.py

- L87: `assert sent_keys[0][0] == "tmux_test"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L94: `assert "document.pdf" in sent_messages[0][1]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L95: `assert "5.00 MB" in sent_messages[0][1]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L161: `assert "requires an active process" in sent_messages[0][1]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L162: `assert "File saved: file.pdf" in sent_messages[0][1]`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/integration/test_redis_heartbeat.py

- L23: `assert session.computer_name == "TestPC"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/integration/test_e2e_smoke.py

- L211: `assert call_args["event"] == "session_created"`
  - Category: **EventName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L212: `assert call_args["data"]["session_id"] == "test-session-123"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L246: `assert call_args["event"] == "session_removed"`
  - Category: **EventName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L247: `assert call_args["data"]["session_id"] == "test-session-123"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L296: `assert computers[0].name == "fresh-computer"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L299: `assert "stale-computer" not in cache._computers`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L300: `assert "fresh-computer" in cache._computers`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L332: `assert "tampered" not in cache.get_interested_computers("sessions")`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L358: `assert sessions[0].session_id == "redis-session-456"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L359: `assert sessions[0].computer == "remote-computer"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L410: `assert call_args["event"] == "session_created"`
  - Category: **EventName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L411: `assert call_args["data"]["session_id"] == "round-trip-789"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L412: `assert call_args["data"]["computer"] == "remote-computer"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L499: `assert call_args["event"] == "session_created"`
  - Category: **EventName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L501: `assert call_args["data"]["computer"] == "test-computer"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L502: `assert call_args["data"]["title"] == "Local Lifecycle Test Session"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L578: `assert call_args["event"] == "session_created"`
  - Category: **EventName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L579: `assert call_args["data"]["session_id"] == "post-init-session"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L580: `assert call_args["data"]["computer"] == "test-computer"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L581: `assert call_args["data"]["title"] == "Post-Init Cache Test"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L623: `assert call1["event"] == "session_created"`
  - Category: **EventName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L624: `assert call2["event"] == "session_created"`
  - Category: **EventName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L625: `assert call1["data"]["session_id"] == "broadcast-test"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L626: `assert call2["data"]["session_id"] == "broadcast-test"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L660: `assert call_args["event"] == "session_created"`
  - Category: **EventName**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### tests/unit/core/test_next_machine_deferral.py

- L106: `assert 'command="next-defer"' in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L148: `assert 'command="next-finalize"' in result`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### scripts/fix_subprocess_timeouts.py

- L38: `if __name__ == "__main__":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### scripts/verify_resilience.py

- L92: `if __name__ == "__main__":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### scripts/install_hooks.py

- L461: `if __name__ == "__main__":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L36: `if part.endswith(".py") and "receiver" in part:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L63: `if block.get("matcher") == "*":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L389: `if "notify" in config:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L410: `if not skip_notify_update and "notify" not in config:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L167: `if _extract_receiver_script(cmd) == "receiver":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L261: `if _extract_receiver_script(cmd) == "receiver":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L394: `and "receiver.py" in str(existing_notify[1])`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### scripts/research_docs.py

- L90: `if __name__ == "__main__":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### scripts/guardrails.py

- L253: `if __name__ == "__main__":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L70: `if pyright.get("typeCheckingMode") != "strict":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L75: `if "[tool.ruff]" not in pyproject:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### scripts/test_adapter_key.py

- L58: `if __name__ == "__main__":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L38: `assert key == "telegram", f"Expected 'telegram', got '{key}'"`
  - Category: **AdapterType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L45: `assert key == "redis", f"Expected 'redis', got '{key}'"`
  - Category: **AdapterType**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L52: `assert key == "unknown", f"Expected 'unknown', got '{key}'"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L18: `if class_name == "TelegramAdapter":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L20: `if class_name == "RedisTransport":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### bin/mcp-wrapper.py

- L1169: `if __name__ == "__main__":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L105: `if method == "tools/call":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L312: `if message.get("method") == "tools/call":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L126: `if method == "tools/call" and tool_name:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L474: `skip_resync = reason == "initialize"`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L281: `if param_name == "cwd":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L289: `has_caller = caller_existing is not None and (not isinstance(caller_existing, str) or caller_existing != "")`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L988: `if msg.get("method") == "initialize":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L276: `has_value = existing is not None and (not isinstance(existing, str) or existing != "")`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L721: `if method == "tools/list" and request_id is not None:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L840: `if method == "notifications/initialized" and request_id is None:`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L733: `if msg.get("method") == "initialize":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L736: `elif msg.get("method") == "notifications/initialized":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L918: `and "result" in msg`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

- L928: `"result" in msg`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### bin/notify_agents.py

- L266: `if __name__ == "__main__":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)

### bin/send_telegram.py

- L182: `if __name__ == "__main__":`
  - Category: **StringLiteral**
  - Action: _TBD_ (enum/helper/constant or structured error code)
