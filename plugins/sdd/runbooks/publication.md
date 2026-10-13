# Lock and unlock (owner approves every move)

Accepted = what sits in the **Baselines** team as a team document. The set changes only by moving documents.

## How a move happens
1. Agent asks a clickable question: "Lock <title>?" / "Unlock <title>?" (unlock comes with the exact proposed change).
2. You answer yes or no. No → nothing moves.
3. Yes → agent runs `lock.py lock|unlock <id>`. Claude shows a **permission prompt** (forced by the `hook_lock_gate.py` hook) — Allow = second confirmation.
4. `lock.py` moves the doc (team change only, no content edits), reads it back, prints `verified: true`. Unlock snapshots the locked text first.
5. Agent confirms with `linear_probe.py baseline` and `audit`.

You can still move docs yourself in the Linear UI (document menu → move team); the agent checks the result with `baseline`.

## Unlock window
While a doc is in Delivery it is not accepted; its last accepted text is the snapshot (`.sdd/snapshots/`, path + sha256 in evidence). Review the diff in Linear version history before approving the re-lock.

## What protects accepted docs (honest)
- `linear-drafts` (the agent's normal writing connection) cannot see Baselines — enforced by key scope (P04–P08).
- `LINEAR_LOCK_KEY` can move docs and sits on this PC. Its use is gated by your two confirmations (question + permission prompt) and by the rules — **not** by key scope. A process deliberately ignoring the rules could misuse it. Revoke `sdd-lock` in Linear to fall back to manual moves.
- Run `baseline` regularly: sha256 changes show any unexpected edit.

## Never
- Accepted docs inside a project (`baseline` ignores them; `audit` flags projects linked to Baselines).
- Erasing history: corrections are new revisions.
