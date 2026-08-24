#!/usr/bin/env python3
import json, re, sys

def is_blocked_env_path(value: str) -> bool:
    name = value.rsplit("/", 1)[-1]
    return name.startswith(".env") and name != ".env.example" and not name.startswith(".env.example.")

def main():
    payload = json.load(sys.stdin)
    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input") or {}
    reason = None

    if tool_name == "Read":
        path = tool_input.get("file_path", "")
        if is_blocked_env_path(path):
            reason = f"Blocked: {path} is a .env file — its contents may not be read."

    elif tool_name == "Bash":
        command = tool_input.get("command", "")
        for token in re.findall(r"[^\s\"']+", command):
            token = token.strip("'\"")
            if is_blocked_env_path(token):
                reason = f"Blocked: command references a .env file ({token!r})."
                break

    elif tool_name in ("Grep", "Glob"):
        for key in ("path", "pattern", "glob"):
            val = tool_input.get(key, "")
            if isinstance(val, str) and is_blocked_env_path(val):
                reason = f"Blocked: {tool_name} targets a .env file ({val!r})."
                break

    if reason:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }))
    sys.exit(0)

if __name__ == "__main__":
    main()
