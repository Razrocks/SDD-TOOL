import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins" / "sdd" / "scripts"))
import hook_lock_gate as gate  # noqa: E402
import lock  # noqa: E402

DEL, BASE = "team-del", "team-base"
TITLE = "Dice Roller / Requirements v1"
OK = (200, {"data": {"documentUpdate": {"success": True}}})


def doc(team, project=None, title=TITLE, content="REQ-001"):
    return {"id": "d1", "title": title, "url": "u", "updatedAt": "t", "content": content,
            "team": {"id": team, "name": team}, "project": project}


class LockTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        (root / ".sdd").mkdir()
        self.map_path = root / ".sdd" / "project-map.json"
        self.map_path.write_text(json.dumps({"teams": {"delivery": {"id": DEL}, "baselines": {"id": BASE}}}))

    def tearDown(self):
        self._tmp.cleanup()

    def run_lock(self, argv, before, after, mutation=OK):
        reads = [{"document": before}, {"document": after}]
        with mock.patch.object(lock.lp, "call", side_effect=reads), \
                mock.patch.object(lock.lp, "post_raw", return_value=mutation) as sender, \
                contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
            code = lock.main(["--project-map", str(self.map_path), *argv])
        return code, out.getvalue(), err.getvalue(), sender

    def lock_args(self, title=TITLE, project="Dice Roller"):
        return ["lock", "d1", "--title", title, "--project", project]

    def baselines_rows(self):
        return json.loads(self.map_path.read_text())["baselines"]

    def test_lock_moves_and_records_with_snapshot(self):
        code, out, _, sender = self.run_lock(self.lock_args(), doc(DEL), doc(BASE))
        self.assertEqual(code, 0)
        self.assertEqual(sender.call_args[0][1], {"id": "d1", "input": {"teamId": BASE}})
        self.assertEqual(sender.call_args[0][2], "LINEAR_LOCK_KEY")
        result = json.loads(out)
        self.assertTrue(result["verified"])
        snap = Path(result["snapshot_after"]["path"])
        self.assertEqual(snap.name, f"{lock.lp.content_digest('REQ-001')[0]}.md")
        self.assertEqual(snap.read_text(encoding="utf-8"), "REQ-001")
        self.assertEqual(self.baselines_rows()[0]["status"], "locked")

    def test_title_must_match_and_have_prefix(self):
        code, _, err, sender = self.run_lock(self.lock_args(title="Pong / X"), doc(DEL), doc(BASE))
        self.assertEqual(code, 2)
        self.assertIn("does not match", err)
        code, _, err, sender = self.run_lock(self.lock_args(title="Reqs"), doc(DEL, title="Reqs"), doc(BASE))
        self.assertEqual(code, 2)
        self.assertIn("must start with", err)
        sender.assert_not_called()

    def test_lock_refuses_project_doc_and_wrong_team(self):
        code, _, _, sender = self.run_lock(self.lock_args(), doc(DEL, project={"id": "p"}), doc(DEL))
        self.assertEqual(code, 2)
        code, _, _, sender = self.run_lock(self.lock_args(), doc(BASE), doc(BASE))
        self.assertEqual(code, 2)
        sender.assert_not_called()

    def test_unverified_move_fails(self):
        code, out, _, _ = self.run_lock(self.lock_args(), doc(DEL), doc(DEL))
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(out)["verified"])

    def test_unlock_snapshots_before_moving(self):
        code, out, _, sender = self.run_lock(["unlock", "d1", "--title", TITLE], doc(BASE), doc(DEL))
        result = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(result["snapshot_before"]["reason"], "before unlock")
        self.assertEqual(sender.call_args[0][1]["input"], {"teamId": DEL})
        self.assertEqual(self.baselines_rows()[0]["status"], "unlocked")

    def test_apply_writes_merge_with_sha_guard(self):
        merged = Path(self._tmp.name) / "merged.md"
        merged.write_text("REQ-001\n\nREQ-002 new\n", encoding="utf-8")
        sha = lock.lp.content_digest("REQ-001")[0]
        argv = ["apply", "d1", "--title", TITLE, "--content-file", str(merged), "--expect-sha", sha]
        code, out, _, sender = self.run_lock(argv, doc(BASE), doc(BASE, content="REQ-001\n\nREQ-002 new"))
        result = json.loads(out)
        self.assertEqual(code, 0)
        self.assertTrue(result["verified"])
        self.assertEqual(set(sender.call_args[0][1]["input"]), {"content"})
        self.assertEqual(result["snapshot_before"]["sha256"], sha)
        self.assertEqual(self.baselines_rows()[0]["previous_sha256"], sha)

    def test_apply_refuses_if_doc_changed_since_plan(self):
        merged = Path(self._tmp.name) / "merged.md"
        merged.write_text("x", encoding="utf-8")
        argv = ["apply", "d1", "--title", TITLE, "--content-file", str(merged), "--expect-sha", "0" * 64]
        code, _, err, sender = self.run_lock(argv, doc(BASE), doc(BASE))
        self.assertEqual(code, 2)
        self.assertIn("changed since the merge was planned", err)
        sender.assert_not_called()

    def test_apply_unverified_when_readback_differs(self):
        merged = Path(self._tmp.name) / "merged.md"
        merged.write_text("REQ-009", encoding="utf-8")
        sha = lock.lp.content_digest("REQ-001")[0]
        argv = ["apply", "d1", "--title", TITLE, "--content-file", str(merged), "--expect-sha", sha]
        code, out, _, _ = self.run_lock(argv, doc(BASE), doc(BASE, content="REQ-001"))
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(out)["verified"])

    def test_missing_project_map_refused(self):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            code = lock.main(["--project-map", str(Path(self._tmp.name) / "nope.json"), *self.lock_args()])
        self.assertEqual(code, 2)
        self.assertIn("project-map", err.getvalue())


class GateTests(unittest.TestCase):
    def reason(self, command):
        return gate.decide({"tool_input": {"command": command}})["hookSpecificOutput"]["permissionDecisionReason"]

    def test_prompt_names_action_and_title(self):
        self.assertIn('LOCK "Dice Roller / Requirements v1" into Baselines',
                      self.reason('python lock.py lock d1 --title "Dice Roller / Requirements v1" --project "Dice Roller"'))
        self.assertIn('UNLOCK "Pong / Requirements v1"', self.reason("python lock.py unlock d1 --title 'Pong / Requirements v1'"))
        self.assertIn('APPLY "Dice Roller / Requirements v1"',
                      self.reason('python lock.py apply d1 --title "Dice Roller / Requirements v1" --content-file m.md --expect-sha x'))

    def test_lock_key_access_triggers_ask(self):
        self.assertIsNotNone(gate.decide({"tool_input": {"command": "echo $env:LINEAR_LOCK_KEY"}}))

    def test_other_commands_pass_through(self):
        self.assertIsNone(gate.decide({"tool_input": {"command": "python sdd_docs.py merge-plan d1"}}))
        self.assertIsNone(gate.decide({}))


if __name__ == "__main__":
    unittest.main()
