"""Read-only Linear GraphQL probe. Stdlib only. The key is read from an environment
variable and never printed, logged, or passed on the command line.

Commands:
  whoami                      viewer + organization (workspace identity)
  teams                       teams visible to the key
  doc <id> [--content]        one document's metadata (and body with --content)
  introspect <TypeName>       field / input-field names of a schema type
  audit [--baselines-team-id ID]
                              flag projects linked to the Baselines team and documents
                              inside them (Baselines must only hold team documents).
                              Team ID defaults to .sdd/project-map.json. Exit 3 = findings.

Options: --key-env NAME (default LINEAR_READ_KEY)
         --cafile PATH  verify TLS against this CA bundle only (default: system store).
                        Use when the Windows store builds an expired chain, e.g.
                        C:\\Program Files\\Git\\usr\\ssl\\certs\\ca-bundle.crt. Verification stays on.
Exit codes: 0 ok, 1 API/GraphQL/transport error, 2 usage or missing key.
No mutations exist in this script.
"""

import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.linear.app/graphql"

QUERIES = {
    "whoami": "query { viewer { id name } organization { id name urlKey } }",
    "teams": "query { teams(first: 100) { nodes { id key name private } pageInfo { hasNextPage endCursor } } }",
    "doc": "query($id: String!) { document(id: $id) { id title url updatedAt project { id name } } }",
    "doc_content": "query($id: String!) { document(id: $id) { id title url updatedAt project { id name } content } }",
    "introspect": "query($name: String!) { __type(name: $name) { name kind fields { name } inputFields { name } } }",
}


AUDIT_PROJECTS = (
    "query($after: String) { projects(first: 100, after: $after, includeArchived: true) "
    "{ nodes { id name url archivedAt trashed teams { nodes { id } } } pageInfo { hasNextPage endCursor } } }"
)
AUDIT_DOCUMENTS = (
    "query($after: String) { documents(first: 100, after: $after, includeArchived: true) "
    "{ nodes { id title url archivedAt trashed team { id } project { id } } pageInfo { hasNextPage endCursor } } }"
)
MAX_PAGES = 50
PROJECT_MAP = Path(__file__).resolve().parents[1] / "project-map.json"


class ProbeError(Exception):
    pass


def inactive(item):
    return bool(item.get("trashed") or item.get("archivedAt"))


def find_violations(projects, documents, baselines_id):
    """Baselines may hold team documents only. Anything active and project-shaped there is a
    finding. Trashed/archived items are returned separately: restorable, so reported, not blocking."""
    linked_all = {
        p["id"]: p for p in projects
        if baselines_id in [t["id"] for t in (p.get("teams") or {}).get("nodes", [])]
    }
    linked = {pid: p for pid, p in linked_all.items() if not inactive(p)}
    info = [
        {"kind": "inactive_project_linked_to_baselines", "id": p["id"], "name": p.get("name"),
         "trashed": bool(p.get("trashed")), "archivedAt": p.get("archivedAt")}
        for pid, p in linked_all.items() if pid not in linked
    ]
    findings = [
        {"kind": "project_linked_to_baselines", "id": p["id"], "name": p.get("name"), "url": p.get("url")}
        for p in linked.values()
    ]
    for doc in documents:
        if inactive(doc):
            continue
        project_id = (doc.get("project") or {}).get("id")
        team_id = (doc.get("team") or {}).get("id")
        if project_id in linked:
            findings.append({"kind": "document_in_baselines_linked_project", "id": doc["id"],
                             "title": doc.get("title"), "project": project_id})
        elif team_id == baselines_id and project_id:
            findings.append({"kind": "baselines_document_attached_to_project", "id": doc["id"],
                             "title": doc.get("title"), "project": project_id})
    team_docs = [d for d in documents
                 if (d.get("team") or {}).get("id") == baselines_id and not d.get("project") and not inactive(d)]
    return findings, len(team_docs), info


def paginate(query, root, key_env, cafile):
    nodes, after = [], None
    for _ in range(MAX_PAGES):
        page = call(query, {"after": after}, key_env, cafile)[root]
        nodes.extend(page["nodes"])
        if not page["pageInfo"]["hasNextPage"]:
            return nodes, True
        after = page["pageInfo"]["endCursor"]
    return nodes, False


def baselines_team_from_map():
    try:
        data = json.loads(PROJECT_MAP.read_text(encoding="utf-8-sig"))
        return data["teams"]["baselines"]["id"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def tls_context(cafile):
    # With cafile set, only that bundle is trusted; the system store is not merged in.
    return ssl.create_default_context(cafile=cafile) if cafile else None


def call(query, variables, key_env, cafile=None):
    if query.lstrip().lower().startswith("mutation"):
        raise ProbeError("mutations are not allowed in linear_probe.py")
    return post(query, variables, key_env, cafile)


def post_raw(query, variables, key_env, cafile=None):
    """Send one GraphQL request; return (http_status, payload). No error interpretation."""
    key = os.environ.get(key_env)
    if not key:
        print(f"{key_env} is not set in this process environment", file=sys.stderr)
        sys.exit(2)
    body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    request = urllib.request.Request(
        API,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": key},
    )
    try:
        with urllib.request.urlopen(request, timeout=30, context=tls_context(cafile)) as response:
            return 200, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:2000]
        try:
            return exc.code, json.loads(detail)
        except json.JSONDecodeError:
            return exc.code, {"errors": [{"message": detail}]}
    except urllib.error.URLError as exc:
        raise ProbeError(f"transport error (outcome unknown): {exc.reason}")


def post(query, variables, key_env, cafile=None):
    status, payload = post_raw(query, variables, key_env, cafile)
    if status != 200 and not payload.get("errors"):
        raise ProbeError(f"HTTP {status}")
    if payload.get("errors"):
        messages = [
            {"message": e.get("message"), "code": (e.get("extensions") or {}).get("code")}
            for e in payload["errors"]
        ]
        raise ProbeError(f"GraphQL errors (HTTP {status}): " + json.dumps(messages))
    return payload.get("data")


def run_audit(args):
    baselines_id = args.baselines_team_id or baselines_team_from_map()
    if not baselines_id:
        print("no Baselines team ID: pass --baselines-team-id or fill .sdd/project-map.json", file=sys.stderr)
        return 2
    try:
        projects, projects_complete = paginate(AUDIT_PROJECTS, "projects", args.key_env, args.cafile)
        documents, documents_complete = paginate(AUDIT_DOCUMENTS, "documents", args.key_env, args.cafile)
    except ProbeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    findings, team_doc_count, info = find_violations(projects, documents, baselines_id)
    complete = projects_complete and documents_complete
    print(json.dumps({
        "baselines_team_id": baselines_id,
        "projects_scanned": len(projects),
        "documents_scanned": len(documents),
        "baselines_team_documents": team_doc_count,
        "scan_complete": complete,
        "findings": findings,
        "inactive_info": info,
        "result": "FINDINGS" if findings else ("CLEAN" if complete else "INCOMPLETE"),
        "note": "Detects only; does not prevent. Accepted scope = Baselines team documents listed in the Baseline Register.",
    }, indent=2))
    if findings:
        return 3
    return 0 if complete else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only Linear probe.")
    parser.add_argument("--key-env", default="LINEAR_READ_KEY")
    parser.add_argument("--cafile", default=None)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("whoami")
    sub.add_parser("teams")
    doc = sub.add_parser("doc")
    doc.add_argument("id")
    doc.add_argument("--content", action="store_true")
    intro = sub.add_parser("introspect")
    intro.add_argument("type_name")
    audit = sub.add_parser("audit")
    audit.add_argument("--baselines-team-id", default=None)
    args = parser.parse_args(argv)

    if args.command == "audit":
        return run_audit(args)
    if args.command == "doc":
        query = QUERIES["doc_content" if args.content else "doc"]
        variables = {"id": args.id}
    elif args.command == "introspect":
        query, variables = QUERIES["introspect"], {"name": args.type_name}
    else:
        query, variables = QUERIES[args.command], {}

    try:
        data = call(query, variables, args.key_env, args.cafile)
    except ProbeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(data, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
