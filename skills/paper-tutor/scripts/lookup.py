#!/usr/bin/env python3
"""Look things up in a stored paper without loading the whole source.

  lookup.py <paper> show  <ref>     raw LaTeX of a result/equation/section/figure (with line numbers)
  lookup.py <paper> proof <ref>     the proof environment belonging to a result
  lookup.py <paper> cite  <key>     bibliography entry (+ arXiv id if it has one)
  lookup.py <paper> fig   <ref>     figure caption and image path(s); PDF figures converted to PNG on macOS
  lookup.py <paper> list  [kind]    list indexed labels (kind: theorem, equation, section, figure, table)

<ref> may be a label key (thm:main), 'Thm 2', 'Lemma 3.1', 'Eq. (7)', '(7)', '§3.2', 'Fig. 3', or a word
from a title. Numbers are recomputed from the source and can be off; confirm against the PDF if a
match looks wrong.
"""

import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
import refs  # noqa: E402

MAX_LINES = 220


def source_lines(d):
    meta = common.read_meta(d)
    f = d / ("main.flat.tex" if meta.get("source_type") == "tex" else "paper.txt")
    if not f.exists():
        sys.exit(f"error: {f.name} not found; re-run fetch_paper.py --reindex")
    return f, f.read_text(encoding="utf-8", errors="replace").splitlines()


def print_range(f, lines, start, end, label):
    start, end = max(1, int(start)), min(len(lines), int(end))
    cut = end - start + 1 > MAX_LINES
    if cut:
        end = start + MAX_LINES - 1
    print(f"--- {label} · {f.name}:{start}-{end}")
    for i in range(start, end + 1):
        print(f"{i:6d}  {lines[i - 1]}")
    if cut:
        print(f"--- truncated at {MAX_LINES} lines; read {f}:{end + 1}+ for more")


def pick(hits, ref):
    if not hits:
        sys.exit(f"no match for '{ref}'. Try `lookup.py <paper> list` or grep main.flat.tex.")
    if len(hits) > 1:
        print(f"{len(hits)} matches for '{ref}':")
        for h in hits[:15]:
            print(f"  {h.get('display', '')}  key={h.get('key', '')}  §{h.get('section', '')}  "
                  f"lines {h.get('start')}-{h.get('end')}  {h.get('title', '')}")
        print("showing the first:")
    return hits[0]


def cmd_show(d, ref):
    idx = refs.load(d)
    h = pick(refs.resolve(ref, idx), ref)
    f, lines = source_lines(d)
    start, end = int(h.get("start") or h.get("line")), int(h.get("end") or h.get("line"))
    if h.get("kind") == "equation":
        start, end = start - 2, end + 2
    print_range(f, lines, start, end, f"{h.get('display', '')} {h.get('key', '')}".strip())


def cmd_proof(d, ref):
    idx = refs.load(d)
    h = pick(refs.resolve(ref, idx), ref)
    proofs = [p for p in idx["proofs"] if h.get("key") and p["of"] == h["key"]]
    if not proofs:
        sys.exit(f"no proof environment linked to {h.get('display')} ({h.get('key')}). It may be in an "
                 f"appendix under another title: grep main.flat.tex for '{h.get('key')}' or 'Proof of'.")
    f, lines = source_lines(d)
    for p in proofs:
        print_range(f, lines, p["start"], p["end"], f"proof of {h.get('display')} {p['title']}".strip())


def cmd_cite(d, key):
    bbl, bib = d / "refs.bbl", d / "refs.bib"
    entry = None
    if bbl.exists():
        t = bbl.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"\\bibitem\s*(?:\[[^\]]*\])?\s*\{" + re.escape(key) + r"\}(.*?)(?=\\bibitem|\\end\{thebibliography\})",
                      t, re.S)
        if m:
            entry = m.group(1)
    if entry is None and bib.exists():
        t = bib.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"@\w+\s*\{\s*" + re.escape(key) + r"\s*,(.*?)\n\s*\}\s*(?=@|\Z)", t, re.S)
        if m:
            entry = m.group(1)
    if entry is None:
        sys.exit(f"citation key '{key}' not found in refs.bbl/refs.bib")
    entry = re.sub(r"\s+", " ", entry).strip()
    print(entry)
    m = re.search(r"(?:arXiv[:\s]*|arxiv\.org/abs/)(\d{4}\.\d{4,5}|[a-z\-]+/\d{7})", entry, re.I) or \
        re.search(r"eprint\s*=\s*[{\"]?(\d{4}\.\d{4,5})", entry, re.I)
    if m:
        print(f"\narXiv: {m.group(1)}  (open with paper-tutor to study it)")


def cmd_fig(d, ref):
    idx = refs.load(d)
    hits = [f for f in idx["figures"] if f["label"] == ref]
    if not hits:
        r = refs.resolve(ref, idx)
        keys = {h.get("key") for h in r}
        disp = {h.get("display") for h in r}
        hits = [f for f in idx["figures"] if f["label"] in keys or f["display"] in disp]
    if not hits:
        sys.exit(f"no figure matching '{ref}'")
    f = hits[0]
    meta = common.read_meta(d)
    src = d / "src" / meta.get("version", "local")
    print(f"{f['display']} ({f['label']}): {f['caption']}")
    for img in [i for i in f["images"].split(";") if i]:
        p = src / img
        if not p.exists():
            print(f"image not found: {img}")
            continue
        if p.suffix.lower() in (".pdf", ".eps"):
            png = d / "cache" / (re.sub(r"[^\w.-]", "_", img) + ".png")
            png.parent.mkdir(exist_ok=True)
            if not png.exists():
                if platform.system() == "Darwin" and shutil.which("sips") and p.suffix.lower() == ".pdf":
                    subprocess.run(["sips", "-s", "format", "png", str(p), "--out", str(png)],
                                   capture_output=True)
                elif shutil.which("pdftoppm") and p.suffix.lower() == ".pdf":
                    subprocess.run(["pdftoppm", "-png", "-singlefile", "-r", "150", str(p),
                                    str(png.with_suffix(""))], capture_output=True)
            print(f"image: {png if png.exists() else p}" + ("" if png.exists() else "  (could not convert)"))
        else:
            print(f"image: {p}")


def cmd_list(d, kind=None):
    idx = refs.load(d)
    if kind in ("section", "sections"):
        for s in idx["sections"]:
            print(f"§{s['num'] or '*'}\t{s['title']}\tlines {s['start']}-{s['end']}")
        return
    for lab in idx["labels"]:
        if kind and lab.get("kind") != kind.rstrip("s"):
            continue
        print(f"{lab.get('display', '') or '?':22s} {lab['key']:30s} §{lab.get('section', ''):6s} "
              f"line {lab.get('line')}  {lab.get('title', '')}")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 2 or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    d = common.paper_dir(argv[0])
    cmd, rest = argv[1], " ".join(argv[2:])
    fns = {"show": cmd_show, "proof": cmd_proof, "cite": cmd_cite, "fig": cmd_fig}
    if cmd == "list":
        cmd_list(d, rest or None)
    elif cmd in fns and rest:
        fns[cmd](d, rest)
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
