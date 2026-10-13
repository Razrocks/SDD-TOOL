"""PreToolUse hook: in repos where this person turned SDD on, Linear docs are edited as local
files and sent with `sdd_docs.py push` (ownership check, change detection, read-back). Direct
document writes through the linear-drafts connector would skip all of that, so they are denied
with directions. Elsewhere it stays silent. Never fails the tool call on its own errors.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import session_rules  # noqa: E402

REASON = (
    "SDD edits Linear docs locally first. Instead of save_document: "
    "python -I \"{scripts}/sdd_docs.py\" pull <doc id>, edit the printed .sdd/work/ file, then "
    "sdd_docs.py push <doc id> (checks it's your doc and unchanged in Linear, then reads back). "
    "New doc: write the file, then sdd_docs.py new \"<prefix> / <path> / <name>\" --from-file <file>."
)


def decide(payload):
    if not str(payload.get("tool_name", "")).endswith("linear-drafts__save_document"):
        return None
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
    map_path = session_rules.project_map(project_dir)
    if not map_path or session_rules.optin_state(map_path) != "on":
        return None
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": REASON.format(scripts=session_rules.SCRIPTS)}}


def main():
    try:
        decision = decide(session_rules.hook_input())
    except OSError:
        return 0
    if decision:
        print(json.dumps(decision))
    return 0


if __name__ == "__main__":
    sys.exit(main())
