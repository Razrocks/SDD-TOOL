"""Owner-approved changes to accepted (Baselines) documents. Stdlib only.

Credential: LINEAR_LOCK_KEY (Write, Baselines + Delivery). Reads use LINEAR_READ_KEY.
Every run is meant to be approved by the owner: a Claude Code PreToolUse hook
(hook_lock_gate.py) forces a permission prompt for any command mentioning lock.py,
and --title makes the document's name visible in that prompt.

  lock <id> --title "<Project> / <name>" --project "<Project>"
      Delivery team document (no project) -> Baselines. Title must start with "<project> / ".
  unlock <id> --title "<title>"
      Snapshot the locked text, then Baselines -> Delivery.
  apply <id> --title "<title>" --content-file merged.md --expect-sha <sha256>
      Write an owner-approved merge into a locked document. Refused if the document changed
      since the merge was planned (sha mismatch). Snapshots before and after.

Team IDs and the snapshot folder come from the project's .sdd/project-map.json (found by
walking up from the working directory, or --project-map). Snapshots are stored as
.sdd/snapshots/<sha256>.md (exact body) plus index.json, and every result is recorded under
"baselines" in the project map.
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
import sdd_merge  # noqa: E402

LOCK_KEY_ENV = "LINEAR_LOCK_KEY"
READ_KEY_ENV = "LINEAR_READ_KEY"
SEPARATOR = " / "
UPDATE = (
    "mutation($id: String!, $input: DocumentUpdateInput!) { documentUpdate(id: $id, input: $input) "
    "{ success } }"
)


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_doc(doc_id, cafile):
    return (lp.call(lp.QUERIES["doc_snapshot"], {"id": doc_id}, READ_KEY_ENV, cafile) or {}).get("document")


def save_snapshot(snapshot_dir, doc, reason):
    """Store the exact body as <sha256>.md and log it in index.json. Returns the record."""
    digest, size = lp.content_digest(doc.get("content"))
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    path = snapshot_dir / f"{digest}.md"
    if not path.exists():
        path.write_text(doc.get("content") or "", encoding="utf-8", newline="")
    record = {"sha256": digest, "bytes": size, "document": doc["id"], "title": doc.get("title"),
              "reason": reason, "taken_at": now(), "path": str(path)}
    index_path = snapshot_dir / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else []
    index.append(record)
    index_path.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return record


def record_in_map(map_path, entry):
    """Upsert the document's entry under "baselines" in the project map."""
    data = json.loads(Path(map_path).read_text(encoding="utf-8-sig"))
    rows = [row for row in data.get("baselines", []) if row.get("id") != entry["id"]]
    rows.append(entry)
    data["baselines"] = rows
    Path(map_path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def refuse(message):
    print(f"refused: {message}", file=sys.stderr)
    return 2


def errors_of(payload):
    return [{"message": e.get("message"), "code": (e.get("extensions") or {}).get("code")}
            for e in payload.get("errors") or []]


def run(args):
    map_path, project_map = lp.load_project_map(args.project_map)
    if not project_map:
        return refuse("no .sdd/project-map.json found (run inside the project, or pass --project-map)")
    try:
        delivery = project_map["teams"]["delivery"]["id"]
        baselines = project_map["teams"]["baselines"]["id"]
    except (KeyError, TypeError):
        return refuse("project map is missing teams.delivery.id / teams.baselines.id")
    snapshot_dir = Path(map_path).parent / "snapshots"

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
    current_team = (doc.get("team") or {}).get("id")
    before = None

    if args.command == "lock":
        if current_team != delivery:
            return refuse("lock moves Delivery team documents only")
        if doc.get("project"):
            return refuse("document belongs to a project; accepted docs must be team documents")
        if not args.allow_fixture and not title.startswith(f"{args.project}{SEPARATOR}"):
            return refuse(f"title must start with {args.project + SEPARATOR!r} so Baselines stays organized")
        update, expected_team = {"teamId": baselines}, baselines
    elif args.command == "unlock":
        if current_team != baselines:
            return refuse("unlock moves Baselines documents only")
        before = save_snapshot(snapshot_dir, doc, "before unlock")
        update, expected_team = {"teamId": delivery}, delivery
    else:  # apply
        if current_team != baselines:
            return refuse("apply writes into locked (Baselines) documents only")
        current_sha, _ = lp.content_digest(doc.get("content"))
        if current_sha != args.expect_sha:
            return refuse("the accepted doc changed since the merge was planned; plan the merge again")
        merged = Path(args.content_file).read_text(encoding="utf-8")
        before = save_snapshot(snapshot_dir, doc, "before merge")
        update, expected_team = {"content": merged}, baselines

    status, payload = lp.post_raw(UPDATE, {"id": doc["id"], "input": update}, LOCK_KEY_ENV, args.cafile)
    errors = errors_of(payload)
    try:
        after = read_doc(doc["id"], args.cafile) or {}
    except lp.ProbeError as exc:
        after, errors = {}, errors + [{"message": f"read-back failed: {exc}", "code": None}]
    verified = (after.get("team") or {}).get("id") == expected_team and not after.get("project") and not errors
    if verified and args.command == "apply":
        verified = sdd_merge.blocks(after.get("content")) == sdd_merge.blocks(merged)

    after_record = None
    if verified:
        reason = {"lock": "locked", "unlock": "unlocked", "apply": "after merge"}[args.command]
        after_record = save_snapshot(snapshot_dir, after, reason)
        entry = {"id": doc["id"], "title": title, "url": doc.get("url"), "sha256": after_record["sha256"],
                 "status": "unlocked" if args.command == "unlock" else "locked", "updated_at": now()}
        if before:
            entry["previous_sha256"] = before["sha256"]
        record_in_map(map_path, entry)

    print(json.dumps({
        "action": args.command,
        "document": doc["id"],
        "title": title,
        "http_status": status,
        "errors": errors,
        "snapshot_before": before,
        "snapshot_after": after_record,
        "verified": verified,
        "project_map": str(map_path),
        "note": "Accepted scope changed. Run linear_probe.py baseline to see the current set.",
    }, indent=2, ensure_ascii=False))
    return 0 if verified else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description="Owner-approved changes to accepted documents.")
    parser.add_argument("--cafile", default=None)
    parser.add_argument("--project-map", default=None)
    parser.add_argument("--allow-fixture", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    lock_cmd = sub.add_parser("lock")
    lock_cmd.add_argument("doc_id")
    lock_cmd.add_argument("--title", required=True, help="exact current title (shown in the approval prompt)")
    lock_cmd.add_argument("--project", required=True, help="project name; title must start with it + ' / '")
    unlock_cmd = sub.add_parser("unlock")
    unlock_cmd.add_argument("doc_id")
    unlock_cmd.add_argument("--title", required=True)
    apply_cmd = sub.add_parser("apply")
    apply_cmd.add_argument("doc_id")
    apply_cmd.add_argument("--title", required=True)
    apply_cmd.add_argument("--content-file", required=True)
    apply_cmd.add_argument("--expect-sha", required=True)
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
