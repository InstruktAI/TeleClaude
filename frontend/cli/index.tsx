#!/usr/bin/env node
/**
 * Entry point for the TeleClaude Ink terminal application.
 *
 * Renders the root App component in fullscreen mode (alternate screen buffer).
 * Uses React 18 -- Ink 6.x is incompatible with React 19.
 */

import React from "react";
import { render } from "ink";

import { App } from "./app.js";

const { waitUntilExit } = render(<App />, {
  patchConsole: false,
});

waitUntilExit().then(() => {
  process.exit(0);
});
