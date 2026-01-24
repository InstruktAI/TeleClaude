---
description: Analyze a screenshot provided by the user or the latest screenshot
argument-hint: "[screenshot-path]"
---

This command analyzes a screenshot provided by the user or the latest screenshot.

## Instructions

1. **Handle Screenshot Input**: If a screenshot path is provided in arguments, use that file. If no path is provided, execute `ls -t ~/Library/CloudStorage/Dropbox/Screenshots | head -n 1` to use the most recent one, or follow instructions in extra context.
2. **Read Screenshot**: Use the Read tool to view the specified or latest screenshot file.
3. **Analyze Issues**: Identify problems/details as laid out in the screenshot.
4. **Explain Your Findings**: Describe the issues found and provide insights/suggestions based on the analysis.

## Response Format

- Briefly describe what you see in the screenshot
- List specific issues identified
- Present your analysis clearly and concisely
- Suggestions

Extra screenshot context or path (optional): $ARGUMENTS
