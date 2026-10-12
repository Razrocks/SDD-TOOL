# Recovery

Linear CSV export covers issues/projects, **not** document bodies, comments, or attachments (Linear docs, checked 2026-10-11). Back up documents via the read connection.

## Export (on demand, at milestones)
1. Inventory every in-scope document (paginate to the end). Record requested scope vs discovered.
2. Save each body as `.sdd/exports/<date>/docs/<id>.md` (gitignored). Record ID, title, parent, URL, updatedAt, fetched-at.
3. Re-check register and updatedAt after capture; note changes during capture.
4. Write `manifest.json` (format: `.sdd/scripts/verify_snapshot.py` docstring). Set `complete: false` if any page, body, attachment, or reference failed.
5. Validate: `python -I .sdd/scripts/verify_snapshot.py .sdd/exports/<date>/manifest.json`
6. Store only on existing private storage. Never in this public repo.

A valid manifest proves local file integrity only — not completeness, authenticity, approval, or truth.

## Restore test
Recreate one requirements doc and one decision doc in a scratch location. New Linear IDs are expected; keep `restored_from: <original ID>` in the header. Recovery copies are not a second source of accepted scope.

## Remove this setup
- Disable connections: delete `linear-read`/`linear-drafts` from `.mcp.json`; revoke keys in Linear (Security & Access); remove env vars:
  `[Environment]::SetEnvironmentVariable("LINEAR_READ_KEY", $null, "User")` (same for `LINEAR_DRAFTS_KEY`).
- Local files: delete `.sdd/`, `CLAUDE.md` import line, `.gitignore` entries. Linear documents and history stay untouched.
