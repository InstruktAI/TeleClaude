/**
 * Modal overlay for creating a new AI agent session.
 *
 * Form fields:
 *   - Computer (dropdown)
 *   - Project (dropdown)
 *   - Agent (radio: Claude, Gemini, Codex)
 *   - Mode (radio: fast, med, slow)
 *   - Title (text input)
 *   - Prompt (text input)
 *
 * Tab cycles through fields. Enter submits. Escape cancels.
 * Unavailable agents are grayed out and skipped during selection.
 *
 * Mirrors the Python StartSessionModal from teleclaude/cli/tui/widgets/modal.py.
 */

import React, { useState, useCallback, useMemo } from "react";
import { Box, Text, useInput } from "ink";

import type {
  AgentName,
  ThinkingMode,
  ComputerInfo,
  ProjectInfo,
  AgentAvailabilityInfo,
  CreateSessionRequest,
} from "@/lib/api/types.js";
import {
  themeText,
  modalBorderColor,
} from "@/lib/theme/ink-colors.js";
import { AgentSelector } from "./inputs/AgentSelector.js";
import { ModeSelector } from "./inputs/ModeSelector.js";
import { PromptInput } from "./inputs/PromptInput.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface StartSessionModalProps {
  computers: ComputerInfo[];
  projects: ProjectInfo[];
  agentAvailability?: Record<string, AgentAvailabilityInfo>;
  /** Pre-selected computer name (e.g. from context). */
  defaultComputer?: string;
  /** Pre-selected project path (e.g. from tree selection). */
  defaultProjectPath?: string;
  onSubmit: (request: CreateSessionRequest) => void;
  onCancel: () => void;
}

// Field indices for tab navigation
const FIELD_COMPUTER = 0;
const FIELD_PROJECT = 1;
const FIELD_AGENT = 2;
const FIELD_MODE = 3;
const FIELD_TITLE = 4;
const FIELD_PROMPT = 5;
const FIELD_COUNT = 6;

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function StartSessionModal({
  computers,
  projects,
  agentAvailability,
  defaultComputer,
  defaultProjectPath,
  onSubmit,
  onCancel,
}: StartSessionModalProps) {
  // ---- Form state ----------------------------------------------------------

  const [activeField, setActiveField] = useState(FIELD_COMPUTER);

  // Computer selection
  const computerNames = useMemo(
    () => computers.map((c) => c.name),
    [computers],
  );
  const defaultComputerIndex = useMemo(() => {
    if (!defaultComputer) return 0;
    const idx = computerNames.indexOf(defaultComputer);
    return idx >= 0 ? idx : 0;
  }, [computerNames, defaultComputer]);
  const [computerIndex, setComputerIndex] = useState(defaultComputerIndex);
  const selectedComputer = computerNames[computerIndex] ?? "";

  // Project selection (filtered by selected computer)
  const filteredProjects = useMemo(
    () => projects.filter((p) => p.computer === selectedComputer),
    [projects, selectedComputer],
  );
  const defaultProjectIndex = useMemo(() => {
    if (!defaultProjectPath) return 0;
    const idx = filteredProjects.findIndex((p) => p.path === defaultProjectPath);
    return idx >= 0 ? idx : 0;
  }, [filteredProjects, defaultProjectPath]);
  const [projectIndex, setProjectIndex] = useState(defaultProjectIndex);
  const selectedProject = filteredProjects[projectIndex];

  // Agent
  const [agent, setAgent] = useState<AgentName>("claude");

  // Mode
  const [mode, setMode] = useState<ThinkingMode>("slow");

  // Title
  const [title, setTitle] = useState("");

  // Prompt
  const [prompt, setPrompt] = useState("");

  // ---- Field navigation ----------------------------------------------------

  const cycleField = useCallback(
    (direction: 1 | -1) => {
      setActiveField((prev) => {
        let next = (prev + direction + FIELD_COUNT) % FIELD_COUNT;
        // Skip project field if no projects available
        if (next === FIELD_PROJECT && filteredProjects.length === 0) {
          next = (next + direction + FIELD_COUNT) % FIELD_COUNT;
        }
        return next;
      });
    },
    [filteredProjects.length],
  );

  // ---- Submission ----------------------------------------------------------

  const handleSubmit = useCallback(() => {
    if (!selectedComputer || !selectedProject) return;

    const request: CreateSessionRequest = {
      computer: selectedComputer,
      project_path: selectedProject.path,
      agent,
      thinking_mode: mode,
      title: title.trim() || undefined,
      message: prompt.trim() || undefined,
    };

    onSubmit(request);
  }, [selectedComputer, selectedProject, agent, mode, title, prompt, onSubmit]);

  // ---- Global input handler ------------------------------------------------

  useInput(
    (input, key) => {
      // Escape always cancels
      if (key.escape) {
        onCancel();
        return;
      }

      // Tab cycles fields forward
      if (key.tab) {
        cycleField(1);
        return;
      }

      // Enter on non-text fields submits; text fields handle Enter internally
      if (key.return && activeField !== FIELD_TITLE && activeField !== FIELD_PROMPT) {
        handleSubmit();
        return;
      }

      // Computer dropdown navigation
      if (activeField === FIELD_COMPUTER) {
        if (key.leftArrow) {
          setComputerIndex((prev) => Math.max(0, prev - 1));
          setProjectIndex(0); // reset project on computer change
        } else if (key.rightArrow) {
          setComputerIndex((prev) =>
            Math.min(computerNames.length - 1, prev + 1),
          );
          setProjectIndex(0);
        }
        return;
      }

      // Project dropdown navigation
      if (activeField === FIELD_PROJECT) {
        if (key.leftArrow) {
          setProjectIndex((prev) => Math.max(0, prev - 1));
        } else if (key.rightArrow) {
          setProjectIndex((prev) =>
            Math.min(filteredProjects.length - 1, prev + 1),
          );
        }
        return;
      }
    },
    { isActive: activeField !== FIELD_AGENT && activeField !== FIELD_MODE },
  );

  // ---- Render helpers ------------------------------------------------------

  const borderFn = modalBorderColor();
  const secondaryFn = themeText("secondary");
  const mutedFn = themeText("muted");

  function fieldLabel(label: string, fieldIndex: number) {
    const focused = activeField === fieldIndex;
    return (
      <Text bold={focused}>
        {focused ? borderFn(`> ${label}`) : mutedFn(`  ${label}`)}
      </Text>
    );
  }

  // ---- Render --------------------------------------------------------------

  return (
    <Box flexDirection="column">
      {/* Outer border */}
      <Box
        flexDirection="column"
        borderStyle="bold"
        borderColor="gray"
        paddingX={1}
        paddingY={0}
        width={64}
      >
        {/* Inner border with title */}
        <Box
          flexDirection="column"
          borderStyle="round"
          borderColor="gray"
          paddingX={1}
          paddingY={0}
        >
          {/* Title */}
          <Box justifyContent="center" marginBottom={1}>
            <Text bold>{borderFn(" Start Session ")}</Text>
          </Box>

          {/* Computer field */}
          <Box flexDirection="column" marginBottom={1}>
            {fieldLabel("Computer", FIELD_COMPUTER)}
            <Box paddingLeft={4}>
              {computerNames.length === 0 ? (
                <Text>{mutedFn("No computers available")}</Text>
              ) : (
                <Box flexDirection="row" gap={1}>
                  {computerNames.map((name, i) => {
                    const selected = i === computerIndex;
                    const computer = computers[i];
                    const isLocal = computer?.is_local;
                    return (
                      <Text
                        key={name}
                        bold={selected}
                        inverse={selected && activeField === FIELD_COMPUTER}
                      >
                        {selected ? " \u25B8 " : "   "}
                        {name}
                        {isLocal ? " (local)" : ""}
                      </Text>
                    );
                  })}
                </Box>
              )}
            </Box>
          </Box>

          {/* Project field */}
          <Box flexDirection="column" marginBottom={1}>
            {fieldLabel("Project", FIELD_PROJECT)}
            <Box paddingLeft={4}>
              {filteredProjects.length === 0 ? (
                <Text>{mutedFn("No projects on this computer")}</Text>
              ) : (
                <Box flexDirection="column">
                  {filteredProjects.map((proj, i) => {
                    const selected = i === projectIndex;
                    return (
                      <Text
                        key={proj.path}
                        bold={selected}
                        inverse={selected && activeField === FIELD_PROJECT}
                      >
                        {selected ? " \u25B8 " : "   "}
                        {proj.name}
                        <Text>{secondaryFn(` (${proj.path})`)}</Text>
                      </Text>
                    );
                  })}
                </Box>
              )}
            </Box>
          </Box>

          {/* Agent field */}
          <Box flexDirection="column" marginBottom={1}>
            {fieldLabel("Agent", FIELD_AGENT)}
            <Box paddingLeft={4}>
              <AgentSelector
                value={agent}
                onChange={setAgent}
                availability={agentAvailability}
                isFocused={activeField === FIELD_AGENT}
              />
            </Box>
          </Box>

          {/* Mode field */}
          <Box flexDirection="column" marginBottom={1}>
            {fieldLabel("Mode", FIELD_MODE)}
            <Box paddingLeft={4}>
              <ModeSelector
                value={mode}
                onChange={setMode}
                isFocused={activeField === FIELD_MODE}
              />
            </Box>
          </Box>

          {/* Title field */}
          <Box flexDirection="column" marginBottom={1}>
            {fieldLabel("Title", FIELD_TITLE)}
            <Box paddingLeft={4}>
              <PromptInput
                value={title}
                onChange={setTitle}
                onSubmit={handleSubmit}
                placeholder="Session title (optional)"
                isFocused={activeField === FIELD_TITLE}
                maxLength={100}
              />
            </Box>
          </Box>

          {/* Prompt field */}
          <Box flexDirection="column" marginBottom={1}>
            {fieldLabel("Prompt", FIELD_PROMPT)}
            <Box paddingLeft={4}>
              <PromptInput
                value={prompt}
                onChange={setPrompt}
                onSubmit={handleSubmit}
                placeholder="Initial message (optional)"
                isFocused={activeField === FIELD_PROMPT}
                maxLength={500}
              />
            </Box>
          </Box>

          {/* Footer actions */}
          <Box flexDirection="row" gap={2} marginTop={1} justifyContent="center">
            <Text bold>{borderFn("[Enter] Start")}</Text>
            <Text>{mutedFn("[Tab] Next field")}</Text>
            <Text>{mutedFn("[Esc] Cancel")}</Text>
          </Box>
        </Box>
      </Box>
    </Box>
  );
}
