---
name: draft
description: Fork an accepted (Baselines) doc into your own editable draft in Delivery, to propose changes without touching the accepted version. Use when work needs an accepted requirement or decision changed.
---

1. Find the accepted doc's ID (`python -I "${CLAUDE_PLUGIN_ROOT}/scripts/linear_probe.py" baseline --project "<prefix>"`).
2. `python -I "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_docs.py" draft <accepted id>` — creates `<title> / draft (<you>, <branch>)` with the accepted text below a marker line, saves the base version in `.sdd/snapshots/`, and prints the draft's local `file`.
3. Edit that local file, only below the marker line. Then `python -I "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_docs.py" push <draft id>` and report `verified`. Teammates can have their own drafts of the same doc at the same time.
4. When ready, use `/sdd:merge` (it refuses while the draft has unpushed local edits).
