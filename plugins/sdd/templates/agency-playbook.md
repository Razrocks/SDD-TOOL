# AGENCY PLAYBOOK

Record ID: AGENCY-PLAYBOOK
Kind: playbook
Status: working
Owner: <workspace steward, or UNRESOLVED>

> Delivery-team working guide. It does **not** grant permissions and cannot change lock rules. Binding policy lives in Baselines.

## Docs
Any development doc, any format, any author style. The only rule is the title: `<Project> / <optional path> / <name>`. These templates are optional starters, never required structure.

## Where things live
- **Baselines team** — accepted (locked) requirements and decisions. Only a human moves docs in (lock) or out (unlock).
- **Delivery team** — every working doc for every engagement, any type. A start page and a handoff help agents resume; everything else is up to the team.
- **GitHub** — code, issues, PRs, CI. Unchanged. Linear docs link to it; no issue mirroring.

## Roles (one person may hold several)
- Workspace steward — structure, templates, key configuration, exports.
- Project owner — accepted scope and material decisions.
- Implementer / agent operator — code, working docs, evidence, handoffs.
- Reviewer — checks consequential deltas against original sources.

## What needs human review
Scope, acceptance criteria, security/data assumptions, external commitments, significant architecture constraints. Batch related proposals. Routine plan/spec edits do not need review.

## Status words
working · proposed · accepted (only by sitting in Baselines) · superseded.
Evidence support: observed · agent-reported · externally sourced · not yet verified.

## Separations to keep
Intended vs observed behavior · commitment vs proposal · implemented ≠ tested ≠ merged ≠ deployed ≠ accepted · source exists vs source supports claim · no result found vs proof of absence · recent vs applicable.

## Costs
No new paid tools, seats, trials, or Linear AI credits. Claude allowance exhausted = wait.
