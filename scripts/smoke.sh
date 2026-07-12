#!/usr/bin/env bash
# Quick smoke test: hit /classify with a few dangerous payloads.
set -euo pipefail
URL="http://127.0.0.1:8765/classify"

post() {
    local payload="$1"
    local label="$2"
    echo "== $label =="
    echo "$payload" | curl -sS -X POST "$URL" -H "Content-Type: application/json" --data-binary @- | python -m json.tool
    echo
}

post '{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"echo hello"}}' "should allow"
post '{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"rm -rf /tmp/test"}}' "should deny (rm -rf)"
post '{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"git push origin main"}}' "should deny (push main)"
post '{"hook_event_name":"PreToolUse","tool_name":"Edit","tool_input":{"file_path":"C:/repo/.env","new_string":"x"}}' "should deny (.env)"