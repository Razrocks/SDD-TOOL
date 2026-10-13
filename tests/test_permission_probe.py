import contextlib
import io
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins" / "sdd" / "scripts"))
import permission_probe as pp  # noqa: E402

FIXTURE = {"id": "d1", "title": "TEST-FIXTURE DEL-FX", "content": "fixture-v1", "updatedAt": "t",
           "team": {"id": "team-del"}, "project": None, "trashed": None, "archivedAt": None}


def run_quiet(argv):
    with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
        code = pp.main(argv)
    return code, out.getvalue(), err.getvalue()


class ClassifyTests(unittest.TestCase):
    def test_no_errors_is_success(self):
        self.assertEqual(pp.classify(200, {"data": {"documentUpdate": {"success": True}}}), "SUCCESS")

    def test_forbidden_code_is_denial(self):
        payload = {"errors": [{"message": "x", "extensions": {"code": "FORBIDDEN"}}]}
        self.assertEqual(pp.classify(200, payload), "DENIED_AUTH")

    def test_http_403_is_denial(self):
        self.assertEqual(pp.classify(403, {"errors": [{"message": "nope"}]}), "DENIED_AUTH")

    def test_validation_error_is_not_denial(self):
        payload = {"errors": [{"message": "Variable invalid", "extensions": {"code": "GRAPHQL_VALIDATION_FAILED"}}]}
        self.assertEqual(pp.classify(200, payload), "INVALID_REQUEST")

    def test_unknown_error_is_not_denial(self):
        self.assertEqual(pp.classify(200, {"errors": [{"message": "Entity not found"}]}), "ERROR")


class GuardTests(unittest.TestCase):
    def test_requires_confirmation_flag(self):
        code, _, err = run_quiet(["--key-env", "K", "update", "d1", "x"])
        self.assertEqual(code, 2)
        self.assertIn("--confirm-fixture-test", err)

    def test_refuses_non_fixture_target_without_sending(self):
        real = dict(FIXTURE, title="Client A Requirements v1")
        with mock.patch.object(pp, "post", return_value={"document": real}), \
                mock.patch.object(pp, "post_raw") as sender:
            code, _, err = run_quiet(["--key-env", "K", "--confirm-fixture-test", "update", "d1", "x"])
        self.assertEqual(code, 2)
        sender.assert_not_called()

    def test_refuses_non_fixture_create_title(self):
        with mock.patch.object(pp, "post_raw") as sender:
            code, _, _ = run_quiet(["--key-env", "K", "--confirm-fixture-test", "create",
                                    "--team-id", "t", "Real doc", "x"])
        self.assertEqual(code, 2)
        sender.assert_not_called()

    def test_delete_refuses_non_fixture_without_sending(self):
        real = dict(FIXTURE, title="Client A Decisions v1")
        with mock.patch.object(pp, "post", return_value={"document": real}), \
                mock.patch.object(pp, "post_raw") as sender:
            code, _, _ = run_quiet(["--key-env", "K", "--confirm-fixture-test", "delete", "d1"])
        self.assertEqual(code, 2)
        sender.assert_not_called()

    def test_comment_targets_document_content(self):
        fixture = dict(FIXTURE, documentContentId="dc-1")
        with mock.patch.object(pp, "post", side_effect=[{"document": fixture}, {"document": fixture}]), \
                mock.patch.object(pp, "post_raw", return_value=(200, {"data": {}})) as sender:
            code, _, _ = run_quiet(["--key-env", "K", "--confirm-fixture-test", "comment", "d1", "hi"])
        self.assertEqual(code, 0)
        self.assertEqual(sender.call_args[0][1], {"input": {"documentContentId": "dc-1", "body": "hi"}})

    def test_project_create_requires_fixture_name(self):
        with mock.patch.object(pp, "post_raw") as sender:
            code, _, _ = run_quiet(["--key-env", "K", "--confirm-fixture-test", "project-create",
                                    "Client A Portal", "--team-ids", "t1"])
        self.assertEqual(code, 2)
        sender.assert_not_called()

    def test_project_teams_refuses_non_fixture_project(self):
        with mock.patch.object(pp, "post", return_value={"project": {"id": "p", "name": "Real", "teams": {}}}), \
                mock.patch.object(pp, "post_raw") as sender:
            code, _, _ = run_quiet(["--key-env", "K", "--confirm-fixture-test", "project-teams",
                                    "p", "--team-ids", "t1,t2"])
        self.assertEqual(code, 2)
        sender.assert_not_called()

    def test_fixture_update_sent_and_change_detected(self):
        changed = dict(FIXTURE, content="mutated")
        with mock.patch.object(pp, "post", side_effect=[{"document": FIXTURE}, {"document": changed}]), \
                mock.patch.object(pp, "post_raw", return_value=(200, {"data": {"documentUpdate": {"success": True}}})):
            code, out, _ = run_quiet(["--key-env", "K", "--confirm-fixture-test", "update", "d1", "mutated"])
        self.assertEqual(code, 0)
        self.assertIn('"classification": "SUCCESS"', out)
        self.assertIn('"target_unchanged": false', out)


if __name__ == "__main__":
    unittest.main()
