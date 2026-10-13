---
name: on
description: Turn the SDD Linear tool on in this repo, for this person only. Use when the user wants SDD (accepted specs, branch docs, checkpoints in Linear) after saying no or not now.
---

Run `python -I "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_status.py" optin on` from the repo, then follow what it prints: it returns the SDD rules and a fresh status. From now on, work under those rules. Tell the user in one line that it's on and anything flagged ATTENTION.

If it says the folder isn't set up for SDD, offer `/sdd:setup` (project mode).
