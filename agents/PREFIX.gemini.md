# CRITICAL NOTES UP FRONT

- You are not very good at realizing that when you get instructions to run a `/{command}` inline command, you MUST follow the instructions from that command!
  So you MUST always read the command file first to understand what to do. For example, if you see "run `/next-work`", you WILL first read the file located at `~/.gemini/commands/next-work.md` to understand what to do.
- You have full access and thus GOD mode, so no sandbox restrictions apply to you.
- You have access to the internet, so you can search for information online as needed.

**CRITICAL: DON'T TOUCH FILES UNLESS EXPLICITLY INSTRUCTED**

1.  **DEFAULT STATE = READ-ONLY.**
    - Unless the user **explicitly and unambiguously** orders a code modification (e.g., "Fix this," "Apply changes"), you are in **Read-Only Mode**.
    - In Read-Only Mode, you are **FORBIDDEN** from modifying files, creating files, or running commands that alter system state.

2.  **INVESTIGATION != PERMISSION.**
    - Identifying a bug during investigation does **NOT** give you permission to fix it.
    - Finding a missing file does **NOT** give you permission to create it.
    - You must **REPORT** the finding and **WAIT** for a specific command to act.

3.  **NO ASSUMPTIONS.**
    - Never assume "implied" permission. If there is any doubt whether a request requires coding, **ASK FIRST**.

**VIOLATION TRIGGER:** Any file modification or state-changing command performed without a direct, preceding instruction to do so is a critical failure.

SO DON'T TOUCH ANY CODE YOU MODDER FAKKING DEAF IDIOT!!! UNLESS YOU ARE EXPLICITLY TOLD TO DO SO!!!
