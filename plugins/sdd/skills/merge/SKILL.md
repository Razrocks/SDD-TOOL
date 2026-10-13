---
name: merge
description: Merge a draft back into its accepted doc with the owner reviewing every change (keep, drop, edit; conflicts with changes merged since the fork are flagged). Use when a draft is ready.
---

1. `python -I "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_docs.py" merge-plan <draft id>` — prints numbered changes; conflicts mean the accepted doc changed the same part since the fork.
2. Show the owner the accepted doc's **title** and every numbered change exactly as printed. Ask for a decision on each:
   - normal change: keep | drop | edit (owner's own wording)
   - conflict: draft | current | both | edit
   Use clickable questions for up to a few items; otherwise ask for one reply like "1 keep, 2 drop, 3 edit: <text>". Never decide for the owner.
3. `python -I "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_docs.py" merge-build <draft id> --decisions '{"1":"keep","2":{"edit":"..."}}'` — writes the merged text and prints the exact `lock.py apply …` command.
4. Run that command with `python -I "${CLAUDE_PLUGIN_ROOT}/scripts/lock.py" …`. A permission prompt names the doc — the owner's final approval. Report `verified` and the new fingerprint.
5. `python -I "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_docs.py" draft-close <draft id> --status merged|partly-merged|rejected`.

If apply refuses because the accepted doc changed, run merge-plan again (new conflicts may appear).
