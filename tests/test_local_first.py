"""Docs are edited as local files, then sent to Linear (pull -> edit -> push)."""
import contextlib
import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins" / "sdd" / "scripts"))
import hook_doc_writes  # noqa: E402
import sdd_docs as docs  # noqa: E402
import sdd_merge  # noqa: E402
import sdd_status  # noqa: E402
import session_rules  # noqa: E402
from test_sdd_docs import ACCEPTED, BASE, DEL, Project, created, run  # noqa: E402

MINE = {"id": "u1", "name": "Alex"}
WORK = {"id": "w1", "title": "Dice Roller / Notes / ideas", "url": "u", "content": "Intro\n\n- one\n- two",
        "team": {"id": DEL}, "creator": MINE}


def doc(**changes):
    return {"document": dict(WORK, **changes)}


def updated(content):
    return (200, {"data": {"documentUpdate": {"success": True, "document": {"id": "w1", "title": WORK["title"],
                                                                             "url": "u"}}}})


def pulled(p, content=WORK["content"]):
    code, out, err, _ = run(p.args("pull", "w1"), reads=[doc(content=content)])
    assert code == 0, err
    return Path(json.loads(out)["file"])


def state(p):
    return {row["id"]: row["state"] for row in docs.work_status(p.map)}["w1"]


class PullPushTests(unittest.TestCase):
    def test_pull_makes_a_local_copy(self):
        p = Project()
        local = pulled(p)
        self.assertEqual(local.name, "dice-roller--notes--ideas.md")
        self.assertEqual(local.read_text(encoding="utf-8"), WORK["content"])
        self.assertEqual(state(p), "clean")

    def test_push_sends_local_edits_and_verifies_readback(self):
        p = Project()
        local = pulled(p)
        local.write_text("Intro\n\n- one\n- two\n- three", encoding="utf-8")
        self.assertEqual(state(p), "edited")
        linear_style = "Intro\n\n* one\n* two\n* three"                  # Linear rewrites bullets
        code, out, err, sender = run(p.args("push", "w1"), reads=[doc(), doc(content=linear_style)],
                                     writes=[updated(linear_style)])
        self.assertEqual(code, 0, err)
        self.assertTrue(json.loads(out)["verified"])
        self.assertIn("- three", sender.call_args[0][1]["input"]["content"])
        self.assertEqual(local.read_text(encoding="utf-8"), linear_style)
        self.assertEqual(state(p), "clean")

    def test_nothing_to_push_needs_no_linear(self):
        p = Project()
        pulled(p)
        code, out, _, sender = run(p.args("push", "w1"))
        self.assertEqual(json.loads(out)["action"], "nothing to push")
        sender.assert_not_called()

    def test_push_refuses_someone_elses_doc(self):
        p = Project()
        local = pulled(p)
        local.write_text("changed", encoding="utf-8")
        code, _, err, sender = run(p.args("push", "w1"), reads=[doc(creator={"id": "u2", "name": "Sam"})])
        self.assertEqual(code, 1)
        self.assertIn("not your doc (owner: Sam)", err)
        sender.assert_not_called()

    def test_push_refuses_if_linear_changed_then_pull_merges_without_overlap(self):
        p = Project()
        local = pulled(p)
        local.write_text("Intro\n\n- one\n- two!", encoding="utf-8")
        theirs = "Intro, updated in Linear\n\n- one\n- two"
        code, _, err, sender = run(p.args("push", "w1"), reads=[doc(content=theirs)])
        self.assertEqual(code, 1)
        self.assertIn("changed in Linear since your pull", err)
        sender.assert_not_called()
        code, out, _, _ = run(p.args("pull", "w1"), reads=[doc(content=theirs)])
        self.assertEqual(json.loads(out)["action"], "merged")
        text = local.read_text(encoding="utf-8")
        self.assertIn("updated in Linear", text)
        self.assertIn("two!", text)
        code, out, err, _ = run(p.args("push", "w1"), reads=[doc(content=theirs), doc(content=text)],
                                writes=[updated(text)])
        self.assertTrue(json.loads(out)["verified"], err)

    def test_overlap_leaves_linear_copy_and_allows_push_after_reconciling(self):
        p = Project()
        local = pulled(p)
        local.write_text("Intro\n\n- one\n- two (mine)", encoding="utf-8")
        theirs = "Intro\n\n- one\n- two (theirs)"
        code, out, _, _ = run(p.args("pull", "w1"), reads=[doc(content=theirs)])
        result = json.loads(out)
        self.assertEqual(result["action"], "conflict")
        self.assertIn("CONFLICT", result["describe"])
        self.assertEqual(Path(result["linear_copy"]).read_text(encoding="utf-8"), theirs)
        self.assertIn("mine", local.read_text(encoding="utf-8"))          # nothing overwritten
        self.assertEqual(state(p), "conflict")
        local.write_text("Intro\n\n- one\n- two (mine and theirs)", encoding="utf-8")
        final = local.read_text(encoding="utf-8")
        code, out, err, _ = run(p.args("push", "w1"), reads=[doc(content=theirs), doc(content=final)],
                                writes=[updated(final)])
        self.assertTrue(json.loads(out)["verified"], err)
        self.assertFalse(Path(result["linear_copy"]).exists())
        self.assertEqual(state(p), "clean")

    def test_unverified_push_keeps_the_local_file(self):
        p = Project()
        local = pulled(p)
        local.write_text("Intro\n\n- one\n- two\n- three", encoding="utf-8")
        code, out, _, _ = run(p.args("push", "w1"), reads=[doc(), doc(content="Intro")], writes=[updated("x")])
        result = json.loads(out)
        self.assertFalse(result["verified"])
        self.assertIn("three", local.read_text(encoding="utf-8"))
        code, out, err, _ = run(p.args("push", "w1"), reads=[doc(content="Intro"), doc(content="Intro\n\n- one\n- two\n- three")],
                                writes=[updated("x")])
        self.assertTrue(json.loads(out)["verified"], err)               # retry allowed over our own write

    def test_docs_inside_a_delivery_project_can_be_pushed(self):
        p = Project()
        in_project = {"team": None, "project": {"id": "pr1", "teams": {"nodes": [{"id": DEL}]}}}
        code, out, _, _ = run(p.args("pull", "w1"), reads=[doc(**in_project)])
        local = Path(json.loads(out)["file"])
        local.write_text("Intro\n\n- one", encoding="utf-8")
        code, out, err, _ = run(p.args("push", "w1"), reads=[doc(**in_project), doc(content="Intro\n\n- one", **in_project)],
                                writes=[updated("x")])
        self.assertTrue(json.loads(out)["verified"], err)

    def test_pull_refuses_accepted_docs(self):
        p = Project()
        code, _, err, _ = run(p.args("pull", "acc1"), reads=[{"document": dict(ACCEPTED, creator=MINE)}])
        self.assertEqual(code, 1)
        self.assertIn("through a draft", err)

    def test_merge_plan_waits_for_unpushed_draft_edits(self):
        p = Project()
        local = pulled(p)
        local.write_text("edited", encoding="utf-8")
        code, _, err, _ = run(p.args("merge-plan", "w1"))
        self.assertEqual(code, 1)
        self.assertIn("push w1", err)


class NewDocTests(unittest.TestCase):
    def test_new_doc_from_local_file(self):
        p = Project()
        source = p.root / "spec.md"
        source.write_text("# API\n\n- GET /roll", encoding="utf-8")
        readback = dict(WORK, id="n1", title="Dice Roller / Specs / API", content="# API\n\n* GET /roll")
        code, out, err, sender = run(p.args("new", "Dice Roller / Specs / API", "--from-file", str(source)),
                                     reads=[{"document": readback}], writes=[created("n1", "Dice Roller / Specs / API")])
        self.assertEqual(code, 0, err)
        result = json.loads(out)
        self.assertTrue(result["verified"])
        self.assertEqual(sender.call_args[0][1]["input"]["teamId"], DEL)
        self.assertEqual(Path(result["file"]).name, "dice-roller--specs--api.md")

    def test_new_doc_needs_prefix_and_unique_title(self):
        p = Project()
        code, _, err, _ = run(p.args("new", "Specs / API"))
        self.assertIn('"Dice Roller / <optional path> / <name>"', err)
        code, _, err, _ = run(p.args("new", "Dice Roller / Notes / ideas"), listing=[WORK])
        self.assertIn("already exists", err)


class GuardTests(unittest.TestCase):
    def test_comparable_ignores_linear_reformatting(self):
        self.assertEqual(sdd_merge.comparable("Run `x`\n\n- a\n- see roll.py  "),
                         sdd_merge.comparable("Run `x`\n\n* a\n* see [roll.py](<http://roll.py>)"))
        self.assertNotEqual(sdd_merge.comparable("- a"), sdd_merge.comparable("- b"))

    def test_hook_blocks_direct_doc_writes_only_when_sdd_is_on(self):
        p = Project()
        call = {"tool_name": "mcp__plugin_sdd_linear-drafts__save_document", "cwd": str(p.root)}
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertIsNone(hook_doc_writes.decide(call))              # not opted in: untouched
            session_rules.set_optin(p.map, "on")
            decision = hook_doc_writes.decide(call)["hookSpecificOutput"]
            self.assertEqual(decision["permissionDecision"], "deny")
            self.assertIn("sdd_docs.py\" pull", decision["permissionDecisionReason"])
            self.assertIsNone(hook_doc_writes.decide(dict(call, tool_name="mcp__linear-drafts__save_comment")))

    def test_session_status_lists_unpushed_edits(self):
        p = Project()
        local = pulled(p)
        local.write_text("edited", encoding="utf-8")
        session_rules.set_optin(p.map, "on")
        env = {k: v for k, v in os.environ.items()
               if k not in ("LINEAR_READ_KEY", "LINEAR_DRAFTS_KEY", "SDD_PROJECT_MAP", "CLAUDE_PROJECT_DIR")}
        with mock.patch.dict(os.environ, env, clear=True):
            status = sdd_status.refresh("s1", p.root)
        text = sdd_status.summarize(status)
        self.assertIn("Dice Roller / Notes / ideas - edited locally, not in Linear yet", text)
        self.assertIn("push w1", text)


if __name__ == "__main__":
    unittest.main()
