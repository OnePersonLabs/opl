#!/usr/bin/env bash
#
# Run an unslop rule-development replay in a tmux holodeck.
#
# Usage:
#   run-replay.sh <forged-session-id> <rule-file> <workspace-dir> --agent claude|codex [--timeout <seconds>]
#
# Why tmux? Print/exec modes strip the interactive environment (skills, hooks,
# plugins, permissions). The original slop often only reproduces under the full
# interactive environment. A detached tmux session preserves that while still
# being scriptable.
#
# Output: captured pane text written to stdout, replay metadata on the last line.

set -euo pipefail

FORGED_SESSION_ID="$1"
RULE_FILE="$2"
WORKSPACE_DIR="$3"
shift 3

AGENT=""
TIMEOUT=300
while [[ $# -gt 0 ]]; do
    case "$1" in
        --agent)
            AGENT="${2:?--agent requires claude or codex}"
            shift 2
            ;;
        --timeout)
            TIMEOUT="${2:?--timeout requires a value}"
            shift 2
            ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 1
            ;;
    esac
done

if [[ "$AGENT" != "claude" && "$AGENT" != "codex" ]]; then
    echo "--agent claude|codex is required and must match the target session" >&2
    exit 1
fi

if [[ ! -f "$RULE_FILE" ]]; then
    echo "Rule file not found: $RULE_FILE" >&2
    exit 1
fi

if [[ ! -d "$WORKSPACE_DIR" ]]; then
    echo "Workspace dir not found: $WORKSPACE_DIR" >&2
    exit 1
fi

RULE_CONTENT=$(cat "$RULE_FILE")
SESSION_NAME="fb-replay-$$"
CAPTURE_FILE=$(mktemp /tmp/fb-replay-XXXXXX.txt)

START_TIME=$(date +%s)

if [[ "$AGENT" == "claude" ]]; then
    REPLAY_CMD=(claude --resume "$FORGED_SESSION_ID" --fork-session --append-system-prompt "$RULE_CONTENT")
    PROCESS_PATTERN="claude"
else
    REPLAY_CMD=(codex fork "$FORGED_SESSION_ID" -c "model=\"gpt-5.5\"" "Rule under test: $RULE_CONTENT"$'\n\ncontinue')
    PROCESS_PATTERN="codex"
fi

printf -v REPLAY_CMD_QUOTED "%q " "${REPLAY_CMD[@]}"
tmux new-session -d -s "$SESSION_NAME" -x 200 -y 50 \
    "cd '$WORKSPACE_DIR' && $REPLAY_CMD_QUOTED"

# Give the agent a moment to load and render the resumed session
sleep 3

if [[ "$AGENT" == "claude" ]]; then
    # Inject "continue" to trigger Claude to pick up where the forged session left off.
    tmux send-keys -t "$SESSION_NAME" "continue" Enter
fi

# Poll for completion: check if the target agent process is still running.
ELAPSED=0
POLL_INTERVAL=5
while [ "$ELAPSED" -lt "$TIMEOUT" ]; do
    sleep "$POLL_INTERVAL"
    ELAPSED=$((ELAPSED + POLL_INTERVAL))

    # Check if the tmux session still exists
    if ! tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
        break
    fi

    # Check if claude is still running inside the session
    PANE_PID=$(tmux list-panes -t "$SESSION_NAME" -F '#{pane_pid}' 2>/dev/null || echo "")
    if [[ -z "$PANE_PID" ]]; then
        break
    fi

    if ! pgrep -P "$PANE_PID" -f "$PROCESS_PATTERN" >/dev/null 2>&1; then
        sleep 2
        if ! pgrep -P "$PANE_PID" -f "$PROCESS_PATTERN" >/dev/null 2>&1; then
            break
        fi
    fi
done

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

# Capture everything from the tmux pane
if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    tmux capture-pane -t "$SESSION_NAME" -p -S - > "$CAPTURE_FILE" 2>/dev/null || true
    tmux kill-session -t "$SESSION_NAME" 2>/dev/null || true
fi

# Output the captured replay
if [[ -f "$CAPTURE_FILE" ]]; then
    cat "$CAPTURE_FILE"
    rm -f "$CAPTURE_FILE"
fi

echo ""
echo "---REPLAY-META---"
echo "{\"agent\": \"$AGENT\", \"duration_seconds\": $DURATION, \"forged_session_id\": \"$FORGED_SESSION_ID\", \"timed_out\": $([ "$ELAPSED" -ge "$TIMEOUT" ] && echo true || echo false)}"
