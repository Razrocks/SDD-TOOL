# Baseline publication (human only)

1. Read the proposal's exact delta and its cited source passages. Check sources support the claim, not just exist.
2. Decide: accept / reject / need info. Fill the proposal's Decision block yourself.
3. Accepted: in Linear UI, create the new Baselines document version (e.g. `Requirements v2`) under the Baselines team. Keep v1; mark it superseded in its header.
4. Publish all needed documents **first**.
5. Update the **Baseline Register last**: new row, move old row to Superseded, published by/at, optional digest (`python -I .sdd/scripts/verify_snapshot.py` on an export).
6. Tell agents: "Baseline changed — refresh and list affected specs, plans, tests, handoffs."

Never paste an agent's text as accepted without reading the delta. Agents never perform steps 3–5. Corrections create a new version; history is not erased.
