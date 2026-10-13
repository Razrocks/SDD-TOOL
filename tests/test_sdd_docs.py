import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins" / "sdd" / "scripts"))
import sdd_docs as docs  # noqa: E402
import session_rules  # noqa: E402

DEL, BASE = "team-del", "team-base"
ACCEPTED = {"id": "acc1", "title": "Dice Roller / Requirements v1", "url": "u", "updatedAt": "t",
            "content": "REQ-001 small\n\nREQ-002 quick", "team": {"id": BASE}, "project": None}


class Project:
    def __init__(self, extra=None):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".sdd").mkdir()
        data = {"doc_prefix": "Dice Roller", "teams": {"delivery": {"id": DEL}, "baselines": {"id": BASE}}}
        data.update(extra or {})
        self.map = self.root / ".sdd" / "project-map.json"
        self.map.write_text(json.dumps(data))

    def args(self, *argv):
        return ["--project-map", str(self.map), *argv]


def run(argv, reads=(), writes=(), listing=()):
    reads, writes = list(reads), list(writes)

    def fake_call(query, variables, key_env, cafile=None):
        if "viewer" in query:
            return {"viewer": {"name": "Alex"}}
        return reads.pop(0)

    with mock.patch.object(docs.lp, "call", side_effect=fake_call), \
            mock.patch.object(docs.lp, "post_raw", side_effect=lambda *a, **k: writes.pop(0)) as sender, \
            mock.patch.object(docs, "all_docs", return_value=list(listing)), \
            contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
        code = docs.main(argv)
    return code, out.getvalue(), err.getvalue(), sender


def created(doc_id, title):
    return (200, {"data": {"documentCreate": {"success": True, "document": {"id": doc_id, "title": title, "url": "u"}}}})


class BranchTests(unittest.TestCase):
    def test_branch_open_creates_one_owner_doc(self):
        p = Project()
        code, out, _, sender = run(p.args("branch-open", "--branch", "feature-x"),
                                   writes=[created("b1", "Dice Roller / Branch / feature-x")])
        self.assertEqual(code, 0)
        sent = sender.call_args[0][1]["input"]
        self.assertEqual(sent["title"], "Dice Roller / Branch / feature-x")
        self.assertEqual(sent["teamId"], DEL)
        self.assertIn("Owner: Alex", sent["content"])
        self.assertIn("only Alex", sent["content"])

    def test_branch_open_reuses_existing(self):
        p = Project()
        existing = {"id": "b1", "title": "Dice Roller / Branch / feature-x", "team": {"id": DEL}}
        code, out, _, sender = run(p.args("branch-open", "--branch", "feature-x"), listing=[existing])
        self.assertEqual(json.loads(out)["action"], "opened")
        sender.assert_not_called()

    def test_duplicate_titles_refused(self):
        p = Project()
        dup = {"id": "b1", "title": "Dice Roller / Branch / feature-x", "team": {"id": DEL}}
        code, _, err, _ = run(p.args("branch-open", "--branch", "feature-x"), listing=[dup, dict(dup, id="b2")])
        self.assertEqual(code, 1)
        self.assertIn("fix the duplicate", err)

    def test_branch_close_renames_and_sets_status(self):
        p = Project()
        listing = [{"id": "b1", "title": "Dice Roller / Branch / feature-x", "team": {"id": DEL}}]
        body = {"document": {"id": "b1", "content": "Owner: Alex\nStatus: in progress\n\nnotes"}}
        after = {"document": {"id": "b1", "title": "Dice Roller / Branch / feature-x (merged)"}}
        code, out, _, sender = run(p.args("branch-close", "--branch", "feature-x", "--status", "merged",
                                          "--merge-commit", "abc123"),
                                   reads=[body, after], writes=[(200, {"data": {}})], listing=listing)
        self.assertEqual(code, 0)
        sent = sender.call_args[0][1]["input"]
        self.assertEqual(sent["title"], "Dice Roller / Branch / feature-x (merged)")
        self.assertIn("Status: merged", sent["content"])
        self.assertIn("abc123", sent["content"])
        self.assertTrue(json.loads(out)["verified"])

    def test_branches_lists_status(self):
        p = Project()
        listing = [{"id": "1", "title": "Dice Roller / Branch / a", "team": {"id": DEL}},
                   {"id": "2", "title": "Dice Roller / Branch / b (merged)", "team": {"id": DEL}},
                   {"id": "3", "title": "Pong / Branch / c", "team": {"id": DEL}}]
        _, out, _, _ = run(p.args("branches"), listing=listing)
        rows = json.loads(out)["branches"]
        self.assertEqual([(r["branch"], r["status"]) for r in rows], [("a", "in progress"), ("b", "merged")])


class DraftMergeTests(unittest.TestCase):
    def test_draft_forks_with_header_and_base_snapshot(self):
        p = Project()
        code, out, _, sender = run(p.args("draft", "acc1", "--branch", "feature-x"), reads=[{"document": ACCEPTED}],
                                   writes=[created("dr1", "x")])
        self.assertEqual(code, 0)
        sent = sender.call_args[0][1]["input"]
        self.assertEqual(sent["title"], "Dice Roller / Requirements v1 / draft (Alex, feature-x)")
        fields, body = docs.parse_draft(sent["content"])
        self.assertEqual(fields["base-id"], "acc1")
        sha = docs.lp.content_digest(ACCEPTED["content"])[0]
        self.assertEqual(fields["base-sha256"], sha)
        self.assertEqual(docs.sdd_merge.blocks(body), docs.sdd_merge.blocks(ACCEPTED["content"]))
        self.assertTrue((p.root / ".sdd" / "snapshots" / f"{sha}.md").exists())

    def test_draft_only_from_baselines(self):
        p = Project()
        code, _, err, _ = run(p.args("draft", "acc1"), reads=[{"document": dict(ACCEPTED, team={"id": DEL})}])
        self.assertEqual(code, 1)
        self.assertIn("Baselines", err)

    def test_plan_and_build_end_to_end(self):
        p = Project()
        sha = docs.lp.content_digest(ACCEPTED["content"])[0]
        header = docs.draft_header(ACCEPTED, sha, "Alex", "feature-x")
        draft = {"id": "dr1", "title": "draft", "content": header + "\n\nREQ-001 small\n\nREQ-002 quick, same session"}
        code, out, _, _ = run(p.args("merge-plan", "dr1"), reads=[{"document": draft}, {"document": ACCEPTED}])
        self.assertEqual(code, 0)
        planned = json.loads(out)
        self.assertEqual(planned["items"], 1)
        self.assertEqual(planned["conflicts"], 0)
        code, out, _, _ = run(p.args("merge-build", "dr1", "--decisions", '{"1": "keep"}'))
        built = json.loads(out)
        merged = Path(built["merged_file"]).read_text(encoding="utf-8")
        self.assertIn("same session", merged)
        self.assertIn(f"--expect-sha {sha}", built["next"])
        self.assertIn('lock.py apply acc1 --title "Dice Roller / Requirements v1"', built["next"])

    def test_plan_flags_conflict_after_someone_else_merged(self):
        p = Project()
        base_sha = docs.lp.content_digest(ACCEPTED["content"])[0]
        snapshots = p.root / ".sdd" / "snapshots"
        snapshots.mkdir()
        (snapshots / f"{base_sha}.md").write_text(ACCEPTED["content"], encoding="utf-8")
        current = dict(ACCEPTED, content="REQ-001 small\n\nREQ-002 quick (Sam)")
        header = docs.draft_header(ACCEPTED, base_sha, "Alex", "b")
        draft = {"id": "dr2", "title": "draft", "content": header + "\n\nREQ-001 small\n\nREQ-002 quick (Alex)"}
        code, out, _, _ = run(p.args("merge-plan", "dr2"), reads=[{"document": draft}, {"document": current}])
        planned = json.loads(out)
        self.assertEqual(planned["conflicts"], 1)
        self.assertIn("CONFLICT", planned["describe"])

    def test_plan_refuses_unknown_base_version(self):
        p = Project()
        header = docs.draft_header(ACCEPTED, "f" * 64, "Alex", "b")
        draft = {"id": "dr3", "title": "draft", "content": header + "\n\ntext"}
        code, _, err, _ = run(p.args("merge-plan", "dr3"), reads=[{"document": draft}, {"document": ACCEPTED}])
        self.assertEqual(code, 1)
        self.assertIn("not in .sdd/snapshots", err)

    def test_parse_rejects_non_draft(self):
        with self.assertRaises(docs.DocsError):
            docs.parse_draft("just a doc")


class SessionRulesTests(unittest.TestCase):
    def test_no_context_outside_sdd_projects(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(session_rules.build_context(tmp))

    def test_context_has_rules_with_real_script_paths(self):
        p = Project()
        sub = p.root / "src" / "deep"
        sub.mkdir(parents=True)
        context = session_rules.build_context(sub)
        self.assertIn("SDD project detected", context)
        self.assertIn("doc prefix: Dice Roller", context)
        self.assertNotIn("{SCRIPTS}", context)
        self.assertIn((session_rules.ROOT / "scripts").as_posix(), context)


class FindMapTests(unittest.TestCase):
    def test_walks_up_and_env_override(self):
        p = Project()
        sub = p.root / "a" / "b"
        sub.mkdir(parents=True)
        self.assertEqual(docs.lp.find_project_map(sub), p.map)
        with mock.patch.dict(os.environ, {"SDD_PROJECT_MAP": str(p.map)}):
            self.assertEqual(docs.lp.find_project_map("C:/"), p.map)


if __name__ == "__main__":
    unittest.main()
