---
name: resume
description: Start or resume SDD work in this project — audit Baselines, list the accepted docs, open this branch's doc, read the last handoff, check the code. Use at the start of a session or when the user says resume.
---

Resume SDD work. Run from the project root (it has `.sdd/project-map.json`).

1. `python -I "${CLAUDE_PLUGIN_ROOT}/scripts/linear_probe.py" audit` — exit 3 means something project-shaped sits in Baselines: report it, don't use it.
2. `python -I "${CLAUDE_PLUGIN_ROOT}/scripts/linear_probe.py" baseline --project "<doc_prefix from the map>"` — the accepted set with fingerprints. Compare with the `baselines` entries in the project map; say which accepted docs changed since last time.
3. `python -I "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_docs.py" branch-open` — find or create this branch's doc. Read its latest handoff with `linear-read`.
4. Check `git status`, branch, HEAD, and the files the handoff mentions.
5. Tell the user, briefly: what's accepted that matters here, where the branch stands, what changed, and the next useful action. Fetch other docs only when the task needs them.

If TLS fails with CERTIFICATE_VERIFY_FAILED, rerun with `--cafile <trusted CA bundle>` before the subcommand.
