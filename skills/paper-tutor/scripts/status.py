#!/usr/bin/env python3
"""Resume summary for paper-tutor.

  status.py <paper>        recap: meta, digest state, recent sessions, weak quiz items, coverage
  status.py --store        where papers are stored and whether that was configured
  status.py --list         all stored papers (from index.md)

Exit code 2 if the paper is not in the store yet.
"""

import json
import platform
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
import refs  # noqa: E402

WEAK = {"partial", "wrong", "misconception"}


def quiz_records(d):
    p = Path(d) / "quiz.jsonl"
    if not p.exists():
        return []
    out = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out


def weak_items(recs):
    """Latest attempt per question chain (retry_of links); weak if not answered correctly."""
    by_id = {r.get("qid"): r for r in recs if r.get("qid")}

    def root(r):
        seen = set()
        while r.get("retry_of") in by_id and r["qid"] not in seen:
            seen.add(r["qid"])
            r = by_id[r["retry_of"]]
        return r.get("qid")

    latest = {}
    for r in recs:
        latest[root(r)] = r
    out = []
    for qroot, r in latest.items():
        if r.get("grade") in WEAK:
            first = by_id.get(qroot, r)
            out.append({**r, "q": first.get("q", r.get("q")), "retry_of_id": r.get("qid")})
    return out


def session_blocks(text):
    parts = re.split(r"\n(?=## )", "\n" + text)
    return [p.strip() for p in parts if p.strip().startswith("## ")]


def coverage(d, idx, sessions_text, recs):
    """section -> {modes:set, events:int, quiz:{grade:count}}"""
    cov = defaultdict(lambda: {"modes": set(), "events": 0, "quiz": defaultdict(int)})
    mode = None

    def top(sec):
        return sec.split(".")[0] if sec else ""

    for ln in sessions_text.splitlines():
        m = re.match(r"## .* — mode: ([\w+]+)", ln)
        if m:
            mode = m.group(1)
            continue
        m = re.match(r"- Switched to ([\w+]+)", ln)
        if m:
            mode = m.group(1)
        w = re.search(r"\[([^\]]+)\]", ln)
        if w and ln.startswith("- "):
            sec = top(refs.section_of(w.group(1), idx))
            if sec:
                cov[sec]["events"] += 1
                if mode:
                    cov[sec]["modes"].add(mode)
    for r in recs:
        sec = top(refs.section_of(r.get("where", ""), idx))
        if sec:
            cov[sec]["quiz"][r.get("grade", "?")] += 1
            cov[sec]["modes"].add(r.get("mode", "quiz"))
    return cov


def recap(ref):
    d = common.paper_dir(ref, must_exist=False)
    if not (d / "meta.json").exists():
        print(f"NOT_FOUND: {ref} is not in the store ({common.store_dir()}). Fetch it first.")
        return 2
    warnings = common.ensure_local(d)
    meta = common.read_meta(d)
    idx = refs.load(d)
    out = []
    authors = ", ".join(meta.get("authors", [])[:4]) + (" et al." if len(meta.get("authors", [])) > 4 else "")
    out.append(f"# {meta.get('title', meta.get('id'))}")
    out.append(f"{authors}")
    out.append(f"id {meta.get('id')} {meta.get('version', '')} · source: {meta.get('source_type')} "
               f"({meta.get('main_file', '')}) · dir: {d}")
    if meta.get("latest_version") and meta.get("latest_version") != meta.get("version"):
        warnings.append(f"newer arXiv version {meta['latest_version']} exists (stored {meta['version']})")

    digest = d / "digest.md"
    if not digest.exists():
        out.append("\n**Digest: missing** — read the source and write digest.md before tutoring.")
    else:
        stale = meta.get("digest_version") and meta.get("digest_version") != meta.get("version")
        out.append(f"\nDigest: built {meta.get('digest_date', '?')} from {meta.get('digest_version', '?')}"
                   + (f" — **STALE** (source is {meta['version']})" if stale else ""))

    sessions_text = (d / "sessions.md").read_text(encoding="utf-8") if (d / "sessions.md").exists() else ""
    blocks = session_blocks(sessions_text)
    out.append(f"\n## Sessions ({len(blocks)} total)")
    if not blocks:
        out.append("none yet")
    for b in blocks[-2:]:
        lines = b.splitlines()
        out += lines[:25] + ([f"… ({len(lines) - 25} more lines)"] if len(lines) > 25 else [])

    recs = quiz_records(d)
    graded = [r for r in recs if r.get("grade") in ("correct", "partial", "wrong")]
    counts = defaultdict(int)
    for r in graded:
        counts[r["grade"]] += 1
    weak = weak_items(recs)
    out.append(f"\n## Quiz: {len(graded)} graded ({counts['correct']} correct, {counts['partial']} partial, "
               f"{counts['wrong']} wrong) · {len(weak)} weak items to revisit")
    for w in weak[:10]:
        out.append(f"- [{w.get('retry_of_id')}] ({w.get('grade')}, L{w.get('level')}, {w.get('where') or '—'}) "
                   f"{common_trunc(w.get('q', ''), 140)}")
    if len(weak) > 10:
        out.append(f"- … {len(weak) - 10} more")

    sections = [s for s in idx["sections"] if s.get("level") in ("section", "chapter") and s.get("num")]
    if sections:
        cov = coverage(d, idx, sessions_text, recs)
        out.append("\n## Coverage by section")
        never, unquizzed = [], []
        for s in sections:
            c = cov.get(s["num"])
            if not c or (not c["modes"] and not c["quiz"]):
                never.append(s)
                mark = "not started"
            else:
                q = c["quiz"]
                qs = ", ".join(f"{k} {v}" for k, v in sorted(q.items())) or "not quizzed"
                mark = f"{' / '.join(sorted(c['modes'])) or '?'}; quiz: {qs}"
                if not q:
                    unquizzed.append(s)
            out.append(f"- §{s['num']} {common_trunc(s['title'], 60)} — {mark}")
        sugg = []
        if weak:
            sugg.append(f"re-quiz {len(weak)} weak item(s)")
        if unquizzed:
            sugg.append(f"§{unquizzed[0]['num']} was studied but never quizzed")
        if never:
            sugg.append(f"next unstarted section: §{never[0]['num']} {common_trunc(never[0]['title'], 50)}")
        if sugg:
            out.append("\nSuggested next: " + "; ".join(sugg))

    notes = d / "notes.md"
    if notes.exists():
        nl = [ln for ln in notes.read_text(encoding="utf-8").splitlines() if ln.strip()]
        out.append(f"\n## Your notes ({len(nl)})")
        out += nl[-3:]
    if meta.get("related"):
        out.append("\nRelated papers: " + ", ".join(r["id"] for r in meta["related"]))
    if warnings:
        out.append("\n## Warnings")
        out += [f"- {w}" for w in warnings]
    print("\n".join(out))
    return 0


def common_trunc(s, n):
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[:n - 1] + "…"


def store_status():
    path, how = common.store_info()
    info = {"store": str(path), "chosen_by": how, "configured": how != "default",
            "exists": path.exists(),
            "papers": len(list(path.glob("*/meta.json"))) if path.exists() else 0}
    if platform.system() == "Darwin":
        info["icloud_suggestion"] = str(common.ICLOUD_SUGGESTION)
    print(json.dumps(info, indent=2))
    return 0


def list_papers():
    store = common.store_dir()
    idx = store / "index.md"
    if not idx.exists():
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import log  # noqa: E402
        log.rebuild_index()
    print(idx.read_text(encoding="utf-8"))
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv[0] == "--store":
        return store_status()
    if argv[0] == "--list":
        return list_papers()
    return recap(argv[0])


if __name__ == "__main__":
    sys.exit(main())
