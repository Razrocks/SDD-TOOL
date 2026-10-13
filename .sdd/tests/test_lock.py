import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import hook_lock_gate as gate  # noqa: E402
import lock  # noqa: E402

DEL, BASE = "team-del", "team-base"
TITLE = "Dice Roller / Requirements v1"


def doc(team, project=None, title=TITLE):
    return {"id": "d1", "title": title, "url": "u", "updatedAt": "t", "content": "REQ-001",
            "team": {"id": team, "name": team}, "project": project}


def lock_args(title=TITLE, project="Dice Roller", extra=()):
    return ["lock", "d1", "--title", title, "--project", project, *extra]


def run(argv, before, after, mutation=(200, {"data": {"documentUpdate": {"success": True}}})):
    reads = [{"document": before}, {"document": after}]
    with mock.patch.object(lock, "team_ids", return_value=(DEL, BASE)), \
            mock.patch.object(lock.lp, "call", side_effect=reads), \
            mock.patch.object(lock.lp, "post_raw", return_value=mutation) as sender, \
            contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
        code = lock.main(argv)
    return code, out.getvalue(), err.getvalue(), sender


class LockTests(unittest.TestCase):
    def test_lock_moves_delivery_doc_to_baselines_and_verifies(self):
        code, out, _, sender = run(lock_args(), doc(DEL), doc(BASE))
        self.assertEqual(code, 0)
        self.assertEqual(sender.call_args[0][1], {"id": "d1", "input": {"teamId": BASE}})
        self.assertEqual(sender.call_args[0][2], "LINEAR_LOCK_KEY")
        self.assertTrue(json.loads(out)["verified"])

    def test_only_team_change_is_ever_sent(self):
        _, _, _, sender = run(lock_args(), doc(DEL), doc(BASE))
        self.assertEqual(set(sender.call_args[0][1]["input"]), {"teamId"})

    def test_title_must_match_document(self):
        code, _, err, sender = run(lock_args(title="Pong / Requirements v1"), doc(DEL), doc(BASE))
        self.assertEqual(code, 2)
        self.assertIn("does not match", err)
        sender.assert_not_called()

    def test_title_needs_project_prefix(self):
        code, _, err, sender = run(lock_args(title="Requirements v1"), doc(DEL, title="Requirements v1"), doc(BASE))
        self.assertEqual(code, 2)
        self.assertIn("must start with", err)
        sender.assert_not_called()

    def test_lock_refuses_doc_already_in_baselines(self):
        code, _, _, sender = run(lock_args(), doc(BASE), doc(BASE))
        self.assertEqual(code, 2)
        sender.assert_not_called()

    def test_lock_refuses_project_document(self):
        code, _, err, sender = run(lock_args(), doc(DEL, project={"id": "p"}), doc(DEL))
        self.assertEqual(code, 2)
        self.assertIn("project", err)
        sender.assert_not_called()

    def test_fixture_refused_without_flag(self):
        fixture = "TEST-FIXTURE X"
        code, _, _, sender = run(lock_args(title=fixture), doc(DEL, title=fixture), doc(BASE))
        self.assertEqual(code, 2)
        sender.assert_not_called()

    def test_unverified_move_is_a_failure(self):
        code, out, _, _ = run(lock_args(), doc(DEL), doc(DEL))
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(out)["verified"])

    def test_lock_records_in_project_map(self):
        with tempfile.TemporaryDirectory() as tmp:
            map_path = Path(tmp) / "project-map.json"
            map_path.write_text(json.dumps({"schema": "x", "baselines": [{"id": "d1", "status": "unlocked"}]}))
            code, _, _, _ = run(lock_args(extra=["--project-map", str(map_path)]), doc(DEL), doc(BASE))
            rows = json.loads(map_path.read_text())["baselines"]
        self.assertEqual(code, 0)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "locked")
        self.assertEqual(rows[0]["sha256"], lock.lp.content_digest("REQ-001")[0])

    def test_unlock_snapshots_before_moving(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(lock, "SNAPSHOT_DIR", Path(tmp)):
            code, out, _, sender = run(["unlock", "d1", "--title", TITLE], doc(BASE), doc(DEL))
            snap = json.loads(out)["snapshot"]
            saved = Path(snap["path"]).read_text(encoding="utf-8")
        self.assertEqual(code, 0)
        self.assertTrue(saved.endswith("REQ-001"))
        self.assertEqual(snap["sha256"], lock.lp.content_digest("REQ-001")[0])
        self.assertEqual(sender.call_args[0][1]["input"], {"teamId": DEL})

    def test_unlock_refuses_doc_not_in_baselines(self):
        code, _, _, sender = run(["unlock", "d1", "--title", TITLE], doc(DEL), doc(DEL))
        self.assertEqual(code, 2)
        sender.assert_not_called()


class GateTests(unittest.TestCase):
    def reason(self, command):
        return gate.decide({"tool_input": {"command": command}})["hookSpecificOutput"]["permissionDecisionReason"]

    def test_lock_script_triggers_ask(self):
        decision = gate.decide({"tool_input": {"command": "python -I .sdd/scripts/lock.py lock d1"}})
        self.assertEqual(decision["hookSpecificOutput"]["permissionDecision"], "ask")

    def test_prompt_names_action_and_title(self):
        reason = self.reason('python -I .sdd/scripts/lock.py --cafile x lock d1 --title "Dice Roller / Requirements v1" --project "Dice Roller"')
        self.assertIn('LOCK "Dice Roller / Requirements v1" into Baselines', reason)
        reason = self.reason("python lock.py unlock d1 --title 'Pong / Requirements v1'")
        self.assertIn('UNLOCK "Pong / Requirements v1" out of Baselines', reason)

    def test_lock_key_access_triggers_ask(self):
        self.assertIsNotNone(gate.decide({"tool_input": {"command": "echo $env:LINEAR_LOCK_KEY"}}))

    def test_other_commands_pass_through(self):
        self.assertIsNone(gate.decide({"tool_input": {"command": "python -I .sdd/scripts/linear_probe.py baseline"}}))
        self.assertIsNone(gate.decide({}))


if __name__ == "__main__":
    unittest.main()
