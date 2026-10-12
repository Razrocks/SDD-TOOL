"""Read-only Linear GraphQL probe. Stdlib only. The key is read from an environment
variable and never printed, logged, or passed on the command line.

Commands:
  whoami                      viewer + organization (workspace identity)
  teams                       teams visible to the key
  doc <id> [--content]        one document's metadata (and body with --content)
  introspect <TypeName>       field / input-field names of a schema type

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
    args = parser.parse_args(argv)

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
