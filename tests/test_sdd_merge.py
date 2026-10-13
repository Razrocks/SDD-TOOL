import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins" / "sdd" / "scripts"))
import sdd_merge as m  # noqa: E402

BASE = "# Reqs\n\nREQ-001 small\n\nREQ-002 quick\n\nNotes here"


class BlockTests(unittest.TestCase):
    def test_blocks_split_on_blank_lines_and_ignore_extra_space(self):
        self.assertEqual(m.blocks("a\n\n\n b \r\n\r\nc"), ["a", "b", "c"])
        self.assertEqual(m.blocks(""), [])

    def test_join_round_trip(self):
        self.assertEqual(m.blocks(m.join(["a", "b"])), ["a", "b"])


class TwoWayTests(unittest.TestCase):
    def test_no_changes(self):
        p = m.plan(BASE, BASE, BASE)
        self.assertEqual(p["items"], [])
        self.assertEqual(m.build(p, {})[0].strip(), m.join(m.blocks(BASE)).strip())

    def test_change_keep_and_drop(self):
        draft = BASE.replace("REQ-002 quick", "REQ-002 quick, under 1 hour")
        p = m.plan(BASE, draft, BASE)
        self.assertEqual(len(p["items"]), 1)
        self.assertEqual(p["items"][0]["kind"], "changed")
        self.assertFalse(p["items"][0]["conflict"])
        kept, _ = m.build(p, {1: "keep"})
        dropped, _ = m.build(p, {1: "drop"})
        self.assertIn("under 1 hour", kept)
        self.assertNotIn("under 1 hour", dropped)

    def test_added_and_removed(self):
        draft = BASE.replace("Notes here", "REQ-003 fun") .replace("REQ-001 small\n\n", "")
        p = m.plan(BASE, draft, BASE)
        kinds = sorted(item["kind"] for item in p["items"])
        self.assertIn("removed", kinds)
        merged, summary = m.build(p, {item["id"]: "keep" for item in p["items"]})
        self.assertNotIn("REQ-001", merged)
        self.assertIn("REQ-003 fun", merged)
        self.assertEqual(summary["kept"], len(p["items"]))

    def test_edit_decision_uses_owner_text(self):
        draft = BASE.replace("REQ-002 quick", "REQ-002 fast")
        p = m.plan(BASE, draft, BASE)
        merged, summary = m.build(p, {1: {"edit": "REQ-002 quick (same session)"}})
        self.assertIn("REQ-002 quick (same session)", merged)
        self.assertNotIn("REQ-002 fast", merged)
        self.assertEqual(summary["edited"], 1)

    def test_every_item_needs_a_decision(self):
        draft = BASE.replace("REQ-002 quick", "REQ-002 fast")
        with self.assertRaises(ValueError):
            m.build(m.plan(BASE, draft, BASE), {})

    def test_invalid_decision_rejected(self):
        draft = BASE.replace("REQ-002 quick", "REQ-002 fast")
        with self.assertRaises(ValueError):
            m.build(m.plan(BASE, draft, BASE), {1: "current"})


class GranularityTests(unittest.TestCase):
    def test_neighbouring_edit_and_addition_are_separate_decisions(self):
        draft = BASE.replace("REQ-002 quick", "REQ-002 quick, under 2 hours\n\nREQ-003 offline")
        p = m.plan(BASE, draft, BASE)
        kinds = [item["kind"] for item in p["items"]]
        self.assertEqual(sorted(kinds), ["added", "changed"])
        merged, _ = m.build(p, {item["id"]: ("keep" if item["kind"] == "added" else "drop") for item in p["items"]})
        self.assertIn("REQ-003 offline", merged)          # kept the addition
        self.assertIn("REQ-002 quick", merged)
        self.assertNotIn("under 2 hours", merged)        # dropped the edit

    def test_insert_before_edited_block_keeps_order(self):
        draft = BASE.replace("REQ-002 quick", "REQ-001b new\n\nREQ-002 quick!")
        p = m.plan(BASE, draft, BASE)
        merged, _ = m.build(p, {item["id"]: "keep" for item in p["items"]})
        self.assertEqual(m.blocks(merged), m.blocks(draft))

    def test_unrelated_block_removed_separately(self):
        draft = BASE.replace("Notes here", "")
        p = m.plan(BASE, draft, BASE)
        self.assertEqual([item["kind"] for item in p["items"]], ["removed"])


class ThreeWayTests(unittest.TestCase):
    def test_non_overlapping_changes_merge_without_conflict(self):
        current = BASE.replace("REQ-001 small", "REQ-001 small, one file")  # merged earlier by Sam
        draft = BASE.replace("Notes here", "Notes here, updated")            # Alex's change
        p = m.plan(BASE, draft, current)
        self.assertTrue(p["baseline_changed_since_fork"])
        self.assertEqual(len(p["items"]), 1)
        self.assertFalse(p["items"][0]["conflict"])
        merged, summary = m.build(p, {1: "keep"})
        self.assertIn("one file", merged)          # Sam's accepted change survives
        self.assertIn("Notes here, updated", merged)
        self.assertEqual(summary["auto_kept_current"], 1)

    def test_same_block_changed_twice_is_a_conflict(self):
        current = BASE.replace("REQ-002 quick", "REQ-002 quick (Sam)")
        draft = BASE.replace("REQ-002 quick", "REQ-002 quick (Alex)")
        p = m.plan(BASE, draft, current)
        self.assertEqual(len(p["items"]), 1)
        item = p["items"][0]
        self.assertTrue(item["conflict"])
        self.assertEqual(item["current"], ["REQ-002 quick (Sam)"])
        self.assertEqual(item["draft"], ["REQ-002 quick (Alex)"])
        self.assertIn("(Sam)", m.build(p, {1: "current"})[0])
        self.assertIn("(Alex)", m.build(p, {1: "draft"})[0])
        both = m.build(p, {1: "both"})[0]
        self.assertIn("(Sam)", both)
        self.assertIn("(Alex)", both)

    def test_conflict_decisions_differ_from_simple_ones(self):
        current = BASE.replace("REQ-002 quick", "REQ-002 quick (Sam)")
        draft = BASE.replace("REQ-002 quick", "REQ-002 quick (Alex)")
        with self.assertRaises(ValueError):
            m.build(m.plan(BASE, draft, current), {1: "keep"})

    def test_adjacent_edits_are_separate_and_both_survive(self):
        current = BASE.replace("REQ-001 small", "REQ-001 small (Sam)")
        draft = BASE.replace("REQ-002 quick", "REQ-002 quick (Alex)")
        p = m.plan(BASE, draft, current)
        self.assertEqual(len(p["items"]), 1)
        self.assertFalse(p["items"][0]["conflict"])     # still an explicit owner decision
        merged, _ = m.build(p, {1: "keep"})
        self.assertIn("(Sam)", merged)
        self.assertIn("(Alex)", merged)

    def test_choosing_draft_never_drops_neighbouring_accepted_insert(self):
        # accepted doc gained REQ-003 right after REQ-002 and REQ-002 changed; draft changed REQ-002 too
        current = BASE.replace("REQ-002 quick", "REQ-002 quick (A)\n\nREQ-003 offline")
        draft = BASE.replace("REQ-002 quick", "REQ-002 quick (S)")
        p = m.plan(BASE, draft, current)
        conflicts = [i for i in p["items"] if i["conflict"]]
        self.assertEqual(len(conflicts), 1)
        merged, _ = m.build(p, {conflicts[0]["id"]: "draft"})
        self.assertIn("REQ-002 quick (S)", merged)
        self.assertIn("REQ-003 offline", merged)        # accepted addition survives
        self.assertNotIn("(A)", merged)

    def test_two_inserts_at_same_point_conflict(self):
        current = BASE.replace("Notes here", "Notes here\n\nX from Sam")
        draft = BASE.replace("Notes here", "Notes here\n\nY from Alex")
        p = m.plan(BASE, draft, current)
        self.assertTrue(p["items"][0]["conflict"])

    def test_describe_lists_decisions(self):
        current = BASE.replace("REQ-002 quick", "REQ-002 quick (Sam)")
        draft = BASE.replace("REQ-002 quick", "REQ-002 quick (Alex)").replace("Notes here", "Notes here 2")
        text = m.describe(m.plan(BASE, draft, current))
        self.assertIn("CONFLICT", text)
        self.assertIn("decide: draft | current | both | edit", text)
        self.assertIn("accepted doc changed since this draft was forked", text)


if __name__ == "__main__":
    unittest.main()
