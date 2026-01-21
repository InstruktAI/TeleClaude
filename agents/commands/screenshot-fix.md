---
description: Fix UI issues based on a screenshot provided by the user or the latest screenshot
argument-hint: "[screenshot-path]"
---

This command helps fix UI issues by analyzing a screenshot provided by the user or the latest screenshot.

## Instructions

1. **Handle Screenshot Input**:

- If a screenshot path is provided in arguments, use that file
- If no path is provided, execute `ls -t ~/Library/CloudStorage/Dropbox/Screenshots | head -n 1` to use the most recent one.

1. **Read Screenshot**: Use the Read tool to view the specified or latest screenshot file
2. **Analyze Issues**: Identify UI problems, layout issues, styling problems, or functional bugs visible in the screenshot
3. **Fix Issues**:
   - Make the necessary code changes to fix identified issues
   - Modify relevant component files directly
   - Apply CSS/styling fixes
   - Implement responsive design improvements
   - Test changes and ensure they work properly

## Response Format

- Briefly describe what you see in the screenshot
- List specific issues identified
- Implement the fixes directly in the codebase
- Keep responses concise and focused on the actual work done

Screenshot path (optional): $ARGUMENTS
