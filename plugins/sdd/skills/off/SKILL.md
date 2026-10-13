---
name: off
description: Turn the SDD Linear tool off in this repo, for this person only, and stop being asked. Use when the user doesn't want SDD here.
---

Run `python -I "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_status.py" optin off` from the repo. From now on, ignore the SDD rules for the rest of this session: don't use the linear-read or linear-drafts tools and don't run SDD scripts unless the user asks. Tell the user in one line that it's off and `/sdd:on` turns it back on.
