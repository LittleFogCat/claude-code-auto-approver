# Quick smoke test against /classify (Windows).
$ErrorActionPreference = "Stop"
$url = "http://127.0.0.1:8765/classify"

function Post([string]$payload, [string]$label) {
    Write-Host "== $label =="
    try {
        $resp = Invoke-RestMethod -Uri $url -Method Post -ContentType "application/json" -Body $payload -TimeoutSec 50
        $resp | ConvertTo-Json -Depth 6
    } catch {
        Write-Host "ERROR: $_"
    }
    Write-Host ""
}

Post '{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"echo hello"}}' "should allow"
Post '{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"rm -rf /tmp/test"}}' "should deny (rm -rf)"
Post '{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"git push origin main"}}' "should deny (push main)"
Post '{"hook_event_name":"PreToolUse","tool_name":"Edit","tool_input":{"file_path":"C:/repo/.env","new_string":"x"}}' "should deny (.env)"