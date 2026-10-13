"""Branch docs and draft fork/merge for the SDD workflow. Stdlib only.

Writes go only to Delivery (LINEAR_DRAFTS_KEY); reads use LINEAR_READ_KEY. Nothing here can
change an accepted doc — the final merge is applied by owner-approved `lock.py apply`.

  branch-open  [--branch B] [--owner NAME] [--pr URL]   find or create "<P> / Branch / <B>"
  branch-close [--branch B] --status merged|abandoned [--merge-commit SHA]
  branches                                               list branch docs and their status
  draft  <accepted_doc_id> [--owner NAME] [--branch B]   fork an accepted doc into a personal draft
  merge-plan  <draft_id>                                 numbered changes vs the accepted doc (3-way)
  merge-build <draft_id> --decisions JSON                merged text + the lock.py apply command
  draft-close <draft_id> --status merged|partly-merged|rejected

<P> is "doc_prefix" from the project's .sdd/project-map.json (or --project). Branch defaults to
the current git branch; owner defaults to your Linear name.
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import linear_probe as lp  # noqa: E402
import sdd_merge  # noqa: E402

READ_KEY_ENV = "LINEAR_READ_KEY"
DRAFTS_KEY_ENV = "LINEAR_DRAFTS_KEY"
MARKER = "SDD-DRAFT-BODY-BELOW"
CREATE = ("mutation($input: DocumentCreateInput!) { documentCreate(input: $input) "
          "{ success document { id title url } } }")
UPDATE = ("mutation($id: String!, $input: DocumentUpdateInput!) { documentUpdate(id: $id, input: $input) "
          "{ success document { id title url } } }")
VIEWER = "query { viewer { name } }"
STATUS_SUFFIX = re.compile(r" \((merged|abandoned|partly-merged|rejected)\)$")


class DocsError(Exception):
    pass


def today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def read(query, variables, cafile):
    return lp.call(query, variables, READ_KEY_ENV, cafile) or {}


def write(query, variables, cafile):
    status, payload = lp.post_raw(query, variables, DRAFTS_KEY_ENV, cafile)
    if payload.get("errors"):
        raise DocsError(f"write failed (HTTP {status}): {json.dumps(payload['errors'])[:400]}")
    return payload.get("data") or {}


def get_doc(doc_id, cafile):
    doc = read(lp.QUERIES["doc_snapshot"], {"id": doc_id}, cafile).get("document")
    if not doc:
        raise DocsError(f"document {doc_id} not found")
    return doc


def context(args):
    map_path, project_map = lp.load_project_map(args.project_map)
    if not project_map:
        raise DocsError("no .sdd/project-map.json found (run inside the project, or pass --project-map)")
    prefix = args.project or project_map.get("doc_prefix")
    if not prefix:
        raise DocsError('project map has no "doc_prefix"; pass --project')
    return Path(map_path), project_map, prefix


def git_branch():
    try:
        out = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    name = out.stdout.strip()
    return name if out.returncode == 0 and name and name != "HEAD" else None


def owner_name(args):
    if args.owner:
        return args.owner
    viewer = (lp.call(VIEWER, {}, DRAFTS_KEY_ENV, args.cafile) or {}).get("viewer") or {}
    return viewer.get("name") or "unknown"


def all_docs(cafile):
    docs, _ = lp.paginate(lp.AUDIT_DOCUMENTS, "documents", READ_KEY_ENV, cafile)
    return [d for d in docs if not lp.inactive(d)]


def find_by_title(docs, title, team_id):
    hits = [d for d in docs if d.get("title") == title and (d.get("team") or {}).get("id") == team_id]
    if len(hits) > 1:
        raise DocsError(f"{len(hits)} active documents are titled {title!r}; fix the duplicate first")
    return hits[0] if hits else None


# ------------------------------------------------------------------ branch docs

def branch_title(prefix, branch):
    return f"{prefix} / Branch / {branch}"


def cmd_branch_open(args):
    _, project_map, prefix = context(args)
    branch = args.branch or git_branch()
    if not branch:
        raise DocsError("not on a git branch; pass --branch")
    delivery = project_map["teams"]["delivery"]["id"]
    title = branch_title(prefix, branch)
    existing = find_by_title(all_docs(args.cafile), title, delivery)
    if existing:
        return {"action": "opened", "id": existing["id"], "title": title, "url": existing.get("url")}
    owner = owner_name(args)
    content = "\n".join([
        f"Owner: {owner}",
        f"Branch: {branch}",
        f"PR: {args.pr or 'not opened yet'}",
        "Status: in progress",
        "",
        f"Work notes, decisions, evidence and handoffs for this branch, in any format. "
        f"One owner: only {owner} (and their agent) writes here.",
    ])
    created = write(CREATE, {"input": {"teamId": delivery, "title": title, "content": content}}, args.cafile)
    doc = created["documentCreate"]["document"]
    return {"action": "created", "id": doc["id"], "title": doc["title"], "url": doc.get("url"), "owner": owner}


def cmd_branch_close(args):
    _, project_map, prefix = context(args)
    branch = args.branch or git_branch()
    if not branch:
        raise DocsError("not on a git branch; pass --branch")
    title = branch_title(prefix, branch)
    doc = find_by_title(all_docs(args.cafile), title, project_map["teams"]["delivery"]["id"])
    if not doc:
        raise DocsError(f"no open branch doc titled {title!r}")
    body = get_doc(doc["id"], args.cafile).get("content") or ""
    note = f"Status: {args.status} {today()}" + (f" (merge commit {args.merge_commit})" if args.merge_commit else "")
    body = re.sub(r"^Status: .*$", note, body, count=1, flags=re.M) if re.search(r"^Status: ", body, re.M) \
        else note + "\n\n" + body
    new_title = f"{title} ({args.status})"
    write(UPDATE, {"id": doc["id"], "input": {"title": new_title, "content": body}}, args.cafile)
    after = get_doc(doc["id"], args.cafile)
    return {"action": "closed", "id": doc["id"], "title": after.get("title"), "status": args.status,
            "verified": after.get("title") == new_title}


def cmd_branches(args):
    _, project_map, prefix = context(args)
    lead = f"{prefix} / Branch / "
    rows = []
    for d in all_docs(args.cafile):
        title = d.get("title", "")
        if title.startswith(lead) and (d.get("team") or {}).get("id") == project_map["teams"]["delivery"]["id"]:
            match = STATUS_SUFFIX.search(title)
            rows.append({"branch": STATUS_SUFFIX.sub("", title[len(lead):]),
                         "status": match.group(1) if match else "in progress",
                         "id": d["id"], "url": d.get("url")})
    return {"project": prefix, "branches": sorted(rows, key=lambda r: (r["status"] != "in progress", r["branch"]))}


# ------------------------------------------------------------------ drafts and merges

def draft_header(base, sha, owner, branch):
    return "\n".join([
        "SDD DRAFT",
        f"base-title: {base['title']}",
        f"base-id: {base['id']}",
        f"base-sha256: {sha}",
        f"owner: {owner}",
        f"branch: {branch or '-'}",
        "Write your changes below the marker line. The lines above it are not merged.",
        MARKER,
    ])


def parse_draft(content):
    if MARKER not in (content or ""):
        raise DocsError("not an SDD draft (marker line missing)")
    head, body = content.split(MARKER, 1)
    fields = dict(re.findall(r"^(base-title|base-id|base-sha256|owner|branch):\s*(.+?)\s*$", head, re.M))
    for key in ("base-id", "base-sha256"):
        if key not in fields:
            raise DocsError(f"draft header is missing {key}")
    return fields, body


def cmd_draft(args):
    map_path, project_map, _ = context(args)
    base = get_doc(args.doc_id, args.cafile)
    if (base.get("team") or {}).get("id") != project_map["teams"]["baselines"]["id"]:
        raise DocsError("drafts fork accepted (Baselines) documents only")
    owner = owner_name(args)
    branch = args.branch or git_branch()
    title = f"{base['title']} / draft ({owner}{', ' + branch if branch else ''})"
    existing = find_by_title(all_docs(args.cafile), title, project_map["teams"]["delivery"]["id"])
    if existing:
        return {"action": "opened", "id": existing["id"], "title": title, "url": existing.get("url")}
    sha, _ = lp.content_digest(base.get("content"))
    snapshots = map_path.parent / "snapshots"
    snapshots.mkdir(parents=True, exist_ok=True)
    base_file = snapshots / f"{sha}.md"
    if not base_file.exists():
        base_file.write_text(base.get("content") or "", encoding="utf-8", newline="")
    content = draft_header(base, sha, owner, branch) + "\n\n" + (base.get("content") or "")
    created = write(CREATE, {"input": {"teamId": project_map["teams"]["delivery"]["id"], "title": title,
                                       "content": content}}, args.cafile)
    doc = created["documentCreate"]["document"]
    return {"action": "created", "id": doc["id"], "title": doc["title"], "url": doc.get("url"),
            "base": base["title"], "base_sha256": sha}


def load_plan_inputs(args):
    map_path, project_map, _ = context(args)
    draft = get_doc(args.draft_id, args.cafile)
    fields, body = parse_draft(draft.get("content"))
    current = get_doc(fields["base-id"], args.cafile)
    if (current.get("team") or {}).get("id") != project_map["teams"]["baselines"]["id"]:
        raise DocsError("the accepted doc is not in Baselines right now (unlocked?); merge after it is locked")
    current_sha, _ = lp.content_digest(current.get("content"))
    base_file = map_path.parent / "snapshots" / f"{fields['base-sha256']}.md"
    if base_file.exists():
        base_text = base_file.read_text(encoding="utf-8")
    elif current_sha == fields["base-sha256"]:
        base_text = current.get("content") or ""
    else:
        raise DocsError(f"base version {fields['base-sha256'][:12]}… is not in .sdd/snapshots; pull the repo")
    return map_path, draft, fields, body, current, current_sha, base_text


def cmd_merge_plan(args):
    map_path, draft, fields, body, current, current_sha, base_text = load_plan_inputs(args)
    plan = sdd_merge.plan(base_text, body, current.get("content") or "")
    record = {"draft_id": draft["id"], "draft_title": draft.get("title"), "accepted_id": current["id"],
              "accepted_title": current.get("title"), "accepted_sha256": current_sha,
              "base_sha256": fields["base-sha256"], "plan": plan}
    merges = map_path.parent / "merges"
    merges.mkdir(parents=True, exist_ok=True)
    plan_file = merges / f"{draft['id']}.plan.json"
    plan_file.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"plan_file": str(plan_file), "items": len(plan["items"]),
            "conflicts": sum(1 for i in plan["items"] if i["conflict"]),
            "auto_kept_current": plan["auto_kept"], "describe": sdd_merge.describe(plan)}


def cmd_merge_build(args):
    map_path, _, _ = context(args)
    plan_file = map_path.parent / "merges" / f"{args.draft_id}.plan.json"
    if not plan_file.exists():
        raise DocsError("no merge plan for this draft; run merge-plan first")
    record = json.loads(plan_file.read_text(encoding="utf-8"))
    decisions = json.loads(args.decisions)
    merged, summary = sdd_merge.build(record["plan"], decisions)
    out = plan_file.with_name(f"{args.draft_id}.merged.md")
    out.write_text(merged, encoding="utf-8", newline="\n")
    title = record["accepted_title"].replace('"', '\\"')
    return {"merged_file": str(out), "summary": summary, "accepted_title": record["accepted_title"],
            "next": (f'lock.py apply {record["accepted_id"]} --title "{title}" '
                     f'--content-file "{out}" --expect-sha {record["accepted_sha256"]}')}


def cmd_draft_close(args):
    draft = get_doc(args.draft_id, args.cafile)
    parse_draft(draft.get("content"))
    title = STATUS_SUFFIX.sub("", draft.get("title", ""))
    new_title = f"{title} ({args.status})"
    write(UPDATE, {"id": draft["id"], "input": {"title": new_title}}, args.cafile)
    after = get_doc(draft["id"], args.cafile)
    return {"action": "closed", "id": draft["id"], "title": after.get("title"),
            "verified": after.get("title") == new_title}


COMMANDS = {"branch-open": cmd_branch_open, "branch-close": cmd_branch_close, "branches": cmd_branches,
            "draft": cmd_draft, "merge-plan": cmd_merge_plan, "merge-build": cmd_merge_build,
            "draft-close": cmd_draft_close}


def main(argv=None):
    parser = argparse.ArgumentParser(description="SDD branch docs and draft merges (Delivery only).")
    parser.add_argument("--cafile", default=None)
    parser.add_argument("--project-map", default=None)
    parser.add_argument("--project", default=None, help="title prefix; defaults to doc_prefix in the map")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("branch-open")
    p.add_argument("--branch")
    p.add_argument("--owner")
    p.add_argument("--pr")
    p = sub.add_parser("branch-close")
    p.add_argument("--branch")
    p.add_argument("--status", required=True, choices=["merged", "abandoned"])
    p.add_argument("--merge-commit")
    sub.add_parser("branches")
    p = sub.add_parser("draft")
    p.add_argument("doc_id")
    p.add_argument("--owner")
    p.add_argument("--branch")
    p = sub.add_parser("merge-plan")
    p.add_argument("draft_id")
    p = sub.add_parser("merge-build")
    p.add_argument("draft_id")
    p.add_argument("--decisions", required=True, help='JSON, e.g. {"1": "keep", "2": {"edit": "text"}}')
    p = sub.add_parser("draft-close")
    p.add_argument("draft_id")
    p.add_argument("--status", required=True, choices=["merged", "partly-merged", "rejected"])
    args = parser.parse_args(argv)
    try:
        result = COMMANDS[args.command](args)
    except (DocsError, lp.ProbeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
