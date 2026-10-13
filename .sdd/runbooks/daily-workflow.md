# Daily workflow

## Start or resume a task
Prompt: "Resume <task>. Follow .sdd/AGENTS.md start steps."
Agent: project map → audit → `baseline` (accepted set) → relevant REQ/DEC → working spec, questions, latest handoff → git state → states its working understanding and any stale/conflicting context.

## Lock / unlock
Agent asks "Ready to lock?" or "Unlock <doc>?" — you move the doc between Delivery and Baselines (`publication.md`). The agent cannot move docs itself.

## Work
Normal coding, tests, commits, PRs. Docs update at boundaries, not every turn.

## Update a draft
Agent (writer enabled) or human edits Delivery docs: fetch → patch → read back. Without writer: agent prepares text, human pastes.

## Change something already accepted
Agent writes a proposal (`decision-proposal.md`) in Delivery and asks you to unlock → `publication.md`.

## Leave a handoff
"Checkpoint now." Agent appends a `handoff.md` entry: code state, verification, unresolved, next action, sync status.

## Writing tips (observed in the pilot)
- Wrap file names in backticks: Linear auto-links bare `name.py` / `name.md` as web domains (`.py`, `.md` are real TLDs).
- Linear rewrites `-` bullets to `*`. Fetch before patching and copy anchors from the fetched text; a failed patch saves nothing.
- `updatedAt` is not a reliable change signal; compare content.

## Linear down
Agent writes `.sdd/pending/<date>-<task>.md` (gitignored), marked NOT SYNCED. Git work continues. Sync later; read back.
