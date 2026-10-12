"""Read-only Linear GraphQL probe. Stdlib only. The key is read from an environment
variable and never printed, logged, or passed on the command line.

Commands:
  whoami                      viewer + organization (workspace identity)
  teams                       teams visible to the key
  doc <id> [--content]        one document's metadata (and body with --content)
  introspect <TypeName>       field / input-field names of a schema type

Options: --key-env NAME (default LINEAR_READ_KEY)
Exit codes: 0 ok, 1 API/GraphQL/transport error, 2 usage or missing key.
No mutations exist in this script.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

API = "https://api.linear.app/graphql"

QUERIES = {
    "whoami": "query { viewer { id name } organization { id name urlKey } }",
    "teams": "query { teams(first: 100) { nodes { id key name private } pageInfo { hasNextPage endCursor } } }",
    "doc": "query($id: String!) { document(id: $id) { id title url updatedAt project { id name } } }",
    "doc_content": "query($id: String!) { document(id: $id) { id title url updatedAt project { id name } content } }",
    "introspect": "query($name: String!) { __type(name: $name) { name kind fields { name } inputFields { name } } }",
}


class ProbeError(Exception):
    pass


def call(query, variables, key_env):
    if query.lstrip().lower().startswith("mutation"):
        raise ProbeError("mutations are not allowed in linear_probe.py")
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
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:2000]
        raise ProbeError(f"HTTP {exc.code}: {detail}")
    except urllib.error.URLError as exc:
        raise ProbeError(f"transport error (outcome unknown): {exc.reason}")
    if payload.get("errors"):
        messages = [
            {"message": e.get("message"), "code": (e.get("extensions") or {}).get("code")}
            for e in payload["errors"]
        ]
        raise ProbeError("GraphQL errors (HTTP 200): " + json.dumps(messages))
    return payload.get("data")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only Linear probe.")
    parser.add_argument("--key-env", default="LINEAR_READ_KEY")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("whoami")
    sub.add_parser("teams")
    doc = sub.add_parser("doc")
    doc.add_argument("id")
    doc.add_argument("--content", action="store_true")
    intro = sub.add_parser("introspect")
    intro.add_argument("type_name")
    args = parser.parse_args(argv)

    if args.command == "doc":
        query = QUERIES["doc_content" if args.content else "doc"]
        variables = {"id": args.id}
    elif args.command == "introspect":
        query, variables = QUERIES["introspect"], {"name": args.type_name}
    else:
        query, variables = QUERIES[args.command], {}

    try:
        data = call(query, variables, args.key_env)
    except ProbeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(data, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
