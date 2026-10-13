import contextlib
import io
import json
import os
import ssl
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import linear_probe as lp  # noqa: E402

FAKE_KEY = "lin_api_TESTVALUE_not_real"


class FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class ProbeTests(unittest.TestCase):
    def run_main(self, argv, payload=None):
        out, err = io.StringIO(), io.StringIO()
        seen = {}

        def fake_urlopen(request, timeout, context=None):
            seen["request"] = request
            seen["context"] = context
            return FakeResponse(payload or {"data": {}})

        with mock.patch.dict(os.environ, {"LINEAR_READ_KEY": FAKE_KEY}), \
                mock.patch.object(lp.urllib.request, "urlopen", fake_urlopen), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = lp.main(argv)
        self.last_context = seen.get("context")
        return code, out.getvalue(), err.getvalue(), seen.get("request")

    def test_default_uses_system_trust(self):
        self.run_main(["whoami"])
        self.assertIsNone(self.last_context)

    def test_cafile_keeps_verification_on(self):
        real_context = ssl.create_default_context()
        with mock.patch.object(lp.ssl, "create_default_context", return_value=real_context) as factory:
            self.run_main(["--cafile", "bundle.pem", "whoami"])
        factory.assert_called_once_with(cafile="bundle.pem")
        self.assertIs(self.last_context, real_context)
        self.assertEqual(self.last_context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(self.last_context.check_hostname)

    def test_mutation_query_refused(self):
        with self.assertRaises(lp.ProbeError):
            lp.call("mutation { documentDelete(id: \"x\") { success } }", {}, "LINEAR_READ_KEY")

    def test_all_builtin_queries_are_reads(self):
        for name, query in lp.QUERIES.items():
            self.assertFalse(query.lstrip().lower().startswith("mutation"), name)

    def test_missing_key_exits_2(self):
        env = {k: v for k, v in os.environ.items() if k != "LINEAR_READ_KEY"}
        with mock.patch.dict(os.environ, env, clear=True), \
                contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                lp.main(["whoami"])
        self.assertEqual(ctx.exception.code, 2)

    def test_graphql_errors_inside_http_200_are_failures(self):
        payload = {"data": None, "errors": [{"message": "Forbidden", "extensions": {"code": "FORBIDDEN"}}]}
        code, out, err, _ = self.run_main(["whoami"], payload)
        self.assertEqual(code, 1)
        self.assertIn("FORBIDDEN", err)

    def test_key_sent_in_header_never_printed(self):
        payload = {"data": {"viewer": {"id": "u1", "name": "n"}, "organization": {"id": "o1", "name": "W", "urlKey": "w"}}}
        code, out, err, request = self.run_main(["whoami"], payload)
        self.assertEqual(code, 0)
        self.assertEqual(request.get_header("Authorization"), FAKE_KEY)
        self.assertNotIn(FAKE_KEY, out + err)

    def test_doc_without_content_does_not_request_body(self):
        _, _, _, request = self.run_main(["doc", "abc"], {"data": {"document": None}})
        sent = json.loads(request.data.decode("utf-8"))
        self.assertNotIn("content", sent["query"])
        self.assertEqual(sent["variables"], {"id": "abc"})


class BaselineTests(unittest.TestCase):
    BASE = "team-base"

    def test_accepted_set_rules(self):
        docs = [
            {"id": "a", "title": "Pong Requirements v1", "team": {"id": self.BASE}, "project": None},
            {"id": "f", "title": "TEST-FIXTURE BASE-FX", "team": {"id": self.BASE}, "project": None},
            {"id": "p", "title": "In a project", "team": {"id": self.BASE}, "project": {"id": "x"}},
            {"id": "t", "title": "Trashed", "team": {"id": self.BASE}, "project": None, "trashed": True},
            {"id": "d", "title": "Draft", "team": {"id": "team-del"}, "project": None},
        ]
        accepted, fixtures = lp.accepted_set(docs, self.BASE)
        self.assertEqual([d["id"] for d in accepted], ["a"])
        self.assertEqual([d["id"] for d in fixtures], ["f"])

    def test_digest_is_sha256_of_utf8_body(self):
        import hashlib
        digest, size = lp.content_digest("héllo")
        self.assertEqual(digest, hashlib.sha256("héllo".encode("utf-8")).hexdigest())
        self.assertEqual(size, 6)
        self.assertEqual(lp.content_digest(None)[1], 0)

    def test_baseline_lists_accepted_with_digest(self):
        listing = {"documents": {"nodes": [
            {"id": "a", "title": "Req v1", "url": "u", "updatedAt": "t", "team": {"id": self.BASE}, "project": None}],
            "pageInfo": {"hasNextPage": False, "endCursor": None}}}

        def fake_call(query, variables, key_env, cafile=None):
            if "documents(" in query:
                return listing
            return {"document": {"id": "a", "content": "REQ-001"}}

        with mock.patch.object(lp, "call", fake_call), contextlib.redirect_stdout(io.StringIO()) as out:
            code = lp.main(["baseline", "--baselines-team-id", self.BASE])
        self.assertEqual(code, 0)
        result = json.loads(out.getvalue())
        self.assertEqual(result["accepted"][0]["sha256"], lp.content_digest("REQ-001")[0])

    def test_snapshot_writes_body_and_digest(self):
        import tempfile
        doc = {"id": "a", "title": "Req v1", "url": "u", "updatedAt": "t", "content": "REQ-001 text",
               "team": {"id": self.BASE, "name": "Baselines"}, "project": None}
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(lp, "call", return_value={"document": doc}), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            code = lp.main(["snapshot", "a", "--out", tmp])
            result = json.loads(out.getvalue())
            saved = Path(result["saved"]).read_text(encoding="utf-8")
        self.assertEqual(code, 0)
        self.assertTrue(saved.endswith("REQ-001 text"))
        self.assertIn(lp.content_digest("REQ-001 text")[0], saved)
        self.assertEqual(result["team"], "Baselines")


class AuditTests(unittest.TestCase):
    BASE = "team-base"

    def project(self, pid, *teams):
        return {"id": pid, "name": pid, "teams": {"nodes": [{"id": t} for t in teams]}}

    def test_clean_workspace_has_no_findings(self):
        projects = [self.project("p1", "team-del")]
        docs = [{"id": "d1", "team": {"id": self.BASE}, "project": None},
                {"id": "d2", "team": None, "project": {"id": "p1"}}]
        findings, team_docs, info = lp.find_violations(projects, docs, self.BASE)
        self.assertEqual(findings, [])
        self.assertEqual(team_docs, 1)
        self.assertEqual(info, [])

    def test_trashed_linked_project_is_info_not_finding(self):
        projects = [dict(self.project("p-cross", "team-del", self.BASE), trashed=True)]
        docs = [{"id": "d9", "team": None, "project": {"id": "p-cross"}}]
        findings, _, info = lp.find_violations(projects, docs, self.BASE)
        self.assertEqual(findings, [])
        self.assertEqual(info[0]["kind"], "inactive_project_linked_to_baselines")

    def test_archived_baselines_document_not_counted(self):
        docs = [{"id": "d1", "team": {"id": self.BASE}, "project": None, "archivedAt": "2026-10-12T00:00:00Z"}]
        _, team_docs, _ = lp.find_violations([], docs, self.BASE)
        self.assertEqual(team_docs, 0)

    def test_project_linked_to_baselines_flagged_with_its_documents(self):
        projects = [self.project("p-cross", "team-del", self.BASE)]
        docs = [{"id": "d9", "team": None, "project": {"id": "p-cross"}}]
        kinds = sorted(f["kind"] for f in lp.find_violations(projects, docs, self.BASE)[0])
        self.assertEqual(kinds, ["document_in_baselines_linked_project", "project_linked_to_baselines"])

    def test_baselines_document_attached_to_project_flagged(self):
        docs = [{"id": "d3", "team": {"id": self.BASE}, "project": {"id": "p-other"}}]
        findings, _, _ = lp.find_violations([], docs, self.BASE)
        self.assertEqual(findings[0]["kind"], "baselines_document_attached_to_project")

    def test_audit_exit_code_3_on_findings(self):
        pages = {
            "projects": {"nodes": [self.project("p-cross", self.BASE)], "pageInfo": {"hasNextPage": False, "endCursor": None}},
            "documents": {"nodes": [], "pageInfo": {"hasNextPage": False, "endCursor": None}},
        }

        def fake_call(query, variables, key_env, cafile=None):
            return {"projects": pages["projects"]} if "projects(" in query else {"documents": pages["documents"]}

        with mock.patch.object(lp, "call", fake_call), contextlib.redirect_stdout(io.StringIO()) as out:
            code = lp.main(["audit", "--baselines-team-id", self.BASE])
        self.assertEqual(code, 3)
        self.assertIn('"result": "FINDINGS"', out.getvalue())


if __name__ == "__main__":
    unittest.main()
