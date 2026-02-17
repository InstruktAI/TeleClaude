/**
 * Registry of all animation algorithms.
 *
 * Maps camelCase names to their pure algorithm functions, grouped by category:
 * - GENERAL_ALGORITHMS: full-palette banner animations
 * - AGENT_ALGORITHMS: 3-color agent-palette animations
 * - CONFIG_ALGORITHMS: variable-width config-section animations
 */

import type { AnimationAlgorithm } from '../types.js'

// General-purpose algorithms
import { spectrumCycle } from './spectrum-cycle.js'
import { letterWaveLR } from './letter-wave-lr.js'
import { letterWaveRL } from './letter-wave-rl.js'
import { lineSweepTB } from './line-sweep-tb.js'
import { lineSweepBT } from './line-sweep-bt.js'
import { middleOut } from './middle-out.js'
import { withinLetterLR } from './within-letter-lr.js'
import { withinLetterRL } from './within-letter-rl.js'
import { sparkle } from './sparkle.js'
import { checkerboard } from './checkerboard.js'
import { wordSplit } from './word-split.js'
import { diagonalDR } from './diagonal-dr.js'
import { diagonalDL } from './diagonal-dl.js'
import { letterShimmer } from './letter-shimmer.js'
import { wavePulse } from './wave-pulse.js'

// Agent-specific algorithms (3-color agent palette)
import { agentPulse } from './agent-pulse.js'
import { agentWaveLR } from './agent-wave-lr.js'
import { agentWaveRL } from './agent-wave-rl.js'
import { agentLineSweep } from './agent-line-sweep.js'
import { agentMiddleOut } from './agent-middle-out.js'
import { agentSparkle } from './agent-sparkle.js'
import { agentWithinLetter } from './agent-within-letter.js'
import { agentHeartbeat } from './agent-heartbeat.js'
import { agentWordSplit } from './agent-word-split.js'
import { agentLetterCascade } from './agent-letter-cascade.js'
import { agentFadeCycle } from './agent-fade-cycle.js'
import { agentSpotlight } from './agent-spotlight.js'
import { agentBreathing } from './agent-breathing.js'
import { agentDiagonal } from './agent-diagonal.js'

// Config-section algorithms (variable-width targets)
import { configPulse } from './config-pulse.js'
import { configTyping } from './config-typing.js'
import { configSuccess } from './config-success.js'
import { configError } from './config-error.js'

export {
  // General
  spectrumCycle,
  letterWaveLR,
  letterWaveRL,
  lineSweepTB,
  lineSweepBT,
  middleOut,
  withinLetterLR,
  withinLetterRL,
  sparkle,
  checkerboard,
  wordSplit,
  diagonalDR,
  diagonalDL,
  letterShimmer,
  wavePulse,
  // Agent
  agentPulse,
  agentWaveLR,
  agentWaveRL,
  agentLineSweep,
  agentMiddleOut,
  agentSparkle,
  agentWithinLetter,
  agentHeartbeat,
  agentWordSplit,
  agentLetterCascade,
  agentFadeCycle,
  agentSpotlight,
  agentBreathing,
  agentDiagonal,
  // Config
  configPulse,
  configTyping,
  configSuccess,
  configError,
}

export const GENERAL_ALGORITHMS: Record<string, AnimationAlgorithm> = {
  spectrumCycle,
  letterWaveLR,
  letterWaveRL,
  lineSweepTB,
  lineSweepBT,
  middleOut,
  withinLetterLR,
  withinLetterRL,
  sparkle,
  checkerboard,
  wordSplit,
  diagonalDR,
  diagonalDL,
  letterShimmer,
  wavePulse,
}

export const AGENT_ALGORITHMS: Record<string, AnimationAlgorithm> = {
  agentPulse,
  agentWaveLR,
  agentWaveRL,
  agentLineSweep,
  agentMiddleOut,
  agentSparkle,
  agentWithinLetter,
  agentHeartbeat,
  agentWordSplit,
  agentLetterCascade,
  agentFadeCycle,
  agentSpotlight,
  agentBreathing,
  agentDiagonal,
}

export const CONFIG_ALGORITHMS: Record<string, AnimationAlgorithm> = {
  configPulse,
  configTyping,
  configSuccess,
  configError,
}
