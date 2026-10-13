---
name: branch
description: Open (or create) the Linear branch doc for the current git branch — one owner, holds notes, decisions, evidence and handoffs for this branch. Use when starting work on a branch or to find its doc.
---

Run `python -I "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_docs.py" branch-open` from the project root.
Add `--branch <name>` if the folder is not a git repo, `--pr <url>` once a PR exists, `--owner <name>` to override your Linear name.

Report the doc title and link. This doc has one owner: only that person's agent writes in it. To list every branch doc and its status: `sdd_docs.py branches`.
