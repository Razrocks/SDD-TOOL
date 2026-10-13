---
name: checkpoint
description: Save a handoff into this branch's Linear doc so another session or teammate can continue — what changed, verification, open questions, next step. Use at milestones, before stopping, or before a long session compacts.
---

1. Open the branch doc (`python -I "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_docs.py" branch-open`) and fetch its current content with `linear-drafts`.
2. Insert a dated handoff entry near the top of the notes (narrow patch, read back). Any format, but cover: task, accepted docs relied on (title + fingerprint), code state (branch, HEAD, dirty or not, pushed or not), what changed, verification with real evidence, what is not verified, open questions, next useful action.
3. Never write in someone else's doc. If Linear is unavailable, save `.sdd/pending/<date>-checkpoint.md` marked NOT SYNCED.
