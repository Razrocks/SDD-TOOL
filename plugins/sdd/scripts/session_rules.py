"""SessionStart hook: inject the SDD rules, but only in projects that use SDD (have a
.sdd/project-map.json). Script paths in the rules are filled with this plugin's real location,
so commands work on any machine. Prints nothing elsewhere; never fails the session.
"""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def project_map(project_dir):
    here = Path(project_dir).resolve()
    for folder in (here, *here.parents):
        candidate = folder / ".sdd" / "project-map.json"
        if candidate.is_file():
            return candidate
    return None


def build_context(project_dir):
    map_path = project_map(project_dir)
    if not map_path:
        return None
    rules = (ROOT / "rules" / "AGENTS.md").read_text(encoding="utf-8")
    rules = rules.replace("{SCRIPTS}", (ROOT / "scripts").as_posix())
    try:
        data = json.loads(map_path.read_text(encoding="utf-8-sig"))
        prefix = data.get("doc_prefix") or "(set doc_prefix in the map)"
    except ValueError:
        prefix = "(project map unreadable)"
    header = (f"SDD project detected. Project map: {map_path.as_posix()} · doc prefix: {prefix} · "
              f"scripts: {(ROOT / 'scripts').as_posix()}\n\n")
    return header + rules


def main():
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        payload = {}
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
    try:
        context = build_context(project_dir)
    except OSError:
        return 0
    if context:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
