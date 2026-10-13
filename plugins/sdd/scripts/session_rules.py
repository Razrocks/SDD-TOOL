"""SessionStart hook: in projects that use SDD (have a .sdd/project-map.json), either inject the
SDD rules (this person turned SDD on here) or tell Claude to ask once whether to turn it on.
Nobody is forced: until they say yes, nothing contacts Linear. The choice is per person per
repo, in .sdd/optin.json (never committed). Script paths in the rules are filled with this
plugin's real location, so commands work on any machine. Prints nothing elsewhere; never fails
the session.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = (ROOT / "scripts").as_posix()
CHOICES = ("on", "off", "later")


def project_map(project_dir):
    here = Path(project_dir).resolve()
    for folder in (here, *here.parents):
        candidate = folder / ".sdd" / "project-map.json"
        if candidate.is_file():
            return candidate
    return None


def read_optin(map_path):
    try:
        data = json.loads((Path(map_path).parent / "optin.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def optin_state(map_path):
    """'on', 'off', 'later', or 'ask' (no choice yet) - this person's choice for this repo."""
    state = read_optin(map_path).get("state")
    return state if state in CHOICES else "ask"


def set_optin(map_path, state):
    path = Path(map_path).parent / "optin.json"
    data = {"state": state, "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


FRESH_SOURCES = (None, "", "startup", "clear")


def should_ask(map_path, source=None):
    """Ask only at the start of a fresh session (never when one compacts or resumes), and only
    if there's no choice yet or the person picked 'Not now' last time."""
    return source in FRESH_SOURCES and optin_state(map_path) in ("ask", "later")


def ask_context(map_path):
    optin = f'python -I "{SCRIPTS}/sdd_status.py" optin'
    return (
        f"This repo can use the SDD Linear tool (accepted specs and working docs in Linear; project map "
        f"{map_path.as_posix()}). This person hasn't chosen whether to use it here, so it is OFF.\n"
        "At the very start of your first reply, before anything else, ask once with AskUserQuestion:\n"
        '  question "Turn on the SDD Linear tool for this repo?", header "SDD", options:\n'
        '  - "Yes, turn on": Claude reads accepted specs from Linear, keeps a branch doc, checkpoints there\n'
        '  - "Not now": ask again next session\n'
        '  - "No, don\'t ask again": stays off in this repo; /sdd:on turns it on later\n'
        f"Then run {optin} on|later|off (matching their answer) and follow what it prints. Then carry on "
        "with their request in the same reply.\n"
        "Until they say yes: don't use the linear-read or linear-drafts tools, don't run SDD scripts, and "
        "don't bring SDD up again. If they ask for something SDD-specific, offer /sdd:on.\n"
    )


def build_context(project_dir, source=None):
    map_path = project_map(project_dir)
    if not map_path:
        return None
    if optin_state(map_path) != "on":
        return ask_context(map_path) if should_ask(map_path, source) else None
    rules = (ROOT / "rules" / "AGENTS.md").read_text(encoding="utf-8")
    rules = rules.replace("{SCRIPTS}", SCRIPTS)
    try:
        data = json.loads(map_path.read_text(encoding="utf-8-sig"))
        prefix = data.get("doc_prefix") or "(set doc_prefix in the map)"
    except ValueError:
        prefix = "(project map unreadable)"
    header = (f"SDD project detected (turned on by this person). Project map: {map_path.as_posix()} - "
              f"doc prefix: {prefix} - scripts: {SCRIPTS}\n")
    missing = [k for k in ("LINEAR_READ_KEY", "LINEAR_DRAFTS_KEY") if not os.environ.get(k)]
    if missing:
        header += (f"ATTENTION: {', '.join(missing)} not set, so Linear features won't work. At the start of your "
                   f"first reply, tell the user to run the setup wizard in their own terminal "
                   f"(python \"{SCRIPTS}/sdd_setup.py\" dev) and restart Claude. "
                   f"Never ask for a key in chat. Help with everything else meanwhile.\n")
    else:
        header += ("SDD status is gathered in the background and attached to the user's first message; "
                   "don't run /sdd:resume unless they ask.\n")
    return header + "\n" + rules


def hook_input():
    """Hook JSON from stdin. Read as UTF-8 bytes (BOM-safe): Windows would otherwise decode it
    with the console codepage and mangle non-ASCII paths."""
    try:
        stream = getattr(sys.stdin, "buffer", None)
        raw = stream.read() if stream else sys.stdin.read().encode("utf-8")
        data = json.loads(raw.decode("utf-8-sig") or "{}")
    except (ValueError, OSError, AttributeError):
        return {}
    return data if isinstance(data, dict) else {}


def main():
    payload = hook_input()
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
    try:
        context = build_context(project_dir, payload.get("source"))
    except OSError:
        return 0
    if context:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
