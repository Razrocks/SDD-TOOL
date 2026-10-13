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
import sdd_status as st  # noqa: E402
import session_rules  # noqa: E402

NO_KEYS = {k: v for k, v in os.environ.items()
           if k not in ("LINEAR_READ_KEY", "LINEAR_DRAFTS_KEY", "SDD_PROJECT_MAP", "CLAUDE_PROJECT_DIR",
                        "CLAUDE_CODE_SESSION_ID")}


class Project:
    def __init__(self, optin=None):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".sdd").mkdir()
        self.map = self.root / ".sdd" / "project-map.json"
        self.map.write_text(json.dumps({"doc_prefix": "Dice Roller", "teams": {"baselines": {"id": "b"},
                                                                                "delivery": {"id": "d"}}}))
        self.status = self.root / ".sdd" / "status.json"
        if optin:
            session_rules.set_optin(self.map, optin)


def status_for(session_id, **extra):
    data = {"session_id": session_id, "generated_at": "now", "prefix": "Dice Roller", "problems": [],
            "audit": "CLEAN", "accepted": [{"id": "a", "title": "Dice Roller / Requirements v3",
                                             "sha256": "dfa2b2ce" + "0" * 56, "state": "unchanged"}],
            "branch": "main", "branch_doc": None, "handoff": None}
    data.update(extra)
    return data


class HelperTests(unittest.TestCase):
    def test_latest_handoff_takes_first_dated_section_only(self):
        doc = ("# Dice Roller / Branch / feature-a\nOwner: Alex\n\n## 2026-10-12 handoff\nDid X.\nNext: Y.\n\n"
               "## 2026-10-11 handoff\nOlder.\n")
        self.assertEqual(st.latest_handoff(doc), "## 2026-10-12 handoff\nDid X.\nNext: Y.")
        self.assertIsNone(st.latest_handoff("no dates here"))
        self.assertTrue(st.latest_handoff("## 2026-10-12\n" + "x" * 900, limit=50).endswith(" …"))

    def test_compare_baselines_marks_new_changed_unchanged(self):
        rows = [{"id": "1", "sha256": "aa"}, {"id": "2", "sha256": "bb"}, {"id": "3", "sha256": "cc"}]
        recorded = [{"id": "1", "sha256": "aa"}, {"id": "2", "sha256": "old"}]
        self.assertEqual([r["state"] for r in st.compare_baselines(rows, recorded)], ["unchanged", "changed", "new"])

    def test_summary_flags_changes_and_problems(self):
        text = st.summarize(status_for("s", problems=["Linear keys missing: LINEAR_DRAFTS_KEY."],
                                       accepted=[{"title": "T", "sha256": "12345678abc", "state": "changed"}]))
        self.assertIn("ATTENTION: Linear keys missing", text)
        self.assertIn("CHANGED since last recorded", text)


class OptInGateTests(unittest.TestCase):
    def test_refresh_does_nothing_until_opted_in(self):
        for state in (None, "later", "off"):
            p = Project(state)
            with mock.patch.dict(os.environ, NO_KEYS, clear=True), \
                    mock.patch.object(st.lp, "paginate", side_effect=AssertionError("contacted Linear")):
                self.assertIsNone(st.refresh("s1", p.root))
            self.assertFalse(p.status.exists())

    def test_refresh_when_on_reports_missing_keys_without_calling_linear(self):
        p = Project("on")
        with mock.patch.dict(os.environ, NO_KEYS, clear=True), \
                mock.patch.object(st.lp, "paginate", side_effect=AssertionError("contacted Linear")):
            status = st.refresh("s1", p.root)
        self.assertIn("LINEAR_READ_KEY", status["problems"][0])
        self.assertEqual(json.loads(p.status.read_text(encoding="utf-8"))["session_id"], "s1")

    def test_inject_only_when_on_once_per_session(self):
        p = Project("on")
        p.status.write_text(json.dumps(status_for("s1")), encoding="utf-8")
        self.assertIsNone(st.inject("other-session", p.root))          # status not for this session yet
        self.assertIn("Dice Roller / Requirements v3", st.inject("s1", p.root))
        self.assertIsNone(st.inject("s1", p.root))                     # already shown
        session_rules.set_optin(p.map, "off")
        (p.root / ".sdd" / ".status-shown.json").unlink()
        self.assertIsNone(st.inject("s1", p.root))


class OptInCommandTests(unittest.TestCase):
    def run_main(self, *argv, cwd):
        env = dict(NO_KEYS, CLAUDE_PROJECT_DIR=str(cwd))
        with mock.patch.dict(os.environ, env, clear=True), contextlib.redirect_stdout(io.StringIO()) as out:
            code = st.main(list(argv))
        return code, out.getvalue()

    def test_off_and_later_record_choice(self):
        p = Project()
        code, out = self.run_main("optin", "off", cwd=p.root)
        self.assertEqual((code, session_rules.optin_state(p.map)), (0, "off"))
        self.assertIn("/sdd:on", out)
        self.run_main("optin", "later", cwd=p.root)
        self.assertEqual(session_rules.optin_state(p.map), "later")

    def test_on_returns_rules_and_status_and_marks_shown(self):
        p = Project()
        fake = status_for("manual")
        with mock.patch.object(st, "refresh", return_value=fake):
            code, out = self.run_main("optin", "on", cwd=p.root)
        self.assertEqual((code, session_rules.optin_state(p.map)), (0, "on"))
        self.assertIn("# SDD workflow", out)
        self.assertIn("Dice Roller / Requirements v3", out)
        self.assertIn("manual", json.loads((p.root / ".sdd" / ".status-shown.json").read_text(encoding="utf-8")))

    def test_on_still_succeeds_when_linear_check_fails(self):
        p = Project()
        with mock.patch.object(st, "refresh", side_effect=st.lp.ProbeError("offline")):
            code, out = self.run_main("optin", "on", cwd=p.root)
        self.assertEqual((code, session_rules.optin_state(p.map)), (0, "on"))
        self.assertIn("run /sdd:resume", out)

    def test_output_survives_a_cp1252_console(self):
        console = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        with contextlib.redirect_stdout(console):
            st.say("Implemented ≠ tested — title 文書 …")
        console.flush()
        self.assertEqual(console.buffer.getvalue().decode("cp1252").strip(), "Implemented != tested - title ?? ...")

    def test_bad_choice_and_no_project(self):
        p = Project()
        self.assertEqual(self.run_main("optin", "maybe", cwd=p.root)[0], 2)
        with tempfile.TemporaryDirectory() as empty:
            code, out = self.run_main("optin", "on", cwd=empty)
        self.assertIn("isn't set up for SDD", out)


if __name__ == "__main__":
    unittest.main()
