# SDD-TOOL

Claude Code plugin for spec-driven development with Linear: accepted docs stay locked in a **Baselines** team, work happens in **Delivery**, every doc has one owner, and changes to accepted docs go through personal drafts and an owner-reviewed merge. Code stays in Git, unchanged.

## Easiest: the setup wizard
```
git clone https://github.com/Razrocks/SDD-TOOL
python SDD-TOOL/plugins/sdd/scripts/sdd_setup.py dev        # once per person: keys (typed hidden, checked live)
cd your-repo
python ../SDD-TOOL/plugins/sdd/scripts/sdd_setup.py project # once per repo
python ../SDD-TOOL/plugins/sdd/scripts/sdd_setup.py check   # any time: diagnose with fixes
```
The wizard prints the exact Linear clicks for each key, verifies the key has exactly the right access before saving it, fixes the Windows certificate issue automatically, and writes the project files. Inside Claude: `/sdd:setup`.

The manual steps below do the same thing.

## Add SDD to a project (once per repo)
1. Copy `plugins/sdd/templates/client-settings.json` to `.claude/settings.json` in the repo (merge if one exists) and commit it. Teammates opening the repo are prompted to install the plugin.
2. Create `.sdd/project-map.json` (start from `plugins/sdd/templates/project-map.example.json`): set `doc_prefix` (e.g. `"Dice Roller"`) and the Linear `teams.delivery.id` / `teams.baselines.id`. Commit it, plus `.sdd/snapshots/` (accepted-version history). Ignore `.sdd/merges/`, `.sdd/pending/`, `.sdd/status.json`, `.sdd/.status-shown.json` and `.sdd/optin.json`.

## Set up a dev machine (once per person)
1. Join the Linear workspace. Create your own API keys (Settings → Account → Security & access):
   - `sdd-read`: **Read**, all teams
   - `sdd-drafts`: **Read + Write**, team **Delivery** only
   - `sdd-lock`: **Write**, Baselines + Delivery — only for people who approve scope
2. Store each as a user environment variable without pasting it in a terminal history, e.g. PowerShell:
   `$s = Read-Host -AsSecureString; [Environment]::SetEnvironmentVariable("LINEAR_READ_KEY", [Net.NetworkCredential]::new("", $s).Password, "User"); Remove-Variable s`
   (repeat for `LINEAR_DRAFTS_KEY` and, if you approve scope, `LINEAR_LOCK_KEY`). Restart Claude.
3. Open the repo in Claude and accept the plugin.

## Opt-in, per person
Nobody is forced. At the start of a fresh session in an SDD repo, Claude asks once: **"Turn on the SDD Linear tool for this repo?"** with three choices: Yes, Not now (asks again next fresh session), or No (never asks again). It never asks when a session compacts or resumes. The choice is stored per person in `.sdd/optin.json`, which is never committed. Until you say yes, nothing touches Linear. Change it anytime with `/sdd:on` or `/sdd:off`. Whoever runs `sdd_setup.py project` is opted in automatically.

Once it's on, SDD runs by itself: at session start it checks Linear in the background, opens your branch doc on feature branches, and hands Claude the status with your first message.

## Daily use
`/sdd:resume` start or continue · `/sdd:branch` your branch doc · `/sdd:checkpoint` save a handoff · `/sdd:draft` + `/sdd:merge` change an accepted doc · `/sdd:lock` accept a new doc · `/sdd:merged` close a branch after merge · `/sdd:on` / `/sdd:off` opt in or out.

## Develop the kit
`python -I -m unittest discover -s tests` · `claude plugin validate ./plugins/sdd` · `claude plugin validate .`
Bump `version` in `plugins/sdd/.claude-plugin/plugin.json` when releasing so teammates' plugins update.
