import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import verify_snapshot as vs  # noqa: E402

BODY = b"fixture-v1 requirement text\n"


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "docs").mkdir()
        (self.root / "docs" / "a.md").write_bytes(BODY)

    def tearDown(self):
        self._tmp.cleanup()

    def entry(self, **overrides):
        item = {
            "path": "docs/a.md",
            "sha256": hashlib.sha256(BODY).hexdigest(),
            "bytes": len(BODY),
            "linear_id": "doc-1",
            "updated_at": "2026-10-11T10:00:00Z",
            "fetched_at": "2026-10-11T10:05:00+00:00",
        }
        item.update(overrides)
        return item

    def write(self, files=None, raw=None, **top):
        manifest = {
            "schema": vs.SCHEMA,
            "created_at": "2026-10-11T10:06:00Z",
            "complete": True,
            "scope": "test",
            "files": files if files is not None else [self.entry()],
        }
        manifest.update(top)
        path = self.root / "manifest.json"
        path.write_text(raw if raw is not None else json.dumps(manifest), encoding="utf-8")
        return path

    def errors(self, path):
        return vs.verify(path)[0]

    def assertRejected(self, path, fragment):
        errs = self.errors(path)
        self.assertTrue(any(fragment in e for e in errs), f"expected {fragment!r} in {errs}")

    def test_valid_manifest_passes(self):
        errs, warns = vs.verify(self.write())
        self.assertEqual(errs, [])
        self.assertEqual(warns, [])

    def test_partial_export_is_flagged_not_hidden(self):
        errs, warns = vs.verify(self.write(complete=False))
        self.assertEqual(errs, [])
        self.assertTrue(any("PARTIAL" in w for w in warns))

    def test_partial_flag_printed_by_main(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = vs.main([str(self.write(complete=False))])
        self.assertEqual(code, 0)
        self.assertIn("PARTIAL", out.getvalue())
        self.assertIn("does not prove export completeness", out.getvalue())

    def test_parent_traversal_rejected(self):
        self.assertRejected(self.write([self.entry(path="../a.md")]), "'..'")

    def test_absolute_path_rejected(self):
        self.assertRejected(self.write([self.entry(path="/etc/passwd")]), "absolute")

    def test_windows_drive_path_rejected(self):
        self.assertRejected(self.write([self.entry(path="C:/x/a.md")]), "colon")

    def test_backslash_path_rejected(self):
        self.assertRejected(self.write([self.entry(path="docs\\a.md")]), "backslash")

    def test_empty_segment_rejected(self):
        self.assertRejected(self.write([self.entry(path="docs//a.md")]), "empty")

    def test_digest_mismatch_rejected(self):
        self.assertRejected(self.write([self.entry(sha256="0" * 64)]), "sha256 mismatch")

    def test_malformed_digest_rejected(self):
        bad = hashlib.sha256(BODY).hexdigest().upper()
        self.assertRejected(self.write([self.entry(sha256=bad)]), "64 lowercase hex")

    def test_size_mismatch_rejected(self):
        self.assertRejected(self.write([self.entry(bytes=len(BODY) + 1)]), "size")

    def test_missing_file_rejected(self):
        self.assertRejected(self.write([self.entry(path="docs/missing.md")]), "file missing")

    def test_directory_entry_rejected(self):
        self.assertRejected(self.write([self.entry(path="docs")]), "not a regular file")

    def test_duplicate_path_case_insensitive_rejected(self):
        files = [self.entry(), self.entry(path="DOCS/A.md", linear_id="doc-2")]
        self.assertRejected(self.write(files), "duplicate path")

    def test_duplicate_linear_id_rejected(self):
        (self.root / "docs" / "b.md").write_bytes(BODY)
        files = [self.entry(), self.entry(path="docs/b.md")]
        self.assertRejected(self.write(files), "duplicate linear_id")

    def test_missing_linear_id_key_rejected(self):
        item = self.entry()
        del item["linear_id"]
        self.assertRejected(self.write([item]), "linear_id key required")

    def test_timestamp_without_zone_rejected(self):
        self.assertRejected(self.write([self.entry(updated_at="2026-10-11T10:00:00")]), "updated_at")

    def test_bad_created_at_rejected(self):
        self.assertRejected(self.write(created_at="yesterday"), "created_at")

    def test_wrong_schema_rejected(self):
        self.assertRejected(self.write(schema="other/9"), "schema")

    def test_malformed_json_rejected(self):
        self.assertRejected(self.write(raw="{not json"), "not valid UTF-8 JSON")

    def test_symlink_rejected(self):
        link = self.root / "docs" / "link.md"
        try:
            os.symlink(self.root / "docs" / "a.md", link)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"cannot create symlink here: {exc}")
        self.assertRejected(self.write([self.entry(path="docs/link.md")]), "symlink")

    def test_oversized_manifest_is_unreadable(self):
        path = self.write()
        original = vs.MAX_MANIFEST_BYTES
        vs.MAX_MANIFEST_BYTES = 10
        try:
            with self.assertRaises(vs.ManifestUnreadable):
                vs.verify(path)
        finally:
            vs.MAX_MANIFEST_BYTES = original

    def test_exit_codes(self):
        quiet = io.StringIO()
        with contextlib.redirect_stdout(quiet):
            self.assertEqual(vs.main([str(self.write())]), 0)
            self.assertEqual(vs.main([str(self.write([self.entry(sha256="0" * 64)]))]), 1)
            self.assertEqual(vs.main([str(self.root / "nope.json")]), 2)


if __name__ == "__main__":
    unittest.main()
