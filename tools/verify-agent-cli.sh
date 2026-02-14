#!/bin/bash
set -e

# verify-agent-cli.sh
# Robust end-to-end verification of the teleclaude.helpers.agent_cli wrapper.
# Ensures that Claude, Codex, and Gemini can be invoked via the wrapper,
# receive a prompt+schema, and return valid JSON without pollution.

PYTHON_CMD="./.venv/bin/python"
WRAPPER_MOD="teleclaude.helpers.agent_cli"
SCHEMA_FILE="docs/project/spec/release-report-schema.md"

# Generate a real diff to feed them
echo "🔍 Generating context..."
git diff HEAD~5..HEAD > /tmp/context-diff.txt
DIFF_CONTENT=$(cat /tmp/context-diff.txt)

# Construct the prompt (Simulating the release inspector)
PROMPT_FILE="/tmp/verify-prompt.txt"
cat <<EOF > "$PROMPT_FILE"
You are a Release Inspector. Analyze this diff against Semver 0.x.
Diff:
$DIFF_CONTENT

Return valid JSON matching the schema.
EOF

run_agent() {
    AGENT=$1
    echo "---------------------------------------------------"
    echo "🤖 Testing Agent: $AGENT"
    echo "---------------------------------------------------"
    
    # Run the wrapper and capture output
    # We use a temp file for output to separate stdout/stderr cleanly
    OUT_FILE="/tmp/verify-$AGENT.json"
    LOG_FILE="/tmp/verify-$AGENT.log"
    
    # Construct args array to avoid shell splitting issues
    ARGS=(
        "-m" "$WRAPPER_MOD"
        "--agent" "$AGENT"
        "--thinking-mode" "fast"
        "--prompt-file" "$PROMPT_FILE"
        "--schema-file" "$SCHEMA_FILE"
    )

    echo "DEBUG: Arg count: ${#ARGS[@]}"
    for i in "${!ARGS[@]}"; do 
        echo "Arg $i: ${ARGS[$i]}"
    done
    
    set +e
    "$PYTHON_CMD" -u "${ARGS[@]}" > "$OUT_FILE" 2> "$LOG_FILE"
    EXIT_CODE=$?
    set -e

    if [ $EXIT_CODE -ne 0 ]; then
        echo "❌ FAILED (Exit Code: $EXIT_CODE)"
        echo "STDOUT (Error JSON):"
        cat "$OUT_FILE"
        echo "STDERR:"
        cat "$LOG_FILE"
        return 1
    fi

    # Verify JSON validity
    # Check file size first
    if [ ! -s "$OUT_FILE" ]; then
        echo "❌ FAILED: Output file is empty"
        echo "STDERR:"
        cat "$LOG_FILE"
        return 1
    fi

    if jq empty "$OUT_FILE" 2>/dev/null; then
        echo "✅ Valid JSON received."
        # cat "$OUT_FILE" | jq . # Optional: print it
    else
        echo "❌ INVALID JSON:"
        cat "$OUT_FILE"
        echo "--- STDERR ---"
        cat "$LOG_FILE"
        return 1
    fi
}

# Run them all
run_agent "claude" || exit 1
run_agent "codex" || exit 1
run_agent "gemini" || exit 1

echo "---------------------------------------------------"
echo "🎉 ALL AGENTS VERIFIED SUCCESSFUL"
echo "---------------------------------------------------"
