"""Block-level 2-way / 3-way merge for free-form documents. Stdlib only, no I/O.

A document is split into blocks (paragraphs, headings, list groups) separated by blank
lines. Changes are found with difflib against the common ancestor ("base"):

  draft   = the author's copy (forked from base)
  current = the accepted document now (base, or base plus changes merged since the fork)

Every region the draft changed becomes a numbered item for the owner to decide:
  keep | drop | edit:<text>              (region untouched in current)
  draft | current | both | edit:<text>   (conflict: current changed the same region)
Regions changed only in current are kept automatically (they are already accepted).
A conflict is a true overlap (same blocks, or an insertion inside the other's range); changes
that merely sit next to each other stay separate, so choosing one side of a conflict can never
discard an unrelated accepted change. Every draft change still needs an explicit decision.
"""

import difflib
import re

BLANK_LINES = re.compile(r"\n[ \t]*\n+")


def blocks(text):
    text = (text or "").replace("\r\n", "\n").strip()
    return [b.strip() for b in BLANK_LINES.split(text) if b.strip()] if text else []


def join(block_list):
    return "\n\n".join(block_list) + ("\n" if block_list else "")


SIMILAR = 0.5


def _split_replace(i1, base_part, new_part):
    """Break one replaced run into separate edits, additions and removals, so independent
    neighbouring changes become separate decisions. Pairs blocks by similarity, in order."""
    out, j = [], 0
    for k, block in enumerate(base_part):
        best, best_ratio = None, SIMILAR
        for jj in range(j, len(new_part)):
            ratio = difflib.SequenceMatcher(None, block, new_part[jj], autojunk=False).ratio()
            if ratio >= best_ratio:
                best, best_ratio = jj, ratio
        i = i1 + k
        if best is None:
            out.append((i, i + 1, []))                      # removed
            continue
        if best > j:
            out.append((i, i, new_part[j:best]))            # added before this block
        if new_part[best] != block:
            out.append((i, i + 1, [new_part[best]]))         # edited
        j = best + 1
    if j < len(new_part):
        out.append((i1 + len(base_part), i1 + len(base_part), new_part[j:]))   # added after
    return out


def changes(base, other):
    """List of (i1, i2, replacement_blocks) turning base into other, one per independent change."""
    matcher = difflib.SequenceMatcher(None, base, other, autojunk=False)
    out = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "replace":
            out.extend(_split_replace(i1, base[i1:i2], other[j1:j2]))
        elif tag != "equal":
            out.append((i1, i2, other[j1:j2]))
    return out


def _overlap(a, b):
    """True when two changes compete for the same text: overlapping ranges, an insertion
    strictly inside the other's range, or two insertions at the same point. Changes that only
    sit next to each other are independent (each still needs its own owner decision)."""
    (a0, a1), (b0, b1) = a, b
    if a0 == a1 and b0 == b1:
        return a0 == b0
    if a0 == a1:
        return b0 < a0 < b1
    if b0 == b1:
        return a0 < b0 < a1
    return a0 < b1 and b0 < a1


def _regions(draft_changes, current_changes):
    """Each change is its own region, except that a draft change and a current change that
    touch are joined (a conflict). One side's neighbouring changes stay separate decisions."""
    tagged = [(c, "draft") for c in draft_changes] + [(c, "current") for c in current_changes]
    parent = list(range(len(tagged)))

    def root(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, (change_a, side_a) in enumerate(tagged):
        for b in range(a + 1, len(tagged)):
            change_b, side_b = tagged[b]
            if side_a != side_b and _overlap(change_a[:2], change_b[:2]):
                parent[root(a)] = root(b)
    groups = {}
    for index, (change, side) in enumerate(tagged):
        region = groups.setdefault(root(index), {"lo": change[0], "hi": change[1], "draft": [], "current": []})
        region["lo"] = min(region["lo"], change[0])
        region["hi"] = max(region["hi"], change[1])
        region[side].append(change)
    return sorted(groups.values(), key=lambda r: (r["lo"], r["hi"]))


def _apply(base, lo, hi, side_changes):
    out, pos = [], lo
    for i1, i2, replacement in sorted(side_changes, key=lambda c: (c[0], c[1])):
        out.extend(base[pos:i1])
        out.extend(replacement)
        pos = i2
    out.extend(base[pos:hi])
    return out


def _kind(base_part, new_part):
    if not base_part:
        return "added"
    if not new_part:
        return "removed"
    return "changed"


def plan(base_text, draft_text, current_text):
    """Return a merge plan: numbered items plus everything needed to build the result."""
    base, draft, current = blocks(base_text), blocks(draft_text), blocks(current_text)
    regions = _regions(changes(base, draft), changes(base, current))
    items, auto = [], 0
    for region in regions:
        lo, hi = region["lo"], region["hi"]
        base_part = base[lo:hi]
        current_part = _apply(base, lo, hi, region["current"])
        if not region["draft"]:
            region["auto"] = current_part
            auto += 1
            continue
        draft_part = _apply(base, lo, hi, region["draft"])
        item = {
            "id": len(items) + 1,
            "conflict": bool(region["current"]),
            "kind": _kind(base_part, draft_part),
            "base": base_part,
            "draft": draft_part,
            "current": current_part,
        }
        region["item"] = item["id"]
        items.append(item)
    return {"base": base, "regions": regions, "items": items, "auto_kept": auto,
            "baseline_changed_since_fork": base != current}


def _choice(item, decision):
    if isinstance(decision, dict) and "edit" in decision:
        return blocks(decision["edit"])
    if item["conflict"]:
        options = {"draft": item["draft"], "current": item["current"], "both": item["current"] + item["draft"]}
    else:
        options = {"keep": item["draft"], "drop": item["current"]}
    if decision not in options:
        raise ValueError(f"item {item['id']}: decision must be one of {sorted(options)} or an edit")
    return options[decision]


def build(merge_plan, decisions):
    """Apply owner decisions ({item id: decision}) and return (merged_text, summary)."""
    items = {item["id"]: item for item in merge_plan["items"]}
    decisions = {int(k): v for k, v in decisions.items()}
    missing = sorted(set(items) - set(decisions))
    if missing:
        raise ValueError(f"no decision for items {missing}")
    base, out, pos = merge_plan["base"], [], 0
    summary = {"kept": 0, "dropped": 0, "edited": 0, "auto_kept_current": merge_plan["auto_kept"]}
    for region in merge_plan["regions"]:
        out.extend(base[pos:region["lo"]])
        if "item" in region:
            item, decision = items[region["item"]], decisions[region["item"]]
            out.extend(_choice(item, decision))
            if isinstance(decision, dict):
                summary["edited"] += 1
            elif decision in ("drop", "current"):
                summary["dropped"] += 1
            else:
                summary["kept"] += 1
        else:
            out.extend(region["auto"])
        pos = region["hi"]
    out.extend(base[pos:])
    return join(out), summary


def describe(merge_plan, limit=280):
    """Human-readable numbered list of decisions to make."""
    def show(part):
        text = " / ".join(part) if part else "(nothing)"
        return text if len(text) <= limit else text[:limit] + "…"

    lines = []
    if merge_plan["baseline_changed_since_fork"]:
        lines.append("Note: the accepted doc changed since this draft was forked.")
    for item in merge_plan["items"]:
        if item["conflict"]:
            lines.append(f"{item['id']}. CONFLICT ({item['kind']} in draft, also changed in accepted doc)")
            lines.append(f"   accepted now: {show(item['current'])}")
            lines.append(f"   draft:        {show(item['draft'])}")
            lines.append("   decide: draft | current | both | edit")
        else:
            lines.append(f"{item['id']}. {item['kind'].upper()}")
            if item["kind"] != "added":
                lines.append(f"   before: {show(item['base'])}")
            if item["kind"] != "removed":
                lines.append(f"   after:  {show(item['draft'])}")
            lines.append("   decide: keep | drop | edit")
    if not merge_plan["items"]:
        lines.append("No changes in this draft.")
    return "\n".join(lines)
