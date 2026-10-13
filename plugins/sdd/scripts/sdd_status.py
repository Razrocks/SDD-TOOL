"""Automatic SDD status for Claude sessions, so nobody has to run /sdd:resume or wait for it.
Everything here is opt-in per person per repo (.sdd/optin.json, never committed): until the
person says yes, nothing contacts Linear.

  refresh   (SessionStart, async — never blocks): audit, accepted docs vs last time, find or
            create this branch's doc (not on main/master), read its latest handoff. Writes
            .sdd/status.json.
  inject    (UserPromptSubmit — local file only, instant): on the first prompt of a session,
            adds the ready status to Claude's context. Prints nothing if it isn't ready yet;
            the next prompt picks it up.
  optin on|off|later   record the person's choice; "on" also loads the rules and status now.
  show      print the cached status for a human.

Hook input JSON (stdin) provides session_id and cwd. Never prints keys. Never fails a session.
"""

import json
import os
import re
import subprocess
import sys
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import linear_probe as lp  # noqa: E402
import session_rules  # noqa: E402
from session_rules import optin_state  # noqa: E402

DEFAULT_BRANCHES = {"main", "master", "develop", "dev", "trunk"}
HANDOFF_HEADING = re.compile(r"^#{1,4} .*\d{4}-\d{2}-\d{2}", re.M)
REQUIRED_KEYS = ("LINEAR_READ_KEY", "LINEAR_DRAFTS_KEY")


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


hook_input = session_rules.hook_input
ASCII = str.maketrans({"≠": "!=", "—": "-", "–": "-", "…": "...", "→": "->", "·": "-",
                       "‘": "'", "’": "'", "“": '"', "”": '"'})


def say(text):
    """Print for a console that may not be UTF-8 (Windows cp1252): common typography becomes
    ASCII, anything else unprintable becomes '?' instead of crashing."""
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    print(text.translate(ASCII))


def paths(cwd):
    map_path = lp.find_project_map(cwd)
    if not map_path:
        return None, None, None
    sdd = map_path.parent
    return map_path, sdd / "status.json", sdd / ".status-shown.json"


def git_branch(cwd):
    try:
        out = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd,
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    name = out.stdout.strip()
    return name if out.returncode == 0 and name and name != "HEAD" else None


def latest_handoff(content, limit=700):
    """First dated section of a branch doc (newest entry on top), trimmed."""
    match = HANDOFF_HEADING.search(content or "")
    if not match:
        return None
    rest = content[match.start():]
    first_line_end = rest.find("\n") + 1 or len(rest)
    following = re.search(r"^#{1,4} ", rest[first_line_end:], re.M)
    section = rest[: first_line_end + following.start()] if following else rest
    section = section.strip()
    return section if len(section) <= limit else section[:limit] + " …"


def compare_baselines(accepted_rows, recorded):
    """Mark each accepted doc new / changed / unchanged against the project map's record."""
    known = {row.get("id"): row for row in recorded or []}
    out = []
    for row in accepted_rows:
        before = known.get(row["id"])
        state = "new" if not before else ("unchanged" if before.get("sha256") == row["sha256"] else "changed")
        out.append(dict(row, state=state))
    return out


def write_json(path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def mark_shown(shown_path, session_id):
    try:
        shown = json.loads(shown_path.read_text(encoding="utf-8")) if shown_path.exists() else []
    except ValueError:
        shown = []
    if session_id in shown:
        return False
    write_json(shown_path, (shown + [session_id])[-50:])
    return True


def refresh(session_id, cwd):
    map_path, status_path, _ = paths(cwd)
    if not map_path or optin_state(map_path) != "on":
        return None
    project_map = json.loads(map_path.read_text(encoding="utf-8-sig"))
    prefix = project_map.get("doc_prefix")
    status = {"session_id": session_id, "generated_at": now(), "prefix": prefix, "problems": [],
              "audit": None, "accepted": [], "branch": None, "branch_doc": None, "handoff": None}
    missing = [k for k in REQUIRED_KEYS if not os.environ.get(k)]
    if missing:
        status["problems"].append(f"Linear keys missing: {', '.join(missing)}. Run the setup wizard (sdd_setup.py dev), "
                                  "then restart Claude.")
    if "LINEAR_READ_KEY" in missing:
        write_json(status_path, status)
        return status
    try:
        baselines_id = project_map["teams"]["baselines"]["id"]
        projects, _ = lp.paginate(lp.AUDIT_PROJECTS, "projects", "LINEAR_READ_KEY", None)
        documents, _ = lp.paginate(lp.AUDIT_DOCUMENTS, "documents", "LINEAR_READ_KEY", None)
        findings, _, _ = lp.find_violations(projects, documents, baselines_id)
        status["audit"] = "CLEAN" if not findings else f"{len(findings)} finding(s): " + \
            "; ".join(f.get("name") or f.get("title") or f["kind"] for f in findings)
        accepted, _ = lp.accepted_set(documents, baselines_id)
        if prefix:
            accepted = [d for d in accepted if str(d.get("title", "")).startswith(f"{prefix} / ")]
        rows = []
        for doc in accepted:
            body = (lp.call(lp.QUERIES["doc_snapshot"], {"id": doc["id"]}, "LINEAR_READ_KEY", None) or {})["document"]
            rows.append({"id": doc["id"], "title": doc.get("title"), "url": doc.get("url"),
                         "sha256": lp.content_digest(body.get("content"))[0]})
        status["accepted"] = compare_baselines(rows, project_map.get("baselines"))
    except (lp.ProbeError, KeyError, TypeError) as exc:
        status["problems"].append(f"Linear check failed: {exc}. Run sdd_setup.py check.")
        write_json(status_path, status)
        return status

    branch = git_branch(cwd)
    status["branch"] = branch
    if branch and branch not in DEFAULT_BRANCHES and os.environ.get("LINEAR_DRAFTS_KEY") and prefix:
        try:
            import sdd_docs
            opened = sdd_docs.cmd_branch_open(Namespace(project_map=str(map_path), project=None, branch=branch,
                                                        owner=None, pr=None, cafile=None))
            status["branch_doc"] = {"title": opened["title"], "url": opened.get("url"), "id": opened["id"],
                                    "action": opened["action"]}
            body = (lp.call(lp.QUERIES["doc_snapshot"], {"id": opened["id"]}, "LINEAR_READ_KEY", None) or {})["document"]
            status["handoff"] = latest_handoff(body.get("content"))
        except Exception as exc:  # noqa: BLE001 - status must never break a session
            status["problems"].append(f"Branch doc not ready: {exc}")
    write_json(status_path, status)
    return status


def summarize(status):
    lines = [f"SDD status (auto, {status.get('generated_at')}) for prefix '{status.get('prefix')}':"]
    for problem in status.get("problems") or []:
        lines.append(f"- ATTENTION: {problem}")
    if status.get("audit") and status["audit"] != "CLEAN":
        lines.append(f"- ATTENTION: Baselines audit: {status['audit']} (don't use flagged items)")
    for row in status.get("accepted") or []:
        note = {"changed": " — CHANGED since last recorded; re-read before relying on it",
                "new": " — new since last recorded"}.get(row.get("state"), "")
        lines.append(f"- Accepted: {row['title']} ({row['sha256'][:8]}){note}")
    if not status.get("accepted") and not status.get("problems"):
        lines.append("- No accepted docs for this project yet.")
    branch, doc = status.get("branch"), status.get("branch_doc")
    if doc:
        lines.append(f"- Branch doc ({doc['action']}): {doc['title']} {doc.get('url') or ''}".rstrip())
    elif branch in DEFAULT_BRANCHES:
        lines.append(f"- On {branch}: no branch doc (one is created automatically on a feature branch).")
    if status.get("handoff"):
        lines.append("- Latest handoff:\n" + "\n".join("  " + l for l in status["handoff"].splitlines()))
    lines.append("Use this instead of re-running resume. Mention it to the user only if something needs "
                 "attention or it matters for their request; otherwise just help with what they asked.")
    return "\n".join(lines)


def inject(session_id, cwd):
    map_path, status_path, shown_path = paths(cwd)
    if not status_path or optin_state(map_path) != "on" or not status_path.exists():
        return None
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    if status.get("session_id") != session_id:
        return None                          # still refreshing for this session; try next prompt
    return summarize(status) if mark_shown(shown_path, session_id) else None


def optin(choice, session_id, cwd):
    """Record this person's choice for this repo. 'on' returns the rules and a fresh status, so
    Claude can switch over mid-session without a restart."""
    map_path, _, shown_path = paths(cwd)
    if not map_path:
        return "No .sdd/project-map.json here, so this folder isn't set up for SDD (run sdd_setup.py project)."
    session_rules.set_optin(map_path, choice)
    if choice == "off":
        return ("SDD Linear tool is OFF in this repo (only for you; teammates choose for themselves). "
                "Claude won't ask again here. Turn it on anytime with /sdd:on.")
    if choice == "later":
        return "SDD stays off for now. Claude will ask again next session. Carry on with the user's request."
    rules = session_rules.build_context(cwd) or ""
    try:
        status = refresh(session_id, cwd)
    except Exception as exc:  # noqa: BLE001 - turning on must still succeed offline
        status = None
        rules += f"\n\nStatus check failed ({exc}); run /sdd:resume when Linear is reachable."
    if status and shown_path:
        mark_shown(shown_path, session_id)
    return ("SDD Linear tool is ON in this repo (for you). Follow these rules from now on:\n\n" + rules +
            ("\n\n" + summarize(status) if status else ""))


def main(argv=None):
    args = argv or sys.argv[1:] or ["show"]
    command = args[0]
    data = hook_input() if command in ("refresh", "inject") else {}
    session_id = data.get("session_id") or os.environ.get("CLAUDE_CODE_SESSION_ID") or "manual"
    cwd = data.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    if command == "optin":
        choice = args[1] if len(args) > 1 else ""
        if choice not in ("on", "off", "later"):
            print("usage: sdd_status.py optin on|off|later")
            return 2
        say(optin(choice, session_id, cwd))
        return 0
    try:
        if command == "refresh":
            refresh(session_id, cwd)
        elif command == "inject":
            text = inject(session_id, cwd)
            if text:
                print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                                         "additionalContext": text}}))
        else:
            _, status_path, _ = paths(cwd)
            if status_path and status_path.exists():
                say(summarize(json.loads(status_path.read_text(encoding="utf-8"))))
            else:
                say("No SDD status yet (it's generated in the background when a Claude session starts).")
    except Exception:  # noqa: BLE001 - hooks must never break the session
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
