import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins" / "sdd" / "scripts"))
import sdd_setup as s  # noqa: E402

TEAMS = [{"id": "b", "name": "Baselines", "key": "BASE"}, {"id": "d", "name": "Delivery", "key": "DEL"}]


def facts(read=True, write=None, teams=TEAMS, ok=True):
    return {"ok": ok, "read": read, "viewer": "Alex", "workspace": {"name": "AGENCY"}, "teams": teams,
            "write": write, "error": None if ok else "boom"}


class WriteClassificationTests(unittest.TestCase):
    def test_scope_error_means_no_write(self):
        payload = {"errors": [{"message": "Invalid scope: `write` required"}]}
        self.assertFalse(s.classify_write(payload))

    def test_not_found_means_write_allowed(self):
        self.assertTrue(s.classify_write({"errors": [{"message": "Entity not found: Document"}]}))

    def test_unknown_error_is_unknown(self):
        self.assertIsNone(s.classify_write({"errors": [{"message": "rate limited"}]}))


class RoleTests(unittest.TestCase):
    def test_read_key_correct(self):
        self.assertEqual(s.problems_for("read", facts(write=False)), [])

    def test_read_key_that_can_write_is_wrong(self):
        self.assertTrue(any("WRITE" in p for p in s.problems_for("read", facts(write=True))))

    def test_drafts_key_must_not_see_baselines(self):
        self.assertTrue(any("Baselines" in p for p in s.problems_for("drafts", facts(write=True))))
        self.assertEqual(s.problems_for("drafts", facts(write=True, teams=[TEAMS[1]])), [])

    def test_lock_key_write_only_is_fine(self):
        self.assertEqual(s.problems_for("lock", facts(read=False, write=True, teams=[])), [])
        self.assertTrue(s.problems_for("lock", facts(read=False, write=False, teams=[])))

    def test_rejected_key(self):
        self.assertTrue(s.problems_for("read", facts(ok=False)))


class FileHelperTests(unittest.TestCase):
    def test_merge_settings_keeps_existing_and_adds_plugin(self):
        merged = s.merge_settings({"permissions": {"allow": ["Bash(git *)"]},
                                   "enabledPlugins": {"other@x": True}})
        self.assertEqual(merged["permissions"], {"allow": ["Bash(git *)"]})
        self.assertTrue(merged["enabledPlugins"]["other@x"])
        self.assertTrue(merged["enabledPlugins"][s.PLUGIN_ID])
        self.assertEqual(merged["extraKnownMarketplaces"]["sdd-tool"]["source"]["repo"], s.MARKETPLACE_REPO)

    def test_merge_settings_keeps_custom_marketplace_source(self):
        local = {"extraKnownMarketplaces": {"sdd-tool": {"source": {"source": "directory", "path": "C:/x"}}}}
        self.assertEqual(s.merge_settings(local)["extraKnownMarketplaces"]["sdd-tool"]["source"]["source"], "directory")

    def test_merge_gitignore_idempotent(self):
        once = s.merge_gitignore("node_modules/\n")
        self.assertIn(".sdd/merges/", once)
        self.assertEqual(s.merge_gitignore(once), once)
        self.assertIn(".sdd/pending/", s.merge_gitignore(""))

    def test_upsert_export_replaces_existing(self):
        out = s.upsert_export(['export PATH="x"', 'export LINEAR_READ_KEY="old"'], "LINEAR_READ_KEY", "new")
        self.assertIn('export LINEAR_READ_KEY="new"', out)
        self.assertNotIn("old", out)
        self.assertIn('export PATH="x"', out)

    def test_build_project_map_preserves_history(self):
        existing = {"baselines": [{"id": "a"}], "custom": 1}
        teams = {t["name"]: t for t in TEAMS}
        m = s.build_project_map(existing, {"id": "w", "name": "AGENCY", "url_key": "x"}, teams, "Dice Roller")
        self.assertEqual(m["doc_prefix"], "Dice Roller")
        self.assertEqual(m["teams"]["baselines"]["id"], "b")
        self.assertEqual(m["baselines"], [{"id": "a"}])
        self.assertEqual(m["custom"], 1)


if __name__ == "__main__":
    unittest.main()
