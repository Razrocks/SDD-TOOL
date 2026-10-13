---
name: merged
description: Close this branch's doc after its PR merged (or the branch was abandoned) and refresh the as-built docs from main. Use after a merge to main.
---

1. Confirm in git that the branch merged (or ask the dev). Note the merge commit SHA.
2. `python -I "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_docs.py" branch-close --branch <branch> --status merged --merge-commit <sha>` (or `--status abandoned`).
3. As-built docs (`<prefix> / As-built / …`): regenerate the affected ones from the code on main (API, architecture, changelog). They are generated — rewrite them from main, never hand-merge.
4. Report what was closed and refreshed.
