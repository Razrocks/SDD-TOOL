# AGENCY PLAYBOOK

Record ID: AGENCY-PLAYBOOK
Kind: playbook
Status: working
Owner: <workspace steward, or UNRESOLVED>

> Delivery-team working guide. It does **not** grant permissions and cannot change publication rules. Binding policy lives in Baselines (see Baseline Register → policy reference).

## Where things live
- **Baselines team** — accepted requirements and decisions, Baseline Register. Human-published only.
- **Delivery team** — one project per engagement: 00 START HERE, 10 WORKING SPEC, 20 IMPLEMENTATION PLAN, 30 EVIDENCE AND QUESTIONS, 40 HANDOFF. Extra documents only when they have their own purpose.
- **GitHub** — code, issues, PRs, CI. Unchanged. Linear docs link to it; no issue mirroring.

## Roles (one person may hold several)
- Workspace steward — structure, templates, key configuration, exports.
- Project owner — accepted scope and material decisions.
- Implementer / agent operator — code, working docs, evidence, handoffs.
- Reviewer — checks consequential deltas against original sources.

## What needs human review
Scope, acceptance criteria, security/data assumptions, external commitments, significant architecture constraints. Batch related proposals. Routine plan/spec edits do not need review.

## Status words
working · proposed · accepted (only via publication + register) · superseded.
Evidence support: observed · agent-reported · externally sourced · not yet verified.

## Separations to keep
Intended vs observed behavior · commitment vs proposal · implemented ≠ tested ≠ merged ≠ deployed ≠ accepted · source exists vs source supports claim · no result found vs proof of absence · recent vs applicable.

## Costs
No new paid tools, seats, trials, or Linear AI credits. Claude allowance exhausted = wait.
