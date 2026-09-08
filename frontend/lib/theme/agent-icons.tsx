/**
 * Exhaustive agent icon presentation.
 *
 * One `Record<AgentType, LucideIcon>` owner replaces the three independently
 * hand-duplicated icon switch statements that used to exist in
 * SessionTree.tsx, SessionHeader.tsx, and SessionList.tsx. Adding a
 * canonical agent without adding it here is a TypeScript error, not a
 * silent fallback to another agent's icon.
 */

import type { SVGProps } from 'react';
import { Bot, Brain, Code2, Sparkles, Zap } from 'lucide-react';
import type { AgentType } from '@/lib/theme/tokens';

// Exhaustiveness lives in this switch: TypeScript's completeness check
// (`never` in the default arm) fails to compile if a canonical agent is
// added without an icon here. Each branch returns a directly named import as
// the JSX tag — never a variable holding a runtime-selected component
// reference — so eslint-plugin-react-hooks' static-components rule, which
// forbids exactly that pattern, has nothing to flag.
export function AgentIcon({ agent, ...props }: { agent: AgentType | null | undefined } & SVGProps<SVGSVGElement>) {
  switch (agent) {
    case 'claude':
      return <Brain {...props} />;
    case 'codex':
      return <Code2 {...props} />;
    case 'gemini':
      return <Sparkles {...props} />;
    case 'deepseek':
      return <Zap {...props} />;
    case null:
    case undefined:
      return <Bot {...props} />;
    default: {
      const exhaustive: never = agent;
      return exhaustive;
    }
  }
}
