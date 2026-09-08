/**
 * Auto-generated from teleclaude.agent_registry.
 * Do not edit by hand.
 */

import type { AgentName } from './generated-types';

export interface AgentColorTiers {
  readonly subtle: string;
  readonly muted: string;
  readonly normal: string;
  readonly highlight: string;
}

export interface AgentThemeTiers {
  readonly dark: AgentColorTiers;
  readonly light: AgentColorTiers;
}

export const AGENT_NAMES: readonly AgentName[] = ['claude', 'codex', 'gemini', 'deepseek'];

export const AGENT_REGISTRY_REVISION = 'f0e1725866e0';

export const AGENT_PALETTE: Record<AgentName, AgentThemeTiers> = {
  claude: {
    dark: { subtle: '#875f00', muted: '#af875f', normal: '#d7af87', highlight: '#ffffff' },
    light: { subtle: '#d7af87', muted: '#af875f', normal: '#875f00', highlight: '#000000' },
  },
  codex: {
    dark: { subtle: '#5f87af', muted: '#87afd7', normal: '#afd7ff', highlight: '#ffffff' },
    light: { subtle: '#87afd7', muted: '#5f87af', normal: '#005f87', highlight: '#000000' },
  },
  gemini: {
    dark: { subtle: '#8787af', muted: '#af87ff', normal: '#d7afff', highlight: '#ffffff' },
    light: { subtle: '#d787ff', muted: '#af5fff', normal: '#870087', highlight: '#000000' },
  },
  deepseek: {
    dark: { subtle: '#3b4a8a', muted: '#7582cf', normal: '#9babfb', highlight: '#ffffff' },
    light: { subtle: '#6d7fe0', muted: '#4d6bfe', normal: '#2f4ad0', highlight: '#000000' },
  },
};
