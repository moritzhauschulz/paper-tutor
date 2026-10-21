"""Resolve human references ('Thm 2', 'Eq. (7)', '§3.2', 'fig:arch') against a paper's indexes."""

import re
from pathlib import Path

from common import read_tsv

ABBREV = {
    "thm": "theorem", "theorem": "theorem", "lem": "lemma", "lemma": "lemma", "prop": "proposition",
    "proposition": "proposition", "cor": "corollary", "corollary": "corollary", "def": "definition",
    "defn": "definition", "definition": "definition", "ass": "assumption", "asm": "assumption",
    "assumption": "assumption", "rem": "remark", "remark": "remark", "ex": "example",
    "example": "example", "claim": "claim", "conj": "conjecture", "conjecture": "conjecture",
    "cond": "condition", "condition": "condition", "fig": "figure", "figure": "figure",
    "tab": "table", "table": "table", "alg": "algorithm", "algorithm": "algorithm",
}
NUM = r"([A-Z]?\d+(?:\.\d+)*[a-z]?)"


def load(d):
    d = Path(d)
    return {
        "labels": read_tsv(d / "labels.tsv"),
        "sections": read_tsv(d / "sections.tsv"),
        "figures": read_tsv(d / "figures.tsv"),
        "proofs": read_tsv(d / "proofs.tsv"),
    }


def resolve(ref, idx):
    """Return list of matches: dicts with display, start, end, section, key, kind."""
    r = ref.strip()
    labels, sections = idx["labels"], idx["sections"]

    exact = [lab for lab in labels if lab["key"] == r]
    if exact:
        return exact

    m = re.match(rf"^(?:§+|sec(?:tion)?\.?|app(?:endix)?\.?|ch(?:apter)?\.?)\s*{NUM}$", r, re.I)
    if m:
        return [_sec(s) for s in sections if s["num"] == m.group(1)]

    m = re.match(rf"^(?:eqs?\.?|equation)?\s*\(\s*{NUM}\s*\)$|^(?:eqs?\.?|equation)\s*{NUM}$", r, re.I)
    if m:
        num = m.group(1) or m.group(2)
        return [lab for lab in labels if lab.get("kind") == "equation" and lab.get("num") == num]

    m = re.match(rf"^([A-Za-z]+)\.?\s*~?\s*{NUM}$", r)
    if m and m.group(1).lower() in ABBREV:
        name, num = ABBREV[m.group(1).lower()], m.group(2)
        hits = [lab for lab in labels if lab.get("display", "").lower() == f"{name} {num}".lower()]
        if not hits and name in ("figure", "table"):
            hits = [_fig(f) for f in idx["figures"] if f["display"].lower() == f"{name} {num}"]
        if not hits:
            # maybe theorem-likes share one counter: 'Lemma 3' may be printed as 'Theorem 3'
            hits = [lab for lab in labels if lab.get("kind") == "theorem" and lab.get("num") == num]
        return hits

    if re.match(rf"^{NUM}$", r):
        return [_sec(s) for s in sections if s["num"] == r]

    low = r.lower()
    hits = [lab for lab in labels if low in lab["key"].lower() or low in lab.get("title", "").lower()]
    hits += [_sec(s) for s in sections if low in s["title"].lower()]
    return hits


def section_of(where, idx):
    """Map a 'where' string to its top-level section number, or ''."""
    if not where:
        return ""
    for part in re.split(r"[,;]| and ", where):
        hits = resolve(part.strip(), idx)
        for h in hits:
            sec = h.get("section") or (h.get("num") if h.get("kind") == "section" else "")
            if sec:
                return sec
        m = re.search(r"§\s*([A-Z0-9][\w.]*)", part)
        if m:
            return m.group(1)
    return ""


def _sec(s):
    return {"key": "", "kind": "section", "display": f"§{s['num']} {s['title']}".strip(),
            "start": s["start"], "end": s["end"], "section": s["num"], "num": s["num"],
            "title": s["title"]}


def _fig(f):
    return {"key": f["label"], "kind": f["display"].split()[0].lower(), "display": f["display"],
            "start": f["start"], "end": f["end"], "section": "", "title": f["caption"][:80]}
