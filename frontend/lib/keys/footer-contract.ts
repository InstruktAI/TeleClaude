import type { ViewContext } from './types';

export interface FooterHint {
  action: string;
  key: string;
  description: string;
}

export interface FooterRows {
  contextHints: FooterHint[];
  globalHints: FooterHint[];
}

export type FooterNodeType = 'computer' | 'project' | 'session' | null | undefined;
export type FooterContext = ViewContext;

const GLOBAL_HINTS: FooterHint[] = [
  { key: 'q', description: 'Quit', action: 'quit' },
  { key: 'v', description: 'TTS', action: 'toggle_tts' },
  { key: 'Esc', description: 'Back', action: 'go_back' },
];

const PREPARATION_HINTS: FooterHint[] = [
  { key: 'Space', description: 'Preview file', action: 'preview_file' },
  { key: 'n', description: 'New todo', action: 'new_todo' },
  { key: 'b', description: 'New bug', action: 'new_bug' },
  { key: 'p', description: 'Prepare todo', action: 'prepare_todo' },
  { key: 's', description: 'Start work', action: 'start_work' },
  { key: 'r', description: 'Refine input', action: 'refine_input' },
  { key: 'R', description: 'Remove todo', action: 'remove_todo' },
  { key: 'f', description: 'Freeze todo', action: 'freeze_todo' },
  { key: 'Shift+\u2191', description: 'Move todo up', action: 'move_todo_up' },
  { key: 'Shift+\u2193', description: 'Move todo down', action: 'move_todo_down' },
];

const CONFIGURATION_HINTS: FooterHint[] = [
  { key: 'Enter', description: 'Select/Toggle', action: 'select_item' },
  { key: 'Tab', description: 'Next tab', action: 'next_tab' },
  { key: 'Shift+Tab', description: 'Previous tab', action: 'prev_tab' },
];

const JOBS_HINTS: FooterHint[] = [{ key: 'Enter', description: 'Run job', action: 'run_job' }];

const SESSIONS_SHARED_HINTS: FooterHint[] = [
  { key: '+', description: 'All', action: 'expand_all' },
  { key: '-', description: 'None', action: 'collapse_all' },
];

const SESSION_HINTS_BY_NODE_TYPE: Record<'session' | 'project' | 'computer' | 'none', FooterHint[]> = {
  session: [
    { key: 'Space', description: 'Preview', action: 'space_action' },
    { key: 'Enter', description: 'Focus', action: 'activate_session' },
    { key: 'n', description: 'New session', action: 'new_session' },
    { key: 'k', description: 'Kill session', action: 'kill_session' },
    { key: 'R', description: 'Restart', action: 'restart_agent' },
  ],
  project: [
    { key: 'Enter', description: 'New session', action: 'activate_session' },
    { key: 'n', description: 'New session', action: 'new_session' },
  ],
  computer: [],
  none: [{ key: 'n', description: 'New session', action: 'new_session' }],
};

function sessionNodeKey(nodeType: FooterNodeType): keyof typeof SESSION_HINTS_BY_NODE_TYPE {
  if (nodeType === 'session' || nodeType === 'project' || nodeType === 'computer') {
    return nodeType;
  }
  return 'none';
}

export function getFooterRows(context: FooterContext, selectedNodeType?: FooterNodeType): FooterRows {
  switch (context) {
    case 'sessions': {
      const contextHints = [...SESSION_HINTS_BY_NODE_TYPE[sessionNodeKey(selectedNodeType)], ...SESSIONS_SHARED_HINTS];
      return { contextHints, globalHints: GLOBAL_HINTS };
    }
    case 'preparation':
      return { contextHints: PREPARATION_HINTS, globalHints: GLOBAL_HINTS };
    case 'configuration':
      return { contextHints: CONFIGURATION_HINTS, globalHints: GLOBAL_HINTS };
    case 'jobs':
      return { contextHints: JOBS_HINTS, globalHints: GLOBAL_HINTS };
    case 'global':
    default:
      return { contextHints: [], globalHints: GLOBAL_HINTS };
  }
}
