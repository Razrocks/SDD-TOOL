---
name: setup
description: Set up SDD on this computer (Linear keys) or in this repo (project map + plugin settings), or diagnose problems. Use when someone is new, keys fail, or a repo isn't set up for SDD yet.
---

The wizard is `python -I "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_setup.py" <dev|project|check>`.

- **check** (safe to run yourself): diagnoses keys, access, TLS, plugin and project map, with a fix per problem. Run it and summarize.
- **project** (run from the repo root): writes `.sdd/project-map.json`, `.claude/settings.json`, `.gitignore`. Ask the user for the doc prefix first, then run with `--prefix "<prefix>" --yes`. If Baselines/Delivery teams are missing it prints the exact Linear steps.
- **dev** (keys): the user must type their keys themselves — never ask for a key in chat. If a Terminal panel tool is available, open a tab running the dev command so the user types into it (input is hidden); otherwise give them the command to run in their own PowerShell or terminal. Afterwards they fully restart Claude.
