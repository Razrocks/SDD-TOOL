---
name: checkpoint
description: Save a handoff into this branch's Linear doc so another session or teammate can continue — what changed, verification, open questions, next step. Use at milestones, before stopping, or before a long session compacts.
---

1. `python -I "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_docs.py" branch-open` gives the branch doc id. Then `python -I "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_docs.py" pull <id>` copies it to a local file.
2. Edit that local file: insert a dated handoff entry near the top of the notes. Any format, but cover: task, accepted docs relied on (title + fingerprint), code state (branch, HEAD, dirty or not, pushed or not), what changed, verification with real evidence, what is not verified, open questions, next useful action.
3. `python -I "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_docs.py" push <id>` and report `verified`. If push says Linear changed, `pull` again (non-overlapping changes merge automatically), then push.
4. Never write in someone else's doc (push refuses). If Linear is down, the edit stays in the local file; push it later.
