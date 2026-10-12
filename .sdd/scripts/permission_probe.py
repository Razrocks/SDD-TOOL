"""Live permission-test helper for P02-P10. MUTATES Linear. Stdlib only.

Safety rails:
  - Requires --confirm-fixture-test.
  - Existing targets are fetched with the READ key first; the title must start with
    "TEST-FIXTURE" or nothing is sent.
  - Created documents must have a title starting with "TEST-FIXTURE".
  - Keys come from environment variables and are never printed.

Commands (run with --key-env set to the credential under test):
  update <doc_id> <content>                 documentUpdate content
  move <doc_id> --team-id ID                documentUpdate teamId (reparent)
  nest <doc_id> --parent-document-id ID     documentUpdate parentDocumentId (sub-document)
  trash <doc_id>                            documentUpdate trashed=true
  create --team-id ID <title> <content>     documentCreate

Each attempt prints one JSON record: credential env name, operation, HTTP status,
classification (SUCCESS / DENIED_AUTH / INVALID_REQUEST / ERROR), raw error messages,
and the target's before/after state read with the READ key. A denial is only a PASS
when the same operation succeeds for an allowed fixture (see runbooks/permissions.md).
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from linear_probe import ProbeError, post, post_raw  # noqa: E402

FIXTURE_PREFIX = "TEST-FIXTURE"
READ_DOC = (
    "query($id: String!) { document(id: $id) "
    "{ id title content updatedAt team { id } project { id } parentDocument { id } trashed archivedAt } }"
)
UPDATE = (
    "mutation($id: String!, $input: DocumentUpdateInput!) { documentUpdate(id: $id, input: $input) "
    "{ success document { id team { id } updatedAt } } }"
)
CREATE = (
    "mutation($input: DocumentCreateInput!) { documentCreate(input: $input) "
    "{ success document { id title team { id } } } }"
)
AUTH_HINTS = ("forbidden", "permission", "not authorized", "unauthorized", "scope", "access")
INVALID_CODES = ("GRAPHQL_VALIDATION_FAILED", "BAD_USER_INPUT", "INVALID_INPUT")


def classify(status, payload):
    errors = payload.get("errors") or []
    if not errors:
        return "SUCCESS"
    for error in errors:
        code = str((error.get("extensions") or {}).get("code") or "")
        message = str(error.get("message") or "").lower()
        if code.upper() in INVALID_CODES:
            return "INVALID_REQUEST"
        if code.upper() == "FORBIDDEN" or status in (401, 403) or any(h in message for h in AUTH_HINTS):
            return "DENIED_AUTH"
    return "ERROR"


def read_doc(doc_id, read_env, cafile):
    data = post(READ_DOC, {"id": doc_id}, read_env, cafile)
    return (data or {}).get("document")


def run(args):
    if not args.confirm_fixture_test:
        print("refusing: pass --confirm-fixture-test", file=sys.stderr)
        return 2

    before = None
    if args.command == "create":
        if not args.title.startswith(FIXTURE_PREFIX):
            print(f"refusing: created title must start with {FIXTURE_PREFIX}", file=sys.stderr)
            return 2
        query = CREATE
        variables = {"input": {"teamId": args.team_id, "title": args.title, "content": args.content}}
    else:
        try:
            before = read_doc(args.doc_id, args.read_env, args.cafile)
        except ProbeError as exc:
            print(f"refusing: cannot read target with {args.read_env}: {exc}", file=sys.stderr)
            return 2
        if not before or not str(before.get("title", "")).startswith(FIXTURE_PREFIX):
            print(f"refusing: target is not a {FIXTURE_PREFIX} document", file=sys.stderr)
            return 2
        query = UPDATE
        if args.command == "update":
            update_input = {"content": args.content}
        elif args.command == "move":
            update_input = {"teamId": args.team_id}
        elif args.command == "nest":
            update_input = {"parentDocumentId": args.parent_document_id}
        else:
            update_input = {"trashed": True}
        variables = {"id": args.doc_id, "input": update_input}

    status, payload = post_raw(query, variables, args.key_env, args.cafile)
    after = read_doc(args.doc_id, args.read_env, args.cafile) if args.command != "create" else None
    record = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "credential_env": args.key_env,
        "operation": args.command,
        "variables": variables,
        "http_status": status,
        "classification": classify(status, payload),
        "errors": [
            {"message": e.get("message"), "code": (e.get("extensions") or {}).get("code")}
            for e in payload.get("errors") or []
        ],
        "result": payload.get("data"),
        "before": before,
        "after": after,
        "target_unchanged": (before == after) if before is not None else None,
    }
    print(json.dumps(record, indent=2))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Permission test helper (mutates fixtures).")
    parser.add_argument("--key-env", required=True, help="credential under test")
    parser.add_argument("--read-env", default="LINEAR_READ_KEY", help="independent read credential")
    parser.add_argument("--cafile", default=None)
    parser.add_argument("--confirm-fixture-test", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    update = sub.add_parser("update")
    update.add_argument("doc_id")
    update.add_argument("content")
    move = sub.add_parser("move")
    move.add_argument("doc_id")
    move.add_argument("--team-id", required=True)
    nest = sub.add_parser("nest")
    nest.add_argument("doc_id")
    nest.add_argument("--parent-document-id", required=True)
    trash = sub.add_parser("trash")
    trash.add_argument("doc_id")
    create = sub.add_parser("create")
    create.add_argument("--team-id", required=True)
    create.add_argument("title")
    create.add_argument("content")
    args = parser.parse_args(argv)
    try:
        return run(args)
    except ProbeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
