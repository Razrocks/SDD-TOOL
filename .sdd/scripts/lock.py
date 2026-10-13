"""Lock / unlock a Linear document by moving it between the Delivery and Baselines teams.

The only mutation is documentUpdate(teamId). Content cannot be edited with this script.
Credential: LINEAR_LOCK_KEY (Write, Baselines + Delivery). Reads use LINEAR_READ_KEY.
Every run is meant to be approved by the owner: a Claude Code PreToolUse hook
(hook_lock_gate.py) forces a permission prompt for any command mentioning lock.py,
and the --title argument makes the document's name visible in that prompt.

  lock <doc_id> --title "Dice Roller / Requirements v1" --project "Dice Roller" [--project-map PATH]
      Delivery team document (no project) -> Baselines. Title must start with "<project> / ".
  unlock <doc_id> --title "<current title>" [--project-map PATH]
      Snapshot the locked text first, then Baselines -> Delivery.

--title must equal the document's current title exactly (guards against a wrong ID).
--project-map records the result in that project's .sdd/project-map.json ("baselines").
Options: --cafile PATH, --allow-fixture (permit TEST-FIXTURE documents, for testing)
Exit codes: 0 done and verified, 1 API failure or unverified result, 2 refused.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import linear_probe as lp  # noqa: E402

LOCK_KEY_ENV = "LINEAR_LOCK_KEY"
READ_KEY_ENV = "LINEAR_READ_KEY"
SEPARATOR = " / "
SNAPSHOT_DIR = Path(__file__).resolve().parents[1] / "snapshots"
MOVE = (
    "mutation($id: String!, $input: DocumentUpdateInput!) { documentUpdate(id: $id, input: $input) "
    "{ success } }"
)


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def team_ids():
    try:
        data = json.loads(lp.PROJECT_MAP.read_text(encoding="utf-8-sig"))
        return data["teams"]["delivery"]["id"], data["teams"]["baselines"]["id"]
    except (OSError, ValueError, KeyError, TypeError):
        return None, None


def read_doc(doc_id, cafile):
    return (lp.call(lp.QUERIES["doc_snapshot"], {"id": doc_id}, READ_KEY_ENV, cafile) or {}).get("document")


def take_snapshot(doc):
    fetched = now()
    digest, size = lp.content_digest(doc.get("content"))
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOT_DIR / f"{fetched.replace(':', '')}-{doc['id']}.md"
    header = [
        f"Snapshot of: {doc.get('title')} (last locked text, taken before unlock)",
        f"Document ID: {doc['id']}",
        f"URL: {doc.get('url')}",
        f"Fetched at: {fetched} · Linear updatedAt: {doc.get('updatedAt')}",
        f"Body sha256: {digest} ({size} bytes)",
        "---",
    ]
    path.write_text("\n".join(header) + "\n" + (doc.get("content") or ""), encoding="utf-8", newline="\n")
    return {"path": str(path), "sha256": digest, "bytes": size, "fetched_at": fetched}


def record_in_map(map_path, entry):
    """Upsert the document's entry under "baselines" in a project's map."""
    path = Path(map_path)
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    rows = [row for row in data.get("baselines", []) if row.get("id") != entry["id"]]
    rows.append(entry)
    data["baselines"] = rows
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def refuse(message):
    print(f"refused: {message}", file=sys.stderr)
    return 2


def run(args):
    delivery, baselines = team_ids()
    if not delivery or not baselines:
        return refuse("Delivery/Baselines team IDs missing from .sdd/project-map.json")
    if args.project_map and not Path(args.project_map).is_file():
        return refuse(f"project map not found: {args.project_map}")
    try:
        doc = read_doc(args.doc_id, args.cafile)
    except lp.ProbeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if not doc:
        return refuse(f"document {args.doc_id} not found")
    title = str(doc.get("title", ""))
    if title != args.title:
        return refuse(f"--title does not match this document (its title is {title!r})")
    if title.startswith(lp.FIXTURE_PREFIX) and not args.allow_fixture:
        return refuse("TEST-FIXTURE document (pass --allow-fixture to test)")
    current = (doc.get("team") or {}).get("id")
    if args.command == "lock":
        if current != delivery:
            return refuse("lock moves Delivery team documents only")
        if doc.get("project"):
            return refuse("document belongs to a project; accepted docs must be team documents")
        if not args.allow_fixture and not title.startswith(f"{args.project}{SEPARATOR}"):
            return refuse(f"title must start with {args.project + SEPARATOR!r} so Baselines stays organized")
        target, snapshot = baselines, None
    else:
        if current != baselines:
            return refuse("unlock moves Baselines documents only")
        target, snapshot = delivery, take_snapshot(doc)

    status, payload = lp.post_raw(MOVE, {"id": doc["id"], "input": {"teamId": target}}, LOCK_KEY_ENV, args.cafile)
    errors = [
        {"message": e.get("message"), "code": (e.get("extensions") or {}).get("code")}
        for e in payload.get("errors") or []
    ]
    try:
        after = read_doc(doc["id"], args.cafile) or {}
    except lp.ProbeError as exc:
        after, errors = {}, errors + [{"message": f"read-back failed: {exc}", "code": None}]
    verified = (after.get("team") or {}).get("id") == target and not after.get("project") and not errors

    recorded = None
    if verified and args.project_map:
        digest, size = lp.content_digest(after.get("content"))
        entry = {"id": doc["id"], "title": title, "url": doc.get("url"), "sha256": digest, "bytes": size}
        if args.command == "lock":
            entry.update({"status": "locked", "locked_at": now()})
        else:
            entry.update({"status": "unlocked", "unlocked_at": now(), "last_accepted_snapshot": snapshot})
        record_in_map(args.project_map, entry)
        recorded = args.project_map

    print(json.dumps({
        "action": args.command,
        "document": doc["id"],
        "title": title,
        "from_team": current,
        "to_team": target,
        "http_status": status,
        "errors": errors,
        "snapshot": snapshot,
        "verified": verified,
        "recorded_in": recorded,
        "note": "Accepted scope changed. Run linear_probe.py baseline to see the current set.",
    }, indent=2, ensure_ascii=False))
    return 0 if verified else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description="Lock/unlock a document (owner-approved moves only).")
    parser.add_argument("--cafile", default=None)
    parser.add_argument("--allow-fixture", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    lock_cmd = sub.add_parser("lock")
    lock_cmd.add_argument("doc_id")
    lock_cmd.add_argument("--title", required=True, help="exact current title (shown in the approval prompt)")
    lock_cmd.add_argument("--project", required=True, help="project name; title must start with it + ' / '")
    lock_cmd.add_argument("--project-map", default=None)
    unlock_cmd = sub.add_parser("unlock")
    unlock_cmd.add_argument("doc_id")
    unlock_cmd.add_argument("--title", required=True, help="exact current title (shown in the approval prompt)")
    unlock_cmd.add_argument("--project-map", default=None)
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
