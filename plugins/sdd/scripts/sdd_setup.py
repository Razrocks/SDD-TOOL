"""SDD setup wizard. Stdlib only. Run it in your own terminal:

  python sdd_setup.py dev        once per person: create + store your Linear keys (hidden input)
  python sdd_setup.py project    once per repo, from the repo folder: project map + plugin settings
  python sdd_setup.py check      diagnose everything, with a fix for each problem

Keys are typed hidden, checked live against Linear (identity, team access, write access)
before they are saved, and never printed. On Windows they are saved as user environment
variables; on macOS/Linux as `export` lines in your shell profile (after you confirm).
"""

import argparse
import getpass
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import linear_probe as lp  # noqa: E402
import session_rules  # noqa: E402

MARKETPLACE_REPO = "Razrocks/SDD-TOOL"
PLUGIN_ID = "sdd@sdd-tool"
ZERO_ID = "00000000-0000-0000-0000-000000000000"
CAFILE_CANDIDATES = [
    r"C:\Program Files\Git\usr\ssl\certs\ca-bundle.crt",
    r"C:\Program Files\Git\mingw64\etc\ssl\certs\ca-bundle.crt",
    "/etc/ssl/cert.pem",
    "/etc/ssl/certs/ca-certificates.crt",
]
OPEN_KEYS = [
    "Open Linear (desktop app or linear.app) in the agency workspace.",
    "Click the workspace name (top-left) -> Settings.",
    "Left sidebar, under Account: Security & access.",
    "Section Personal API keys -> New API key.",
]
KEYS = [
    {"env": "LINEAR_READ_KEY", "label": "sdd-read", "required": True, "role": "read",
     "why": "lets Claude READ every doc (accepted and working). It cannot change anything.",
     "steps": ["Key name: sdd-read",
               "Permissions: choose 'Only select permissions...' and tick ONLY  Read",
               "Team access: 'All teams you have access to'"]},
    {"env": "LINEAR_DRAFTS_KEY", "label": "sdd-drafts", "required": True, "role": "drafts",
     "why": "lets Claude write drafts and working docs in Delivery only. It cannot see Baselines.",
     "steps": ["Key name: sdd-drafts",
               "Permissions: 'Only select permissions...' and tick  Read  and  Write  (nothing else)",
               "Team access: 'Only select teams...' and pick ONLY  Delivery"]},
    {"env": "LINEAR_LOCK_KEY", "label": "sdd-lock", "required": False, "role": "lock",
     "why": "ONLY for people who approve scope: lets Claude move/merge accepted docs after your approval.",
     "steps": ["Key name: sdd-lock",
               "Permissions: 'Only select permissions...' and tick  Write  (Read optional; nothing else)",
               "Team access: 'Only select teams...' and pick  Baselines  and  Delivery"]},
]
TEAM_STEPS = [
    "In Linear: Settings -> Teams.",
    "If there is one default team, open it and rename it to  Delivery  (team key DEL).",
    "Create a second team named  Baselines  (team key BASE).  (Free plan allows 2 teams.)",
    "If both team slots are already used for something else, stop and talk to your lead.",
]


# ------------------------------------------------------------------ small helpers

def say(text=""):
    print(text, flush=True)


def heading(text):
    say()
    say("=" * 64)
    say(text)
    say("=" * 64)


def numbered(lines):
    for number, line in enumerate(lines, 1):
        say(f"  {number}. {line}")


def ask(prompt, default=None):
    suffix = f" [{default}]" if default else ""
    answer = input(f"{prompt}{suffix}: ").strip()
    return answer or (default or "")


def yes(prompt, default=True):
    answer = ask(f"{prompt} ({'Y/n' if default else 'y/N'})").lower()
    return default if not answer else answer.startswith("y")


def pause(prompt="Press Enter when done"):
    input(f"{prompt}... ")


# ------------------------------------------------------------------ checking a key against Linear

def classify_write(payload):
    """Write access from a documentUpdate on a non-existent ID: a scope error means no write;
    'not found' means the key may write (nothing exists, so nothing changes)."""
    errors = payload.get("errors") or []
    text = " ".join(str(e.get("message", "")) for e in errors).lower()
    if not errors:
        return True
    if "scope" in text and "write" in text:
        return False
    if "not found" in text or "entity" in text:
        return True
    return None


def check_key(key, cafile=None):
    """Live checks with a key held only in this process. Returns facts, never the key."""
    temp_env = "SDD_SETUP_KEY_UNDER_TEST"
    os.environ[temp_env] = key
    result = {"ok": False, "read": None, "viewer": None, "workspace": None, "teams": [], "write": None,
              "error": None}
    try:
        try:
            who = lp.call(lp.QUERIES["whoami"], {}, temp_env, cafile)
            result["viewer"] = (who.get("viewer") or {}).get("name")
            org = who.get("organization") or {}
            result["workspace"] = {"id": org.get("id"), "name": org.get("name"), "url_key": org.get("urlKey")}
            teams = lp.call(lp.QUERIES["teams"], {}, temp_env, cafile)["teams"]["nodes"]
            result["teams"] = [{"id": t["id"], "name": t["name"], "key": t.get("key")} for t in teams]
            result["read"] = True
        except lp.ProbeError as exc:
            text = str(exc).lower()
            if "scope" in text and "read" in text:
                result["read"] = False            # a Write-only key: valid, just can't read
            else:
                raise
        _, payload = lp.post_raw("mutation($id: String!) { documentUpdate(id: $id, input: {title: \"x\"}) { success } }",
                                 {"id": ZERO_ID}, temp_env, cafile)
        result["write"] = classify_write(payload)
        result["ok"] = True
    except lp.ProbeError as exc:
        result["error"] = str(exc)
    except SystemExit:
        result["error"] = "key missing"
    finally:
        os.environ.pop(temp_env, None)
    return result


def problems_for(role, facts):
    """What is wrong with a key for its role (empty list = correct)."""
    if not facts["ok"]:
        return [f"Linear rejected it: {facts['error']}"]
    names = {t["name"] for t in facts["teams"]}
    issues = []
    if role in ("read", "drafts") and facts["read"] is not True:
        issues.append("it has no Read permission. Tick 'Read'.")
    if role == "read":
        if facts["write"] is not False:
            issues.append("it can WRITE. Recreate it with only 'Read' ticked.")
        for team in ("Baselines", "Delivery"):
            if facts["read"] and team not in names:
                issues.append(f"it cannot see the {team} team (team access should be 'All teams').")
    elif role == "drafts":
        if facts["write"] is not True:
            issues.append("it cannot write. Tick 'Read' and 'Write'.")
        if "Baselines" in names:
            issues.append("it can see Baselines. Team access must be ONLY Delivery.")
        if facts["read"] and "Delivery" not in names:
            issues.append("it cannot see Delivery. Team access must be Delivery.")
    elif role == "lock":
        if facts["write"] is not True:
            issues.append("it cannot write. Tick 'Write'.")
        for team in ("Baselines", "Delivery"):
            if facts["read"] and team not in names:
                issues.append(f"it cannot see {team}. Team access must be Baselines + Delivery.")
    return issues


def describe_ok(facts):
    if facts["read"]:
        return (f"{facts['workspace']['name']} as {facts['viewer']}, "
                f"teams: {', '.join(t['name'] for t in facts['teams'])}")
    return "write access OK (Write-only key: team access can't be listed, which is fine for sdd-lock)"


# ------------------------------------------------------------------ TLS (Windows certificate store issue)

def ensure_tls(key):
    """Return a CA bundle path if the system store fails and a known bundle works, else None."""
    facts = check_key(key)
    if facts["ok"] or "CERTIFICATE_VERIFY_FAILED" not in (facts["error"] or ""):
        return None
    for candidate in [os.environ.get("SDD_CAFILE")] + CAFILE_CANDIDATES:
        if candidate and Path(candidate).is_file() and check_key(key, candidate)["ok"]:
            return candidate
    return None


# ------------------------------------------------------------------ saving environment variables

def set_user_env(name, value):
    """Persist a user-level environment variable. Returns a human description of where."""
    os.environ[name] = value
    if os.name == "nt":
        import ctypes
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as handle:
            winreg.SetValueEx(handle, name, 0, winreg.REG_SZ, value)
        result = ctypes.c_ulong()
        ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x1A, 0, "Environment", 0x0002, 5000, ctypes.byref(result))
        return "Windows user environment variables"
    if not re.fullmatch(r"[A-Za-z0-9_\-./:\\ ]+", value):
        raise ValueError(f"refusing to write unusual characters for {name}")
    profile = shell_profile()
    lines = profile.read_text(encoding="utf-8").splitlines() if profile.exists() else []
    profile.write_text(upsert_export(lines, name, value), encoding="utf-8")
    return str(profile)


def shell_profile():
    home = Path.home()
    if "zsh" in os.environ.get("SHELL", "") or sys.platform == "darwin":
        return home / ".zshrc"
    return home / ".bashrc"


def upsert_export(lines, name, value):
    line = f'export {name}="{value}"'
    out, replaced = [], False
    for existing in lines:
        if re.match(rf"^\s*export\s+{re.escape(name)}=", existing):
            if not replaced:
                out.append(line)
                replaced = True
        else:
            out.append(existing)
    if not replaced:
        out.append(line)
    return "\n".join(out) + "\n"


def saved_value(name):
    """Current value from this process or (Windows) the saved user variables."""
    value = os.environ.get(name)
    if value or os.name != "nt":
        return value
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as handle:
            return winreg.QueryValueEx(handle, name)[0]
    except OSError:
        return None


# ------------------------------------------------------------------ plugin

def claude_cli():
    return shutil.which("claude")


def plugin_installed():
    cli = claude_cli()
    if not cli:
        return None
    out = subprocess.run([cli, "plugin", "list"], capture_output=True, text=True, timeout=60)
    return PLUGIN_ID in (out.stdout + out.stderr)


def marketplace_known():
    cli = claude_cli()
    if not cli:
        return None
    out = subprocess.run([cli, "plugin", "marketplace", "list"], capture_output=True, text=True, timeout=60)
    return "sdd-tool" in (out.stdout + out.stderr)


# ------------------------------------------------------------------ project files

NEXT_IN_CLAUDE = [
    "Fully quit Claude (tray icon -> Quit) and reopen it, so it sees your keys.",
    "Open the project folder in Claude (desktop: Code tab -> pick the folder; terminal: cd into it, run 'claude').",
    "If Claude asks to trust the folder and enable the 'sdd' plugin: say yes (one time per computer).",
    "When a fresh session starts, Claude asks 'Turn on the SDD Linear tool for this repo?' - pick Yes, "
    "Not now, or No (only affects you; /sdd:on or /sdd:off changes it anytime).",
    "Once it's on, just work. SDD runs by itself: at session start it checks Linear in the background, "
    "creates your branch doc (on feature branches), and gives Claude the status with your first message.",
    "If Claude says a key is missing or Linear 'needs authentication': don't sign in there - run "
    "'python sdd_setup.py check' and follow the fix.",
    "Handy anytime: /sdd:checkpoint (save progress), /sdd:draft + /sdd:merge (change an accepted doc), "
    "/sdd:lock (accept a new doc), /sdd:merged (after a PR merges).",
]


ALREADY_ON = ("SDD is already on for you in this repo, so Claude won't ask you (teammates get the question). "
              "/sdd:off turns it off.")


def print_next_steps(opted_in=False):
    heading("Next, in Claude")
    numbered([ALREADY_ON if opted_in and step.startswith("When a fresh session") else step for step in NEXT_IN_CLAUDE])


def merge_settings(existing):
    """Add the SDD marketplace + plugin to a .claude/settings.json dict without touching the rest."""
    data = dict(existing or {})
    markets = dict(data.get("extraKnownMarketplaces") or {})
    markets.setdefault("sdd-tool", {"source": {"source": "github", "repo": MARKETPLACE_REPO}})
    data["extraKnownMarketplaces"] = markets
    plugins = dict(data.get("enabledPlugins") or {})
    plugins[PLUGIN_ID] = True
    data["enabledPlugins"] = plugins
    return data


def merge_gitignore(text):
    needed = [".sdd/merges/", ".sdd/pending/", ".sdd/status.json", ".sdd/.status-shown.json", ".sdd/optin.json",
              ".sdd/work/"]
    lines = text.splitlines() if text else []
    missing = [n for n in needed if n not in lines]
    if not missing:
        return text
    block = (["", "# SDD local working files"] if lines else ["# SDD local working files"]) + missing
    return "\n".join(lines + block) + "\n"


def build_project_map(existing, workspace, teams, prefix):
    data = dict(existing or {})
    data.setdefault("schema", "sdd-project-map/2")
    data["doc_prefix"] = prefix
    data["workspace"] = workspace
    data["teams"] = {
        "baselines": {"id": teams["Baselines"]["id"], "key": teams["Baselines"].get("key")},
        "delivery": {"id": teams["Delivery"]["id"], "key": teams["Delivery"].get("key")},
    }
    data.setdefault("baselines", [])
    return data


# ------------------------------------------------------------------ commands

def cmd_dev(args):
    heading("SDD setup for this computer")
    say("You will create up to 3 Linear API keys. Each is typed hidden, checked live, then saved.")
    say("Never paste a key into chat or anywhere else.")
    cafile = None
    for spec in KEYS:
        heading(f"{spec['label']}  ->  {spec['env']}" + ("" if spec["required"] else "   (optional)"))
        say(f"What it does: {spec['why']}")
        if not spec["required"] and not yes("Do you approve scope (accept/merge docs) and need this key?", False):
            say("Skipped.")
            continue
        current = saved_value(spec["env"])
        if current:
            facts = check_key(current, cafile)
            issues = problems_for(spec["role"], facts)
            if not issues:
                say(f"Already set and correct: {describe_ok(facts)}.")
                if not yes("Replace it anyway?", False):
                    continue
            else:
                say("Already set, but: " + "; ".join(issues))
        say()
        say("In Linear:")
        numbered(OPEN_KEYS + spec["steps"] + ["Click Create, then Copy the key (Linear shows it only once)."])
        while True:
            key = getpass.getpass(f"Paste {spec['label']} here (input hidden), or Enter to skip: ").strip()
            if not key:
                say("Skipped." if not spec["required"] else "Skipped - Claude can't use Linear without this key.")
                break
            if cafile is None:
                found = ensure_tls(key)
                if found:
                    cafile = found
                    where = set_user_env("SDD_CAFILE", cafile)
                    say(f"Note: this PC's certificate store fails for Linear; using {cafile} (saved as SDD_CAFILE).")
            facts = check_key(key, cafile)
            issues = problems_for(spec["role"], facts)
            if issues:
                say("That key isn't right yet: " + "; ".join(issues))
                say("Fix it in Linear (or delete it and create a new one), then paste again.")
                continue
            where = set_user_env(spec["env"], key)
            say(f"OK: {describe_ok(facts)}. Saved to {where}.")
            break
    heading("Claude plugin")
    known = marketplace_known()
    if known is None:
        say("Claude CLI not found on PATH. In Claude Code run:  /plugin marketplace add " + MARKETPLACE_REPO)
    elif not known:
        if yes(f"Add the SDD plugin marketplace ({MARKETPLACE_REPO}) now?"):
            subprocess.run([claude_cli(), "plugin", "marketplace", "add", MARKETPLACE_REPO])
    else:
        say("SDD marketplace already added.")
    say()
    say("This computer is set up. If a repo isn't set up for SDD yet, run  python sdd_setup.py project  inside it.")
    print_next_steps()
    return 0


def cmd_project(args):
    heading("SDD setup for this repo")
    root = Path(args.root or os.getcwd()).resolve()
    say(f"Repo folder: {root}")
    read_key = saved_value("LINEAR_READ_KEY")
    if not read_key:
        say("LINEAR_READ_KEY is not set. Run:  python sdd_setup.py dev   (then reopen this terminal).")
        return 1
    cafile = saved_value("SDD_CAFILE")
    while True:
        facts = check_key(read_key, cafile)
        if not facts["ok"]:
            say(f"Linear check failed: {facts['error']}")
            return 1
        teams = {t["name"]: t for t in facts["teams"]}
        if "Baselines" in teams and "Delivery" in teams:
            break
        say("This workspace needs two teams, Baselines and Delivery. In Linear:")
        numbered(TEAM_STEPS)
        if args.yes:
            return 1
        pause("Press Enter after creating them (or Ctrl+C to stop)")
    say(f"Workspace: {facts['workspace']['name']}  -  teams Baselines + Delivery found.")
    map_path = root / ".sdd" / "project-map.json"
    existing = json.loads(map_path.read_text(encoding="utf-8-sig")) if map_path.exists() else {}
    default_prefix = existing.get("doc_prefix") or root.name.replace("-", " ").replace("_", " ").title()
    say("Doc prefix = the start of every Linear doc title for this project, e.g.  Dice Roller / Requirements v1")
    prefix = args.prefix or (default_prefix if args.yes else ask("Doc prefix", default_prefix))
    map_path.parent.mkdir(parents=True, exist_ok=True)
    project_map = build_project_map(existing, facts["workspace"], teams, prefix)
    map_path.write_text(json.dumps(project_map, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    settings_path = root / ".claude" / "settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8-sig")) if settings_path.exists() else {}
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(merge_settings(settings), indent=2) + "\n", encoding="utf-8", newline="\n")
    gitignore = root / ".gitignore"
    gitignore.write_text(merge_gitignore(gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""),
                         encoding="utf-8", newline="\n")
    session_rules.set_optin(map_path, "on")
    heading("Done")
    say("Written:")
    numbered([f".sdd/project-map.json   (prefix: {prefix})",
              ".claude/settings.json    (teammates get asked to enable the sdd plugin)",
              ".gitignore               (SDD's local working files stay out of git)",
              ".sdd/optin.json          (SDD is on for you here; teammates are asked on their first session)"])
    say("Commit .sdd/project-map.json, .claude/settings.json, .gitignore, and later .sdd/snapshots/.")
    say("Teammates then just clone the repo - they only need their own keys (python sdd_setup.py dev).")
    print_next_steps(opted_in=True)
    return 0


def cmd_check(args):
    heading("SDD check")
    failures = 0
    cafile = saved_value("SDD_CAFILE")
    probe_key = next((saved_value(s["env"]) for s in KEYS if saved_value(s["env"])), None)
    if not cafile and probe_key:
        found = ensure_tls(probe_key)
        if found:
            say(f"[FIX ] TLS: this PC's certificate store fails for Linear; {found} works.")
            try:
                save = sys.stdin.isatty() and yes("Save it as SDD_CAFILE so all SDD scripts use it?")
            except EOFError:
                save = False
            if save:
                set_user_env("SDD_CAFILE", found)
                say("       Saved. Restart Claude so it picks it up.")
            else:
                say(f"       Fix: python sdd_setup.py dev  (saves it), or set user env SDD_CAFILE={found}")
                failures += 1
            cafile = found
    say(f"TLS bundle: {cafile or 'system default'}")
    for spec in KEYS:
        value = saved_value(spec["env"])
        if not value:
            status = "MISSING" if spec["required"] else "not set (optional)"
            say(f"[{'FAIL' if spec['required'] else ' -- '}] {spec['env']}: {status}  -> run: python sdd_setup.py dev")
            failures += spec["required"]
            continue
        facts = check_key(value, cafile)
        issues = problems_for(spec["role"], facts)
        if issues:
            say(f"[FAIL] {spec['env']}: " + "; ".join(issues))
            failures += 1
        else:
            say(f"[ OK ] {spec['env']}: {describe_ok(facts)}")
        if value and not os.environ.get(spec["env"]):
            say(f"       note: saved, but this terminal doesn't have it yet. Restart Claude/terminal.")
    installed = plugin_installed()
    say(f"[{' OK ' if installed else ' -- '}] plugin {PLUGIN_ID}: " +
        ("installed" if installed else "not found (fine if the repo prompts you to enable it)"
         if installed is not None else "Claude CLI not on PATH"))
    map_path = lp.find_project_map(args.root)
    if map_path:
        data = json.loads(map_path.read_text(encoding="utf-8-sig"))
        ok = bool(data.get("doc_prefix")) and bool((data.get("teams") or {}).get("baselines", {}).get("id"))
        say(f"[{' OK ' if ok else 'FAIL'}] project map: {map_path} (prefix: {data.get('doc_prefix')})")
        failures += not ok
    else:
        say("[ -- ] no .sdd/project-map.json here (run  python sdd_setup.py project  inside a repo)")
    say()
    say("All required checks passed." if not failures else f"{failures} problem(s) to fix (see above).")
    return 1 if failures else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="SDD setup wizard")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("dev", help="once per person: Linear keys + plugin marketplace")
    project = sub.add_parser("project", help="once per repo: project map + plugin settings")
    project.add_argument("--root", default=None)
    project.add_argument("--prefix", default=None)
    project.add_argument("--yes", action="store_true", help="no questions; use defaults")
    check = sub.add_parser("check", help="diagnose")
    check.add_argument("--root", default=None)
    args = parser.parse_args(argv)
    try:
        return {"dev": cmd_dev, "project": cmd_project, "check": cmd_check}[args.command](args)
    except (KeyboardInterrupt, EOFError):
        say()
        say("Stopped. Nothing else was changed.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
