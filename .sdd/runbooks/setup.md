# Setup runbook

States: `LOCAL_ONLY` → `READ_ONLY_VERIFIED` → `DRAFT_WRITER_VERIFIED`. Record each step's result in `.sdd/reports/implementation-status.md` (gitignored).

## A. Confirm target (operator)
1. Open the **agency** Linear workspace (not an employer/client workspace). Note name + URL key.
2. Settings → Billing: confirm **Free**, no active trial. Record it. If not visible → status `UNKNOWN`, not "Free".
3. Settings → Teams: count teams. Free allows 2. Do not rename/delete existing teams without a decision.

## B. Workspace structure (operator, Linear UI)
1. Teams: **Baselines** and **Delivery** (reuse only if purpose fits).
2. Delivery → team settings → Templates: paste `.sdd/templates/*.md` (except baseline-register, requirements).
3. Baselines → team home: create **BASELINE REGISTER** from `baseline-register.md` and pilot **Requirements v1** from `requirements.md`, both as team documents, status `AWAITING HUMAN PUBLICATION`.
4. Delivery → create project for the pilot; add 00–40 documents from templates.
Documents can attach to teams, projects, initiatives, issues, cycles (Linear docs, checked 2026-10-11).

## C. Read-only connection
1. Linear → Settings → Account → Security & Access → New API key. Permission: **Read** only. Teams: Baselines + Delivery. Label: `sdd-read`.
2. Store it without chat or shell history — in your own PowerShell:
   ```powershell
   $s = Read-Host "Paste Linear READ-ONLY key" -AsSecureString
   [Environment]::SetEnvironmentVariable("LINEAR_READ_KEY", [Net.NetworkCredential]::new("", $s).Password, "User")
   Remove-Variable s
   ```
   Stored plaintext in your Windows user profile (HKCU\Environment). Acceptable for a read key; never for an admin key.
3. Fully quit the Claude desktop app (tray icon → Quit) and reopen so it inherits the variable.
4. Copy `.sdd/config/mcp.readonly.example.json` → `.mcp.json` at repo root (gitignored). The desktop app loads project `.mcp.json` **without** an approval prompt.
5. Verify: `python -I .sdd/scripts/linear_probe.py whoami` then `teams`. Fill `.sdd/project-map.json` with returned IDs.
6. If the server shows "needs authentication": **do not** sign in via OAuth. That grants your full access. Fix the variable instead.

## D. Alternate-route audit (P12) — before any writer
- claude.ai Settings → Connectors: no Linear connector (it would sync into Claude Code with full access). If present, disable for coding or set `"disableClaudeAiConnectors": true` in that project's `.claude/settings.json`.
- Claude in Chrome / browser control: a browser signed in to Linear is a full-access route. Certified sessions use a Chrome profile not signed in to Linear, or no browser tools.
- No other Linear keys in env vars, `.env` files, or other MCP configs.
- Residual: the agent's shell runs as your Windows user; this boundary stops agent mistakes, not a deliberately hostile process.

## E. Draft writer (operator + tests)
1. New API key `sdd-drafts`: **Write** only (no Admin; leave Create issues off if the form allows), Teams: **Delivery only**.
2. Human creates fixtures per `permissions.md`.
3. Store as `LINEAR_DRAFTS_KEY` (same method), restart app.
4. Run P01–P13. Any protected write → revoke key immediately (Security & Access → delete), restore fixture from recorded content.
5. Only after all required tests pass: merge `linear-drafts` from `mcp.read-and-drafts.example.json` into `.mcp.json`.

## Optional operator decision
Agent edits are attributed to the key's owner. A dedicated member (e.g. `agency-agent`, free on unlimited-member plan) owning both keys makes agent vs human edits distinguishable in history. This is a membership change — operator only.

## Re-verify when
Key rotated or permissions changed · team/project moved · Claude Code or Linear MCP update changes tools · new connector/browser access · any sign of bypass.
