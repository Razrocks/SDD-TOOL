# SDD-TOOL

Internal spec-driven development kit: Linear Free documents + Linear hosted MCP + existing Claude Code + unchanged GitHub flow. No hosting, no added spend.

This repository is **public**. Commit only generic material. Never commit keys, real workspace/team/document IDs, client names, reports, or exports — `.gitignore` covers `.sdd/project-map.json`, `.sdd/reports/`, `.sdd/exports/`, `.sdd/pending/`, `.mcp.json`.

Layout: `.sdd/templates` (Linear document templates), `.sdd/config` (MCP examples, inactive), `.sdd/runbooks`, `.sdd/scripts` (stdlib Python, local only), `.sdd/tests`.

Run local tests: `python -I -m unittest discover -s .sdd/tests -v`

@.sdd/AGENTS.md
