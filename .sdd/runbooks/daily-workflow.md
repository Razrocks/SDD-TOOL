# Daily workflow

## Start or resume a task
Prompt: "Resume <task>. Follow .sdd/AGENTS.md start steps."
Agent: project map → Baseline Register → relevant REQ/DEC → working spec, questions, latest handoff → git state → states its working understanding and any stale/conflicting context.

## Work
Normal coding, tests, commits, PRs. Docs update at boundaries, not every turn.

## Update a draft
Agent (writer enabled) or human edits Delivery docs: fetch → patch → read back. Without writer: agent prepares text, human pastes.

## Request acceptance
Agent writes a proposal (`decision-proposal.md`) in Delivery. Human reviews the delta → `publication.md`.

## Leave a handoff
"Checkpoint now." Agent appends a `handoff.md` entry: code state, verification, unresolved, next action, sync status.

## Linear down
Agent writes `.sdd/pending/<date>-<task>.md` (gitignored), marked NOT SYNCED. Git work continues. Sync later; read back.
