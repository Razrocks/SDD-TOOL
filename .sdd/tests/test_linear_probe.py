import contextlib
import io
import json
import os
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

        def fake_urlopen(request, timeout):
            seen["request"] = request
            return FakeResponse(payload or {"data": {}})

        with mock.patch.dict(os.environ, {"LINEAR_READ_KEY": FAKE_KEY}), \
                mock.patch.object(lp.urllib.request, "urlopen", fake_urlopen), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = lp.main(argv)
        return code, out.getvalue(), err.getvalue(), seen.get("request")

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


if __name__ == "__main__":
    unittest.main()
