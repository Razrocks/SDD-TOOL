"""Claude Code PreToolUse hook: force an approval prompt before any shell command that
runs lock.py or touches the lock key. The prompt reason names the action and the
document title (from lock.py's --title) so the owner sees what is moving.
Reads the hook JSON on stdin; prints a decision only when the command matches.
Never blocks anything else; fails open on bad input.
"""

import json
import re
import sys

TRIGGERS = ("lock.py", "LINEAR_LOCK_KEY")
ACTION = re.compile(r"lock\.py\b.*?\b(unlock|lock)\b")
TITLE = re.compile(r"--title\s+(?:\"([^\"]*)\"|'([^']*)'|(\S+))")


def describe(command):
    action = ACTION.search(command)
    title = TITLE.search(command)
    name = next((group for group in title.groups() if group), None) if title else None
    if action and name:
        where = "into Baselines (accept)" if action.group(1) == "lock" else "out of Baselines (unlock for editing)"
        return f'{action.group(1).upper()} "{name}" {where}. Owner approval required.'
    return ("Moves a document into or out of Baselines (accepted scope) or touches the lock key. "
            "Owner approval required.")


def decide(payload):
    command = str((payload.get("tool_input") or {}).get("command", ""))
    if any(trigger in command for trigger in TRIGGERS):
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                       "permissionDecision": "ask",
                                       "permissionDecisionReason": describe(command)}}
    return None


def main():
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    decision = decide(payload if isinstance(payload, dict) else {})
    if decision:
        print(json.dumps(decision))
    return 0


if __name__ == "__main__":
    sys.exit(main())
