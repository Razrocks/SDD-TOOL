---
name: lock
description: Make a finished Delivery doc accepted by moving it into Baselines, after the owner approves. Use when a new requirement or decision doc is done.
---

1. Confirm the title follows `<prefix> / <name>`; if not, rename it first (it's still a Delivery doc).
2. Ask the owner with a clickable question naming the doc: Lock "<title>"? Only continue on a clear yes.
3. `python -I "${CLAUDE_PLUGIN_ROOT}/scripts/lock.py" lock <id> --title "<exact title>" --project "<prefix>"` — a permission prompt names the doc (second approval).
4. Report `verified`, then `linear_probe.py baseline --project "<prefix>"` to show it in the accepted set.

To change an accepted doc later, use `/sdd:draft` + `/sdd:merge`, not unlock.
