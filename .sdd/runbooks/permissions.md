# Live permission tests (P01–P13)

Run only in the confirmed agency workspace, on disposable fixtures. Record every test in `.sdd/reports/validation.md` (gitignored): timestamp, workspace, client/version, credential label, permissions, fixture IDs, operation, response, before/after content + parent, result.

Results: `PASS` · `FAIL` · `BLOCKED` · `NOT_TESTED` · `UNSUPPORTED`. `UNSUPPORTED` is not a pass. A local simulation is not a live result.

## Fixtures (human creates in Linear UI)
| Fixture | Where | Title | Body |
|---|---|---|---|
| BASE-FX | Baselines team document | `TEST-FIXTURE BASE-FX — not real scope` | `fixture-v1 <random word>` |
| DEL-FX | Delivery team document | `TEST-FIXTURE DEL-FX` | `fixture-v1 <random word>` |
Record both IDs and exact bodies. List them under "Test fixtures" in the Baseline Register.

## Counting a denial
A denial counts only if: (1) the same operation succeeds on an allowed fixture with valid input, (2) the response is an authorization error (HTTP or GraphQL `errors` inside HTTP 200), and (3) the reader confirms the protected fixture unchanged (content + parent). Timeout, schema error, expired key, missing tool, unrelated 404 = `BLOCKED`, not `PASS`.

## Tests
| ID | Credential | Operation | Expected |
|---|---|---|---|
| P01 | read | fetch BASE-FX and DEL-FX by ID | exact bodies returned |
| P02 | read | document update/create via raw API | authorization denial, no change |
| P03 | drafts | create, read, update, read back a Delivery doc | all succeed |
| P04 | drafts | update BASE-FX content | denied, unchanged |
| P05 | drafts | create document under Baselines team | denied, nothing created |
| P06 | drafts | move BASE-FX to Delivery, then edit | denied at move |
| P07 | drafts | move its Delivery draft into Baselines | denied |
| P08 | drafts | archive/delete/restore, comment, resource change on BASE-FX | denied or no authority change |
| P09 | drafts | team/project association change on safe disposable case | protected doc stays unwritable; unsafe paths = residual risk |
| P10 | drafts | same key via raw API (not MCP) for P04–P07 | same denials |
| P11 | read, drafts | known-ID fetch, search, list | match declared scope; no claim of client isolation inside Delivery |
| P12 | runtime | audit other routes (connectors, OAuth, browser, env, configs) | none unrestricted |
| P13 | both | repeat P01, P03, P04 after reconnect / any scope change | same results |

## Tooling
- Discover real MCP tool names/schemas in the session; do not assume.
- Raw API: `python -I .sdd/scripts/linear_probe.py introspect DocumentCreateInput` (and `DocumentUpdateInput`, `Mutation`) to confirm live field names **before** writing any mutation probe. Mutation probes are added only after fixtures exist and schema is confirmed.

## On unexpected protected write
Stop writer use. Record before/after. Revoke `sdd-drafts` key (Linear → Settings → Account → Security & Access). Human restores fixture from recorded body. Read back to confirm. Never broaden a key to make a test pass.

## Known gap: projects linked to Baselines (P09)
Tested 2026-10-12: a Delivery-only Read+Write key **can** `projectCreate` with `teamIds` including Baselines (adding Baselines to an existing project did not take effect). It cannot touch Baselines team documents or the register.
Operator decision (2026-10-12): accept with detection, not prevention.
- Accepted scope = Baselines **team documents** listed in the register. Projects never live in Baselines.
- `linear_probe.py audit` flags any project linked to Baselines and documents inside it; agents run it at start/resume.
- Finding → operator reviews and deletes in the Linear UI.
Stronger option if this ever matters more: move Baselines to a separate free workspace.

## Guarantee scope
A pass covers only the tested key, runtime, parent arrangement, and operations — not future Linear behavior.
